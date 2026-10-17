#!/usr/bin/env python3
"""SilentSOS device registry.

SQLite-backed device registry implementing the storage half of
docs/PROTOCOL.md (section 3). Standard library only.

Usage:
    python3 backend/registry.py --seed    # create DB + seed the demo device
    python3 backend/registry.py --show    # list devices and their contacts
    python3 backend/registry.py --export-config dev-001  # config.h snippet

The demo seed generates a fresh 32-byte AES key and prints it ONCE.
Store it in the SILENT_DEVICE_KEY environment variable (see .env.example)
— never in source code.
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import sqlite3
from pathlib import Path

# Project root = parent of this file's directory (silentsos/).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# DB location: env override, else data/silentsos.db under the project root.
DEFAULT_DB_PATH = str(PROJECT_ROOT / "data" / "silentsos.db")


def db_path() -> str:
    """Resolve the SQLite path (env var wins, then the project default)."""
    return os.environ.get("SILENT_DB_PATH", DEFAULT_DB_PATH)


# --- Schema (docs/PROTOCOL.md, section 3) ---------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
  device_id   TEXT PRIMARY KEY,
  secret_key  TEXT NOT NULL,             -- base64 of the 32-byte AES key
  owner_name  TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen   INTEGER                   -- unix seconds of last device contact
);

CREATE TABLE IF NOT EXISTS contacts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id   TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  relation    TEXT,
  phone       TEXT NOT NULL,
  email       TEXT,
  priority    INTEGER NOT NULL DEFAULT 1,
  tier        INTEGER NOT NULL DEFAULT 1 CHECK (tier IN (1, 2)),
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Written by the server only; backs validation checks 4 and 5.
CREATE TABLE IF NOT EXISTS used_nonces (
  device_id   TEXT NOT NULL,
  nonce_b64   TEXT NOT NULL,
  seen_at     TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (device_id, nonce_b64)
);

CREATE TABLE IF NOT EXISTS request_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id   TEXT NOT NULL,
  received_at INTEGER NOT NULL
);

-- Alert lifecycle (written by the FastAPI backend in backend/main.py).
CREATE TABLE IF NOT EXISTS alerts (
  id          TEXT PRIMARY KEY,            -- UUID v4, server-generated
  device_id   TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'safe')),
  latest_lat  REAL,                        -- NULL after 24h location purge
  latest_lon  REAL,                        -- NULL after 24h location purge
  battery     INTEGER NOT NULL,
  created_at  INTEGER NOT NULL,            -- unix seconds (server time)
  resolved_at INTEGER,                     -- unix seconds, NULL until resolved
  escalated_at INTEGER,                     -- unix seconds, NULL until tier-2 escalation
  trail       TEXT NOT NULL DEFAULT '[]'   -- JSON array of {ts, lat, lon}
);
CREATE INDEX IF NOT EXISTS idx_alerts_device ON alerts(device_id, created_at DESC);

-- Trusted-contact acknowledgements for an alert.
CREATE TABLE IF NOT EXISTS acks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_id    TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
  contact_id  INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  acked_at    INTEGER NOT NULL,            -- unix seconds (server time)
  UNIQUE (alert_id, contact_id)
);

-- Every POST /api/alert request is logged here, accepted or rejected.
-- `reason` is the validation check that failed (format, registry,
-- decryption, plaintext, freshness, replay, rate_limit) or, for accepted
-- requests, the disposition (alert_created, cooldown_ignored,
-- update_appended, safe_resolved, safe_noop, update_no_active).
CREATE TABLE IF NOT EXISTS audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id   TEXT,
  alert_id    TEXT,
  outcome     TEXT NOT NULL CHECK (outcome IN ('accepted', 'rejected')),
  reason      TEXT NOT NULL,
  received_at INTEGER NOT NULL             -- unix seconds (server time)
);
CREATE INDEX IF NOT EXISTS idx_audit_device ON audit_log(device_id, received_at DESC);
"""


# --- Low-level helpers ------------------------------------------------------

