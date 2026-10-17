"""On-screen attack demo for the home page's "Skip to attack demo" button.

Runs the same 6 attacks as scripts/attack_demo.py, but in-process through
the real validation chain instead of over HTTP, and against an *ephemeral*
device. That keeps a self-running demo honest: the attacks never disturb
real alerts, contacts, or the dev-001 rate-limit window, and nothing is
notified over Telegram (notifications live in the HTTP endpoint wrapper,
which is bypassed here).

The ephemeral device and all its rows are deleted before returning.
"""
from __future__ import annotations

import base64
import os
import time
import uuid

from backend.crypto import encrypt
from backend.registry import get_connection

# Plausible demo coordinates (Biratnagar, Nepal).
LAT, LON, BATTERY = 26.4525, 87.2718, 87


def _envelope(device_id: str, key: bytes, ts: int | None = None,
              typ: str = "alert") -> dict:
    pt = {"ts": int(time.time()) if ts is None else ts,
          "lat": LAT, "lon": LON, "battery": BATTERY, "type": typ}
    nonce_b64, ct_b64, tag_b64 = encrypt(device_id, key, pt)
    return {"device_id": device_id, "nonce": nonce_b64,
            "ciphertext": ct_b64, "tag": tag_b64}


def _submit(conn, handle_parsed, body: dict) -> int:
    """One envelope through the real validation chain. Returns HTTP code."""
    try:
        code, _payload, audit = handle_parsed(conn, body)
    except Exception:
        conn.rollback()
        return -1
    device_id, alert_id, outcome, reason = audit
    conn.execute(
        "INSERT INTO audit_log (device_id, alert_id, outcome, reason,"
        " received_at) VALUES (?, ?, ?, ?, ?)",
        (device_id, alert_id, outcome, reason, int(time.time())))
    conn.commit()
    return code


def run_attack_demo(handle_parsed, db_path: str) -> list[dict]:
    """Run the 6 attacks. Returns [{name, expected, got, result}]."""
    eph = "dev-atk-" + uuid.uuid4().hex[:8]
    key = os.urandom(32)
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO devices (device_id, secret_key, owner_name, active)"
            " VALUES (?, ?, ?, 1)",
            (eph, base64.b64encode(key).decode("ascii"),
             "Attack demo (ephemeral)"))
        conn.commit()

        rows: list[dict] = []

        def record(name: str, expected: str, got: str, ok: bool):
            rows.append({"name": name, "expected": expected, "got": got,
                         "result": "PASS" if ok else "FAIL"})

        # 1. Replay: resend a previously accepted packet ---------------------
        body = _envelope(eph, key)
        s = _submit(conn, handle_parsed, body)
        if s != 200:
            rows.append({"name": "Replay attack", "expected": "409",
                         "got": f"setup got {s}", "result": "SKIP"})
        else:
            s2 = _submit(conn, handle_parsed, body)  # identical bytes/nonce
            record("Replay attack", "409", str(s2), s2 == 409)

        # 2. Tamper: flip a byte in the ciphertext ---------------------------
        body = _envelope(eph, key)
        raw = bytearray(base64.b64decode(body["ciphertext"], validate=True))
        raw[0] ^= 0x01
        body["ciphertext"] = base64.b64encode(bytes(raw)).decode("ascii")
        s = _submit(conn, handle_parsed, body)
        record("Tampered ciphertext", "401", str(s), s == 401)

        # 3. Expired: timestamp 5 minutes old --------------------------------
        body = _envelope(eph, key, ts=int(time.time()) - 300)
        s = _submit(conn, handle_parsed, body)
        record("Expired timestamp", "408", str(s), s == 408)

        # 4. Wrong key --------------------------------------------------------
        body = _envelope(eph, os.urandom(32))
        s = _submit(conn, handle_parsed, body)
        record("Wrong key", "401", str(s), s == 401)

        # 5. Unknown device ---------------------------------------------------
        body = _envelope("dev-unknown-999", os.urandom(32))
        s = _submit(conn, handle_parsed, body)
        record("Unknown device", "401", str(s), s == 401)

        # 6. Flood: 20 rapid requests (runs last: exhausts the rate limit) ---
        codes = [_submit(conn, handle_parsed, _envelope(eph, key))
                 for _ in range(20)]
        n429 = sum(1 for c in codes if c == 429)
        n200 = sum(1 for c in codes if c == 200)
        weird = [c for c in codes if c not in (200, 429)]
        record("Flood (20 rapid)", ">=10x 429",
               f"{n200}x 200, {n429}x 429", n429 >= 10 and not weird)

        # Cleanup: the demo leaves no trace behind. --------------------------
        conn.execute("DELETE FROM alerts WHERE device_id = ?", (eph,))
        conn.execute("DELETE FROM audit_log WHERE device_id = ?", (eph,))
        conn.execute("DELETE FROM used_nonces WHERE device_id = ?", (eph,))
        conn.execute("DELETE FROM request_log WHERE device_id = ?", (eph,))
        conn.execute("DELETE FROM devices WHERE device_id = ?", (eph,))
        conn.commit()
        return rows
    finally:
        conn.close()


# --- single-attack simulator for the security center ------------------------

