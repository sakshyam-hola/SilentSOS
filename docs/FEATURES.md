> Back to [README](../README.md) · Part of the SilentSOS docs.


# Features

| Feature | Status |
|---|---|
| Encrypted alert protocol (AES-256-GCM, replay + freshness + rate-limit protection) | **Working now** |
| FastAPI backend: alert intake, validation, audit log, tracking API | **Working now** |
| Telegram notifications to trusted contacts (alert / escalated / safe) | **Working now** |
| Contact replies `ack` via Telegram, shown live on the tracking page | **Working now** |
| Automatic escalation to tier-2 contacts if nobody acks in time | **Working now** |
| Live tracking page (`/track/{id}`) with map, timeline, stat cards | **Working now** |
| Operator dashboard (`/`) with KPIs, charts, device list | **Working now** |
| Security center (`/security`): live audit feed, attack simulator | **Working now** |
| Incident report (`/report/{id}`): printable/PDF report for resolved alerts | **Working now** |
| Web + CLI device simulators (speak the exact encrypted protocol) | **Working now** |
| Safe Walk timer with duress PIN (web simulator) | **Working now** |
| PWA: installable, offline tracking page, English/नेपाली, high-contrast mode | **Working now** |
| ESP32 firmware (button, vibration, GPS, NTP, TLS) | **Simulated until hardware arrives** — written and Wokwi-testable, never run on a physical board here |
| Real GPS coordinates from a NEO-6M module | **Simulated until hardware arrives** (`USE_GPS 0` sends fixed demo coordinates) |
| SMS fallback via SIM800L for low-connectivity areas | **Roadmap** |
| Signal / push notifications as an alternative to Telegram | **Roadmap** |
| Battery optimization (real battery sensing, deep sleep) | **Roadmap** — firmware currently sends a fixed demo battery value |
