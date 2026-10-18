"""FastAPI dependencies: services, DB session, and who is calling (user or guest)."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import jwt
import structlog
from fastapi import Depends, Request, Response
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found, rate_limited, unauthorized
from app.core.logging import hash_id
from app.core.security import decode_access_token, hash_token
from app.db.models import Scan
from app.services.context import Services

GUEST_COOKIE = "fs_guest"


def get_services(request: Request) -> Services:
    return request.app.state.services  # type: ignore[no-any-return]


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_session(svc: ServicesDep) -> AsyncIterator[AsyncSession]:
    async with svc.sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True, slots=True)
class Owner:
    user_id: uuid.UUID | None
    guest_id: str | None  # sha256 of the guest cookie
    ip_hash: str
    is_admin: bool = False

    @property
    def is_guest(self) -> bool:
        return self.user_id is None

    @property
    def key(self) -> str:
        return f"u:{self.user_id}" if self.user_id else f"g:{self.guest_id}"

    def scope(self, stmt: Select[Scan]) -> Select[Scan]:
        """Filter a scan query to this owner. Every scan query goes through here (IDOR)."""
        if self.user_id is not None:
            return stmt.where(Scan.user_id == self.user_id)
        return stmt.where(Scan.user_id.is_(None), Scan.guest_id == self.guest_id)

    def owns(self, scan: Scan) -> bool:
        if self.user_id is not None:
            return scan.user_id == self.user_id
        return scan.user_id is None and self.guest_id is not None and scan.guest_id == self.guest_id


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _user_from_header(request: Request, svc: Services) -> tuple[uuid.UUID, bool] | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        payload = decode_access_token(header[7:].strip(), svc.settings)
        return uuid.UUID(payload["sub"]), bool(payload.get("adm"))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise unauthorized("Access token is invalid or expired") from exc


async def get_owner(request: Request, response: Response, svc: ServicesDep) -> Owner:
    """Authenticated user if a valid Bearer token is sent, otherwise a guest.

    Guests get a random httpOnly cookie; only its hash is stored, so guests can see their own
    scans (by polling) but have no history list.
    """
    ip_hash = hash_id(client_ip(request))
    user = _user_from_header(request, svc)
    if user is not None:
        structlog.contextvars.bind_contextvars(user=hash_id(user[0]))
        return Owner(user_id=user[0], guest_id=None, ip_hash=ip_hash, is_admin=user[1])

    raw = request.cookies.get(GUEST_COOKIE)
    if not raw or len(raw) > 128:
        raw = secrets.token_urlsafe(32)
        response.set_cookie(
            GUEST_COOKIE,
            raw,
            max_age=30 * 24 * 3600,
            httponly=True,
            secure=svc.settings.cookie_secure,
            samesite="lax",
            path="/",
        )
    return Owner(user_id=None, guest_id=hash_token(raw), ip_hash=ip_hash)


OwnerDep = Annotated[Owner, Depends(get_owner)]


async def require_user(owner: OwnerDep) -> Owner:
    if owner.is_guest:
        raise unauthorized("Sign in to use this feature")
    return owner


UserDep = Annotated[Owner, Depends(require_user)]


async def get_owned_scan(scan_id: uuid.UUID, owner: Owner, session: AsyncSession) -> Scan:
    scan = await session.get(Scan, scan_id)
    if scan is None or not owner.owns(scan):
        raise not_found("Scan")
    return scan


async def enforce_rate_limit(svc: Services, key: str, limit: int) -> None:
    allowed, retry_after = await svc.limiter.hit(key, limit)
    if not allowed:
        raise rate_limited(retry_after)
