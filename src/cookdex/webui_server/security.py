from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw.encode("utf-8"))


def hash_password(password: str, iterations: int = 390_000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, raw_iterations, salt_raw, digest_raw = encoded.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    try:
        iterations = int(raw_iterations)
    except ValueError:
        return False
    salt = _b64decode(salt_raw)
    expected = _b64decode(digest_raw)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


@dataclass(frozen=True)
class SecretCipher:
    key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "_fernet", Fernet(self.key.encode("utf-8")))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted: str) -> str:
        try:
            raw = self._fernet.decrypt(encrypted.encode("utf-8"))
        except InvalidToken as exc:
            raise ValueError("Secret decryption failed; invalid key or ciphertext.") from exc
        return raw.decode("utf-8")
