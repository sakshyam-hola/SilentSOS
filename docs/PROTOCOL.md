# SilentSOS — Protocol Specification

**Status:** single source of truth. Every implementation (simulated device,
ESP32 firmware, backend server) MUST follow this document exactly.
Field names are frozen — do not rename, add, or remove fields without a
spec version bump.

**Version:** 1.0.0 · **Date:** 2026-10-14

---

## 1. Overview

SilentSOS is a discreet emergency-alert system. A hardware device (ESP32 +
button) encrypts an alert and POSTs it to the backend. The backend verifies
the alert, notifies the device owner's trusted contacts, and serves a live
tracking page.

- Transport: HTTPS (TLS 1.2+) in production. Plain HTTP is allowed **only**
  for local development and testing.
- All timestamps are Unix seconds (UTC).
- All JSON is UTF-8.

---

## 2. Alert request

### 2.1 Endpoint

```http
POST /api/alert
Content-Type: application/json
```

### 2.2 Request body (field names frozen)

```json
{
  "device_id": "dev-001",
  "nonce": "<base64 of 12 random bytes>",
  "ciphertext": "<base64>",
  "tag": "<base64 of 16-byte GCM tag>"
}
```

| Field        | Type            | Rules                                                                  |
|--------------|-----------------|------------------------------------------------------------------------|
| `device_id`  | string          | Registry identifier, sent in plaintext.                                |
| `nonce`      | string (base64) | MUST decode to exactly 12 bytes. MUST be freshly generated random bytes for every request. |
| `ciphertext` | string (base64) | AES-256-GCM ciphertext of the plaintext (§2.3).                        |
| `tag`        | string (base64) | MUST decode to exactly 16 bytes (the GCM authentication tag).          |

### 2.3 Encryption

- **Algorithm:** AES-256-GCM.
- **Key:** 32-byte per-device key, provisioned out-of-band, stored base64 in
  the device registry (§3). One key per device. Keys are never transmitted.
- **Nonce:** 12 cryptographically random bytes per request, transmitted in
  the `nonce` field.
- **AAD (associated data):** the `device_id` string encoded as UTF-8 bytes.
  The AAD used for decryption MUST be the `device_id` value from the request
  body.
- **Plaintext:** compact JSON, UTF-8, exactly these fields:

```json
{"ts": 1728859200, "lat": 27.7172, "lon": 85.3240, "battery": 87, "type": "alert"}
```

| Field     | Type    | Rules                                                        |
|-----------|---------|--------------------------------------------------------------|
| `ts`      | integer | Unix seconds (UTC) when the event occurred.                  |
| `lat`     | number  | WGS84 latitude, decimal degrees, −90 … 90.                   |
| `lon`     | number  | WGS84 longitude, decimal degrees, −180 … 180.                |
| `battery` | integer | 0 … 100.                                                     |
| `type`    | string  | One of `"alert"`, `"update"`, `"safe"`.                      |

Semantics: `"alert"` = SOS (button pressed 3× quickly);
`"update"` = position update for an active alert;
`"safe"` = all-clear / cancel.

### 2.4 Server validation (in this order)

0. **Format** — body is a JSON object containing exactly the four fields
   above, with correct types, valid base64, and correct decoded lengths.
   → fail: `400`
1. **Registry** — `device_id` exists in the registry and `active = 1`.
   → fail: `401`
2. **Decryption** — AES-256-GCM decrypt `ciphertext` with the device's key,
   the request `nonce`, and AAD = `device_id` UTF-8 bytes. Tag verification
   must succeed. → fail: `401`
3. **Freshness** — `|server_time − ts| ≤ 60` seconds. → fail: `408`
4. **Replay** — `nonce` has never been used before for this device.
   Check-then-insert MUST be atomic (unique constraint on
   `(device_id, nonce)`). A nonce is recorded only for requests that pass
   all checks. → fail: `409`
5. **Rate limit** — max 5 requests per minute per device (sliding 60-second
   window, counting requests that reached this check). → fail: `429`

After successful decryption, the plaintext MUST also satisfy the schema in
§2.3 (types, ranges, `type` enum); violations → `400`.

### 2.5 Responses

| Code | Body                              | Meaning                                              |
|------|-----------------------------------|------------------------------------------------------|
| 200  | `{"status":"ok","alert_id":"..."}` | Accepted. `alert_id` is a server-generated UUID v4 identifying the stored event (for any `type`). |
| 400  | `{"status":"error"}`              | Invalid format (request body or decrypted plaintext). |
| 401  | `{"status":"error"}`              | Unknown/inactive device, or decryption/tag failure.   |
| 408  | `{"status":"error"}`              | `ts` outside the ±60 s window.                       |
| 409  | `{"status":"error"}`              | Nonce already used (replay).                         |
| 429  | `{"status":"error"}`              | More than 5 requests in the last 60 s.                |

Error response bodies MUST NOT contain any further detail — no reason
strings, no field names. The status code is the only signal about which
check failed.

---

## 3. Device registry (SQLite)

```sql
CREATE TABLE devices (
  device_id   TEXT PRIMARY KEY,          -- e.g. 'dev-001'
  secret_key  TEXT NOT NULL,             -- base64 of the 32-byte AES key
  owner_name  TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE contacts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id   TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  relation    TEXT,                      -- e.g. 'spouse', 'friend'
  phone       TEXT NOT NULL,
  email       TEXT,
  priority    INTEGER NOT NULL DEFAULT 1,  -- lower value = notified first
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Written by the server only. Implements validation checks 4 and 5.
CREATE TABLE used_nonces (
  device_id   TEXT NOT NULL,
  nonce_b64   TEXT NOT NULL,
  seen_at     TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (device_id, nonce_b64)
);

CREATE TABLE request_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id   TEXT NOT NULL,
  received_at INTEGER NOT NULL           -- unix seconds, for the sliding window
);
```

Contacts are notified in `priority` order (lowest first) when a
`type: "alert"` event is accepted.

---

## 4. Secrets & configuration

- The backend reads configuration from environment variables (optionally via
  a `.env` file that is **never committed**):
  - `SILENT_DB_PATH` — SQLite path (default `./data/silentsos.db`).
- The simulated device / ESP32 provisioning reads:
  - `SILENT_DEVICE_ID`, `SILENT_DEVICE_KEY` (base64).
- Never hardcode secrets in source. Never commit `.env` or `*.db` files
  (see `.gitignore`).

---

## 5. Changelog

- **1.0.0** (2026-10-14): initial frozen spec.
