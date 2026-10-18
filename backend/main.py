#!/usr/bin/env python3
"""SilentSOS backend — FastAPI implementation of docs/PROTOCOL.md.

Endpoints:
    POST /api/alert            device alert/update/safe message (encrypted)
    GET  /api/alerts           recent alerts, newest first (operator)
    GET  /api/alerts/{id}      alert detail: status, position, trail, acks
    POST /api/alerts/{id}/safe mark an alert resolved
    POST /api/alerts/{id}/ack  record a trusted-contact acknowledgement
    GET  /api/audit            audit log, newest first (security page)
    GET  /api/health           liveness probe (server time + DB)
    GET  /api/devices          registered devices with last-seen timestamps
    GET  /api/stats            dashboard KPIs + 7-day series (read-only)
    POST /api/simulator/send   demo helper: server-side encryption for /simulator
    POST /api/demo/attack      demo helper: 6-attack security demo, in-process
    POST /api/demo/simulate-attack  demo helper: single attack for security center
    GET  /manifest.json        PWA manifest
    GET  /icons/{name}         PWA icons (192/512 px)
    GET  /sw.js                service worker (offline app shell + API cache)
    GET  /i18n.js              UI strings (English + Nepali)
    GET  /                     operator home page
    GET  /simulator            web device simulator
    GET  /track/{id}           live tracking map (Leaflet)
    GET  /report/{id}           printable incident report
    GET  /security             color-coded audit log viewer

Run:
    cd ~/workspace/silentsos && uvicorn backend.main:app --port 8001

Config (env, see ../.env.example):
    SILENT_DB_PATH  SQLite path (default ./data/silentsos.db)
"""

from __future__ import annotations

import base64
import binascii
import datetime
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)

from backend import demo
from backend import telegram
from backend.crypto import NONCE_BYTES, TAG_BYTES, b64d, decrypt, encrypt
from backend.registry import get_connection, init_db

logger = logging.getLogger("silentsos")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# PROTOCOL.md section 2.4 — validation tunables.
FRESHNESS_WINDOW_S = 60
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW_S = 60
# Extra rule (not in PROTOCOL.md): ignore a new "alert" within this many
# seconds of the device's previous alert.
ALERT_COOLDOWN_S = 30
# Automatic escalation: if nobody acknowledges an active alert within this
# many seconds, tier-2 contacts are notified and the alert is marked
# escalated. Configurable via the ESCALATION_SECONDS environment variable.
ESCALATION_SECONDS = int(os.environ.get("ESCALATION_SECONDS", "60"))
ESCALATION_POLL_S = 5

ALERT_FIELDS = ("device_id", "nonce", "ciphertext", "tag")
PLAINTEXT_FIELDS = ("ts", "lat", "lon", "battery", "type")
ALERT_TYPES = ("alert", "update", "safe")

ERR = {"status": "error"}


def db_path() -> str:
    return os.environ.get("SILENT_DB_PATH",
                           str(PROJECT_ROOT / "data" / "silentsos.db"))


def now_s() -> int:
    return int(time.time())


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(db_path())
    stop_event = threading.Event()
    if telegram.get_token():
        threading.Thread(target=telegram.poll_forever, args=(stop_event,),
                         daemon=True, name="tg-poll").start()
        logger.info("telegram polling started")
    else:
        logger.info("TELEGRAM_BOT_TOKEN not set; telegram disabled")
    threading.Thread(target=_purge_sweeper, args=(stop_event,),
                     daemon=True, name="purge").start()
    threading.Thread(target=_escalation_sweeper, args=(stop_event,),
                     daemon=True, name="escalation").start()
    yield


