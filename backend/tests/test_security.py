"""SilentSOS security features — tests.

Covers: security headers, restricted CORS, the audit API + /security page,
automatic location-data deletion 24 h after an alert is resolved,
/api/health, /api/devices, per-device last_seen, and registry --export-config.
"""
import os
import time

from backend.main import purge_expired_locations
from backend.registry import export_config, get_connection, init_db
from backend.tests.test_api import DEVICE_ID, _seed_device, b64e, make_body
from backend.tests.test_telegram import _make_alert, tsetup  # noqa: F401


def test_security_headers(tsetup):
    client, key, db_path = tsetup
    for path in ("/", "/api/alerts", "/simulator", "/security"):
        r = client.get(path)
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        csp = r.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp


def test_cors_is_restricted(tsetup):
    client, key, db_path = tsetup
    r = client.get("/api/alerts",
                   headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_audit_api(tsetup):
    client, key, db_path = tsetup
    assert client.get("/api/audit").json() == {"entries": []}
    _make_alert(client, key)
    client.post("/api/alert", json={"bogus": 1})
    entries = client.get("/api/audit").json()["entries"]
    assert [e["reason"] for e in entries] == ["format", "alert_created"]
    assert entries[0]["outcome"] == "rejected"
    assert entries[1]["outcome"] == "accepted"
    assert entries[1]["device_id"] == "dev-001"
    assert len(client.get("/api/audit?limit=1").json()["entries"]) == 1


def test_security_page(tsetup):
    client, key, db_path = tsetup
    r = client.get("/security")
    assert r.status_code == 200
    assert "audit log" in r.text.lower()
    for needle in ("Security center", "Simulate attack", "Why this is secure",
                   "Live request feed", "data-sim", "drawer",
                   "chart.umd.min.js"):
        assert needle in r.text, needle


def test_purge_deletes_location_24h_after_resolve(tsetup):
    client, key, db_path = tsetup
    aid = _make_alert(client, key).json()["alert_id"]
    assert client.post(f"/api/alerts/{aid}/safe").status_code == 200
    # pretend it was resolved 25 h ago
    conn = get_connection(db_path)
    conn.execute("UPDATE alerts SET resolved_at = ? WHERE id = ?",
                 (time.time() - 25 * 3600, aid))
    conn.commit()
    conn.close()

    assert purge_expired_locations(db_path) == 1
    d = client.get(f"/api/alerts/{aid}").json()
    assert d["lat"] is None and d["lon"] is None and d["trail"] == []
    assert d["status"] == "safe"  # the record itself is kept
    assert purge_expired_locations(db_path) == 0  # idempotent


def test_purge_skips_active_and_freshly_resolved(tsetup):
    client, key, db_path = tsetup
    aid1 = _make_alert(client, key).json()["alert_id"]
    # backdate so the next alert isn't folded by the 30 s cooldown
    conn = get_connection(db_path)
    conn.execute("UPDATE alerts SET created_at = ? WHERE id = ?",
                 (time.time() - 60, aid1))
    conn.commit()
    conn.close()
    aid2 = _make_alert(client, key).json()["alert_id"]
    assert aid2 != aid1
    assert client.post(f"/api/alerts/{aid2}/safe").status_code == 200

    assert purge_expired_locations(db_path) == 0  # active + fresh: kept
    d1 = client.get(f"/api/alerts/{aid1}").json()
    assert d1["lat"] is not None and len(d1["trail"]) == 1


# --- health, devices, last_seen ----------------------------------------------

def test_health(tsetup):
    client, key, db_path = tsetup
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["db"] == "ok"
    assert abs(body["time"] - time.time()) < 5


def test_devices_endpoint(tsetup):
    client, key, db_path = tsetup
    devices = client.get("/api/devices").json()["devices"]
    assert len(devices) == 1
    d = devices[0]
    assert d["device_id"] == "dev-001" and d["owner_name"] == "Test Owner"
    assert d["active"] == 1 and d["last_seen"] is None


def test_last_seen_updates_on_device_contact(tsetup):
    client, key, db_path = tsetup
    before = time.time()
    assert _make_alert(client, key).status_code == 200
    seen = client.get("/api/devices").json()["devices"][0]["last_seen"]
    assert seen is not None and abs(seen - before) < 5
    # even a failed-decrypt request counts: the device talked to us
    bad = make_body(DEVICE_ID, os.urandom(32))
    assert client.post("/api/alert", json=bad).status_code == 401
    seen2 = client.get("/api/devices").json()["devices"][0]["last_seen"]
    assert seen2 >= seen


def test_export_config(capsys, tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("SILENT_DB_PATH", db_path)
    init_db(db_path)
    key = _seed_device(db_path)
    export_config("dev-001", db_path)
    out = capsys.readouterr().out
    assert '#define DEVICE_ID       "dev-001"' in out
    assert b64e(key) in out
    assert "never commit config.h" in out
    export_config("nope", db_path)
    assert "Unknown device" in capsys.readouterr().out


# --- HTTPS enforcement + PUBLIC_BASE_URL ------------------------------------

def test_https_redirect_when_edge_saw_http(tsetup):
    client, key, db_path = tsetup
    r = client.get("/", headers={"x-forwarded-proto": "http"},
                   follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://")


def test_no_redirect_without_proxy_header(tsetup):
    client, key, db_path = tsetup
    r = client.get("/")
    assert r.status_code == 200
    assert "strict-transport-security" not in r.headers


def test_hsts_when_edge_saw_https(tsetup):
    client, key, db_path = tsetup
    r = client.get("/", headers={"x-forwarded-proto": "https"})
    assert r.status_code == 200
    assert (r.headers["strict-transport-security"]
            == "max-age=31536000; includeSubDomains")


def test_tracking_link_uses_public_base_url(monkeypatch):
    from backend import telegram
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://demo.example.com/")
    assert (telegram.tracking_link("abc")
            == "https://demo.example.com/track/abc")