def get_connection(path: str | None = None) -> sqlite3.Connection:
    """Open the registry DB with dict-like rows and foreign keys on."""
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | None = None) -> str:
    """Create all registry tables if they do not exist. Returns the DB path."""
    path = path or db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(path) as conn:
        conn.executescript(SCHEMA)
        # Lightweight migrations for columns added after the initial schema.
        for column, ddl in (("telegram_chat_id", "TEXT"),
                            ("link_code", "TEXT"),
                            ("tier", "INTEGER NOT NULL DEFAULT 1")):
            try:
                conn.execute(f"ALTER TABLE contacts ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS"
                     " idx_contacts_link_code ON contacts(link_code)")
        try:
            conn.execute("ALTER TABLE devices ADD COLUMN last_seen INTEGER")
        except sqlite3.OperationalError:
            pass  # column already exists
        _migrate_alerts_nullable_location(conn)
        # After the alerts rebuild above, so the new column is never dropped.
        try:
            conn.execute("ALTER TABLE alerts ADD COLUMN escalated_at INTEGER")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()
    return path


def _migrate_alerts_nullable_location(conn: sqlite3.Connection) -> None:
    """Rebuild alerts so latest_lat/latest_lon are nullable (needed for the
    24 h location purge). No-op on databases that already allow NULL."""
    info = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(alerts)")}
    if info.get("latest_lat", 0) == 0:
        return  # already nullable
    conn.execute("""CREATE TABLE alerts_new (
      id          TEXT PRIMARY KEY,
      device_id   TEXT NOT NULL REFERENCES devices(device_id)
                  ON DELETE CASCADE,
      status      TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'safe')),
      latest_lat  REAL,
      latest_lon  REAL,
      battery     INTEGER NOT NULL,
      created_at  INTEGER NOT NULL,
      resolved_at INTEGER,
      trail       TEXT NOT NULL DEFAULT '[]'
    )""")
    conn.execute("""INSERT INTO alerts_new
        (id, device_id, status, latest_lat, latest_lon, battery,
         created_at, resolved_at, trail)
        SELECT id, device_id, status, latest_lat, latest_lon, battery,
         created_at, resolved_at, trail FROM alerts""")
    conn.execute("DROP TABLE alerts")
    conn.execute("ALTER TABLE alerts_new RENAME TO alerts")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_device"
                 " ON alerts(device_id, created_at DESC)")


# --- Queries (used by the backend in a later step) --------------------------

def get_device(device_id: str, path: str | None = None) -> dict | None:
    """Return the device row as a dict, or None if unknown."""
    with get_connection(path) as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
    return dict(row) if row else None