app = FastAPI(title="SilentSOS", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Harden every response. No CORS middleware is installed on purpose:
    browsers then enforce the same-origin policy and block cross-origin
    reads by default.

    HTTPS is enforced at the edge: hosting platforms (Render/Railway/Fly)
    terminate TLS and forward plain HTTP with X-Forwarded-Proto. A request
    that reached the edge over http is bounced to https (307 preserves
    method + body). Direct local access sets no X-Forwarded-Proto header
    and is left alone.
    """
    proto = request.headers.get("x-forwarded-proto")
    if proto == "http":
        return RedirectResponse(
            str(request.url).replace("http://", "https://", 1),
            status_code=307)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com"
        " https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'")
    if (proto or request.url.scheme) == "https":
        resp.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains")
    return resp


# --- validation helpers -----------------------------------------------------

def _fail(code: int, reason: str, device_id: str | None = None,
          alert_id: str | None = None):
    """Rejection triple: (http_code, body, audit_tuple)."""
    return code, ERR, (device_id, alert_id, "rejected", reason)


def _check_plaintext(p: dict):
    """Validate decrypted plaintext against PROTOCOL.md section 2.3.

    Returns (ok, error_reason)."""
    if set(p.keys()) != set(PLAINTEXT_FIELDS):
        return False, "plaintext"
    ts, lat, lon, battery, typ = (p["ts"], p["lat"], p["lon"],
                                  p["battery"], p["type"])
    if isinstance(ts, bool) or not isinstance(ts, int):
        return False, "plaintext"
    for v, lo, hi in ((lat, -90, 90), (lon, -180, 180)):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False, "plaintext"
        if not (lo <= v <= hi):
            return False, "plaintext"
    if isinstance(battery, bool) or not isinstance(battery, int):
        return False, "plaintext"
    if not (0 <= battery <= 100):
        return False, "plaintext"
    if typ not in ALERT_TYPES:
        return False, "plaintext"
    return True, ""


def _latest_alert(conn: sqlite3.Connection, device_id: str,
                  only_active: bool = False):
    q = ("SELECT * FROM alerts WHERE device_id = ?"
         + (" AND status = 'active'" if only_active else "")
         + " ORDER BY created_at DESC LIMIT 1")
    return conn.execute(q, (device_id,)).fetchone()


def _handle_alert(conn: sqlite3.Connection, raw: bytes):
    """Parse the raw body, then run the validation chain."""
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _fail(400, "format")
    return _handle_parsed(conn, body)


def _handle_parsed(conn: sqlite3.Connection, body):
    """Run the PROTOCOL.md section 2.4 validation chain on a parsed body.

    Returns (http_code, body, (device_id, alert_id, outcome, reason)).
    Writes request_log / used_nonces / alerts rows into conn (uncommitted);
    the caller commits once and always writes the audit_log row.
    """
    server_now = now_s()

    # -- check 0: format ----------------------------------------------------
    if not isinstance(body, dict) or set(body.keys()) != set(ALERT_FIELDS):
        return _fail(400, "format")
    if not all(isinstance(body[f], str) for f in ALERT_FIELDS):
        return _fail(400, "format", body.get("device_id")
                     if isinstance(body.get("device_id"), str) else None)
    device_id = body["device_id"]
    try:
        nonce = b64d(body["nonce"])
        ciphertext = b64d(body["ciphertext"])
        tag = b64d(body["tag"])
    except (binascii.Error, ValueError):
        return _fail(400, "format", device_id)
    if len(nonce) != NONCE_BYTES or len(tag) != TAG_BYTES:
        return _fail(400, "format", device_id)

    # -- check 1: registry --------------------------------------------------
    row = conn.execute(
        "SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
    if row is None or not row["active"]:
        return _fail(401, "registry", device_id)
    # The device talked to us: record last contact (even if later checks fail).
    conn.execute("UPDATE devices SET last_seen = ? WHERE device_id = ?",
                 (server_now, device_id))
    try:
        key = base64.b64decode(row["secret_key"].encode("ascii"),
                               validate=True)
    except (binascii.Error, ValueError):
        return _fail(401, "registry", device_id)

    # -- check 2: decryption ------------------------------------------------
    try:
        plain = decrypt(device_id, key, nonce, ciphertext, tag)
    except Exception:
        return _fail(401, "decryption", device_id)

    # -- plaintext schema (section 2.3) -------------------------------------
    ok, reason = _check_plaintext(plain)
    if not ok:
        return _fail(400, reason, device_id)

    # -- check 3: freshness -------------------------------------------------
    if abs(server_now - plain["ts"]) > FRESHNESS_WINDOW_S:
        return _fail(408, "freshness", device_id)

    # -- check 4: replay (SELECT now; atomic INSERT later) ------------------
    seen = conn.execute(
        "SELECT 1 FROM used_nonces WHERE device_id = ? AND nonce_b64 = ?",
        (device_id, body["nonce"])).fetchone()
    if seen:
        return _fail(409, "replay", device_id)

    # -- check 5: rate limit (sliding 60 s window) --------------------------
    recent = conn.execute(
        "SELECT COUNT(*) AS c FROM request_log"
        " WHERE device_id = ? AND received_at > ?",
        (device_id, server_now - RATE_LIMIT_WINDOW_S)).fetchone()["c"]
    conn.execute(
        "INSERT INTO request_log (device_id, received_at) VALUES (?, ?)",
        (device_id, server_now))
    if recent >= RATE_LIMIT_MAX:
        return _fail(429, "rate_limit", device_id)

    # -- record the nonce (PRIMARY KEY makes check-then-insert atomic) -----
    try:
        conn.execute(
            "INSERT INTO used_nonces (device_id, nonce_b64) VALUES (?, ?)",
            (device_id, body["nonce"]))
    except sqlite3.IntegrityError:
        return _fail(409, "replay", device_id)

    # -- all checks passed: process the event ------------------------------
    typ = plain["type"]
    point = {"ts": plain["ts"], "lat": plain["lat"], "lon": plain["lon"],
             "battery": plain["battery"]}

    if typ == "alert":
        prev = _latest_alert(conn, device_id)
        if prev and server_now - prev["created_at"] < ALERT_COOLDOWN_S:
            # Cooldown: ignore the duplicate, report the existing alert.
            return (200, {"status": "ok", "alert_id": prev["id"]},
                    (device_id, prev["id"], "accepted", "cooldown_ignored"))
        alert_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO alerts (id, device_id, status, latest_lat,"
            " latest_lon, battery, created_at, trail)"
            " VALUES (?, ?, 'active', ?, ?, ?, ?, ?)",
            (alert_id, device_id, plain["lat"], plain["lon"],
             plain["battery"], server_now, json.dumps([point])))
        return (200, {"status": "ok", "alert_id": alert_id},
                (device_id, alert_id, "accepted", "alert_created"))

    if typ == "update":
        active = _latest_alert(conn, device_id, only_active=True)
        if active is None:
            return _fail(400, "no_active_alert", device_id)
        trail = json.loads(active["trail"])
        trail.append(point)
        conn.execute(
            "UPDATE alerts SET latest_lat = ?, latest_lon = ?, battery = ?,"
            " trail = ? WHERE id = ?",
            (plain["lat"], plain["lon"], plain["battery"],
             json.dumps(trail), active["id"]))
        return (200, {"status": "ok", "alert_id": active["id"]},
                (device_id, active["id"], "accepted", "update_appended"))

    # typ == "safe": resolve the active alert, if any.
    active = _latest_alert(conn, device_id, only_active=True)
    if active is None:
        alert_id = str(uuid.uuid4())
        return (200, {"status": "ok", "alert_id": alert_id},
                (device_id, alert_id, "accepted", "safe_noop"))
    conn.execute(
        "UPDATE alerts SET status = 'safe', resolved_at = ?,"
        " latest_lat = ?, latest_lon = ?, battery = ? WHERE id = ?",
        (server_now, plain["lat"], plain["lon"], plain["battery"],
         active["id"]))
    return (200, {"status": "ok", "alert_id": active["id"]},
            (device_id, active["id"], "accepted", "safe_resolved"))


# --- endpoints --------------------------------------------------------------

def _audit(conn: sqlite3.Connection, device_id, alert_id, outcome, reason):
    conn.execute(
        "INSERT INTO audit_log (device_id, alert_id, outcome, reason,"
        " received_at) VALUES (?, ?, ?, ?, ?)",
        (device_id, alert_id, outcome, reason, now_s()))


def _finish(conn: sqlite3.Connection, code: int, payload: dict, audit: tuple):
    """Write the audit row, commit, and build the JSON response."""
    _audit(conn, *audit)
    conn.commit()
    return JSONResponse(status_code=code, content=payload)


def _notify_later(fn, *args) -> None:
    """Run a notification in a daemon thread; failures are logged, never
    raised, so alert handling is never blocked by Telegram."""

    def _guarded():
        try:
            fn(*args)
        except Exception:
            logger.exception("telegram notification failed")

    threading.Thread(target=_guarded, daemon=True,
                     name="tg-notify").start()


def _notify_for_alert(alert_id: str, kind: str) -> None:
    """Build the Telegram payload and dispatch it in the background.

    kind is "alert" (tier 1 only), "escalated" (tier 2 only) or "safe"
    (all tiers). Never raises; never blocks the request."""
    try:
        tier = {"alert": 1, "escalated": 2}.get(kind)
        payload = telegram._linked_contacts_payload(db_path(), alert_id,
                                                    tier=tier)
    except Exception:
        logger.exception("telegram payload build failed")
        return
    if payload is None:
        return
    sender = {"alert": telegram.send_alert_notifications,
              "escalated": telegram.send_escalation_notifications,
              "safe": telegram.send_safe_notifications}[kind]
    _notify_later(sender, payload)


def check_escalations(now: int | None = None) -> int:
    """Escalate overdue active alerts. Returns the number escalated.

    An active alert with no acknowledgements older than ESCALATION_SECONDS
    gets escalated_at set, an `escalated_tier2` audit row, and a tier-2
    Telegram notification. Idempotent: already-escalated alerts are skipped.
    """
    now = now if now is not None else now_s()
    conn = get_connection(db_path())
    try:
        rows = conn.execute(
            "SELECT id, device_id FROM alerts"
            " WHERE status = 'active' AND escalated_at IS NULL"
            " AND created_at <= ?", (now - ESCALATION_SECONDS,)).fetchall()
        escalated = 0
        for r in rows:
            acked = conn.execute(
                "SELECT COUNT(*) FROM acks WHERE alert_id = ?",
                (r["id"],)).fetchone()[0]
            if acked:
                continue
            conn.execute("UPDATE alerts SET escalated_at = ? WHERE id = ?",
                         (now, r["id"]))
            _audit(conn, r["device_id"], r["id"], "accepted",
                   "escalated_tier2")
            conn.commit()
            _notify_for_alert(r["id"], "escalated")
            escalated += 1
        return escalated
    finally:
        conn.close()


def _escalation_sweeper(stop_event: threading.Event) -> None:
    """Poll for overdue alerts every ESCALATION_POLL_S seconds. Never raises."""
    while not stop_event.wait(ESCALATION_POLL_S):
        try:
            check_escalations()
        except Exception:
            logger.exception("escalation check failed")


@app.post("/api/alert")
async def post_alert(request: Request):
    raw = await request.body()
    conn = get_connection(db_path())
    try:
        code, payload, audit = _handle_alert(conn, raw)
        resp = _finish(conn, code, payload, audit)
        _, alert_id, _, reason = audit
        if reason == "alert_created":
            _notify_for_alert(alert_id, "alert")
        elif reason == "safe_resolved":
            _notify_for_alert(alert_id, "safe")
        return resp
    except Exception:
        conn.rollback()
        return JSONResponse(status_code=500, content=ERR)
    finally:
        conn.close()


@app.post("/api/simulator/send")
async def simulator_send(request: Request):
    """Demo-only helper for the web simulator (/simulator).

    Accepts plaintext fields, encrypts with the device's registry key
    *server-side*, then runs the exact same validation chain as
    POST /api/alert. The device key never reaches the browser.
    """
    try:
        req = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return JSONResponse(status_code=400, content=ERR)
    if not isinstance(req, dict):
        return JSONResponse(status_code=400, content=ERR)
    device_id, typ = req.get("device_id"), req.get("type")
    lat, lon, battery = req.get("lat"), req.get("lon"), req.get("battery")

    def _bad():
        return JSONResponse(status_code=400, content=ERR)

    if not isinstance(device_id, str) or typ not in ALERT_TYPES:
        return _bad()
    for v, lo, hi in ((lat, -90, 90), (lon, -180, 180)):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return _bad()
        if not (lo <= v <= hi):
            return _bad()
    if (isinstance(battery, bool) or not isinstance(battery, int)
            or not (0 <= battery <= 100)):
        return _bad()

    conn = get_connection(db_path())
    try:
        row = conn.execute(
            "SELECT * FROM devices WHERE device_id = ?",
            (device_id,)).fetchone()
        if row is None or not row["active"]:
            _audit(conn, device_id, None, "rejected", "registry")
            conn.commit()
            return JSONResponse(status_code=401, content=ERR)
        key = base64.b64decode(row["secret_key"].encode("ascii"),
                               validate=True)
        nonce_b64, ct_b64, tag_b64 = encrypt(
            device_id, key,
            {"ts": now_s(), "lat": lat, "lon": lon,
             "battery": battery, "type": typ})
        body = {"device_id": device_id, "nonce": nonce_b64,
                "ciphertext": ct_b64, "tag": tag_b64}
        code, payload, audit = _handle_parsed(conn, body)
        return _finish(conn, code, payload, audit)
    except Exception:
        conn.rollback()
        return JSONResponse(status_code=500, content=ERR)
    finally:
        conn.close()


@app.post("/api/demo/attack")
def demo_attack():
    """Run the 6-attack security demo in-process; returns the PASS/FAIL table.

    Demo helper (like /api/simulator/send): runs against an ephemeral
    device so it never disturbs real alerts, contacts, or rate limits,
    and notifies nobody. Powers the home page's "Skip to attack demo"."""
    rows = demo.run_attack_demo(_handle_parsed, db_path())
    passed = sum(1 for r in rows if r["result"] == "PASS")
    return {"results": rows, "passed": passed, "total": len(rows)}


@app.post("/api/demo/simulate-attack")
async def demo_simulate_attack(request: Request):
    """Fire one attack (replay|tampered|flood) at the live validation chain.

    Demo helper for the security center's "Simulate attack" buttons.
    Runs on an ephemeral device (real device's rate limit untouched);
    audit rows are kept so the live feed shows the attack. Returns each
    attempt with its HTTP code, color-coded verdict, and validation
    checklist."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content=ERR)
    attack = body.get("attack") if isinstance(body, dict) else None
    if attack not in ("replay", "tampered", "flood"):
        return JSONResponse(status_code=400, content=ERR)
    return demo.simulate_attack(_handle_parsed, db_path(), attack)


@app.get("/simulator", response_class=HTMLResponse)
def simulator_page():
    html_path = PROJECT_ROOT / "simulator" / "web.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


def _static_page(name: str) -> HTMLResponse:
    return HTMLResponse(
        (PROJECT_ROOT / "backend" / "static" / name).read_text(
            encoding="utf-8"))


_TRACK_404 = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Alert not found — SilentSOS</title>
<style>body{font-family:system-ui,sans-serif;background:#0b0e14;color:#e6edf3;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;
padding:20px;text-align:center}.card{max-width:420px}a{color:#58a6ff}</style>
</head><body><div class="card">
<h1>🔍 Alert not found</h1>
<p>This tracking link doesn't match any alert. It may have been typed
incorrectly, or the alert was created on a different server.</p>
<p><a href="/">← Back to the operator home page</a></p>
</div></body></html>"""


@app.get("/track/{alert_id}", response_class=HTMLResponse)
def track_page(alert_id: str):
    """Live tracking page (Leaflet map) linked from Telegram notifications."""
    conn = get_connection(db_path())
    try:
        row = conn.execute("SELECT id FROM alerts WHERE id = ?",
                           (alert_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return HTMLResponse(_TRACK_404, status_code=404)
    return _static_page("track.html")


@app.get("/track-shell", response_class=HTMLResponse, include_in_schema=False)
def track_shell():
    """Track page shell for the service worker's offline cache.

    Same static HTML as /track/{id} (which reads the id from the URL);
    no alert data is embedded, so no id check is needed."""
    return _static_page("track.html")


@app.get("/report/{alert_id}", response_class=HTMLResponse)
def report_page(alert_id: str):
    """Printable incident report (alert detail, trail, timeline, security)."""
    conn = get_connection(db_path())
    try:
        row = conn.execute("SELECT id FROM alerts WHERE id = ?",
                           (alert_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return HTMLResponse(_TRACK_404, status_code=404)
    return _static_page("report.html")


@app.get("/", response_class=HTMLResponse)
def home_page():
    """Operator home: recent alerts, links to simulator and tracking pages."""
    return _static_page("home.html")


@app.get("/security", response_class=HTMLResponse)
def security_page():
    """Security demo page: readable, color-coded audit log."""
    return _static_page("security.html")


@app.get("/manifest.json")
def pwa_manifest():
    """Web app manifest for installability."""
    return {
        "name": "SilentSOS Operator",
        "short_name": "SilentSOS",
        "description": "Discreet emergency alerts — operator console",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0d1117",
        "theme_color": "#0d1117",
        "lang": "en",
        "icons": [
            {"src": "/icons/icon-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": "/icons/icon-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
        ],
    }


@app.get("/icons/{name}")
def pwa_icon(name: str):
    """PWA icons. Only the two generated sizes are served."""
    if name not in ("icon-192.png", "icon-512.png"):
        return JSONResponse(status_code=404, content=ERR)
    path = PROJECT_ROOT / "backend" / "static" / "icons" / name
    return FileResponse(path, media_type="image/png")


@app.get("/sw.js")
def service_worker():
    """Service worker: app-shell + API cache for offline use."""
    path = PROJECT_ROOT / "backend" / "static" / "sw.js"
    return FileResponse(path, media_type="application/javascript")


@app.get("/i18n.js")
def translations():
    """UI strings (English + Nepali) shared by all pages."""
    path = PROJECT_ROOT / "backend" / "static" / "i18n.js"
    return FileResponse(path, media_type="application/javascript")


@app.get("/api/alerts/{alert_id}")
def get_alert(alert_id: str):
    conn = get_connection(db_path())
    try:
        row = conn.execute(
            "SELECT a.*, d.owner_name FROM alerts a"
            " JOIN devices d ON d.device_id = a.device_id"
            " WHERE a.id = ?",
            (alert_id,)).fetchone()
        if row is None:
            return JSONResponse(status_code=404, content=ERR)
        acks = conn.execute(
            "SELECT a.contact_id, c.name, a.acked_at FROM acks a"
            " JOIN contacts c ON c.id = a.contact_id"
            " WHERE a.alert_id = ? ORDER BY a.acked_at ASC",
            (alert_id,)).fetchall()
        contacts = conn.execute(
            "SELECT id, name, tier FROM contacts WHERE device_id = ?"
            " ORDER BY priority", (row["device_id"],)).fetchall()
        ack_map = {a["contact_id"]: a["acked_at"] for a in acks}
        return {
            "alert_id": row["id"],
            "device_id": row["device_id"],
            "owner_name": row["owner_name"],
            "status": row["status"],
            "lat": row["latest_lat"],
            "lon": row["latest_lon"],
            "battery": row["battery"],
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
            "escalated_at": row["escalated_at"],
            "escalation_seconds": ESCALATION_SECONDS,
            "trail": json.loads(row["trail"]),
            "acks": [{"contact_id": a["contact_id"], "name": a["name"],
                      "acked_at": a["acked_at"]} for a in acks],
            "contacts": [{"id": c["id"], "name": c["name"], "tier": c["tier"],
                          "acked": c["id"] in ack_map,
                          "acked_at": ack_map.get(c["id"])}
                         for c in contacts],
        }
    finally:
        conn.close()


@app.get("/api/alerts")
def list_alerts(limit: int = 20):
    """Recent alerts, newest first (for the operator home page)."""
    limit = max(1, min(limit, 100))
    conn = get_connection(db_path())
    try:
        rows = conn.execute(
            "SELECT a.id, a.device_id, a.status, a.latest_lat, a.latest_lon,"
            " a.battery, a.created_at, a.resolved_at, d.owner_name,"
            " (SELECT MIN(acked_at) FROM acks WHERE alert_id = a.id)"
            " AS first_acked_at"
            " FROM alerts a JOIN devices d ON d.device_id = a.device_id"
            " ORDER BY a.created_at DESC LIMIT ?", (limit,)).fetchall()
        return {"alerts": [
            {"alert_id": r["id"], "device_id": r["device_id"],
             "owner": r["owner_name"], "status": r["status"],
             "lat": r["latest_lat"], "lon": r["latest_lon"],
             "battery": r["battery"], "created_at": r["created_at"],
             "resolved_at": r["resolved_at"],
             "first_acked_at": r["first_acked_at"]} for r in rows]}
    finally:
        conn.close()


@app.get("/api/audit")
def audit_log_api(limit: int = 100):
    """Audit log entries, newest first (for the /security page)."""
    limit = max(1, min(limit, 500))
    conn = get_connection(db_path())
    try:
        rows = conn.execute(
            "SELECT id, device_id, alert_id, outcome, reason, received_at"
            " FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return {"entries": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/health")
def health():
    """Liveness probe: server time + DB reachability."""
    conn = get_connection(db_path())
    try:
        conn.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        conn.close()
    return {"status": "ok" if db_ok else "degraded",
            "time": now_s(), "db": "ok" if db_ok else "error"}


@app.get("/api/devices")
def list_devices():
    """Registered devices with last-seen timestamps (operator home page)."""
    conn = get_connection(db_path())
    try:
        rows = conn.execute(
            "SELECT device_id, owner_name, active, created_at, last_seen"
            " FROM devices ORDER BY device_id").fetchall()
        return {"devices": [dict(r) for r in rows]}
    finally:
        conn.close()


ONLINE_WINDOW_S = 300  # last_seen within this many seconds = "online"


@app.get("/api/stats")
def dashboard_stats():
    """Dashboard KPIs + 7-day series. Read-only, additive.

    Response time = alert created_at -> first acknowledgement. "Today"
    uses the server-local day boundary."""
    conn = get_connection(db_path())
    try:
        now = now_s()
        active = conn.execute(
            "SELECT COUNT(*) AS c FROM alerts WHERE status = 'active'"
        ).fetchone()["c"]
        devs = conn.execute(
            "SELECT last_seen FROM devices").fetchall()
        online = sum(1 for d in devs
                     if d["last_seen"] and now - d["last_seen"] <= ONLINE_WINDOW_S)
        today = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0)
        day0 = int(today.timestamp())
        resolved_today = conn.execute(
            "SELECT COUNT(*) AS c FROM alerts WHERE resolved_at >= ?",
            (day0,)).fetchone()["c"]
        week_ago = now - 7 * 86400
        resp_rows = conn.execute(
            "SELECT a.created_at, MIN(k.acked_at) AS first_ack"
            " FROM alerts a JOIN acks k ON k.alert_id = a.id"
            " WHERE a.created_at >= ? GROUP BY a.id",
            (week_ago,)).fetchall()
        avg_resp = (sum(r["first_ack"] - r["created_at"] for r in resp_rows)
                    / len(resp_rows)) if resp_rows else None

        labels, per_day, resp_day = [], [], []
        for i in range(6, -1, -1):
            d0 = today - datetime.timedelta(days=i)
            d1 = d0 + datetime.timedelta(days=1)
            t0, t1 = int(d0.timestamp()), int(d1.timestamp())
            labels.append(d0.strftime("%a"))
            per_day.append(conn.execute(
                "SELECT COUNT(*) AS c FROM alerts"
                " WHERE created_at >= ? AND created_at < ?", (t0, t1)
            ).fetchone()["c"])
            rws = conn.execute(
                "SELECT a.created_at, MIN(k.acked_at) AS first_ack"
                " FROM alerts a JOIN acks k ON k.alert_id = a.id"
                " WHERE a.created_at >= ? AND a.created_at < ?"
                " GROUP BY a.id", (t0, t1)).fetchall()
            resp_day.append(
                sum(r["first_ack"] - r["created_at"] for r in rws) / len(rws)
                if rws else None)

        return {
            "kpis": {
                "active_alerts": active,
                "devices_online": online,
                "devices_total": len(devs),
                "avg_response_s": avg_resp,
                "avg_response_n": len(resp_rows),
                "resolved_today": resolved_today,
            },
            "series": {
                "labels": labels,
                "alerts": per_day,
                "avg_response_s": resp_day,
            },
        }
    finally:
        conn.close()


def purge_expired_locations(path: str | None = None,
                              older_than_s: int = 86400) -> int:
    """Delete location data for alerts resolved more than `older_than_s`
    ago (default 24 h): latest position nulled, trail emptied. The alert
    record itself (status, timestamps) is kept for the audit trail.
    Returns the number of alerts purged."""
    db = path or db_path()
    cutoff = time.time() - older_than_s
    conn = get_connection(db)
    try:
        cur = conn.execute(
            "UPDATE alerts SET latest_lat = NULL, latest_lon = NULL,"
            " trail = '[]' WHERE status = 'safe' AND resolved_at IS NOT NULL"
            " AND resolved_at <= ? AND latest_lat IS NOT NULL",
            (cutoff,))
        n = cur.rowcount
        conn.commit()
        if n:
            logger.info("purged location data for %d resolved alerts", n)
        return n
    finally:
        conn.close()


def _purge_sweeper(stop_event: threading.Event) -> None:
    """Run the location purge hourly (plus once at startup). Never raises."""
    try:
        purge_expired_locations()
    except Exception:
        logger.exception("location purge failed")
    while not stop_event.wait(3600):
        try:
            purge_expired_locations()
        except Exception:
            logger.exception("location purge failed")


@app.post("/api/alerts/{alert_id}/safe")
def mark_safe(alert_id: str):
    conn = get_connection(db_path())
    try:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?",
                           (alert_id,)).fetchone()
        if row is None:
            return JSONResponse(status_code=404, content=ERR)
        if row["status"] != "safe":
            conn.execute(
                "UPDATE alerts SET status = 'safe', resolved_at = ?"
                " WHERE id = ?", (now_s(), alert_id))
            conn.commit()
            _notify_for_alert(alert_id, "safe")
        return {"status": "ok", "alert_id": alert_id}
    finally:
        conn.close()


@app.post("/api/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str, request: Request):
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return JSONResponse(status_code=400, content=ERR)
    contact_id = body.get("contact_id") if isinstance(body, dict) else None
    if isinstance(contact_id, bool) or not isinstance(contact_id, int):
        return JSONResponse(status_code=400, content=ERR)

    conn = get_connection(db_path())
    try:
        alert = conn.execute("SELECT * FROM alerts WHERE id = ?",
                             (alert_id,)).fetchone()
        if alert is None:
            return JSONResponse(status_code=404, content=ERR)
        contact = conn.execute(
            "SELECT * FROM contacts WHERE id = ? AND device_id = ?",
            (contact_id, alert["device_id"])).fetchone()
        if contact is None:
            return JSONResponse(status_code=404, content=ERR)
        try:
            conn.execute(
                "INSERT INTO acks (alert_id, contact_id, acked_at)"
                " VALUES (?, ?, ?)", (alert_id, contact_id, now_s()))
            conn.commit()
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=409, content=ERR)
        return {"status": "ok", "alert_id": alert_id,
                "contact_id": contact_id}
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8001)
