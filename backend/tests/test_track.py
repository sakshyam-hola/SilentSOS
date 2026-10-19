"""SilentSOS tracking + operator home pages — tests.

Covers: GET /track/{id} (Leaflet shell, friendly 404), GET / (home page),
GET /api/alerts (recent-alerts list), and the contacts-with-ack-status
field on GET /api/alerts/{id}.
"""
from backend.tests.test_telegram import _make_alert, tsetup  # noqa: F401


def test_track_page_serves_map(tsetup):
    client, key, db_path = tsetup
    alert_id = _make_alert(client, key).json()["alert_id"]
    r = client.get(f"/track/{alert_id}")
    assert r.status_code == 200
    assert "leaflet" in r.text.lower()
    assert "pulse-dot" in r.text          # pulsing marker CSS
    assert 'id="status-badge"' in r.text  # incident status header
    assert "track.badge_escalated" in r.text  # three-state badge: ACTIVE / ESCALATED / RESOLVED (i18n key)
    assert "I'm safe / resolve" in r.text  # resolve button


def test_track_page_unknown_id_is_friendly(tsetup):
    client, key, db_path = tsetup
    r = client.get("/track/no-such-alert")
    assert r.status_code == 404
    assert "not found" in r.text.lower()
    assert 'href="/"' in r.text  # link back home


def test_home_page(tsetup):
    client, key, db_path = tsetup
    r = client.get("/")
    assert r.status_code == 200
    assert "Recent alerts" in r.text
    assert 'href="/simulator"' in r.text


def test_list_alerts(tsetup):
    client, key, db_path = tsetup
    assert client.get("/api/alerts").json() == {"alerts": []}
    a1 = _make_alert(client, key).json()["alert_id"]
    alerts = client.get("/api/alerts").json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["alert_id"] == a1
    assert alerts[0]["owner"] == "Test Owner"
    assert alerts[0]["status"] == "active"
    assert alerts[0]["battery"] == 87
    # limit clamps to [1, 100]
    assert len(client.get("/api/alerts?limit=0").json()["alerts"]) == 1


def test_detail_includes_contacts_with_ack_status(tsetup):
    client, key, db_path = tsetup
    alert_id = _make_alert(client, key).json()["alert_id"]
    d = client.get(f"/api/alerts/{alert_id}").json()
    assert d["contacts"] == [
        {"id": 1, "name": "Asha Sharma", "tier": 1,
         "acked": False, "acked_at": None}]
    assert client.post(f"/api/alerts/{alert_id}/ack",
                       json={"contact_id": 1}).status_code == 200
    d = client.get(f"/api/alerts/{alert_id}").json()
    asha = d["contacts"][0]
    assert asha["acked"] is True
    assert isinstance(asha["acked_at"], int)
