# SilentSOS device simulator

Behaves like the future ESP32 firmware and speaks the exact encrypted
protocol from `docs/PROTOCOL.md`.

## CLI simulator

```bash
cd ~/workspace/silentsos   # project root
cp simulator/config.example.json simulator/config.json
# put the base64 key from `python backend/registry.py --seed` into
# simulator/config.json  (it is git-ignored; never commit it)
python simulator/device_sim.py
```

Interactive commands:

| Input     | Action                                                        |
|-----------|---------------------------------------------------------------|
| `<Enter>` | button press — 3 presses within 2 s send `type: "alert"`      |
| `hold`    | 3-second long press → sends `type: "safe"`                    |
| `route`   | `type: "update"` every 3 s along a preset route (Ctrl+C stops)|
| `quit`    | exit                                                          |

Presses closer than 50 ms are debounced. Success prints
`vibration: 1 short pulse`, failure prints `vibration: 3 short pulses`
after exponential-backoff retries (max 3 tries, fresh nonce per try).

## Web simulator

Start the backend, then open http://127.0.0.1:8001/simulator :

```bash
cd ~/workspace/silentsos
uvicorn backend.main:app --port 8001
```

Triple-click the round SOS button within 2 s to trigger an alert.
The page calls `POST /api/simulator/send`; the server encrypts with the
device's registry key, so the key never reaches the browser.
