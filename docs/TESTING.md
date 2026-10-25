> Back to [README](../README.md) · Part of the SilentSOS docs.


# Testing

```bash
# From the repo root, venv activated:
pip install pytest httpx   # test-only deps, not in requirements.txt
python -m pytest backend/tests/ -q
```

*Expected result:* `96 passed`.

What the suite proves (`backend/tests/`):

| File | Proves |
|---|---|
| `test_api.py` | Protocol validation order and status codes (400/401/408/409/429), cooldown, trail updates, safe resolution, ack endpoint |
| `test_telegram.py` | `/start` linking, `ack` handling, tiered notifications, chat_id stored as text |
| `test_escalation.py` | Tier-1-only notify, no escalation when acked in time, escalation sets `escalated_at` + notifies tier 2 exactly once |
| `test_demo.py` | Attack-demo endpoint (6/6 PASS), dashboard stats API, home-page content |
| `test_security.py` | Simulate-attack endpoint, security page content |
| `test_pwa_i18n.py` | Manifest/icons/service-worker routes, English/Nepali key parity, PWA wiring on all pages |
| `test_report.py` | Report page serves, 404 for unknown ids, report button on track page, battery recorded per trail point |
| `test_track.py` | Track page serves, friendly 404, contacts carry ack status |

The live attack demo (`python scripts/attack_demo.py`, needs the server
running) proves the same six rejections against a running backend.
