> Back to [README](../README.md) · Part of the SilentSOS docs.


# FAQ

**Why Telegram?**
Because it needs no app install for contacts, delivers push notifications
reliably, supports bots with a free API, and works on every phone. The
trade-off is honest: bot messages are not end-to-end encrypted.

**Why not just use a phone app?**
In an emergency, unlocking a phone and opening an app is slow and visible.
A single-purpose button is faster, works with gloves, and draws no
attention. The phone stays in the pocket.

**What if there is no internet?**
The device needs connectivity to send — that's a real limitation. The
roadmap has an SMS fallback (SIM800L, ~$4) for low-connectivity areas.
Meanwhile, the tracking page works offline showing the last known state.

**What if the button is pressed by accident?**
Single presses do nothing — it takes three presses within two seconds. And
a 3-second hold (or the tracking page button) sends `safe` to stand
everyone down.

**What does a real unit cost?**
About **$13** in parts: ESP32 dev board ($5–8), button ($0.50), vibration
motor with transistor driver ($1–2), plus optional GPS ($8–12) and battery
($5–8). No subscription, no cloud fees on the free tier.

**Can someone fake an alert from my device?**
Only with the 32-byte device key. Without it, forged messages fail GCM
tag verification (`401`); replayed real messages fail the nonce check
(`409`); old messages fail the ±60 s freshness window (`408`).

**What happens to my location data?**
Latest position and trail are auto-deleted 24 hours after the alert
resolves. The alert record (without location) stays for the audit trail.

**How many contacts can I have?**
As many as you like, in two tiers: tier 1 is notified immediately, tier 2
only if nobody acknowledges within `ESCALATION_SECONDS` (default 60 s).

**Does it work outside Nepal?**
Yes — the coordinates are plain WGS84, Telegram works worldwide, and the
emergency number on the tracking page is a constant (`112`) you can change.
Only the demo data (Kathmandu places, +977 numbers) is Nepal-specific.

**Can I use it without Telegram?**
Yes. Alerts, tracking, escalation timers, and the audit log all work; only
the push notifications need the bot. The tracking link can be shared any
other way.
