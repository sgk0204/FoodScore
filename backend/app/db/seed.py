"""Seed / refresh the additives_ref table from data/additives_ref.csv.

python -m app.db.seed
"""

from __future__ import annotations

import asyncio

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import AdditiveRefRow
from app.db.session import make_engine, make_sessionmaker
from app.services.scoring import DEFAULT_ADDITIVES_PATH, load_additive_table


async def main() -> None:
    table = load_additive_table(DEFAULT_ADDITIVES_PATH)
    engine = make_engine(get_settings().database_url)
    async with make_sessionmaker(engine)() as session:
        await session.execute(delete(AdditiveRefRow))
        for ref in table.by_code.values():
            session.add(
                AdditiveRefRow(
                    code=ref.code,
                    name=ref.name,
                    aliases=list(ref.aliases),
                    risk_tier=ref.risk_tier,
                    source_url=ref.source_url,
                    notes=ref.notes,
                )
            )
        await session.commit()
    await engine.dispose()
    print(f"Seeded {len(table)} additives")


if __name__ == "__main__":
    asyncio.run(main())
