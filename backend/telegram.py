#!/usr/bin/env python3
"""SilentSOS Telegram notifications.

- Reads the bot token from TELEGRAM_BOT_TOKEN (never hardcoded).
- Sends alert / safe / ack-confirmation messages to linked contacts.
- Long-polls getUpdates in a background thread: handles /start <code>
  (links a Telegram chat to a contacts row) and "ack" replies (records
  into the acks table).
- Every send is failure-safe: a missing token or a Telegram error is
  logged and never raised, so alerts always succeed regardless.

Usage:
    python backend/telegram.py --codes
        print every contact's /start link code (generates missing ones)
    python backend/telegram.py --add-contact "Your Name" "+97798XXXXXXXX" [--device dev-001]
        add yourself as a contact for testing
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import sqlite3
import sys
import threading
import time
from pathlib import Path

# Allow `python backend/telegram.py` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from backend.registry import db_path as registry_db_path, get_connection, init_db

logger = logging.getLogger("silentsos.telegram")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- configuration ----------------------------------------------------------

def get_token() -> str | None:
    """Bot token from the environment. None when not configured."""
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


def api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{get_token()}/{method}"


def public_url() -> str:
    """Base URL used for tracking links (override for tunnels/prod)."""
    return os.environ.get("PUBLIC_BASE_URL",
                           "http://127.0.0.1:8001").rstrip("/")


def tracking_link(alert_id: str) -> str:
    return f"{public_url()}/track/{alert_id}"


# --- sending (never raises) -------------------------------------------------

def send_message(chat_id: int, text: str) -> bool:
    """Send a Telegram message. Returns True on success, False otherwise.

    Never raises: a missing token or any API/network error is logged.
    """
    if not get_token():
        logger.warning("TELEGRAM_BOT_TOKEN not set; skipping message")
        return False
    try:
        r = requests.post(api_url("sendMessage"),
                          json={"chat_id": chat_id, "text": text},
                          timeout=10)
        if r.status_code != 200:
            logger.error("telegram sendMessage HTTP %s: %s",
                         r.status_code, r.text[:200])
            return False
        return True
    except Exception:
        logger.exception("telegram sendMessage failed")
        return False


# --- notification payloads --------------------------------------------------

def _linked_contacts_payload(db_path: str, alert_id: str,
                             tier: int | None = None) -> dict | None:
    """Owner, battery and linked contacts for an alert. None if unknown.

    tier filters to one escalation tier (1 or 2); None means all tiers."""
    conn = get_connection(db_path)
    try:
        alert = conn.execute("SELECT * FROM alerts WHERE id = ?",
                             (alert_id,)).fetchone()
        if alert is None:
            return None
        dev = conn.execute(
            "SELECT owner_name FROM devices WHERE device_id = ?",
            (alert["device_id"],)).fetchone()
        q = ("SELECT id, name, telegram_chat_id FROM contacts"
             " WHERE device_id = ? AND telegram_chat_id IS NOT NULL")
        params: list = [alert["device_id"]]
        if tier is not None:
            q += " AND tier = ?"
            params.append(tier)
        contacts = conn.execute(q, params).fetchall()
        return {
            "owner": dev["owner_name"],
            "alert_id": alert_id,
            "battery": alert["battery"],
            "tracking_link": tracking_link(alert_id),
            "contacts": [{"chat_id": c["telegram_chat_id"], "name": c["name"]}
                         for c in contacts],
        }
    finally:
        conn.close()


def send_alert_notifications(payload: dict) -> None:
    """Notify linked contacts of a new alert. Never raises."""
    if not get_token():
        logger.warning("TELEGRAM_BOT_TOKEN not set; skipping alert notify")
        return
    if not payload["contacts"]:
        logger.info("no linked Telegram contacts for device; skipping")
        return
    text = (f"🚨 SilentSOS alert from {payload['owner']}. "
            f"Live location: {payload['tracking_link']}. "
            f"Battery {payload['battery']}%. Reply 'ack' if you're responding.")
    for c in payload["contacts"]:
        send_message(c["chat_id"], text)


def send_safe_notifications(payload: dict) -> None:
    """Notify linked contacts that the owner is safe. Never raises."""
    if not get_token():
        logger.warning("TELEGRAM_BOT_TOKEN not set; skipping safe notify")
        return
    if not payload["contacts"]:
        logger.info("no linked Telegram contacts for device; skipping")
        return
    text = f"✅ {payload['owner']} has marked themselves safe."
    for c in payload["contacts"]:
        send_message(c["chat_id"], text)


def send_escalation_notifications(payload: dict) -> None:
    """Notify tier-2 contacts: nobody in tier 1 acknowledged in time."""
    if not get_token():
        logger.warning("TELEGRAM_BOT_TOKEN not set; skipping escalation notify")
        return
    if not payload["contacts"]:
        logger.info("no linked tier-2 Telegram contacts for device; skipping")
        return
    text = (f"🚨 ESCALATED: SilentSOS alert from {payload['owner']} — "
            f"no response from tier 1. "
            f"Live location: {payload['tracking_link']}. "
            f"Battery {payload['battery']}%. Reply 'ack' if you're responding.")
    for c in payload["contacts"]:
        send_message(c["chat_id"], text)


# --- incoming updates: /start linking + ack --------------------------------

def ensure_link_code(db_path: str, contact_id: int) -> str:
    """Return the contact's link code, generating one if missing."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT link_code FROM contacts WHERE id = ?",
                           (contact_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown contact id {contact_id}")
        if row["link_code"]:
            return row["link_code"]
        for _ in range(10):
            code = secrets.token_hex(3).upper()  # e.g. "A3F9C1"
            try:
                conn.execute("UPDATE contacts SET link_code = ? WHERE id = ?",
                             (code, contact_id))
                conn.commit()
                return code
            except sqlite3.IntegrityError:
                continue  # collision; retry
        raise RuntimeError("could not generate a unique link code")
    finally:
        conn.close()


def _handle_start(conn: sqlite3.Connection, chat_id: int, text: str) -> None:
    parts = text.split(None, 1)
    code = parts[1].strip().upper() if len(parts) > 1 else ""
    row = None
    if code:
        row = conn.execute(
            "SELECT c.id, c.name, d.owner_name FROM contacts c"
            " JOIN devices d ON d.device_id = c.device_id"
            " WHERE c.link_code = ?", (code,)).fetchone()
    if row is None:
        send_message(chat_id, "❌ Unknown link code. Ask the device owner "
                              "for your personal /start code.")
        return
    conn.execute("UPDATE contacts SET telegram_chat_id = ? WHERE id = ?",
                 (str(chat_id), row["id"]))
    send_message(chat_id,
                 f"✅ This chat is now linked to {row['name']} "
                 f"({row['owner_name']}'s contact). "
                 f"You'll receive SilentSOS alerts here.")


def _handle_ack(conn: sqlite3.Connection, chat_id: int) -> None:
    contact = conn.execute(
        "SELECT c.id, c.name, c.device_id, d.owner_name FROM contacts c"
        " JOIN devices d ON d.device_id = c.device_id"
        " WHERE c.telegram_chat_id = ?", (str(chat_id),)).fetchone()
    if contact is None:
        send_message(chat_id, "ℹ️ This chat isn't linked yet. Send "
                              "/start <code> with the code from the device "
                              "owner first.")
        return
    alert = conn.execute(
        "SELECT id FROM alerts WHERE device_id = ? AND status = 'active'"
        " ORDER BY created_at DESC LIMIT 1",
        (contact["device_id"],)).fetchone()
    if alert is None:
        send_message(chat_id, "ℹ️ No active alert right now.")
        return
    conn.execute("INSERT OR IGNORE INTO acks (alert_id, contact_id, acked_at)"
                 " VALUES (?, ?, ?)",
                 (alert["id"], contact["id"], int(time.time())))
    send_message(chat_id,
                 f"✅ Thanks {contact['name']} — you're marked as responding "
                 f"to {contact['owner_name']}'s alert.")


def process_update(update: dict, db_path: str) -> None:
    """Handle one Telegram update (message only). Commits on success."""
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if not isinstance(chat_id, int) or not text:
        return
    conn = get_connection(db_path)
    try:
        if text.startswith("/start"):
            _handle_start(conn, chat_id, text)
        elif text.lower() == "ack":
            _handle_ack(conn, chat_id)
        # other messages are ignored
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_updates(offset: int, timeout: int = 25) -> list:
    r = requests.post(api_url("getUpdates"),
                      json={"offset": offset, "timeout": timeout,
                            "allowed_updates": ["message"]},
                      timeout=timeout + 10)
    r.raise_for_status()
    data = r.json()
    return data.get("result", []) if data.get("ok") else []


def poll_forever(stop_event: threading.Event, db_path: str | None = None):
    """Long-poll getUpdates until stop_event is set. Never raises."""
    path = db_path or registry_db_path()
    offset = 0
    logger.info("telegram polling started")
    while not stop_event.is_set():
        try:
            updates = get_updates(offset)
        except Exception:
            logger.exception("telegram getUpdates failed; retrying in 5s")
            stop_event.wait(5)
            continue
        for u in updates:
            offset = max(offset, u.get("update_id", 0) + 1)
            try:
                process_update(u, path)
            except Exception:
                logger.exception("telegram update handling failed")


# --- CLI --------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="SilentSOS Telegram helper")
    ap.add_argument("--db", default=None,
                    help="SQLite path (default: $SILENT_DB_PATH)")
    ap.add_argument("--codes", action="store_true",
                    help="print every contact's /start link code")
    ap.add_argument("--add-contact", nargs=2, metavar=("NAME", "PHONE"),
                    help="add a contact (for linking your own Telegram)")
    ap.add_argument("--device", default="dev-001")
    ap.add_argument("--relation", default="friend")
    ap.add_argument("--tier", type=int, default=1, choices=(1, 2),
                    help="escalation tier for --add-contact")
    args = ap.parse_args()
    path = args.db or registry_db_path()
    init_db(path)  # create tables + run column migrations

    if args.codes:
        conn = get_connection(path)
        rows = conn.execute(
            "SELECT id, device_id, name, link_code, telegram_chat_id"
            " FROM contacts ORDER BY device_id, priority").fetchall()
        conn.close()
        if not rows:
            print("No contacts in the registry.")
            return
        for r in rows:
            code = r["link_code"] or ensure_link_code(path, r["id"])
            linked = (f"linked (chat {r['telegram_chat_id']})"
                      if r["telegram_chat_id"] else "not linked")
            print(f"{r['device_id']} | {r['name']} | code: {code} | {linked}")
        print("\nIn Telegram, open your bot and send:  /start <code>")
    elif args.add_contact:
        name, phone = args.add_contact
        conn = get_connection(path)
        conn.execute("INSERT INTO contacts (device_id, name, relation, phone, tier)"
                     " VALUES (?, ?, ?, ?, ?)",
                     (args.device, name, args.relation, phone, args.tier))
        cid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()
        conn.close()
        code = ensure_link_code(path, cid)
        print(f"Added contact '{name}' (id {cid}) to {args.device}.")
        print(f"Link code: {code}  ->  send  /start {code}  to your bot")
    else:
        ap.print_help()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
