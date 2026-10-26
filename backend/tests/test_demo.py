"""On-screen attack demo + home page demo scenario UI."""
import time

from backend.tests.test_api import make_body, setup  # noqa: F401 (fixture)


def test_attack_demo_endpoint_blocks_all_attacks(setup):
    client, _, _ = setup
    r = client.post("/api/demo/attack")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 6
    assert data["passed"] == 6
    names = [row["name"] for row in data["results"]]
    assert names == ["Replay attack", "Tampered ciphertext",
                    "Expired timestamp", "Wrong key", "Unknown device",
                    "Flood (20 rapid)"]
    for row in data["results"]:
        assert row["result"] == "PASS", row


def test_home_has_demo_scenario(setup):
    client, _, _ = setup
    r = client.get("/")
    assert r.status_code == 200
    for needle in ("Run demo scenario", "Skip to attack demo",
                   "demo-steps", "demo-log", "demo-attack-results",
                   "simulated contact", "/api/demo/attack",
                   "26.4525", "87.2718"):
        assert needle in r.text, needle


def test_stats_kpis_and_series(setup):
    from backend.tests.test_api import DEVICE_ID
    client, key, _ = setup
    # One alert, acked after ~2s, then resolved.
    alert_id = client.post(
        "/api/alert", json=make_body(DEVICE_ID, key)).json()["alert_id"]
    time.sleep(2)
    client.post(f"/api/alerts/{alert_id}/ack", json={"contact_id": 1})
    client.post(f"/api/alerts/{alert_id}/safe")

    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    k = data["kpis"]
    assert k["active_alerts"] == 0
    assert k["devices_total"] == 1
    assert k["resolved_today"] == 1
    assert k["avg_response_n"] == 1
    assert 1 <= k["avg_response_s"] <= 10
    assert len(data["series"]["labels"]) == 7
    assert sum(data["series"]["alerts"]) == 1
    assert data["series"]["avg_response_s"][-1] == k["avg_response_s"]

    # Recent-alerts list carries the first-ack timestamp for the table.
    alerts = client.get("/api/alerts?limit=5").json()["alerts"]
    assert alerts[0]["first_acked_at"] is not None
    assert (alerts[0]["first_acked_at"] - alerts[0]["created_at"]) >= 1


def test_home_has_dashboard(setup):
    client, _, _ = setup
    r = client.get("/")
    assert r.status_code == 200
    for needle in ('id="kpis"', 'id="chart-wrap"', 'id="devices"',
                   'id="alerts"', "chart.umd.min.js", "Active alerts",
                   "Devices online", "Avg response time", "Resolved today",
                   "common.view"):
        assert needle in r.text, needle


def test_simulate_attack_endpoint(setup):
    client, _, _ = setup

    r = client.post("/api/demo/simulate-attack", json={"attack": "replay"})
    assert r.status_code == 200
    res = r.json()["results"]
    assert [x["code"] for x in res] == [200, 409]
    assert res[1]["verdict"] == "Replay blocked"
    assert res[1]["kind"] == "bad"
    assert [s["state"] for s in res[1]["steps"]] == [
        "pass", "pass", "pass", "fail", "skip"]

    r = client.post("/api/demo/simulate-attack", json={"attack": "tampered"})
    assert r.status_code == 200
    res = r.json()["results"]
    assert [x["code"] for x in res] == [401]
    assert res[0]["verdict"] == "Tampered"
    assert [s["state"] for s in res[0]["steps"]] == [
        "pass", "fail", "skip", "skip", "skip"]

    r = client.post("/api/demo/simulate-attack", json={"attack": "flood"})
    assert r.status_code == 200
    res = r.json()["results"]
    assert len(res) == 8
    assert [x["code"] for x in res] == [200] * 5 + [429] * 3
    assert res[7]["verdict"] == "Rate limited"
    assert [s["state"] for s in res[7]["steps"]] == [
        "pass", "pass", "pass", "pass", "fail"]

    # Audit rows stay for the live feed; the ephemeral device is gone.
    reasons = [e["reason"] for e in
               client.get("/api/audit?limit=500").json()["entries"]]
    assert "replay" in reasons and "decryption" in reasons
    assert "rate_limit" in reasons
    devs = [d["device_id"]
            for d in client.get("/api/devices").json()["devices"]]
    assert not any(d.startswith("dev-atk-") for d in devs)


def test_simulate_attack_rejects_bad_input(setup):
    client, _, _ = setup
    assert client.post(
        "/api/demo/simulate-attack",
        json={"attack": "nuke"}).status_code == 400
    assert client.post("/api/demo/simulate-attack").status_code == 400
