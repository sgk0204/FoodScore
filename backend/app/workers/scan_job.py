from __future__ import annotations

import uuid
from typing import Any

from app.services.pipeline import process_scan


async def process_scan_job(ctx: dict[str, Any], scan_id: str) -> None:
    await process_scan(ctx["services"], uuid.UUID(scan_id))
