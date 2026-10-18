"""SilentSOS backend tests — docs/PROTOCOL.md validation chain + alert flow.

Each test gets a fresh SQLite DB (tmp_path) with one seeded device, so the
rate limiter, replay cache and alert cooldown never leak between tests.
"""
import base64
import json
import os
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from backend.crypto import b64e, encrypt
from backend.main import app
from backend.registry import get_connection, init_db

DEVICE_ID = "dev-001"
LAT, LON = 27.7172, 85.3240


# --- fixtures & helpers -----------------------------------------------------

def _seed_device(db_path, device_id=DEVICE_ID, active=1):
    """Insert a device + one contact. Returns the raw 32-byte key."""
    key = os.urandom(32)
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO devices (device_id, secret_key, owner_name, active)"
            " VALUES (?, ?, ?, ?)",
            (device_id, b64e(key), "Test Owner", active))
        conn.execute(
            "INSERT INTO contacts (device_id, name, relation, phone, email,"
            " priority) VALUES (?, ?, ?, ?, ?, ?)",
            (device_id, "Asha Sharma", "spouse", "+977-9800000001",
             "asha@example.com", 1))
        conn.commit()
    finally:
        conn.close()
    return key


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    """Fresh DB + seeded device + test client. Yields (client, key, db_path)."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("SILENT_DB_PATH", db_path)
    init_db(db_path)
    key = _seed_device(db_path)
    with TestClient(app) as client:
        yield client, key, db_path


def make_body(device_id, key, ts=None, lat=LAT, lon=LON, battery=87,
              typ="alert", plaintext=None):
    """Build a valid encrypted POST /api/alert body."""
    pt = {"ts": int(time.time()) if ts is None else ts, "lat": lat,
          "lon": lon, "battery": battery, "type": typ}
    if plaintext is not None:
        pt = plaintext
    nonce_b64, ct_b64, tag_b64 = encrypt(device_id, key, pt)
    return {"device_id": device_id, "nonce": nonce_b64,
            "ciphertext": ct_b64, "tag": tag_b64}


def db_rows(db_path, sql, args=()):
    conn = get_connection(db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


# --- required cases ---------------------------------------------------------

def test_valid_alert(setup):
    client, key, db_path = setup
    r = client.post("/api/alert", json=make_body(DEVICE_ID, key))
    assert r.status_code == 200
    alert_id = r.json()["alert_id"]
    assert r.json()["status"] == "ok"

    d = client.get(f"/api/alerts/{alert_id}").json()
    assert d["status"] == "active"
    assert d["lat"] == LAT and d["lon"] == LON and d["battery"] == 87
    assert len(d["trail"]) == 1 and d["acks"] == []

    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("accepted", "alert_created") in [(a[0], a[1]) for a in audit]


def test_tampered_ciphertext(setup):
    client, key, db_path = setup
    body = make_body(DEVICE_ID, key)
    raw = bytearray(base64.b64decode(body["ciphertext"]))
    raw[0] ^= 0x01  # flip a bit -> GCM tag verification must fail
    body["ciphertext"] = base64.b64encode(bytes(raw)).decode()

    r = client.post("/api/alert", json=body)
    assert r.status_code == 401
    assert r.json() == {"status": "error"}
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("rejected", "decryption") in [(a[0], a[1]) for a in audit]


def test_tampered_tag(setup):
    client, key, _ = setup
    body = make_body(DEVICE_ID, key)
    raw = bytearray(base64.b64decode(body["tag"]))
    raw[-1] ^= 0x01
    body["tag"] = base64.b64encode(bytes(raw)).decode()
    assert client.post("/api/alert", json=body).status_code == 401


def test_wrong_key(setup):
    client, key, db_path = setup
    wrong_key = os.urandom(32)
    r = client.post("/api/alert", json=make_body(DEVICE_ID, wrong_key))
    assert r.status_code == 401
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("rejected", "decryption") in [(a[0], a[1]) for a in audit]


def test_replayed_nonce(setup):
    client, key, db_path = setup
    body = make_body(DEVICE_ID, key)
    assert client.post("/api/alert", json=body).status_code == 200
    r = client.post("/api/alert", json=body)  # identical nonce
    assert r.status_code == 409
    assert r.json() == {"status": "error"}
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    reasons = [(a[0], a[1]) for a in audit]
    assert ("rejected", "replay") in reasons


def test_expired_timestamp(setup):
    client, key, db_path = setup
    old = int(time.time()) - 300
    r = client.post("/api/alert",
                    json=make_body(DEVICE_ID, key, ts=old))
    assert r.status_code == 408
    assert r.json() == {"status": "error"}
    # future timestamps are rejected too (|server - ts| <= 60)
    future = int(time.time()) + 300
    r = client.post("/api/alert",
                    json=make_body(DEVICE_ID, key, ts=future))
    assert r.status_code == 408
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("rejected", "freshness") in [(a[0], a[1]) for a in audit]


def test_unknown_device(setup):
    client, key, db_path = setup
    other_key = os.urandom(32)
    body = make_body("dev-999", other_key)  # not in registry
    r = client.post("/api/alert", json=body)
    assert r.status_code == 401
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("rejected", "registry") in [(a[0], a[1]) for a in audit]


def test_inactive_device(setup):
    client, key, db_path = setup
    conn = get_connection(db_path)
    conn.execute("UPDATE devices SET active = 0 WHERE device_id = ?",
                 (DEVICE_ID,))
    conn.commit()
    conn.close()
    assert client.post("/api/alert",
                       json=make_body(DEVICE_ID, key)).status_code == 401


def test_rate_limit(setup):
    client, key, _ = setup
    codes = [client.post("/api/alert",
                         json=make_body(DEVICE_ID, key)).status_code
             for _ in range(6)]
    # requests 2-5 are cooldown-ignored duplicates (still 200 and still
    # counted); the 6th exceeds 5/min.
    assert codes == [200, 200, 200, 200, 200, 429]
    assert client.post("/api/alert",
                       json=make_body(DEVICE_ID, key)).status_code == 429


# --- alert lifecycle --------------------------------------------------------

def test_update_appends_to_trail(setup):
    client, key, db_path = setup
    alert_id = client.post("/api/alert",
                           json=make_body(DEVICE_ID, key)).json()["alert_id"]

    r = client.post("/api/alert", json=make_body(
        DEVICE_ID, key, lat=27.7200, lon=85.3300, battery=80, typ="update"))
    assert r.status_code == 200
    assert r.json()["alert_id"] == alert_id  # same alert, no new row

    d = client.get(f"/api/alerts/{alert_id}").json()
    assert len(d["trail"]) == 2
    assert d["lat"] == 27.7200 and d["lon"] == 85.3300 and d["battery"] == 80
    n = db_rows(db_path, "SELECT COUNT(*) c FROM alerts")[0]["c"]
    assert n == 1


def test_update_without_active_alert_is_rejected(setup):
    client, key, db_path = setup
    r = client.post("/api/alert", json=make_body(DEVICE_ID, key, typ="update"))
    assert r.status_code == 400
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("rejected", "no_active_alert") in [(a[0], a[1]) for a in audit]


def test_safe_type_message_resolves(setup):
    client, key, _ = setup
    alert_id = client.post("/api/alert",
                           json=make_body(DEVICE_ID, key)).json()["alert_id"]
    r = client.post("/api/alert",
                    json=make_body(DEVICE_ID, key, typ="safe"))
    assert r.status_code == 200
    assert r.json()["alert_id"] == alert_id
    assert client.get(f"/api/alerts/{alert_id}").json()["status"] == "safe"


def test_post_safe_endpoint(setup):
    client, key, _ = setup
    alert_id = client.post("/api/alert",
                           json=make_body(DEVICE_ID, key)).json()["alert_id"]
    r = client.post(f"/api/alerts/{alert_id}/safe")
    assert r.status_code == 200
    d = client.get(f"/api/alerts/{alert_id}").json()
    assert d["status"] == "safe" and d["resolved_at"] is not None
    # idempotent
    assert client.post(f"/api/alerts/{alert_id}/safe").status_code == 200
    assert client.post("/api/alerts/nope/safe").status_code == 404


def test_cooldown_ignores_repeat_alert(setup):
    client, key, db_path = setup
    first = client.post("/api/alert",
                        json=make_body(DEVICE_ID, key)).json()["alert_id"]
    second = client.post("/api/alert",
                         json=make_body(DEVICE_ID, key)).json()["alert_id"]
    assert first == second  # ignored: same alert returned
    n = db_rows(db_path, "SELECT COUNT(*) c FROM alerts")[0]["c"]
    assert n == 1
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("accepted", "cooldown_ignored") in [(a[0], a[1]) for a in audit]


def test_ack_flow(setup):
    client, key, _ = setup
    alert_id = client.post("/api/alert",
                           json=make_body(DEVICE_ID, key)).json()["alert_id"]
    r = client.post(f"/api/alerts/{alert_id}/ack", json={"contact_id": 1})
    assert r.status_code == 200
    acks = client.get(f"/api/alerts/{alert_id}").json()["acks"]
    assert len(acks) == 1 and acks[0]["name"] == "Asha Sharma"
    # duplicate ack
    assert client.post(f"/api/alerts/{alert_id}/ack",
                       json={"contact_id": 1}).status_code == 409
    # unknown contact / alert
    assert client.post(f"/api/alerts/{alert_id}/ack",
                       json={"contact_id": 999}).status_code == 404
    assert client.post("/api/alerts/nope/ack",
                       json={"contact_id": 1}).status_code == 404


def test_get_unknown_alert(setup):
    client, _, _ = setup
    r = client.get("/api/alerts/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"status": "error"}


# --- format / plaintext schema ----------------------------------------------

@pytest.mark.parametrize("mutate", [
    lambda b: b.pop("tag"),                                   # missing field
    lambda b: b.update({"extra": 1}),                          # extra field
    lambda b: b.update({"nonce": "!!!not-base64!!!"}),         # bad base64
    lambda b: b.update({"nonce": b64e(os.urandom(8))}),        # nonce != 12B
    lambda b: b.update({"tag": b64e(os.urandom(8))}),          # tag != 16B
    lambda b: b.update({"device_id": 123}),                    # wrong type
])
def test_format_rejections(setup, mutate):
    client, key, db_path = setup
    body = make_body(DEVICE_ID, key)
    mutate(body)
    r = client.post("/api/alert", json=body)
    assert r.status_code == 400
    assert r.json() == {"status": "error"}
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("rejected", "format") in [(a[0], a[1]) for a in audit]


def test_not_json_body(setup):
    client, _, _ = setup
    r = client.post("/api/alert", content=b"not json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400


@pytest.mark.parametrize("plaintext", [
    {"ts": 1, "lat": LAT, "lon": LON, "battery": 101, "type": "alert"},
    {"ts": 1, "lat": 95.0, "lon": LON, "battery": 87, "type": "alert"},
    {"ts": 1, "lat": LAT, "lon": -200.0, "battery": 87, "type": "alert"},
    {"ts": 1, "lat": LAT, "lon": LON, "battery": 87, "type": "bogus"},
    {"ts": 1, "lat": LAT, "lon": LON, "battery": 87, "type": "alert",
     "extra": 1},
    {"ts": "now", "lat": LAT, "lon": LON, "battery": 87, "type": "alert"},
])
def test_plaintext_schema_rejections(setup, plaintext):
    client, key, db_path = setup
    body = make_body(DEVICE_ID, key, plaintext=plaintext)
    # ts must be fresh; patch it to now when the case uses a dummy ts
    if plaintext.get("ts") == 1:
        from backend.crypto import encrypt as _enc
        n, c, t = _enc(DEVICE_ID, key,
                       {**plaintext, "ts": int(time.time())})
        body.update({"nonce": n, "ciphertext": c, "tag": t})
    r = client.post("/api/alert", json=body)
    assert r.status_code == 400, plaintext
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("rejected", "plaintext") in [(a[0], a[1]) for a in audit]


def test_audit_log_covers_every_request(setup):
    client, key, db_path = setup
    client.post("/api/alert", json=make_body(DEVICE_ID, key))          # ok
    client.post("/api/alert", json={"bogus": 1})                       # 400
    client.post("/api/alert",
                json=make_body("dev-999", os.urandom(32)))             # 401
    rows = db_rows(db_path, "SELECT outcome, reason FROM audit_log"
                            " ORDER BY id")
    assert [(r[0], r[1]) for r in rows] == [
        ("accepted", "alert_created"),
        ("rejected", "format"),
        ("rejected", "registry"),
    ]


# --- web simulator (server-side encryption helper) --------------------------

def _sim_body(typ="alert", **kw):
    body = {"device_id": DEVICE_ID, "type": typ,
            "lat": LAT, "lon": LON, "battery": 87}
    body.update(kw)
    return body


def test_simulator_send_accepts(setup):
    client, _, db_path = setup
    r = client.post("/api/simulator/send", json=_sim_body())
    assert r.status_code == 200
    alert_id = r.json()["alert_id"]
    d = client.get(f"/api/alerts/{alert_id}").json()
    assert d["status"] == "active" and d["lat"] == LAT
    audit = db_rows(db_path, "SELECT outcome, reason FROM audit_log")
    assert ("accepted", "alert_created") in [(a[0], a[1]) for a in audit]


def test_simulator_send_update_appends(setup):
    client, _, _ = setup
    aid = client.post("/api/simulator/send",
                      json=_sim_body()).json()["alert_id"]
    r = client.post("/api/simulator/send",
                    json=_sim_body("update", lat=27.7200))
    assert r.status_code == 200 and r.json()["alert_id"] == aid
    assert len(client.get(f"/api/alerts/{aid}").json()["trail"]) == 2


def test_simulator_send_unknown_device(setup):
    client, _, _ = setup
    r = client.post("/api/simulator/send", json=_sim_body(device_id="dev-9"))
    assert r.status_code == 401
    assert r.json() == {"status": "error"}


@pytest.mark.parametrize("field,value", [
    ("type", "bogus"), ("lat", 95.0), ("lon", -200.0),
    ("battery", 101), ("battery", "87"), ("device_id", 123),
])
def test_simulator_send_bad_fields(setup, field, value):
    client, _, _ = setup
    body = _sim_body()
    body[field] = value
    assert client.post("/api/simulator/send", json=body).status_code == 400


def test_simulator_page_has_demo_note_and_no_key(setup):
    client, key, _ = setup
    r = client.get("/simulator")
    assert r.status_code == 200
    assert ("Demo only. A real device keeps its key in firmware,"
            in r.text)
    assert b64e(key) not in r.text
    assert "secret_key" not in r.text


def test_simulator_page_has_safe_walk(setup):
    client, _, _ = setup
    r = client.get("/simulator")
    assert r.status_code == 200
    # Duration choices: 20s demo + 5/10/15 min, countdown ring, PIN check-in,
    # and the duress-PIN explanation in settings. Client-side only: the
    # alert itself goes through the normal /api/simulator/send path.
    for needle in ("Safe Walk", 'data-secs="20"', 'data-secs="300"',
                   'data-secs="600"', 'data-secs="900"', "Demo",
                   'id="sw-ring"', 'id="sw-ok"', 'id="sw-pin"',
                   "Duress PIN", "/api/simulator/send"):
        assert needle in r.text, needle
