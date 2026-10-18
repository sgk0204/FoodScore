"""Replays recorded provider responses — used in tests, local demos and CI (guide §12).

"Testing the LLM without paying for it": real responses are recorded once as fixtures in
``tests/fixtures/llm_responses`` and replayed here. Only the nightly eval calls a real API.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.schemas.extraction import Extraction
from app.services.extraction.base import ExtractionResult

DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "llm_responses"


class FakeExtractor:
    name = "fake"

    def __init__(self, fixture: str = "chocolate_biscuit", fixture_dir: Path = DEFAULT_FIXTURE_DIR):
        self.fixture = fixture
        self.fixture_dir = fixture_dir
        self.calls = 0

    def _pick(self, images: list[bytes]) -> Path:
        if self.fixture != "auto":
            return self.fixture_dir / f"{self.fixture}.json"
        # "auto": deterministic choice per photo set, so a demo shows different products.
        options = sorted(self.fixture_dir.glob("*.json"))
        digest = int(hashlib.sha256(b"".join(images[:1])).hexdigest(), 16)
        return options[digest % len(options)]

    async def extract(self, images: list[bytes], prompt_version: str) -> ExtractionResult:
        self.calls += 1
        path = self._pick(images)
        extraction = Extraction.model_validate(json.loads(path.read_text(encoding="utf-8")))
        return ExtractionResult(
            extraction=extraction,
            provider=self.name,
            model=f"fixture:{path.stem}",
            prompt_version=prompt_version,
            latency_ms=1,
        )
