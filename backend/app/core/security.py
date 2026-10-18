"""Password hashing (argon2id), JWT access tokens and opaque refresh tokens (guide §4.5)."""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

_hasher = PasswordHasher()
# Pre-computed hash used when the email does not exist, so login timing does not leak it.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")

PASSWORD_MIN_LENGTH = 10


def password_problems(password: str) -> list[str]:
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"at least {PASSWORD_MIN_LENGTH} characters")
    if not re.search(r"[A-Za-z]", password):
        problems.append("at least one letter")
    if not re.search(r"\d", password):
        problems.append("at least one digit")
    if len(password) > 128:
        problems.append("at most 128 characters")
    return problems


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, settings: Settings, *, is_admin: bool = False) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_s),
        "jti": secrets.token_hex(8),
        "typ": "access",
        "adm": is_admin,
    }
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Raises jwt.PyJWTError on any problem (expired, bad signature, wrong type)."""
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "typ"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Refresh tokens and guest ids are stored hashed; the raw value lives only in the cookie."""
    return hashlib.sha256(token.encode()).hexdigest()
