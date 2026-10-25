# Hardware swap checklist — real ESP32

When the board arrives: how to move from the Wokwi/simulator setup to the
physical device. Assumes the firmware is already built
(`firmware/silentsos/silentsos.ino`, see `firmware/README.md`).

## 1. Provision the device ID and key

Use a **fresh** device row for the real board — do not reuse the demo
`dev-001` key on hardware you carry. Register it:

```bash
cd ~/workspace/silentsos
# (one-time) add a real device row — or extend registry.py --seed
sqlite3 data/silentsos.db \
  "INSERT INTO devices (device_id, secret_key, owner_name) VALUES \
   ('esp32-001', '<base64-of-32-random-bytes>', 'Your Name');"
# generate the key with:
python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Then export it straight into `config.h` format:

```bash
python3 backend/registry.py --export-config esp32-001
```

Paste the two `#define` lines into `firmware/silentsos/config.h`
(git-ignored — never commit it). Also add yourself as a contact
(`python3 backend/telegram.py --add-contact "Your Name" "+97798..." --device esp32-001`)
and link Telegram with the printed `/start` code, so alerts reach you.

## 2. Confirm NTP time works

Flash, open Serial Monitor at 115200 baud, and look for:

```
WiFi connected, IP: 192.168.x.x
NTP sync via pool.ntp.org ...
clock synced: 1792001234
ready: 3x press = alert, 3 s hold = safe
```

`clock synced:` with a plausible unix time = good. If you see
`WARNING: NTP sync failed`, the server will 408-reject every packet
(timestamps must be within ±60 s). Fix DNS/firewall for UDP port 123
before going further.

## 3. Phone hotspot instead of venue Wi-Fi

In `config.h`:

```c
#define WIFI_SSID       "YourPhoneHotspotName"
#define WIFI_PASSWORD   "hotspotpassword"
#define SERVER_URL      "https://<your-ngrok-or-tunnel-url>"  // no trailing slash
```

The backend must be reachable from the phone's network — `localhost` will
not work. Run `ngrok http 8001` on the backend machine and use the
`https://` URL. Keep the phone near the ESP32; 2.4 GHz hotspot band works
best (ESP32 has no 5 GHz radio).

## 4. Side-by-side test: simulator vs real device

Goal: prove the backend treats both identically.

1. Start the backend: `uvicorn backend.main:app --port 8001`.
2. CLI simulator (uses `dev-001`): triple-press → alert accepted.
3. Real device (`esp32-001`): triple-press → alert accepted.
4. Open `/` — both devices show **last seen just now**.
5. Open each alert's `/track/{id}` — identical layout, trail, contacts.
6. Open `/security` — both devices' requests appear in the audit log with
   the same `alert_created` / `update_appended` reasons.
7. Reply `ack` to the Telegram message for each alert; both show
   **Acknowledged ✓** on their tracking pages.
8. Hold 3 s on the real device → `safe`; the simulator's alert stays
   active — confirming per-device state isolation.

## 5. Troubleshooting

| Symptom (Serial / HTTP) | Likely cause | Fix |
|---|---|---|
| `HTTP 401` on every send | **Key mismatch**: `config.h` key ≠ registry key, or wrong `DEVICE_ID` (AAD is the device_id — a typo breaks the tag too) | Re-run `registry.py --export-config <id>`, paste fresh, re-flash |
| `HTTP 401` only for this board, simulator works | Nonce reuse after re-flash (same `esp_random()` seed sequence is fine — nonces are random, but a *replayed* packet, e.g. from a Serial-log copy/paste test, is rejected) | Send a fresh press; never replay a captured envelope |
| `HTTP 408` | **Clock**: NTP failed or timezone wrong — `ts` must be within ±60 s of server time | Check Serial for `clock synced:`; verify `GMT_OFFSET_SEC` (Kathmandu = 20700) |
| `HTTP 409` | Duplicate send (button bounce or retry reusing a nonce) | Normal — the firmware uses a fresh nonce per try; check debounce wiring |
| `HTTP 429` | Rate limit: >5 requests/min (e.g. updates faster than every 12 s) | Expected behavior; slow the cadence (firmware uses 15 s) |
| `WiFi failed; rebooting` loop | Wrong SSID/password, 5 GHz-only hotspot, or venue captive portal | Use the phone hotspot (2.4 GHz); captive portals cannot work — no browser on the ESP32 |
| `HTTP -1` (connection failed) | Backend unreachable: wrong `SERVER_URL`, tunnel expired, or plain `http://` URL on a TLS-only setup | `curl` the `/api/health` endpoint from another machine first; check the tunnel is still running |
| Vibration: 3 pulses, Serial shows retries | Any of the above — read the `HTTP <code>` lines to identify which | Match the code to this table |
| GPS never gets a fix (`USE_GPS 1`) | Indoors, or RX/TX swapped | Test outdoors; NEO-6M TX → ESP32 GPIO 16, RX → GPIO 17; fall back to `USE_GPS 0` |
