> Back to [README](../README.md) · Part of the SilentSOS docs.


# Things not (yet) in the code

Listed here per the documentation rules — the README above does not claim
any of these work:

1. **Physical ESP32 hardware** — the firmware has never been compiled or
   run on a real board in this repo (Wokwi-tested only).
2. **Real GPS fixes** — `USE_GPS 1` is implemented but untested against a
   real NEO-6M; the default sends fixed demo coordinates.
3. **SIM800L SMS fallback** — roadmap; mentioned in `docs/PITCH.md`, no
   code exists.
4. **Signal / push-notification alternatives** — roadmap; no code exists.
5. **Battery optimization / real battery sensing** — the firmware sends a
   fixed `BATTERY_PCT` demo value; no ADC or deep-sleep code exists.
6. **Telegram webhooks** — the code uses long-polling only; webhook setup
   is described for completeness but not implemented.
7. **Certificate pinning** — the firmware uses `setInsecure()` (no CA
   validation); pinning is noted as a production requirement, not code.
8. **Authenticated read APIs** — `/api/alerts`, `/api/audit`, `/track`,
   `/security` are intentionally open in this demo build.
