# SilentSOS ESP32 firmware

Arduino-framework firmware for the SilentSOS alert button. Implements
`docs/PROTOCOL.md` exactly: AES-256-GCM via mbedTLS, fresh 12-byte nonce
per message (`esp_random()`), `device_id` as AAD, JSON envelope POSTed to
`/api/alert`.

## Wiring

| ESP32 pin | Connects to | Notes |
|---|---|---|
| GPIO 4 | Pushbutton leg 1 | `INPUT_PULLUP`; leg 2 → GND. Active LOW. |
| GPIO 5 | Vibration motor (+) | **Via a driver** — a coin motor draws more than a GPIO can source. Use a 2N2222 transistor (1 kΩ base resistor), motor between 3V3 and collector, flyback diode across the motor. |
| GPIO 16 (RX2) | NEO-6M TX | Only if `USE_GPS 1` in `config.h`. |
| GPIO 17 (TX2) | NEO-6M RX | Only if `USE_GPS 1` in `config.h`. |
| 3V3 | NEO-6M VCC, motor driver supply | |
| GND | Common ground | Button leg 2, GPS GND, driver emitter. |

In the Wokwi simulator the vibration motor is replaced by a red LED +
220 Ω resistor on GPIO 5 (see `firmware/diagram.json`).

## Required libraries

Installed via Arduino IDE → Tools → Manage Libraries (or auto-installed
by Wokwi from the `#include` lines):

| Library | Needed when |
|---|---|
| **TinyGPS++** (by Mikal Hart) | `USE_GPS 1` only |
| ESP32 Arduino core ≥ 2.0 | always (WiFi, WiFiClientSecure, HTTPClient, mbedTLS are built in — no extra install) |

Board: **ESP32 Dev Module** (or any ESP32). Serial monitor at 115200 baud.

## Configuration

1. `cp firmware/silentsos/config.example.h firmware/silentsos/config.h`
   (`config.h` is git-ignored — never commit it.)
2. Fill in `WIFI_SSID` / `WIFI_PASSWORD`, `SERVER_URL` (no trailing slash;
   `http://` for local dev, `https://` for a public tunnel), `DEVICE_ID`,
   and `DEVICE_KEY_B64` (from `python backend/registry.py --seed`).
3. `https://` uses `setInsecure()` (no CA validation) — fine for the demo
   tunnel; pin the server certificate for production.

## Behavior

- 3 presses within 2 s → `alert` (30 s firmware-side cooldown).
- 3 s hold → `safe`.
- While an alert is active → `update` every 15 s (4/min, under the
  server's 5/min rate limit).
- 1 vibration pulse = HTTP 200; 3 pulses = failed after 3 tries
  (exponential backoff, fresh nonce per try).
- NTP sync at boot (the ESP32 has no RTC after power-up); without it the
  server rejects timestamps (HTTP 408).

## Test checklist

- [ ] `config.h` created from the example; sketch compiles for ESP32 Dev Module.
- [ ] Serial Monitor @115200: WiFi connects, NTP syncs (`clock synced:`), `ready` printed.
- [ ] Single press → `press registered`; 3 quick presses → `triple press`,
      `POST … -> HTTP 200`, 1 vibration pulse; alert appears on `/track`.
- [ ] Hold 3 s → `3 s hold`, `safe` sent, HTTP 200, alert shows RESOLVED.
- [ ] Second triple-press within 30 s → `cooldown: alert suppressed`.
- [ ] While alert active: `sending periodic update` every 15 s; trail grows on `/track`.
- [ ] Bad `SERVER_URL` → `HTTP -1` retries with backoff, then 3 pulses.
- [ ] `USE_GPS 1` with NEO-6M: after a fix, positions follow the GPS
      (Serial shows real coordinates instead of fixed ones).

## Wokwi simulator

1. Go to [wokwi.com](https://wokwi.com) → New Project → ESP32.
2. Replace the sketch with `firmware/silentsos/silentsos.ino` and add a
   `config.h` tab (copy of `config.example.h`) with:
   `WIFI_SSID "Wokwi-GUEST"`, `WIFI_PASSWORD ""`
   (that is Wokwi's built-in open network).
3. Replace `diagram.json` with `firmware/diagram.json` (button on GPIO 4,
   LED as vibration stand-in on GPIO 5).
4. Press ▶. Click the red button in the simulation.
5. **Networking note:** Wokwi cannot reach `localhost`. With the placeholder
   `SERVER_URL` the firmware runs in **dry-run mode**: it builds and
   encrypts each packet and prints the envelope to Serial instead of
   POSTing — enough to verify button logic, encryption, and vibration.
   For a live end-to-end test, expose the backend with
   `ngrok http 8001` (or Cloudflare Tunnel) and put the `https://` URL in
   `config.h`.
