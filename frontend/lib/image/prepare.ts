/**
 * Client-side image preparation (feature F2): type/size check → HEIC conversion →
 * resize to ≤1600 px → JPEG q≈0.8 → EXIF stripped (canvas re-encode drops metadata,
 * after the browser has applied the orientation) → blur/darkness check.
 */
import { judgeQuality, toGray, type QualityVerdict } from "./blur";

export const MAX_INPUT_BYTES = 25 * 1024 * 1024; // raw phone photo
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024; // matches the server limit
export const MAX_DIMENSION = 1600;
const ACCEPTED = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"];

export class ImagePrepError extends Error {}

export type PreparedImage = { blob: Blob; previewUrl: string; quality: QualityVerdict };

export function isHeic(file: File): boolean {
  return /image\/hei[cf]/i.test(file.type) || /\.hei[cf]$/i.test(file.name);
}

export function validateFile(file: File): void {
  if (!ACCEPTED.includes(file.type.toLowerCase()) && !isHeic(file)) {
    throw new ImagePrepError("Please choose a photo (JPEG, PNG, WebP or HEIC).");
  }
  if (file.size > MAX_INPUT_BYTES) {
    throw new ImagePrepError("That photo is very large. Please use a smaller one.");
  }
}

async function measureQuality(blob: Blob): Promise<QualityVerdict> {
  const bitmap = await createImageBitmap(blob);
  const scale = Math.min(1, 512 / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(3, Math.round(bitmap.width * scale));
  const h = Math.max(3, Math.round(bitmap.height * scale));
  const canvas = new OffscreenCanvas(w, h);
  const ctx = canvas.getContext("2d");
  if (!ctx) return { ok: true, sharpness: Number.NaN };
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();
  return judgeQuality(toGray(ctx.getImageData(0, 0, w, h).data), w, h);
}

export async function prepareImage(file: File): Promise<PreparedImage> {
  validateFile(file);
  let source: Blob = file;
  if (isHeic(file)) {
    const heic2any = (await import("heic2any")).default;
    const converted = await heic2any({ blob: file, toType: "image/jpeg", quality: 0.9 });
    source = Array.isArray(converted) ? converted[0]! : converted;
  }
  const imageCompression = (await import("browser-image-compression")).default;
  const blob = await imageCompression(source as File, {
    maxWidthOrHeight: MAX_DIMENSION,
    maxSizeMB: 1.5,
    initialQuality: 0.8,
    fileType: "image/jpeg",
    preserveExif: false,
    useWebWorker: false, // the worker build loads code from a CDN, which our CSP forbids
  });
  if (blob.size > MAX_UPLOAD_BYTES) {
    throw new ImagePrepError("Could not compress this photo enough. Try another one.");
  }
  let quality: QualityVerdict = { ok: true, sharpness: Number.NaN };
  try {
    quality = await measureQuality(blob);
  } catch {
    /* OffscreenCanvas unavailable: skip the check, the server still validates */
  }
  return { blob, previewUrl: URL.createObjectURL(blob), quality };
}
