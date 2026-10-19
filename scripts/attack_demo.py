#!/usr/bin/env python3
"""SilentSOS security demo — runs attacks against the live backend.

Every attack must be REJECTED with the expected status code:

    python scripts/attack_demo.py [--base-url URL] [--config PATH]

Config defaults to simulator/config.json (device_id + base64 key).
Prints a PASS/FAIL table; exits 0 when every attack behaves, 1 otherwise.

Note: run against a backend that has seen little traffic in the last
minute — the flood test intentionally exhausts the rate limiter, so it
runs last.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.crypto import encrypt  # noqa: E402

LAT, LON, BATTERY = 27.7172, 85.3240, 87


def load_config(path: str) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    key = base64.b64decode(cfg["key"].encode("ascii"), validate=True)
    if len(key) != 32:
        sys.exit(f"config {path}: key must decode to 32 bytes")
    return {"device_id": cfg["device_id"], "key": key,
            "base_url": cfg["base_url"].rstrip("/")}


def build_body(cfg: dict, key: bytes | None = None,
               device_id: str | None = None, ts: int | None = None,
               typ: str = "alert") -> dict:
    key = key if key is not None else cfg["key"]
    device_id = device_id or cfg["device_id"]
    plaintext = {"ts": ts if ts is not None else int(time.time()),
                 "lat": LAT, "lon": LON, "battery": BATTERY, "type": typ}
    nonce_b64, ct_b64, tag_b64 = encrypt(device_id, key, plaintext)
    return {"device_id": device_id, "nonce": nonce_b64,
            "ciphertext": ct_b64, "tag": tag_b64}


def post(cfg: dict, body: dict) -> int:
    try:
        r = requests.post(cfg["base_url"] + "/api/alert", json=body,
                          timeout=10)
        return r.status_code
    except Exception as exc:
        print(f"  request failed: {exc}")
        return -1


def main() -> int:
    ap = argparse.ArgumentParser(description="SilentSOS attack demo")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--config", default="simulator/config.json")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.base_url:
        cfg["base_url"] = args.base_url.rstrip("/")

    print(f"Target: {cfg['base_url']}   device: {cfg['device_id']}\n")
    rows: list[tuple[str, str, str, str]] = []

    def record(name: str, expected: str, got: str, ok: bool):
        rows.append((name, expected, got, "PASS" if ok else "FAIL"))

    # 1. Replay: resend a previously accepted packet -------------------------
    body = build_body(cfg)
    s = post(cfg, body)
    if s != 200:
        rows.append(("Replay attack", "409", f"setup got {s}", "SKIP"))
        print("  [!] replay setup not accepted "
              f"(HTTP {s}); skipping replay test")
    else:
        s2 = post(cfg, body)  # exact same bytes, same nonce
        record("Replay attack", "409", str(s2), s2 == 409)

    # 2. Tamper: flip a byte in the ciphertext --------------------------------
    body = build_body(cfg)
    raw = bytearray(base64.b64decode(body["ciphertext"], validate=True))
    raw[0] ^= 0x01
    body["ciphertext"] = base64.b64encode(bytes(raw)).decode("ascii")
    s = post(cfg, body)
    record("Tampered ciphertext", "401", str(s), s == 401)

    # 3. Expired: timestamp 5 minutes old ------------------------------------
    body = build_body(cfg, ts=int(time.time()) - 300)
    s = post(cfg, body)
    record("Expired timestamp", "408", str(s), s == 408)

    # 4. Wrong key ------------------------------------------------------------
    body = build_body(cfg, key=os.urandom(32))
    s = post(cfg, body)
    record("Wrong key", "401", str(s), s == 401)

    # 5. Unknown device -------------------------------------------------------
    body = build_body(cfg, device_id="dev-unknown-999", key=os.urandom(32))
    s = post(cfg, body)
    record("Unknown device", "401", str(s), s == 401)

    # 6. Flood: 20 requests in ~10 seconds (runs last: exhausts rate limit) ---
    codes = []
    for _ in range(20):
        codes.append(post(cfg, build_body(cfg)))  # fresh nonce each time
        time.sleep(0.5)
    n429 = sum(1 for c in codes if c == 429)
    n200 = sum(1 for c in codes if c == 200)
    weird = [c for c in codes if c not in (200, 429)]
    ok = n429 >= 10 and not weird
    record("Flood (20 in 10s)", ">=10x 429", f"{n200}x 200, {n429}x 429", ok)

    # Report ------------------------------------------------------------------
    print(f"{'Attack':<22}{'Expected':<12}{'Got':<18}Result")
    print("─" * 60)
    for name, expected, got, result in rows:
        print(f"{name:<22}{expected:<12}{got:<18}{result}")
    print("─" * 60)
    failed = [r for r in rows if r[3] == "FAIL"]
    skipped = [r for r in rows if r[3] == "SKIP"]
    print(f"{len(rows) - len(failed) - len(skipped)}/{len(rows)} passed"
          + (f", {len(skipped)} skipped" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
