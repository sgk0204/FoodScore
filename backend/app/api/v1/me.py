from __future__ import annotations

import structlog
from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.api.deps import ServicesDep, SessionDep, UserDep
from app.api.v1.auth import COOKIE_PATH, REFRESH_COOKIE
from app.core.logging import hash_id
from app.db.models import Scan, User

router = APIRouter(tags=["account"])
log = structlog.get_logger(__name__)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    owner: UserDep, svc: ServicesDep, session: SessionDep, response: Response
) -> Response:
    """Delete the account and all personal data (India DPDP Act 2023).

    Scans, nutrition rows, penalties, feedback and refresh tokens go via ON DELETE CASCADE.
    Shared product rows stay (they hold no personal data).
    """
    keys = [
        k
        for scan_keys in (
            await session.scalars(select(Scan.image_keys).where(Scan.user_id == owner.user_id))
        ).all()
        for k in scan_keys
    ]
    if keys:
        await svc.store.delete(keys)
    user = await session.get(User, owner.user_id)
    if user is not None:
        await session.delete(user)
        await session.commit()
    log.info("account_deleted", user=hash_id(owner.user_id))
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return response
