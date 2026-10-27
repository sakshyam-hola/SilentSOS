"""PWA (manifest/icons/service worker), i18n file, and a11y/hc toggles."""
import json
import re

from backend.tests.test_api import setup  # noqa: F401 (fixture)


def _page(client, path):
    r = client.get(path)
    assert r.status_code == 200
    return r.text


def test_manifest(setup):
    client, _, _ = setup
    r = client.get("/manifest.json")
    assert r.status_code == 200
    m = r.json()
    assert m["name"] == "SilentSOS Operator"
    assert m["start_url"] == "/"
    assert m["display"] == "standalone"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes


def test_icons_served(setup):
    client, _, _ = setup
    for name in ("icon-192.png", "icon-512.png"):
        r = client.get(f"/icons/{name}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/icons/icon-999.png").status_code == 404


def test_service_worker_served(setup):
    client, _, _ = setup
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "application/javascript" in r.headers["content-type"]
    assert "silentsos-v1" in r.text
    assert "/track/" in r.text


def test_track_shell_for_offline_cache(setup):
    client, _, _ = setup
    r = client.get("/track-shell")
    assert r.status_code == 200
    assert 'id="offline-banner"' in r.text
    # Unknown alert ids still 404 on the real track route.
    assert client.get("/track/does-not-exist").status_code == 404


def test_i18n_file_has_both_languages(setup):
    client, _, _ = setup
    r = client.get("/i18n.js")
    assert r.status_code == 200
    assert "application/javascript" in r.headers["content-type"]
    # Extract the STR object keys by evaluating the lang blocks.
    en = set(re.findall(r'"([a-z0-9_.]+)":', r.text.split("ne: {")[0]))
    ne_block = r.text.split("ne: {", 1)[1]
    ne = set(re.findall(r'"([a-z0-9_.]+)":', ne_block))
    assert en == ne, f"i18n key mismatch: {en ^ ne}"
    assert len(en) > 150
    # Spot-check a Nepali translation is present and non-empty.
    assert "सक्रिय अलर्टहरू" in r.text


def test_pages_wire_pwa_and_toggles(setup):
    client, _, _ = setup
    for path in ("/", "/simulator", "/security"):
        html = _page(client, path)
        assert 'rel="manifest"' in html, path
        assert 'id="lang-toggle"' in html, path
        assert 'id="hc-toggle"' in html, path
        assert "/i18n.js" in html, path
        assert "serviceWorker" in html, path
        assert ":focus-visible" in html, path
        assert "body.hc" in html, path


def test_track_page_wires_pwa_i18n_offline(setup):
    from backend.tests.test_api import make_body, DEVICE_ID
    client, key, _ = setup
    alert_id = client.post(
        "/api/alert", json=make_body(DEVICE_ID, key)).json()["alert_id"]
    html = _page(client, f"/track/{alert_id}")
    assert 'rel="manifest"' in html
    assert 'id="lang-toggle"' in html
    assert 'id="hc-toggle"' in html
    assert 'id="offline-banner"' in html
    assert "silentsos:track:" in html  # localStorage last-known key
    assert ":focus-visible" in html
