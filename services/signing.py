"""
OneCare Loop — services/signing.py

Ed25519 signing for per-actor accountability.
Each actor_id gets an Ed25519 keypair, generated on first use.
Every ledger event is signed over its hash → non-repudiation.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_keypair() -> tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem


def sign(priv_pem: str, message: bytes) -> str:
    priv = serialization.load_pem_private_key(priv_pem.encode(), password=None)
    return base64.b64encode(priv.sign(message)).decode()


def verify(pub_pem: str, message: bytes, signature_b64: str) -> bool:
    try:
        pub = serialization.load_pem_public_key(pub_pem.encode())
        pub.verify(base64.b64decode(signature_b64), message)
        return True
    except Exception:
        return False