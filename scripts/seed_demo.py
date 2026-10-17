#!/usr/bin/env python3
"""Seed a fresh database with the demo device + contacts.

Idempotent: if 'dev-001' already exists, nothing is inserted and the stored
key is NOT re-printed. Safe to run on every deploy — on platforms with an
ephemeral filesystem (e.g. Render's free tier) the database is recreated
from scratch on each deploy, so this keeps the demo working.

The freshly generated 32-byte device key is printed ONCE. Save it as
SILENT_DEVICE_KEY for the simulator (simulator/config.json).

Usage:
    python scripts/seed_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.registry import seed_demo  # noqa: E402

if __name__ == "__main__":
    seed_demo()
