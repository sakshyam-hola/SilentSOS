#!/usr/bin/env python3
"""SilentSOS device simulator (CLI) — behaves like the future ESP32 firmware.

Speaks the exact encrypted protocol from docs/PROTOCOL.md:
builds the JSON payload, encrypts with AES-256-GCM, POSTs to /api/alert.

Usage:
    python simulator/device_sim.py [--config simulator/config.json]
                                   [--base-url http://127.0.0.1:8001]

Interactive commands:
    <Enter>   button press — 3 presses within 2 s trigger an alert
              (presses closer than 50 ms are ignored: debounce)
    hold      simulate a 3-second long press -> sends type "safe"
    route     send "update" every 3 s along a preset route (Ctrl+C stops)
    quit      exit

Feedback (like the device's vibration motor):
    "vibration: 1 short pulse"   request accepted (HTTP 200)
    "vibration: 3 short pulses"  request failed after retries
Failed sends are retried with exponential backoff (max 3 tries total).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
import time
from pathlib import Path

import requests

# Allow `from backend.crypto import ...` when run from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.crypto import encrypt  # noqa: E402

# Firmware constants.
PRESS_WINDOW_S = 2.0    # 3 presses inside this window -> alert
PRESSES_TO_ALERT = 3
DEBOUNCE_S = 0.05       # ignore presses closer than 50 ms
HOLD_S = 3              # long-press duration
MAX_TRIES = 3           # total POST attempts (initial + retries)
RETRY_BASE_DELAY_S = 1  # exponential backoff: 1 s, 2 s, ...
ROUTE_INTERVAL_S = 3

# Preset route around central Kathmandu (lat, lon).
ROUTE = [
    (27.7172, 85.3240),  # Ratnapark
    (27.7185, 85.3262),
    (27.7178, 85.3291),
    (27.7159, 85.3284),
    (27.7152, 85.3256),
    (27.7161, 85.3235),
]


def load_config(path: str) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    for field in ("device_id", "key", "base_url"):
        if field not in cfg:
            sys.exit(f"config {path}: missing field {field!r}")
    try:
        key = base64.b64decode(cfg["key"].encode("ascii"), validate=True)
    except (binascii.Error, ValueError):
        sys.exit(f"config {path}: 'key' is not valid base64")
    if len(key) != 32:
        sys.exit(f"config {path}: key must decode to 32 bytes")
    cfg["_key_bytes"] = key
    cfg.setdefault("lat", 27.7172)
    cfg.setdefault("lon", 85.3240)
    cfg.setdefault("battery", 87)
    return cfg


def send(cfg: dict, msg_type: str, lat: float, lon: float,
         battery: int) -> tuple[bool, str | None]:
    """Encrypt + POST with exponential-backoff retries.

    Each attempt rebuilds the message with a fresh nonce and timestamp, so
    a retry never trips the server's replay protection. Returns
    (accepted, alert_id_or_None)."""
    url = cfg["base_url"].rstrip("/") + "/api/alert"

    delay = RETRY_BASE_DELAY_S
    for attempt in range(1, MAX_TRIES + 1):
        plaintext = {"ts": int(time.time()), "lat": lat, "lon": lon,
                     "battery": battery, "type": msg_type}
        nonce_b64, ct_b64, tag_b64 = encrypt(cfg["device_id"],
                                            cfg["_key_bytes"], plaintext)
        body = {"device_id": cfg["device_id"], "nonce": nonce_b64,
                "ciphertext": ct_b64, "tag": tag_b64}
        try:
            r = requests.post(url, json=body, timeout=10)
            if r.status_code == 200:
                return True, r.json().get("alert_id")
            print(f"  attempt {attempt}/{MAX_TRIES}: HTTP {r.status_code}")
        except Exception as exc:  # connection error, timeout, ...
            print(f"  attempt {attempt}/{MAX_TRIES}: {exc}")
        if attempt < MAX_TRIES:
            time.sleep(delay)
            delay *= 2
    return False, None


def vibrate(ok: bool) -> None:
    print("vibration: 1 short pulse" if ok
          else "vibration: 3 short pulses")


def do_hold(cfig: dict) -> None:
    print(f"holding button ({HOLD_S}s)...", flush=True)
    time.sleep(HOLD_S)
    print("long press detected -> sending 'safe'")
    ok, alert_id = send(cfig, "safe", cfig["lat"], cfig["lon"],
                        cfig["battery"])
    vibrate(ok)
    if ok:
        print(f"  safe accepted (alert {alert_id})")


def do_route(cfg: dict) -> None:
    print(f"route mode: 'update' every {ROUTE_INTERVAL_S}s "
          "(Ctrl+C to stop)")
    try:
        i = 0
        while True:
            lat, lon = ROUTE[i % len(ROUTE)]
            ok, alert_id = send(cfg, "update", lat, lon, cfg["battery"])
            vibrate(ok)
            print(f"  update {i + 1}: ({lat}, {lon}) -> "
                  f"{'ok ' + str(alert_id) if ok else 'FAILED'}")
            i += 1
            time.sleep(ROUTE_INTERVAL_S)
    except KeyboardInterrupt:
        print("\nroute stopped")


def main() -> None:
    ap = argparse.ArgumentParser(description="SilentSOS device simulator")
    ap.add_argument("--config", default="simulator/config.json")
    ap.add_argument("--base-url", default=None,
                    help="override base_url from the config file")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.base_url:
        cfg["base_url"] = args.base_url

    print("SilentSOS device simulator")
    print(f"  device : {cfg['device_id']}")
    print(f"  backend: {cfg['base_url']}")
    print("  <Enter>=press  hold=long-press  route=track  quit=exit")

    presses: list[float] = []
    while True:
        try:
            line = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line in ("quit", "exit"):
            break
        if line == "hold":
            do_hold(cfg)
        elif line == "route":
            do_route(cfg)
        elif line == "":
            t = time.monotonic()
            if presses and t - presses[-1] < DEBOUNCE_S:
                print("  (debounced: ignored, < 50 ms)")
                continue
            presses.append(t)
            presses = [p for p in presses if t - p <= PRESS_WINDOW_S]
            print(f"  press ({len(presses)}/{PRESSES_TO_ALERT})")
            if len(presses) >= PRESSES_TO_ALERT:
                presses.clear()
                print("  triple press -> sending 'alert'")
                ok, alert_id = send(cfg, "alert", cfg["lat"], cfg["lon"],
                                    cfg["battery"])
                vibrate(ok)
                if ok:
                    print(f"  alert accepted (id {alert_id})")
        else:
            print("  commands: <Enter> press | hold | route | quit")


if __name__ == "__main__":
    main()
