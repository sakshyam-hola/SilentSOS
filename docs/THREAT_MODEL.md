# SilentSOS threat model

Short version of what this design protects against — and what it does not.
See `docs/PROTOCOL.md` for the wire protocol and `scripts/attack_demo.py`
for a live demonstration of the rejected attacks.

## Protected

- **Confidentiality (device → server).** Payloads are encrypted with
  AES-256-GCM. The 32-byte key lives in the device firmware and the server
  registry; it never travels over the wire and never appears in a browser
  (the web simulator encrypts server-side).
- **Integrity / authenticity.** GCM authentication with `device_id` as
  additional authenticated data (AAD): a tampered ciphertext, tag, or
  device_id fails decryption → HTTP 401. Demonstrated by the attack demo.
- **Replay.** Every nonce is recorded per device; resending a captured
  packet → HTTP 409. Demonstrated by the attack demo.
- **Freshness.** Plaintext timestamps must be within ±60 s of server time,
  so captured packets expire quickly even if a nonce were somehow reused →
  HTTP 408.
- **Flooding / abuse.** Max 5 alert requests per minute per device
  (sliding window) → HTTP 429; 30 s cooldown collapses accidental
  duplicate alerts into one.
- **Accountability.** Every `/api/alert` request — accepted or rejected —
  is written to `audit_log` with the check that decided it; viewable at
  `/security`.
- **Location retention.** Location data (latest position + trail) is
  automatically deleted 24 h after an alert is resolved. The alert record
  itself is kept for the audit trail.
- **Web hardening.** Security headers on every response
  (`nosniff`, `DENY` framing, `no-referrer` so alert IDs in tracking links
  are not leaked to the map-tile CDN, a restrictive Content-Security-Policy).
  No CORS middleware is installed, so browsers enforce the same-origin
  policy and block cross-origin reads by default.

## NOT protected (out of scope)

- **Telegram is not end-to-end encrypted.** Alert texts travel through
  Telegram's servers via the Bot API; anyone with access to that path
  (including Telegram itself) can read them. Treat notification content
  accordingly.
- **Physical device theft.** The device key lives in firmware. A stolen,
  disassembled device yields a working key until the device is deactivated
  in the registry (`active = 0` → HTTP 401).
- **GPS spoofing.** The server trusts the coordinates the device reports;
  a compromised device (or radio environment) can lie about its position.
- **Read-API authentication.** The demo read endpoints (`/api/alerts`,
  `/api/audit`, `/track`, `/security`) have no login; alert IDs are
  unguessable UUIDs but the endpoints themselves are open.
- **Server compromise.** Anyone with the database or `TELEGRAM_BOT_TOKEN`
  owns the system. Back up and restrict the server like any production box.
- **Transport encryption in local dev.** The demo runs over plain HTTP;
  production must terminate TLS (and only then does HSTS make sense).
