# ADR-5: Images are temporary

**Status:** Accepted · 2026-10-18

## Context
Packet photos can contain faces, hands, home interiors and GPS metadata. Keeping them adds
privacy risk (India DPDP Act 2023) and storage cost.

## Decision
- The browser resizes and re-encodes photos (EXIF dropped) before upload.
- The API re-encodes again server-side after applying EXIF orientation — only pixels survive.
- Images go to S3-compatible storage (R2/S3/MinIO) under `scans/{id}/{role}.jpg`.
- The worker **deletes them as soon as extraction finishes** (any outcome). The bucket's
  1-day lifecycle rule and the reaper are the safety nets.
- The front thumbnail on the result screen comes from the browser's memory, not the server.

## Consequences
- Minimal personal data at rest; nothing to leak from old scans.
- Trade-off: extraction cannot be re-run on old scans (e.g. after a prompt improvement); a
  user must rescan. The eval set (consented, anonymised photos) covers prompt regression testing.
