> Back to [README](../README.md) · Part of the SilentSOS docs.


# Demo guide

**The 90-second script** (full checklist in `docs/DEMO_CHECKLIST.md`):

| Time | You do | Audience sees |
|---|---|---|
| 0:00 | "Three presses, no screen, no sound." Triple-click the SOS button 3× in 2 s. | Status log: alert accepted, vibration pulse. |
| 0:10 | Hold up the phone. | 🚨 Telegram alert with live map link + battery. |
| 0:20 | Open the tracking link. | Live map, ACTIVE badge, stat cards. |
| 0:35 | "Someone responds." Contact replies **`ack`**. | Acknowledged ✓ within seconds. |
| 0:50 | "Now the part attackers try." Run `python scripts/attack_demo.py`. | Live PASS/FAIL table: replay → 409, tampered → 401, expired → 408, wrong key → 401, unknown device → 401, flood → 429s. |
| 1:25 | "Six attacks, six rejections — all in the audit log." | `/security` feed. |

**One-click scenario:** the home page has a **▶ Run demo scenario** button
that plays a ~35 s scripted story by itself (alert → 4 location updates →
simulated contact acks → resolve), with a step indicator and a link to
watch it live on the tracking page.

**Attack demo:** the home page also has **Skip to attack demo**, which runs
the same six attacks in-process against an ephemeral device and shows the
results on screen.

**Backup plan if Wi-Fi or Telegram fails:** the alert still works — show
the tracking page and `/security` instead, and say "the notification
channel is down; the alert and the audit trail are not." If a triple-press
during rehearsal triggered the 30 s cooldown, say so — duplicate presses
don't spam contacts, it's a feature.
