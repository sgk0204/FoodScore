"""Authentication (guide §4.5).

- Access token: JWT, 15 min, returned in the body; the frontend keeps it in memory only.
- Refresh token: opaque, 7 days, httpOnly + Secure + SameSite=Strict cookie scoped to
  /api/v1/auth; stored hashed; rotated on every use. Presenting an already-used token revokes
  the whole token family (theft detection).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Request, Response, status
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import ServicesDep, SessionDep, UserDep, client_ip, enforce_rate_limit
from app.core.errors import AppError, unauthorized
from app.core.logging import hash_id
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    password_problems,
    verify_password,
)
from app.db.models import RefreshToken, User
from app.schemas.api import LoginIn, RegisterIn, TokenOut, UserOut
from app.services.context import Services

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger(__name__)

REFRESH_COOKIE = "fs_refresh"
COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, token: str, svc: Services) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=svc.settings.refresh_token_ttl_s,
        httponly=True,
        secure=svc.settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


async def _issue_tokens(
    svc: Services,
    session: SessionDep,
    user: User,
    response: Response,
    family_id: uuid.UUID | None = None,
) -> TokenOut:
    raw = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(seconds=svc.settings.refresh_token_ttl_s),
        )
    )
    await session.commit()
    _set_refresh_cookie(response, raw, svc)
    return TokenOut(
        access_token=create_access_token(user.id, svc.settings, is_admin=user.is_admin),
        expires_in=svc.settings.access_token_ttl_s,
    )


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn, request: Request, response: Response, svc: ServicesDep, session: SessionDep
) -> TokenOut:
    await enforce_rate_limit(
        svc, f"auth:{hash_id(client_ip(request))}", svc.settings.rate_limit_auth_per_min
    )
    problems = password_problems(body.password)
    if problems:
        raise AppError(
            422,
            "weak-password",
            "Password is too weak",
            "Password needs " + ", ".join(problems) + ".",
        )
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(409, "email-taken", "An account with this email already exists") from exc
    log.info("user_registered", user=hash_id(user.id))
    return await _issue_tokens(svc, session, user, response)


async def _lockout_key_hit(svc: Services, email: str, *, failed: bool) -> int:
    key = f"login_fail:{hash_id(email)}"
    try:
        if not failed:
            await svc.redis.delete(key)
            return 0
        count = int(await svc.redis.incr(key))
        if count == 1:
            await svc.redis.expire(key, svc.settings.login_lockout_s)
        return count
    except RedisError:
        return 0


async def _is_locked(svc: Services, email: str) -> bool:
    try:
        raw = await svc.redis.get(f"login_fail:{hash_id(email)}")
    except RedisError:
        return False
    return int(raw or 0) >= svc.settings.login_max_failures


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn, request: Request, response: Response, svc: ServicesDep, session: SessionDep
) -> TokenOut:
    await enforce_rate_limit(
        svc, f"auth:{hash_id(client_ip(request))}", svc.settings.rate_limit_auth_per_min
    )
    email = body.email.lower()
    if await _is_locked(svc, email):
        raise AppError(
            429,
            "account-locked",
            "Too many failed attempts",
            "This account is temporarily locked. Try again in 15 minutes.",
            headers={"Retry-After": str(svc.settings.login_lockout_s)},
        )
    user = await session.scalar(select(User).where(User.email == email))
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        await _lockout_key_hit(svc, email, failed=True)
        raise AppError(401, "invalid-credentials", "Email or password is incorrect")
    await _lockout_key_hit(svc, email, failed=False)
    return await _issue_tokens(svc, session, user, response)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    request: Request, response: Response, svc: ServicesDep, session: SessionDep
) -> TokenOut:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise unauthorized("No refresh token")
    token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
    )
    now = datetime.now(UTC)
    if token is None:
        raise unauthorized("Refresh token is invalid")
    if token.used_at is not None or token.revoked_at is not None:
        # Reuse of a rotated token: assume theft and revoke the entire family.
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()
        log.warning("refresh_token_reuse", user=hash_id(token.user_id))
        response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
        raise unauthorized("Session revoked — please sign in again")
    if token.expires_at <= now:
        raise unauthorized("Refresh token expired")
    user = await session.get(User, token.user_id)
    if user is None:
        raise unauthorized("Account no longer exists")
    token.used_at = now
    return await _issue_tokens(svc, session, user, response, family_id=token.family_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: SessionDep) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        token = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
        )
        if token is not None:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return response


@router.get("/me", response_model=UserOut)
async def me(owner: UserDep, session: SessionDep) -> User:
    user = await session.get(User, owner.user_id)
    if user is None:
        raise unauthorized("Account no longer exists")
    return user
