# SilentSOS

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests: 96 passed](https://img.shields.io/badge/tests-96%20passed-brightgreen)]()

**SilentSOS is a discreet emergency-alert system.** When someone can't safely
pull out their phone — harassment, assault, a medical emergency — they press
a small pocket button three times. An encrypted distress signal with their
live GPS location goes to a server, which notifies their trusted contacts
over Telegram with a live tracking link. No screen, no sound, no visible
action.

## How it works

1. **Press** — Three quick presses on the ESP32 button (or triple-click in
   the simulator).
2. **Encrypt** — The device seals the alert with AES-256-GCM encryption, so
   nobody can read it or fake it.
3. **Verify** — The server checks the device, the encryption, the timestamp,
   and that the message was never sent before.
4. **Notify** — Trusted contacts get a Telegram message with a live map link.
5. **Resolve** — A long press (or the "I'm safe" button) marks you safe.

## Features

- Encrypted alerts with replay, tampering, and stale-message protection
- Live tracking page with map, location trail, and contact timeline
- Tiered contacts: tier 1 is notified first, tier 2 is auto-notified if
  nobody replies within 60 seconds
- Safe Walk: a check-in timer with a duress PIN that silently alerts
  while pretending to cancel
- Operator dashboard, security center, and printable incident reports
- English and Nepali interface, works offline as an installable app
- One-click demo scenario and a 6-attack security demo

## Quick start

You need Python 3.10+ and Git. No hardware needed — the simulator plays the
role of the device.

```bash
git clone https://github.com/sakshyam-hola/SilentSOS.git
cd SilentSOS
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env && cp simulator/config.example.json simulator/config.json
python scripts/seed_demo.py          # SAVE the printed key, paste it as "key" in simulator/config.json
uvicorn backend.main:app --port 8001
```

Then open http://127.0.0.1:8001/simulator and triple-click the SOS button.

## Try the demo

1. Open http://127.0.0.1:8001 and click **Run demo scenario** — a full
   scripted story (alert → moving map → contact replies → resolved) plays
   by itself in about 35 seconds.
2. Or send an alert yourself from the simulator, then follow the tracking
   link, click **I'm safe / resolve**, and check the audit log
   at http://127.0.0.1:8001/security.
3. To test the security, run the attack demo (needs the server running):

```bash
python scripts/attack_demo.py
```

It fires 6 real attacks — replay, tampered message, expired timestamp,
wrong key, unknown device, flood — and all 6 should be blocked.

No hardware? The command-line simulator works the same way:

```bash
python simulator/device_sim.py
```

Press Enter three times quickly to send an alert, type `hold` for safe,
or `route` to walk a preset path.

## Project structure

```text
backend/        FastAPI server: alert API, crypto, registry, Telegram
backend/static/ Web pages: dashboard, simulator UI, tracking, security
simulator/      Virtual device (command-line + browser)
firmware/       ESP32 code (Arduino) + Wokwi simulator files
scripts/        Demo seeder + attack demo
docs/           Protocol, guides, threat model, judging kit
```

## Documentation

- [docs/FEATURES.md](docs/FEATURES.md) — what works now, what is
  simulated, what is on the roadmap
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system diagram and the
  full story of a button press, stage by stage
- [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) — the repo
  layout, annotated
- [docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md) — the complete run guide:
  setup, environment variables, demo, tests, Docker, troubleshooting
- [docs/TELEGRAM_SETUP.md](docs/TELEGRAM_SETUP.md) — creating the bot,
  linking contacts, troubleshooting delivery
- [docs/ESP32_SETUP.md](docs/ESP32_SETUP.md) — wiring, flashing, and
  testing the real device
- [docs/SECURITY.md](docs/SECURITY.md) — how the system is secured
- [docs/PROTOCOL.md](docs/PROTOCOL.md) — the encrypted protocol, field by
  field (frozen, never changes)
- [docs/DEPLOY.md](docs/DEPLOY.md) — putting the server on the internet
- [docs/HARDWARE_SWAP.md](docs/HARDWARE_SWAP.md) — swapping the simulator
  for the real ESP32
- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) — what is protected, and
  what is not
- [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md) — the 90-second demo script
- [docs/TESTING.md](docs/TESTING.md) — what each test file proves
- [docs/FAQ.md](docs/FAQ.md) — common questions
- [docs/ROADMAP.md](docs/ROADMAP.md) — what is not built yet, honestly
- [docs/PITCH.md](docs/PITCH.md), [docs/DEMO_CHECKLIST.md](docs/DEMO_CHECKLIST.md),
  [docs/JUDGE_QA.md](docs/JUDGE_QA.md) — judging kit

## Testing

```bash
pip install pytest httpx
python -m pytest backend/tests/ -q
```

Expected: `96 passed`.

## Honest status

- The ESP32 firmware is tested in the Wokwi simulator only — it has not
  run on a physical board yet.
- Real GPS support exists in the code but is untested.
- There is no SMS fallback yet (Telegram only); it is on the roadmap.
- The demo read-only APIs are intentionally open — this is a demo, not a
  production deployment.

## Contributing

Issues and pull requests are welcome. Two rules: never change the protocol
field names in `docs/PROTOCOL.md`, and never commit secrets (`.env`,
`config.json`, `config.h`, `*.db` are all git-ignored).

## License

MIT — see [LICENSE](LICENSE).
