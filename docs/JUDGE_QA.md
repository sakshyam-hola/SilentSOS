# 5 likely judge questions — with answers

## 1. "What stops an attacker from intercepting and replaying an alert?"

"Three independent layers. First, every packet is AES-256-GCM encrypted with
a fresh 12-byte random nonce, and the server keeps a registry of every nonce
it has ever seen — replay an old packet and you get a 409, which I can show
you live. Second, the plaintext carries a timestamp that must be within 60
seconds of the server clock, so even a fresh-looking replay goes stale in a
minute. Third, tampering with even one bit breaks the GCM authentication
tag, so the ciphertext can't be modified in transit. The attack demo runs
all of these back to back."

## 2. "What if someone steals the device?"

"Honest answer: the key lives in the device firmware, so a stolen device can
send alerts until it's deactivated — that's in our threat model as a known
limitation, not a secret. The mitigation is operational: the registry has an
active flag per device, and flipping it to zero instantly rejects everything
from that device with a 401. Longer term, we'd add a duress gesture — a
different press pattern that silently alerts while appearing to cancel."

## 3. "What happens with no Wi-Fi? There's no internet in a lot of places."

"Today, nothing — the device needs connectivity, and that's our biggest
honest limitation. The roadmap item is a four-dollar SIM800L GSM module as
an SMS fallback: if Wi-Fi fails, the device sends the encrypted payload —
or a minimal plaintext alert — as an SMS directly to the contacts' phones.
SMS works on 2G where data doesn't, which is exactly the low-connectivity
regions that need this most."

## 4. "How do you handle false alarms? A button in a pocket will get pressed."

"Three deliberate design choices. The trigger gesture — three presses within
two seconds with 50 ms debounce — doesn't happen by accident in a pocket.
Second, a three-second hold sends a 'safe' message that resolves the alert
and notifies contacts the person is okay. Third, the server has a 30-second
cooldown: panicked repeated presses don't spam contacts with five alerts,
they fold into one. False alarms are a UX problem, and the cancel path is as
designed as the alert path."

## 5. "Why hardware at all? Why not just a phone app with a panic button?"

"Because the threat model is *discreet* activation. A phone app means:
wake the phone, unlock it — biometrics fail under stress — find the app,
interact with a glowing screen. Every step is visible to anyone watching.
A dedicated device is one tactile gesture you can do inside a pocket, with
gloves on, without looking, and without a screen recording what you did.
It's also always charged for one job — a phone at 2% battery is a dead
panic button. The hardware costs about thirteen dollars; the phone app is
free and still worse at the one thing that matters."
