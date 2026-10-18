"""Short-lived image storage between API and worker (ADR-5).

Production uses S3-compatible storage (Cloudflare R2 / AWS S3 / MinIO locally) with a 24 h
lifecycle rule as a safety net; the worker also deletes images as soon as a scan finishes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings


class ImageStore(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, keys: list[str]) -> None: ...


class LocalImageStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("invalid storage key")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, keys: list[str]) -> None:
        for key in keys:
            self._path(key).unlink(missing_ok=True)


class S3ImageStore:
    def __init__(self, settings: Settings) -> None:
        import boto3

        self.bucket = settings.s3_bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=(
                settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None
            ),
            aws_secret_access_key=(
                settings.s3_secret_access_key.get_secret_value()
                if settings.s3_secret_access_key
                else None
            ),
        )

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="image/jpeg",
        )

    async def get(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        body: bytes = await asyncio.to_thread(obj["Body"].read)
        return body

    async def delete(self, keys: list[str]) -> None:
        if keys:
            await asyncio.to_thread(
                self._client.delete_objects,
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True},
            )


def build_store(settings: Settings) -> ImageStore:
    if settings.storage_backend == "s3":
        return S3ImageStore(settings)
    return LocalImageStore(settings.storage_local_dir)
