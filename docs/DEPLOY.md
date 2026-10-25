# Deploying SilentSOS publicly (Render free tier)

Why Render: genuinely free web-service tier, automatic TLS certificates,
and native Dockerfile support. Railway and Fly.io also work with the same
`Dockerfile` — the steps below are Render-specific.

What you get: a public `https://` URL that the real ESP32, the judges'
phones, and Telegram tracking links all use. No ngrok needed anymore.

## Prerequisites

- This repo pushed to GitHub (`git init`, commit, push — `.gitignore`
  already excludes `.env`, `*.db`, and `config.h`).
- A Render account (free): https://render.com

## Exact steps

1. **Render dashboard → New → Web Service →** select your GitHub repo.
2. **Settings:**
   - Name: `silentsos` (your URL becomes `https://silentsos.onrender.com`;
     if taken, Render suggests a variant — note the exact URL).
   - Region: closest to you (Singapore works well from Nepal).
   - Runtime: **Docker** (uses the repo's `Dockerfile`).
   - Instance type: **Free**.
3. **Environment variables** (Render dashboard → Environment):
   - `PUBLIC_BASE_URL` = `https://silentsos.onrender.com`
     (your exact URL from step 2 — this is what Telegram tracking links use).
   - `TELEGRAM_BOT_TOKEN` = your bot token (optional; alerts work without it,
     contacts just won't get Telegram messages).
   - `PORT` is set automatically by Render — do not override it.
4. **Deploy.** Watch the logs. On a fresh database the seed script runs and
   prints (once):
   ```
   !!! SAVE THIS KEY NOW — it is shown only once !!!
   SILENT_DEVICE_KEY=<base64 key>
   ```
   Copy that key — it goes into `simulator/config.json` (as
   `SILENT_DEVICE_KEY`) and into the firmware's `config.h` (`DEVICE_KEY_B64`).
5. Open `https://silentsos.onrender.com` — the operator home page loads.
   Open `/simulator` and trigger an alert; reply `ack` to the Telegram
   message if you linked a contact.

## Point the hardware and simulator at it

- **Simulator** (`simulator/config.json`): `base_url` =
  `https://silentsos.onrender.com`, `device_id` = `dev-001`,
  `key` = the base64 key from the deploy logs.
- **ESP32** (`firmware/silentsos/config.h`):
  `SERVER_URL` = `https://silentsos.onrender.com` (no trailing slash),
  `DEVICE_ID`/`DEVICE_KEY_B64` from `--export-config` after registering a
  real device row (see `docs/HARDWARE_SWAP.md`).
- **Judges' phones:** they just open the public URL — `/` for the operator
  view, `/track/{id}` links arrive via Telegram.

## Verify HTTPS

```bash
# 1. Plain http must bounce to https (307 preserves method + body)
curl -sI http://silentsos.onrender.com/api/health | head -4
# → HTTP/1.1 307 Temporary Redirect
# → location: https://silentsos.onrender.com/api/health

# 2. https serves with HSTS
curl -sI https://silentsos.onrender.com/api/health | grep -i strict
# → strict-transport-security: max-age=31536000; includeSubDomains

# 3. Browser check: open https://silentsos.onrender.com — the padlock must
#    show a valid certificate (issued by Render/Let's Encrypt automatically).
```

HTTPS is enforced in two layers: Render terminates TLS at its edge, and
the app's middleware 307-redirects anything that arrived over plain http
(behind a proxy) plus sends `Strict-Transport-Security`. Local direct
access (`http://127.0.0.1:8001`) is unaffected — the middleware only acts
when the `X-Forwarded-Proto` header is present.

## Free-tier caveats (know these before demo day)

- **Sleep:** free services spin down after 15 min idle; the first request
  then takes ~30–60 s to wake. Warm it up a minute before the demo, or add
  a free uptime pinger (e.g. UptimeRobot pinging `/api/health` every 5 min).
- **Ephemeral database:** the free tier has no persistent disk. **Every new
  deploy wipes the SQLite file** and the seed re-runs, generating a **new**
  `dev-001` key. After each redeploy: copy the new key from the logs and
  update `simulator/config.json` / `config.h`. Alert history also resets —
  fine for a demo, not for production.
- **Telegram polling:** the bot's `getUpdates` long-polling runs inside the
  web service and works on Render (outbound https is allowed).
- If you outgrow this, the paid fix is one Render persistent disk mounted
  at `/app/data` (then `SILENT_DB_PATH=/app/data/silentsos.db` keeps the
  same key and history across deploys).
