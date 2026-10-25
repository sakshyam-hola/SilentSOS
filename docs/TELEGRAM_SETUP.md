> Back to [README](../README.md) · Part of the SilentSOS docs.


# Telegram bot setup

### 1. Install Telegram and create an account

Install Telegram on your phone (and optionally Telegram Desktop) and sign
up with your phone number if you haven't.

### 2. Create a bot with @BotFather

1. In Telegram, open a chat with **@BotFather** (the official bot —
   verified checkmark).
2. Send `/newbot`.
3. Choose a display name (e.g. `My SilentSOS`).
4. Choose a username — it **must end in `bot`**, e.g. `my_silentsos_bot`.
5. BotFather replies with a token like `123456:ABC-DEF...`. **Copy it.**

### 3. Put the token in `.env`

```bash
# inside .env:
TELEGRAM_BOT_TOKEN=put-your-token-here
```

> **Warning:** never commit the token, never paste it in a public chat,
> never screenshot it. If it leaks, open @BotFather, send `/revoke`,
> select your bot, and put the new token in `.env`.

### 4. Start (or restart) the backend

The token is read at startup. If the server was already running, stop it
(Ctrl+C) and start it again:

```bash
uvicorn backend.main:app --port 8001
```

Watch the log: `telegram polling started` means the token was accepted.
`TELEGRAM_BOT_TOKEN not set; telegram disabled` means the `.env` wasn't
loaded — check the variable name.

### 5. Link each trusted contact

Each contact links **their own** Telegram account to their contact row:

1. Get the contact's personal code:
   ```bash
   python backend/telegram.py --codes
   ```
   ```text
   dev-001 | Asha Sharma | code: A3F9C1 | not linked
   ```
2. The contact opens your bot in Telegram and sends:
   ```text
   /start A3F9C1
   ```
3. The bot replies `✅ This chat is now linked…`.

**How the linking works in this repo:** `ensure_link_code()` generates a
6-character uppercase hex code (`secrets.token_hex(3).upper()`) stored in
`contacts.link_code` (unique). When `/start <code>` arrives via polling,
the server looks up the code and writes the sender's Telegram `chat_id`
(as text) into `contacts.telegram_chat_id`. From then on, that chat
receives this device's alerts.

To add yourself as a contact for testing:

```bash
python backend/telegram.py --add-contact "Your Name" "+97798XXXXXXXX"
```

### 6. Send a test alert and confirm the message arrives

Triple-press in the simulator. The linked phone should get:

> 🚨 SilentSOS alert from Demo User. Live location:
> http://127.0.0.1:8001/track/…. Battery 87%. Reply 'ack' if you're
> responding.

Tap the link — the tracking page opens.

### 7. Test the `ack` reply and the safe message

Reply `ack` to the bot. The bot confirms (`✅ Thanks … you're marked as
responding`), and the tracking page shows the acknowledgement within a few
seconds. Then resolve the alert (tracking page → **I'm safe / resolve**);
contacts get `✅ {owner} has marked themselves safe.`

### 8. Finding a chat_id manually

You normally never need this — `/start <code>` handles it. If you do: open
`https://api.telegram.org/bot<token>/getMe` in a browser to verify the
token, then after messaging the bot, open
`https://api.telegram.org/bot<token>/getUpdates` and read the `chat.id`
field. (Don't share these URLs — they contain your token.)

### 9. Polling vs webhooks

This repo uses **long-polling** (`getUpdates` in a background thread), not
webhooks. Polling works behind NAT and on localhost with zero setup, which
is why it was chosen for development.

When you deploy publicly, polling keeps working as-is. If you ever switch
to webhooks: Telegram requires a **public HTTPS URL**, you must call
`setWebhook` with that URL, and only one webhook can be active — polling
and webhooks are mutually exclusive (a `409 Conflict` means two clients
are polling the same bot; stop one).

### 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No message arrives | Contact never sent `/start <code>` | Run `--codes`, have them send it |
| `401 Unauthorized` in logs | Bad token | Re-copy from @BotFather into `.env`, restart |
| `403 Forbidden` | Contact blocked the bot | They must unblock it and send `/start` again |
| `409 Conflict` | Two instances polling the same bot | Stop the duplicate backend |
| Message arrives but the link won't open | `PUBLIC_BASE_URL` wrong | Set it to the public `https://` URL in `.env`, restart |
| Bot replies "Unknown link code" | Typo in the code | Codes are 6 uppercase hex chars; re-run `--codes` |

> **Note:** Telegram bot messages are **not end-to-end encrypted** — they
> travel through Telegram's servers. The part protected by AES-256-GCM is
> the **device → server** leg. Treat notification content accordingly.
