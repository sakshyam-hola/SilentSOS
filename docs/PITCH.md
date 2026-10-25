# SilentSOS — 2-minute pitch script

*~260 words. Timings are guides — if the demo runs long, trim the roadmap.*

## 0:00 — Problem (25 s)

"In an emergency — harassment on the street, a medical crisis, an unsafe
ride — your phone is the worst tool you have. You have to pull it out,
unlock it, find the app, type. That's slow, it's visible, and in the worst
cases it's dangerous. The people who need help fastest are the ones who
can't visibly ask for it."

## 0:25 — Solution (25 s)

"SilentSOS is a pocket-sized device with one button. Three quick presses —
no screen, no sound, nothing visible — sends an encrypted distress signal
with your live GPS location to the people you trust. They get a Telegram
message with a live tracking map and your battery level. One of them replies
'ack' and everyone can see help is on the way. A three-second hold cancels
with an 'I'm safe' message if it was a false alarm."

## 0:50 — Live demo (30 s)

*Do the 90-second checklist compressed — or just the alert + map:*

"Watch: triple-press on the simulator — the alert is accepted. The Telegram
message arrives with a live map link. Open it: there's the pulsing marker,
updating every few seconds. A contact replies 'ack' — acknowledged, live.
The whole loop, device to map, in under ten seconds."

## 1:20 — Security design (20 s)

"Every packet is AES-256-GCM encrypted with a fresh nonce — replay an old
alert and the server rejects it, tamper with one byte and the authentication
tag fails, fake the clock and the sixty-second freshness window kills it.
There's a six-attack demo that proves it — I can run it live. And every
single request, accepted or rejected, goes into an audit log you can watch
in real time."

## 1:40 — Cost (10 s)

"The hardware is an ESP32 board, a button, a vibration motor, and a battery —
about thirteen dollars in parts. No subscription, no cloud fees; the backend
runs on a free tier."

## 1:50 — Roadmap (10 s)

"Next: an SMS fallback with a four-dollar SIM800L module, so it works where
there's no Wi-Fi — exactly the low-connectivity regions that need it most.
Then a smaller wearable form factor."

## One-line closer

"SilentSOS: help you can call for without anyone seeing you ask."
