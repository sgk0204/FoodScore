"""Scheduled reaper (guide §4.4): runs every minute.

- PROCESSING for longer than 2 minutes → FAILED (a crashed worker never leaves a user waiting)
- QUEUED for longer than 10 minutes → FAILED (job lost: Redis flushed, or an inline-mode
  process restarted before running it)
- NEEDS_REVIEW not completed within 24 h → EXPIRED

In ``JOB_MODE=arq`` the worker runs it as a cron job; in ``JOB_MODE=inline`` the API process
runs :func:`run_forever` itself.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import or_, select

from app.core import metrics
from app.db.models import Scan, ScanStatus
from app.services.context import Services

log = structlog.get_logger(__name__)


async def reap_once(svc: Services, *, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    stuck_before = now - timedelta(seconds=svc.settings.stuck_processing_s)
    expire_before = now - timedelta(seconds=svc.settings.review_expiry_s)
    lost_before = now - timedelta(seconds=svc.settings.stuck_queued_s)
    counts = {"failed": 0, "expired": 0}
    async with svc.sessionmaker() as session:
        stuck = (
            await session.scalars(
                select(Scan).where(
                    or_(
                        (Scan.status == ScanStatus.PROCESSING) & (Scan.started_at < stuck_before),
                        (Scan.status == ScanStatus.QUEUED) & (Scan.created_at < lost_before),
                    )
                )
            )
        ).all()
        for scan in stuck:
            scan.status = ScanStatus.FAILED
            scan.completed_at = now
            scan.error = {
                "type": "https://foodscore.app/errors/timeout",
                "title": "The scan took too long",
                "status": 504,
                "detail": "Please try again.",
            }
            counts["failed"] += 1
            metrics.SCANS.labels(status="FAILED").inc()

        stale = (
            await session.scalars(
                select(Scan).where(
                    Scan.status == ScanStatus.NEEDS_REVIEW, Scan.updated_at < expire_before
                )
            )
        ).all()
        for scan in stale:
            scan.status = ScanStatus.EXPIRED
            scan.completed_at = now
            counts["expired"] += 1
            metrics.SCANS.labels(status="EXPIRED").inc()

        image_keys = [k for scan in (*stuck, *stale) for k in scan.image_keys]
        for scan in (*stuck, *stale):
            scan.image_keys = []
        await session.commit()
    if image_keys:
        await svc.store.delete(image_keys)
    if counts["failed"] or counts["expired"]:
        log.warning("reaper", **counts)
    return counts


async def reap(ctx: dict[str, Any]) -> dict[str, int]:
    return await reap_once(ctx["services"])


async def run_forever(svc: Services, interval_s: float = 60.0) -> None:
    """In-process reaper for JOB_MODE=inline. Errors are logged, never fatal."""
    while True:
        try:
            await reap_once(svc)
        except Exception:
            log.exception("reaper_failed")
        await asyncio.sleep(interval_s)
