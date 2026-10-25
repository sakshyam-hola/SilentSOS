> Back to [README](../README.md) · Part of the SilentSOS docs.


# Security design

- **AES-256-GCM** device→server encryption: 32-byte per-device key, fresh
  12-byte nonce per message, `device_id` as AAD. Tampering fails closed
  (`401`).
- **Replay protection:** `(device_id, nonce)` recorded atomically; a
  replayed packet gets `409`.
- **Timestamp window:** `|server − ts| ≤ 60 s`, else `408`.
- **Rate limiting:** 5 requests/min/device (sliding window), else `429`,
  plus a 30 s alert cooldown against duplicate alerts.
- **Audit log:** every `/api/alert` request — accepted or rejected — is
  stored with the check that decided it; browsable at `/security`.
- **Data deletion:** locations (latest position + trail) are auto-purged
  24 h after an alert resolves; the alert record itself is kept for the
  audit trail.

**Honest limitations** (see `docs/THREAT_MODEL.md` for the full list):

- Telegram is **not end-to-end encrypted**; notification text passes
  through Telegram's servers.
- A stolen device yields a working key until it's deactivated
  (`active = 0` in the registry → `401`).
- The server trusts the coordinates the device reports (GPS spoofing is
  out of scope).
- The demo read APIs (`/api/alerts`, `/api/audit`, …) have no login;
  alert IDs are unguessable UUIDs, but the endpoints are open.
- Local development runs over plain HTTP; production must terminate TLS.

**Roadmap:** SIM800L SMS fallback for low-connectivity areas (~$4 module,
mentioned in the pitch), Signal or push-notification alternatives to
Telegram, and real battery optimization (the firmware currently sends a
fixed demo battery value).
