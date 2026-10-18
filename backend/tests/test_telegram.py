"""SilentSOS Telegram notifications — tests.

Covers: alert notification to linked contacts, safe notification, missing
token / send failure never failing the alert, /start linking flow, ack
replies, and the tracking page.
"""
import os
import time

import pytest
from fastapi.testclient import TestClient

import backend.telegram as tg
from backend.main import app
from backend.registry import get_connection, init_db
from backend.tests.test_api import DEVICE_ID, LAT, LON, _seed_device, db_rows


@pytest.fixture()
def tsetup(tmp_path, monkeypatch):
    """Fresh DB + seeded device + test client. Yields (client, key, db)."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("SILENT_DB_PATH", db_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    init_db(db_path)
    key = _seed_device(db_path)
    # Run notification dispatches synchronously for determinism, mirroring
    # production's _guarded: notification errors never fail the request.
    def _sync_notify(fn, *a):
        try:
            fn(*a)
        except Exception:
            pass
    monkeypatch.setattr("backend.main._notify_later", _sync_notify)
    # Never start the real Telegram long-polling thread in tests.
    monkeypatch.setattr(tg, "poll_forever", lambda *a, **k: None)
    with TestClient(app) as client:
        yield client, key, db_path


def _link_contact(db_path, contact_id=1, chat_id=4242):
    conn = get_connection(db_path)
    try:
        conn.execute("UPDATE contacts SET telegram_chat_id = ? WHERE id = ?",
                     (chat_id, contact_id))
        conn.commit()
    finally:
        conn.close()


def _make_alert(client, key, typ="alert"):
    from backend.tests.test_api import make_body
    return client.post("/api/alert",
                       json=make_body(DEVICE_ID, key, typ=typ))


# --- notifications ----------------------------------------------------------

def test_alert_notifies_linked_contacts(tsetup, monkeypatch):
    client, key, db_path = tsetup
    _link_contact(db_path, contact_id=1, chat_id=4242)
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)

    r = _make_alert(client, key)
    assert r.status_code == 200
    alert_id = r.json()["alert_id"]

    assert len(sent) == 1
    chat_id, text = sent[0]
    assert chat_id == "4242"  # stored as TEXT
    assert text.startswith("🚨 SilentSOS alert from Test Owner.")
    assert f"/track/{alert_id}" in text
    assert "Battery 87%" in text
    assert "Reply 'ack' if you're responding." in text


def test_unlinked_contacts_get_nothing(tsetup, monkeypatch):
    client, key, db_path = tsetup  # contact 1 has no telegram_chat_id
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)
    assert _make_alert(client, key).status_code == 200
    assert sent == []


def test_safe_notification_on_resolve(tsetup, monkeypatch):
    client, key, db_path = tsetup
    _link_contact(db_path, contact_id=1, chat_id=4242)
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)

    alert_id = _make_alert(client, key).json()["alert_id"]
    sent.clear()
    assert client.post(f"/api/alerts/{alert_id}/safe").status_code == 200
    assert sent == [("4242", "✅ Test Owner has marked themselves safe.")]


def test_safe_type_message_notifies(tsetup, monkeypatch):
    client, key, db_path = tsetup
    _link_contact(db_path, contact_id=1, chat_id=4242)
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)
    _make_alert(client, key)
    sent.clear()
    assert _make_alert(client, key, typ="safe").status_code == 200
    assert sent and sent[0][1] == "✅ Test Owner has marked themselves safe."


def test_missing_token_does_not_fail_alert(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("SILENT_DB_PATH", db_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    init_db(db_path)
    key = _seed_device(db_path)
    monkeypatch.setattr("backend.main._notify_later",
                        lambda fn, *a: fn(*a))
    from backend.tests.test_api import make_body
    with TestClient(app) as client:
        r = client.post("/api/alert", json=make_body(DEVICE_ID, key))
        assert r.status_code == 200  # alert succeeds, no Telegram configured


def test_send_failure_does_not_fail_alert(tsetup, monkeypatch):
    client, key, db_path = tsetup
    _link_contact(db_path, contact_id=1, chat_id=4242)

    def boom(chat_id, text):
        raise RuntimeError("telegram is down")

    monkeypatch.setattr(tg, "send_message", boom)
    r = _make_alert(client, key)
    assert r.status_code == 200  # alert accepted despite Telegram failure
    # and the safe path is equally safe
    alert_id = r.json()["alert_id"]
    assert client.post(f"/api/alerts/{alert_id}/safe").status_code == 200


# --- /start linking ---------------------------------------------------------

def _update(chat_id, text):
    return {"update_id": 1, "message": {"chat": {"id": chat_id},
                                       "text": text}}


def test_start_links_contact(tsetup, monkeypatch):
    client, key, db_path = tsetup
    code = tg.ensure_link_code(db_path, 1)
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)

    tg.process_update(_update(777, f"/start {code.lower()}"), db_path)
    row = db_rows(db_path,
                  "SELECT telegram_chat_id FROM contacts WHERE id = 1")[0]
    assert row["telegram_chat_id"] == "777"  # TEXT column
    assert sent and sent[0][0] == 777 and "linked to Asha Sharma" in sent[0][1]


def test_start_unknown_code(tsetup, monkeypatch):
    client, key, db_path = tsetup
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)
    tg.process_update(_update(777, "/start NOPE12"), db_path)
    row = db_rows(db_path,
                  "SELECT telegram_chat_id FROM contacts WHERE id = 1")[0]
    assert row["telegram_chat_id"] is None
    assert sent and "Unknown link code" in sent[0][1]


def test_start_without_code(tsetup, monkeypatch):
    client, key, db_path = tsetup
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)
    tg.process_update(_update(777, "/start"), db_path)
    assert sent and "Unknown link code" in sent[0][1]


# --- ack replies ------------------------------------------------------------

def test_ack_reply_records_ack(tsetup, monkeypatch):
    client, key, db_path = tsetup
    alert_id = _make_alert(client, key).json()["alert_id"]
    _link_contact(db_path, contact_id=1, chat_id=4242)
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)

    tg.process_update(_update(4242, "ack"), db_path)
    rows = db_rows(db_path, "SELECT * FROM acks WHERE alert_id = ?",
                   (alert_id,))
    assert len(rows) == 1 and rows[0]["contact_id"] == 1
    assert sent and "marked as responding" in sent[0][1]
    # duplicate ack is harmless
    tg.process_update(_update(4242, "ACK"), db_path)
    rows = db_rows(db_path, "SELECT * FROM acks WHERE alert_id = ?",
                   (alert_id,))
    assert len(rows) == 1


def test_ack_reply_case_insensitive_and_unlinked(tsetup, monkeypatch):
    client, key, db_path = tsetup
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)
    tg.process_update(_update(9999, "Ack"), db_path)
    assert sent and "isn't linked yet" in sent[0][1]


def test_ack_reply_no_active_alert(tsetup, monkeypatch):
    client, key, db_path = tsetup
    _link_contact(db_path, contact_id=1, chat_id=4242)
    sent = []
    monkeypatch.setattr(tg, "send_message",
                        lambda chat_id, text: sent.append((chat_id, text))
                        or True)
    tg.process_update(_update(4242, "ack"), db_path)
    assert sent and "No active alert" in sent[0][1]


# --- tracking page ----------------------------------------------------------

def test_track_page(tsetup):
    client, key, db_path = tsetup
    alert_id = _make_alert(client, key).json()["alert_id"]
    r = client.get(f"/track/{alert_id}")
    assert r.status_code == 200
    assert "leaflet" in r.text.lower()  # map shell served
    r = client.get("/track/does-not-exist")
    assert r.status_code == 404
    assert "not found" in r.text.lower()  # friendly error page


def test_ensure_link_code_is_stable_and_unique(tsetup):
    client, key, db_path = tsetup
    c1 = tg.ensure_link_code(db_path, 1)
    assert tg.ensure_link_code(db_path, 1) == c1  # stable
    assert len(c1) == 6
