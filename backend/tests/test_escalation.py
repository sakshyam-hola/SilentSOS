"""Automatic escalation: tiered contacts, ESCALATION_SECONDS, both paths.

Seed: 2 tier-1 contacts (Asha, Bikash) + 1 tier-2 contact (Sita), all
Telegram-linked. Notifications run synchronously and send_message is
captured, so no real Telegram traffic happens in tests. The background
escalation sweeper is disabled; tests call check_escalations() directly.
"""
import os

import pytest
from fastapi.testclient import TestClient

import backend.main as main
import backend.telegram as tg
from backend.main import app
from backend.registry import get_connection, init_db
from backend.tests.test_api import DEVICE_ID, db_rows, make_body

TIER1_CHATS = ("111", "222")
TIER2_CHAT = "333"


def _seed_device_with_tiers(db_path):
    """Insert the demo device + 3 tiered, Telegram-linked contacts."""
    key = os.urandom(32)
    conn = get_connection(db_path)
    try:
        from backend.crypto import b64e
        conn.execute(
            "INSERT INTO devices (device_id, secret_key, owner_name, active)"
            " VALUES (?, ?, ?, ?)",
            (DEVICE_ID, b64e(key), "Test Owner", 1))
        conn.executemany(
            "INSERT INTO contacts (device_id, name, relation, phone,"
            " priority, tier, telegram_chat_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(DEVICE_ID, "Asha Sharma", "spouse", "+977-9800000001", 1, 1,
              TIER1_CHATS[0]),
             (DEVICE_ID, "Bikash Thapa", "friend", "+977-9800000002", 2, 1,
              TIER1_CHATS[1]),
             (DEVICE_ID, "Sita Rai", "neighbor", "+977-9800000003", 3, 2,
              TIER2_CHAT)],
        )
        conn.commit()
    finally:
        conn.close()
    return key


@pytest.fixture()
def esetup(tmp_path, monkeypatch):
    """Fresh DB + tiered contacts + test client. Yields (client, key, db, sent)."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("SILENT_DB_PATH", db_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    init_db(db_path)
    key = _seed_device_with_tiers(db_path)
    # Synchronous, guarded notification dispatch (mirrors production).
    monkeypatch.setattr("backend.main._notify_later",
                        lambda fn, *a: fn(*a))
    # No background threads in tests: polling + sweeper disabled.
    monkeypatch.setattr(tg, "poll_forever", lambda *a, **k: None)
    monkeypatch.setattr(main, "_escalation_sweeper",
                        lambda stop_event: None)
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)
    with TestClient(app) as client:
        yield client, key, db_path, sent


def _new_alert(client, key):
    r = client.post("/api/alert", json=make_body(DEVICE_ID, key))
    assert r.status_code == 200
    return r.json()["alert_id"]


def test_alert_notifies_tier1_only(esetup):
    client, key, db_path, sent = esetup
    _new_alert(client, key)
    chats = {c for c, _ in sent}
    assert chats == set(TIER1_CHATS), f"tier 2 must not be notified yet: {sent}"
    assert all("🚨 SilentSOS alert" in t and "ESCALATED" not in t
               for _, t in sent)


def test_no_escalation_when_acked_in_time(esetup, monkeypatch):
    client, key, db_path, sent = esetup
    alert_id = _new_alert(client, key)
    # Tier-1 contact acknowledges (contact ids are 1, 2, 3 in a fresh DB).
    r = client.post(f"/api/alerts/{alert_id}/ack", json={"contact_id": 1})
    assert r.status_code == 200
    # Even with a zero-second threshold, the ack blocks escalation.
    monkeypatch.setattr(main, "ESCALATION_SECONDS", 0)
    assert main.check_escalations() == 0
    d = client.get(f"/api/alerts/{alert_id}").json()
    assert d["escalated_at"] is None
    assert {c for c, _ in sent} == set(TIER1_CHATS)


def test_escalates_when_no_ack(esetup, monkeypatch):
    client, key, db_path, sent = esetup
    alert_id = _new_alert(client, key)
    sent.clear()
    monkeypatch.setattr(main, "ESCALATION_SECONDS", 0)
    assert main.check_escalations() == 1
    d = client.get(f"/api/alerts/{alert_id}").json()
    assert d["escalated_at"] is not None
    assert d["escalation_seconds"] == 0
    # Exactly one escalation message, to the tier-2 contact only.
    assert len(sent) == 1
    chat, text = sent[0]
    assert chat == TIER2_CHAT
    assert "ESCALATED" in text
    # Audit trail records the escalation.
    reasons = [r["reason"] for r in db_rows(
        db_path, "SELECT reason FROM audit_log WHERE alert_id = ?",
        (alert_id,))]
    assert "escalated_tier2" in reasons
    # Idempotent: a second pass escalates nothing and notifies nobody.
    sent.clear()
    assert main.check_escalations() == 0
    assert sent == []


def test_escalation_skips_resolved_alert(esetup, monkeypatch):
    client, key, db_path, sent = esetup
    alert_id = _new_alert(client, key)
    client.post(f"/api/alerts/{alert_id}/safe")
    sent.clear()
    monkeypatch.setattr(main, "ESCALATION_SECONDS", 0)
    assert main.check_escalations() == 0
    d = client.get(f"/api/alerts/{alert_id}").json()
    assert d["escalated_at"] is None
    assert sent == []
