> Back to [README](../README.md) · Part of the SilentSOS docs.


# Project structure

```text
silentsos/
├── backend/                # FastAPI server (the whole backend)
│   ├── main.py             #  endpoints, validation chain, escalation + purge sweepers
│   ├── crypto.py           #  AES-256-GCM encrypt/decrypt helpers
│   ├── registry.py         #  SQLite schema, seed/show/export-config CLI
│   ├── telegram.py         #  Bot API calls, getUpdates polling, /start linking, ack handling
│   ├── demo.py             #  in-process attack demos for the security center
│   └── static/             #  web pages served by the backend
│       ├── home.html       #  operator dashboard (/)
│       ├── track.html      #  live incident tracking (/track/{id})
│       ├── report.html     #  printable incident report (/report/{id})
│       ├── security.html   #  security center (/security)
│       ├── i18n.js         #  English + Nepali UI strings (separate file)
│       └── sw.js           #  service worker (PWA offline support)
├── simulator/              # software stand-ins for the ESP32
│   ├── device_sim.py       #  CLI simulator: speaks the real encrypted protocol
│   ├── web.html            #  web simulator page (/simulator) incl. Safe Walk
│   └── config.example.json #  copy to config.json, fill in the device key
├── firmware/silentsos/     # ESP32 Arduino sketch (real hardware, when it arrives)
│   ├── silentsos.ino       #  button/GPS/crypto/HTTPS logic
│   ├── config.example.h    #  copy to config.h (git-ignored), fill in secrets
│   └── diagram.json        #  Wokwi simulator wiring
├── scripts/                # helpers: seed_demo.py, attack_demo.py
├── backend/tests/          # automated test suite (pytest)
├── docs/                   # PROTOCOL.md (frozen spec), DEPLOY.md, THREAT_MODEL.md,
│                           #  PITCH.md, DEMO_CHECKLIST.md, JUDGE_QA.md, HARDWARE_SWAP.md
├── Dockerfile              # production container (used by Render)
├── requirements.txt        # Python dependencies
└── .env.example            # copy to .env (never commit the real one)
```
