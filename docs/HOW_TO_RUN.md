> Back to [README](../README.md) · Part of the SilentSOS docs.

> ⚡ **Run it in 60 seconds:**
> ```bash
> git clone https://github.com/sakshyam-hola/SilentSOS.git SilentSOS && cd SilentSOS
> python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
> pip install -r requirements.txt
> cp .env.example .env && cp simulator/config.example.json simulator/config.json
> python scripts/seed_demo.py          # SAVE the printed key → paste it as "key" in simulator/config.json
> uvicorn backend.main:app --port 8001 # then open http://127.0.0.1:8001/simulator and triple-click SOS
> ```


# How to run SilentSOS

> This is the complete reference. For the short path, see the
> [quick start in the README](../README.md#quick-start).

### 1. Prerequisites

| Tool | Minimum version | How to check | Where to get it |
|---|---|---|---|
| **Python** (the language this project uses) | 3.10+ (3.12 is what the Dockerfile uses) | `python --version` | [python.org](https://www.python.org/downloads/) |
| **Git** | any recent version | `git --version` | [git-scm.com](https://git-scm.com/downloads) |
| **pip** | ships with Python | `pip --version` | — |
| **Docker** *(optional, step 12 only)* | 20+ | `docker --version` | [docker.com](https://www.docker.com/products/docker-desktop/) |
| A modern browser (Chrome/Edge/Firefox) | any recent version | — | — |

*Expected result:* `python --version` prints something like `Python 3.12.3`.

*If it fails:* on Windows, `python` may not be found even after installing —
re-run the installer and tick **"Add python.exe to PATH"**, or use `py`
instead of `python` in every command below.

### 2. Get the code

```bash
git clone https://github.com/sakshyam-hola/SilentSOS.git silentsos
cd silentsos
```

*Expected result:* a `silentsos/` folder containing `backend/`, `simulator/`,
`firmware/`, `requirements.txt`, and the rest of the project tree above.

*If it fails:* `git: command not found` — install Git from the table above
and restart your terminal.

### 3. Install dependencies

Create and activate a virtual environment first (keeps this project's
packages separate from your system Python):

```bash
python -m venv .venv
```

```bash
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate
```

Then install from the real requirements file:

```bash
pip install -r requirements.txt
```

*Expected result:* pip installs `fastapi`, `uvicorn`, `cryptography`, and
`requests` with no errors. Your prompt shows `(.venv)` (or `(.venv)` on
Windows).

*If it fails:* `pip: command not found` — the venv isn't activated; repeat
the activate step. On Windows, if activation is blocked by the execution
policy, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
first.

### 4. Configure environment variables

```bash
# Windows (PowerShell):
Copy-Item .env.example .env
# macOS / Linux:
cp .env.example .env
```

Every variable (all from `.env.example`):

| Name | Purpose | Example value | Required? |
|---|---|---|---|
| `SILENT_DB_PATH` | Where the SQLite database lives | `./data/silentsos.db` | No — defaults to `./data/silentsos.db` |
| `PORT` | Port the server listens on | `8001` | No — the run command sets it |
| `PUBLIC_BASE_URL` | Base URL put into Telegram tracking links | `http://127.0.0.1:8001` | No — defaults to `http://127.0.0.1:8001`; set to your public `https://` URL when deployed |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for notifications | *(empty)* | No — **alerts work fine without it**; only Telegram messages stop arriving |
| `ESCALATION_SECONDS` | Seconds with no ack before tier-2 contacts are notified | `60` | No — defaults to `60` |
| `SILENT_DEVICE_ID` / `SILENT_DEVICE_KEY` | Shown commented-out in `.env.example` | — | No — the simulator reads `simulator/config.json`, not these variables |

**For a software-only demo you can leave everything as-is** (all empty or
defaults). The one thing that stops working with an empty
`TELEGRAM_BOT_TOKEN` is Telegram delivery: no alert/safe messages, no
`ack` by reply — but the web **Ack** button on the tracking page
(`POST /api/alerts/{id}/ack`) still works, and so does everything else.

> **Warning:** `.env` is git-ignored. Never commit it, never paste tokens
> or keys from it into a chat.

### 5. Seed the demo data

```bash
python scripts/seed_demo.py
```

*Expected result:*

```text
Seeded demo device 'dev-001' with 3 demo contacts (2x tier 1, 1x tier 2).

!!! SAVE THIS KEY NOW — it is shown only once !!!
SILENT_DEVICE_KEY=<44-character base64 key>

Set it in your environment (PowerShell):
  $env:SILENT_DEVICE_ID="dev-001"
  $env:SILENT_DEVICE_KEY="<44-character base64 key>"
Never commit this key to source control.
```

The key is **shown only in this terminal output** and stored in the
database. Copy it now — the CLI simulator needs it in the next step, and
re-running the seeder will *not* print it again. It must never be
committed to git.

*If it fails:* `ModuleNotFoundError` — the venv isn't activated (step 3).
If it says `dev-001 already seeded`, the database already exists; that's
fine, but you won't get the key back — delete `data/silentsos.db` and run
again if you lost it.

Now point the simulator at the key:

```bash
# Windows (PowerShell):
Copy-Item simulator\config.example.json simulator\config.json
# macOS / Linux:
cp simulator/config.example.json simulator/config.json
```

Open `simulator/config.json` and paste the key as the `"key"` value
(keeping the quotes). `simulator/config.json` is git-ignored.

### 6. Start the server

```bash
uvicorn backend.main:app --port 8001
```

*Expected result:*

```text
INFO:     Uvicorn running on http://127.0.0.1:8001
```

Open **http://127.0.0.1:8001** in your browser — the operator dashboard
loads.

*If it fails:* `Address already in use` — something is already on port
8001; stop it or use `--port 8002` (and change `base_url` in
`simulator/config.json` to match).

**Health check** — in another terminal (or the browser):

```bash
curl http://127.0.0.1:8001/api/health
```

*Expected result:*

```json
{"status":"ok","time":1792131206,"db":"ok"}
```

(`time` is the server's Unix clock; `db` is `ok` when SQLite is
reachable.) *If it fails:* `curl: (7) Failed to connect` — the server
isn't running; go back to the start command.

### 7. Run the demo

**a. Open the home page** — http://127.0.0.1:8001 — the operator dashboard
with KPI cards, device list, and recent alerts.

**b. Open the web simulator** — http://127.0.0.1:8001/simulator — and
**triple-click the SOS button within 2 seconds**. The status log shows the
alert being accepted.

**c. Or use the CLI simulator** (new terminal, venv activated):

```bash
python simulator/device_sim.py
```

Press **Enter three times quickly** (within 2 s). Two extra commands:

```text
hold      simulate a 3-second long press -> sends type "safe"
route     send "update" every 3 s along a preset route (Ctrl+C stops)
quit      exit
```

*Expected result:* `vibration: 1 short pulse` (HTTP 200 accepted).
*If it fails:* `vibration: 3 short pulses` — the server isn't reachable;
check step 6.

**d. Open the tracking link** — the simulator prints the alert id, or
click **View** on the home page. Watch the live map, the ACTIVE badge with
its ticking timer, and the stat cards.

**e. Click "I'm safe / resolve"** — the badge flips to RESOLVED and the
timer freezes.

**f. Open /security** — http://127.0.0.1:8001/security — the audit log
shows every request with its verdict badge; click any row for the
validation checklist.

**g. One-click scenario** — back on the home page, click **▶ Run demo
scenario**. It plays a ~35 s scripted story on its own (alert → location
updates → a simulated contact acks → resolve) with a step indicator and a
"watch it live" link to the tracking page.

### 8. Run the attack demo

With the server running, in another terminal (venv activated):

```bash
python scripts/attack_demo.py
```

*Expected result* — a PASS/FAIL table (exit code 0 when all pass):

```text
Attack                Expected    Got               Result
────────────────────────────────────────────────────────────
Replay                409         409               PASS
Tampered ciphertext   401         401               PASS
Expired timestamp     408         408               PASS
Wrong key             401         401               PASS
Unknown device        401         401               PASS
Flood (20 in 10s)     >=10x 429   4x 200, 16x 429   PASS
────────────────────────────────────────────────────────────
6/6 passed
```

What each attack proves: **Replay** — a captured packet can't be resent
(nonce already used → `409`); **Tampered ciphertext** — modified bytes fail
GCM tag verification (`401`); **Expired timestamp** — a 5-minute-old
message fails the ±60 s freshness window (`408`); **Wrong key** —
decryption with the wrong key fails (`401`); **Unknown device** — unregistered
devices are rejected (`401`); **Flood** — the 5/min rate limit kicks in
(`429`s). The flood test sends 20 requests and runs last because it
exhausts the rate-limit window.

*If it fails:* `config.json` errors mean step 5's key paste wasn't done.
Connection errors mean the server isn't running (step 6).

### 9. Run the automated tests

```bash
pip install pytest httpx
python -m pytest backend/tests/ -q
```

> **Note:** `pytest` and `httpx` are test-only dependencies, intentionally
> **not** in `requirements.txt`.

*Expected result:*

```text
96 passed
```

*If it fails:* run from the repo root (not from `backend/`), with the venv
activated. A single failing test name tells you which area broke — e.g.
`test_escalation.py` failures point at the tier/timeout logic.

### 10. Run with Telegram enabled

Short checklist (full walkthrough in [Telegram bot setup](TELEGRAM_SETUP.md)):

- [ ] Create a bot with @BotFather (`/newbot`, username must end in `bot`)
- [ ] Put the token in `.env` as `TELEGRAM_BOT_TOKEN`
- [ ] **Restart the server** (the token is read at startup) and confirm
      the log says `telegram polling started`
- [ ] Link a contact: `python backend/telegram.py --codes`, then the
      contact sends `/start <CODE>` to the bot
- [ ] Send a test alert and confirm the 🚨 message + tracking link arrive

### 11. Run with the real ESP32 later

Short checklist (full walkthrough in [ESP32 setup](ESP32_SETUP.md)):

- [ ] **Deploy the backend publicly first** — the ESP32 cannot reach
      `localhost`; use the public `https://` URL as `SERVER_URL`
- [ ] Provision a fresh device row (don't reuse the demo key) and fill in
      `firmware/silentsos/config.h` (git-ignored)
- [ ] Flash, open Serial Monitor at 115200 baud, confirm Wi-Fi + NTP sync
- [ ] Triple-press → alert → Telegram → tracking page, same as the demo above

The simulator and the real device speak the **same encrypted protocol**
(`docs/PROTOCOL.md`) and hit the same `/api/alert` endpoint, so everything
you verified with the simulator applies to the hardware.

### 12. Run with Docker

Only if you have Docker — a `Dockerfile` exists in the repo root.

```bash
docker build -t silentsos .
```

```bash
docker run -p 8001:8001 --env-file .env silentsos
```

*Expected result:* the container seeds the demo device on first start
(watch `docker logs` for the printed key — save it), then serves on
http://127.0.0.1:8001.

Notes: the image listens on `0.0.0.0:${PORT:-8001}`; `--env-file .env`
passes all your variables (including `TELEGRAM_BOT_TOKEN` and
`PUBLIC_BASE_URL`) into the container. For a public URL, add
`-e PUBLIC_BASE_URL=https://<your-host>` (or put it in `.env`).

*If it fails:* `docker: command not found` — install Docker Desktop. Port
conflicts behave like step 6 — remap with `-p 8002:8001` and set `PORT=8001`
inside (or just change the host side).

### 13. Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `Address already in use` on start | Something already on port 8001 | Stop it, or run with `--port 8002` (and update `simulator/config.json` → `base_url`) |
| `ModuleNotFoundError: No module named 'fastapi'` | Venv not activated | Activate it (step 3); prompt should show `(.venv)` |
| `no such table: devices` / empty pages | Seed never ran | `python scripts/seed_demo.py` (step 5) |
| `'key' is not valid base64` in the simulator | Placeholder still in `config.json` | Paste the real key from the seed output (step 5) |
| Alerts rejected with `408` | Device/simulator clock off by > 60 s | Fix the system clock; the ESP32 needs NTP sync |
| Alerts rejected with `401` | Wrong key or wrong `device_id` | Re-check the key paste; `device_id` must match the registry row exactly |
| Telegram message not arriving | No token, or contact never linked | Set `TELEGRAM_BOT_TOKEN` + restart; run `--codes` and `/start <CODE>` |
| Map tiles not loading | Tile CDN blocked or offline | The page auto-fails over between Esri providers; fully offline it shows a fallback message and everything else still works |
| Tests fail with collection errors | Run from the wrong folder | Run `pytest` from the repo root, not `backend/` |

### 14. Stop and reset

**Stop the server:** focus the terminal running uvicorn and press
**Ctrl+C**.

**Reset the database to a clean state** (deletes all alerts, acks, and the
demo device):

```bash
# Windows (PowerShell):
Remove-Item data\silentsos.db
# macOS / Linux:
rm data/silentsos.db
```

**Re-seed:**

```bash
python scripts/seed_demo.py
```

> **Note:** re-seeding generates a **new** device key (printed once).
> Paste it into `simulator/config.json` again, replacing the old one.