def get_contacts(device_id: str, path: str | None = None) -> list[dict]:
    """Return the device's contacts, lowest priority first."""
    with get_connection(path) as conn:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE device_id = ? ORDER BY priority ASC",
            (device_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- Seeding ----------------------------------------------------------------

# Demo contacts for dev-001. Obviously fake numbers/emails — demo only.
DEMO_OWNER = "Demo User"
DEMO_CONTACTS = [
    {
        "name": "Asha Sharma",
        "relation": "spouse",
        "phone": "+977-9800000001",
        "email": "asha@example.com",
        "priority": 1,
        "tier": 1,
    },
    {
        "name": "Bikash Thapa",
        "relation": "friend",
        "phone": "+977-9800000002",
        "email": "bikash@example.com",
        "priority": 2,
        "tier": 1,
    },
    {
        "name": "Sita Rai",
        "relation": "neighbor",
        "phone": "+977-9800000003",
        "email": "sita@example.com",
        "priority": 3,
        "tier": 2,
    },
]


def _ensure_demo_contacts(conn) -> int:
    """Insert any missing demo contacts (matched by name). Returns count added.

    Keeps existing databases current when the demo contact list grows."""
    added = 0
    for c in DEMO_CONTACTS:
        exists = conn.execute(
            "SELECT 1 FROM contacts WHERE device_id = 'dev-001' AND name = ?",
            (c["name"],)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO contacts (device_id, name, relation, phone,"
                " email, priority, tier)"
                " VALUES ('dev-001', :name, :relation, :phone, :email,"
                " :priority, :tier)", c)
            added += 1
    return added


def seed_demo(path: str | None = None) -> str:
    """Create the DB and seed the demo device. Returns its base64 secret key.

    Idempotent: if 'dev-001' already exists, nothing is inserted and the
    stored key is returned unchanged (it is NOT printed again).
    """
    path = init_db(path)
    with get_connection(path) as conn:
        existing = conn.execute(
            "SELECT secret_key FROM devices WHERE device_id = 'dev-001'"
        ).fetchone()
        if existing:
            added = _ensure_demo_contacts(conn)
            conn.commit()
            if added:
                print(f"dev-001 already seeded; added {added} missing demo contact(s).")
            else:
                print("dev-001 already seeded; nothing changed.")
            return existing["secret_key"]

        # Fresh 32-byte AES-256 key, base64-encoded for storage/transport.
        secret_key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        conn.execute(
            "INSERT INTO devices (device_id, secret_key, owner_name, active)"
            " VALUES (?, ?, ?, 1)",
            ("dev-001", secret_key, DEMO_OWNER),
        )
        _ensure_demo_contacts(conn)
        conn.commit()

    print("Seeded demo device 'dev-001' with 3 demo contacts (2x tier 1, 1x tier 2).")
    print()
    print("!!! SAVE THIS KEY NOW — it is shown only once !!!")
    print(f"SILENT_DEVICE_KEY={secret_key}")
    print()
    print("Set it in your environment (PowerShell):")
    print('  $env:SILENT_DEVICE_ID="dev-001"')
    print(f'  $env:SILENT_DEVICE_KEY="{secret_key}"')
    print("Never commit this key to source control.")
    return secret_key


def show(path: str | None = None) -> None:
    """Print all devices and their contacts (keys are NOT shown)."""
    path = path or db_path()
    if not Path(path).exists():
        print(f"No database at {path} — run with --seed first.")
        return
    with get_connection(path) as conn:
        devices = conn.execute("SELECT * FROM devices").fetchall()
    if not devices:
        print("Registry is empty.")
        return
    for dev in devices:
        print(f"- {dev['device_id']}  owner={dev['owner_name']}  "
              f"active={bool(dev['active'])}  created={dev['created_at']}")
        for c in get_contacts(dev["device_id"], path):
            print(f"    [prio {c['priority']}] {c['name']} ({c['relation']}) "
                  f"{c['phone']} <{c['email']}>")


def export_config(device_id: str, path: str | None = None) -> None:
    """Print a config.h snippet for a device (id + base64 key).

    The key is printed to the terminal ONLY — paste it into
    firmware/silentsos/config.h (git-ignored) and never commit it.
    """
    path = path or db_path()
    if not Path(path).exists():
        print(f"No database at {path} — run with --seed first.")
        return
    with get_connection(path) as conn:
        dev = conn.execute("SELECT * FROM devices WHERE device_id = ?",
                           (device_id,)).fetchone()
    if dev is None:
        print(f"Unknown device_id {device_id!r}.")
        return
    if not dev["active"]:
        print(f"WARNING: {device_id} is deactivated in the registry.")
    print(f"--- config.h snippet for {device_id} "
          f"(paste into firmware/silentsos/config.h) ---")
    print(f'#define DEVICE_ID       "{dev["device_id"]}"')
    print(f'#define DEVICE_KEY_B64  "{dev["secret_key"]}"')
    print("--- never commit config.h; it is git-ignored ---")


def main() -> None:
    parser = argparse.ArgumentParser(description="SilentSOS device registry")
    parser.add_argument("--seed", action="store_true",
                        help="create the DB and seed the demo device")
    parser.add_argument("--show", action="store_true",
                        help="list devices and contacts (keys hidden)")
    parser.add_argument("--export-config", metavar="DEVICE_ID",
                        help="print a config.h snippet for a device "
                             "(key shown once, paste into git-ignored config.h)")
    parser.add_argument("--db", default=None,
                        help="SQLite path (default: $SILENT_DB_PATH or ./data/silentsos.db)")
    args = parser.parse_args()

    if args.seed:
        seed_demo(args.db)
    elif args.show:
        show(args.db)
    elif args.export_config:
        export_config(args.export_config, args.db)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
