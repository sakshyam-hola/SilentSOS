#!/usr/bin/env python3
"""SilentSOS AES-256-GCM helpers (docs/PROTOCOL.md, section 2.3).

- Algorithm: AES-256-GCM, 32-byte key.
- Nonce: 12 cryptographically random bytes per request.
- AAD: the device_id string, UTF-8 encoded.
- Plaintext: compact JSON, UTF-8.

The wire format carries ciphertext and the 16-byte GCM tag as two separate
base64 fields; `cryptography`'s AESGCM wants them concatenated, so the
helpers join/split at the boundary.
"""

from __future__ import annotations

import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 32

__all__ = [
    "NONCE_BYTES",
    "TAG_BYTES",
    "KEY_BYTES",
    "encrypt",
    "decrypt",
    "b64e",
    "b64d",
]


def b64e(raw: bytes) -> str:
    """Base64-encode bytes to ASCII."""
    return base64.b64encode(raw).decode("ascii")


def b64d(text: str) -> bytes:
    """Base64-decode ASCII to bytes. Raises binascii.Error on bad input."""
    return base64.b64decode(text.encode("ascii"), validate=True)


def encrypt(device_id: str, key: bytes, plaintext: dict) -> tuple[str, str, str]:
    """Encrypt a plaintext dict.

    Returns (nonce_b64, ciphertext_b64, tag_b64). Raises ValueError if the
    key is not 32 bytes.
    """
    if len(key) != KEY_BYTES:
        raise ValueError(f"AES-256 key must be {KEY_BYTES} bytes")
    nonce = os.urandom(NONCE_BYTES)
    raw = json.dumps(plaintext, separators=(",", ":")).encode("utf-8")
    ct_and_tag = AESGCM(key).encrypt(nonce, raw, device_id.encode("utf-8"))
    ciphertext, tag = ct_and_tag[:-TAG_BYTES], ct_and_tag[-TAG_BYTES:]
    return b64e(nonce), b64e(ciphertext), b64e(tag)


def decrypt(device_id: str, key: bytes, nonce: bytes, ciphertext: bytes,
            tag: bytes) -> dict:
    """Decrypt and verify. Returns the parsed plaintext dict.

    Raises InvalidTag on authentication failure, ValueError on a bad key
    length or non-JSON plaintext.
    """
    if len(key) != KEY_BYTES:
        raise ValueError(f"AES-256 key must be {KEY_BYTES} bytes")
    raw = AESGCM(key).decrypt(nonce, ciphertext + tag,
                              device_id.encode("utf-8"))
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("plaintext is not a JSON object")
    return data