# Validation steps, in the order _handle_parsed runs them. The checklist for
# any audit row is derived from (outcome, reason): every step before the
# failing one passed, the failing one failed, later ones never ran.
STEP_LABELS = ["Device found", "Tag verified", "Timestamp valid",
               "Nonce unused", "Within rate limit"]


def verdict_for(outcome: str, reason: str) -> dict:
    """Color-coded verdict for an audit row. kind: ok|info|warn|bad."""
    if outcome == "accepted":
        return {
            "alert_created": ("Accepted", "ok"),
            "update_appended": ("Accepted · update", "ok"),
            "safe_resolved": ("Accepted · safe", "ok"),
            "safe_noop": ("Accepted · noop", "ok"),
            "cooldown_ignored": ("Accepted · deduped", "ok"),
            "escalated_tier2": ("Escalated", "warn"),
        }.get(reason, ("Accepted", "ok"))
    label, kind = {
        "replay": ("Replay blocked", "bad"),
        "decryption": ("Tampered", "bad"),
        "freshness": ("Expired", "warn"),
        "rate_limit": ("Rate limited", "warn"),
        "registry": ("Unknown device", "bad"),
    }.get(reason, ("Malformed", "bad"))
    return label, kind


def steps_for(outcome: str, reason: str) -> list[dict]:
    """Validation checklist derived from the audit record.

    Each step: {"label", "state"} with state pass|fail|skip. System events
    (escalated_tier2) are not device requests: every step is skipped."""
    if reason == "escalated_tier2":
        states = ["skip"] * 5
    elif outcome == "accepted":
        states = ["pass"] * 5
    else:
        states = {
            "registry":   ["fail", "skip", "skip", "skip", "skip"],
            "decryption": ["pass", "fail", "skip", "skip", "skip"],
            "plaintext":  ["pass", "pass", "skip", "skip", "skip"],
            "freshness":  ["pass", "pass", "fail", "skip", "skip"],
            "replay":     ["pass", "pass", "pass", "fail", "skip"],
            "rate_limit": ["pass", "pass", "pass", "pass", "fail"],
        }.get(reason, ["skip"] * 5)
    return [{"label": label, "state": state}
            for label, state in zip(STEP_LABELS, states)]


def _ephemeral_device(conn) -> tuple[str, bytes]:
    eph = "dev-atk-" + uuid.uuid4().hex[:8]
    key = os.urandom(32)
    conn.execute(
        "INSERT INTO devices (device_id, secret_key, owner_name, active)"
        " VALUES (?, ?, ?, 1)",
        (eph, base64.b64encode(key).decode("ascii"),
         "Attack simulator (ephemeral)"))
    conn.commit()
    return eph, key


def _cleanup_device(conn, eph: str, keep_audit: bool) -> None:
    conn.execute("DELETE FROM alerts WHERE device_id = ?", (eph,))
    if not keep_audit:
        conn.execute("DELETE FROM audit_log WHERE device_id = ?", (eph,))
    conn.execute("DELETE FROM used_nonces WHERE device_id = ?", (eph,))
    conn.execute("DELETE FROM request_log WHERE device_id = ?", (eph,))
    conn.execute("DELETE FROM devices WHERE device_id = ?", (eph,))
    conn.commit()


def simulate_attack(handle_parsed, db_path: str, attack: str) -> dict:
    """Fire one attack against the live validation chain.

    attack: "replay" | "tampered" | "flood". Runs on an ephemeral device so
    the real device's rate-limit window is untouched. Audit rows are KEPT
    so the security center's live feed shows the attack; the ephemeral
    device and its alerts are removed. Returns the device id and per-
    attempt results with verdict + validation checklist."""
    if attack not in ("replay", "tampered", "flood"):
        raise ValueError(f"unknown attack {attack!r}")
    conn = get_connection(db_path)
    try:
        eph, key = _ephemeral_device(conn)

        def attempt(body: dict, note: str = "") -> dict:
            code = _submit(conn, handle_parsed, body)
            if code == -1:  # unexpected exception; no audit row was written
                outcome, reason = "rejected", "error"
            else:
                row = conn.execute(
                    "SELECT outcome, reason FROM audit_log"
                    " WHERE device_id = ? ORDER BY id DESC LIMIT 1",
                    (eph,)).fetchone()
                outcome, reason = row["outcome"], row["reason"]
            label, kind = verdict_for(outcome, reason)
            return {"code": code, "note": note,
                    "verdict": label, "kind": kind,
                    "outcome": outcome, "reason": reason,
                    "steps": steps_for(outcome, reason)}

        if attack == "replay":
            body = _envelope(eph, key)
            results = [attempt(body, "setup: valid packet"),
                       attempt(body, "resend: identical bytes")]
        elif attack == "tampered":
            body = _envelope(eph, key)
            raw = bytearray(base64.b64decode(body["ciphertext"],
                                             validate=True))
            raw[0] ^= 0x01
            body["ciphertext"] = base64.b64encode(bytes(raw)).decode("ascii")
            results = [attempt(body, "ciphertext byte flipped")]
        else:  # flood: 8 rapid requests; the limiter kicks in after 5
            results = [attempt(_envelope(eph, key), f"packet {i + 1}/8")
                       for i in range(8)]

        _cleanup_device(conn, eph, keep_audit=True)
        return {"attack": attack, "device_id": eph, "results": results}
    finally:
        conn.close()
