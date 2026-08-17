import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


_password_hasher = PasswordHasher()
_CARD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_admin_token(admin_id: str, secret: str, minutes: int) -> str:
    now = utcnow()
    return jwt.encode(
        {"sub": admin_id, "type": "admin", "iat": now, "exp": now + timedelta(minutes=minutes)},
        secret,
        algorithm="HS256",
    )


def decode_admin_token(token: str, secret: str) -> str:
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    if payload.get("type") != "admin" or not payload.get("sub"):
        raise jwt.InvalidTokenError("invalid token type")
    return str(payload["sub"])


def normalize_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def hash_card_code(code: str, pepper: str) -> str:
    return hmac.new(
        pepper.encode("utf-8"), normalize_code(code).encode("ascii"), hashlib.sha256
    ).hexdigest()


def code_hint(code: str) -> str:
    normalized = normalize_code(code)
    return f"{normalized[:7]}...{normalized[-5:]}"


def generate_card_code(plan_type: str) -> str:
    prefixes = {
        "monthly": "M30",
        "quarterly": "Q90",
        "yearly": "Y365",
        "permanent": "PERM",
        "custom": "CUST",
        "rebind": "RBD",
    }
    blocks = ["".join(secrets.choice(_CARD_ALPHABET) for _ in range(5)) for _ in range(5)]
    return "-".join(["YCF", prefixes[plan_type], *blocks])


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ReceiptSigner:
    def __init__(self, key_path: Path, key_id: str):
        self.key_path = key_path
        self.key_id = key_id
        self.private_key = self._load_or_create_key(key_path)

    @staticmethod
    def _load_or_create_key(path: Path) -> Ed25519PrivateKey:
        if path.exists():
            return serialization.load_pem_private_key(path.read_bytes(), password=None)
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path.write_bytes(pem)
        return key

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    def sign(self, payload: dict) -> str:
        body = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = self.private_key.sign(body)
        return f"{self._b64(body)}.{self._b64(signature)}"

    def public_key_pem(self) -> str:
        return self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
