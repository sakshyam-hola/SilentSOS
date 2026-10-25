# 90-second live-demo checklist

*Rehearse once. Have these open before you start: the `/simulator` page, a
terminal, and the Telegram chat. The backend must be reachable — public
deploy (`docs/DEPLOY.md`) or local + tunnel.*

## Before the demo (do this earlier, not on stage)

- [ ] Backend running and seeded; you have the `dev-001` key in
      `simulator/config.json`.
- [ ] A contact linked to Telegram: `python backend/telegram.py --codes`,
      then `/start <code>` to the bot. **Use your own phone** for the alert —
      asking a judge to link mid-demo wastes the 90 seconds. (If a judge
      *wants* to be the one who acks, link them before the slot.)
- [ ] `/simulator` open in the browser, terminal open beside it.
- [ ] Phone screen-mirroring or hold the phone where the audience sees the
      Telegram message arrive.

## The 90 seconds

| Time | You do | Audience sees |
|---|---|---|
| 0:00 | "Three presses, no screen, no sound." Triple-**click** the SOS button 3× within 2 s. | Status log: `alert accepted`, 1 vibration pulse indicator. |
| 0:10 | Hold up the phone. | 🚨 Telegram alert: live map link + battery %. |
| 0:20 | Open the tracking link from the message. | Live map: pulsing red marker, ACTIVE status header with live timer, stat cards (battery / last update / speed), contacts as "Notified". |
| 0:35 | "Someone responds." The linked contact replies **`ack`** to the bot. | Within 3 s the map shows **Acknowledged ✓** next to the contact. |
| 0:50 | "Now the part attackers try." In the terminal: `python scripts/attack_demo.py` | PASS/FAIL table builds live. Point at the rows as they land: **Replay → 409**, tampered → 401, expired → 408, wrong key → 401, unknown device → 401, flood → 429s. |
| 1:25 | "Six attacks, six rejections — and every one is in the audit log." Open `/security` if time allows. | Green/red audit table. |

## If something goes wrong

- **Telegram message doesn't arrive:** the alert still worked — show the map
  and `/security` instead; say "the notification channel is down, the alert
  and audit trail are not." (This is also a true statement about the design:
  notification failure never fails the alert.)
- **Demo gods and the 429:** if you triple-pressed during rehearsal seconds
  earlier, the cooldown returns the *same* alert — say so, it's a feature:
  "duplicate presses within 30 seconds don't spam your contacts."
- **attack_demo takes ~30 s** (the flood test sends 20 requests). Start it,
  talk over it: narrate each row as it prints.
