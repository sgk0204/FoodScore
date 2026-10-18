/**
 * Client-side blur / darkness check (edge case 1) — variance of the Laplacian.
 *
 * A sharp photo of printed text has strong edges → high variance. Thresholds were picked on
 * downscaled 512 px greyscale images; they are deliberately lenient (we warn, the server and
 * the model have the final say).
 */

export const BLUR_THRESHOLD = 60;
export const DARK_THRESHOLD = 40;

export function toGray(rgba: Uint8ClampedArray): Float32Array {
  const gray = new Float32Array(rgba.length / 4);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j++) {
    gray[j] = 0.299 * rgba[i]! + 0.587 * rgba[i + 1]! + 0.114 * rgba[i + 2]!;
  }
  return gray;
}

export function laplacianVariance(gray: Float32Array, width: number, height: number): number {
  let sum = 0;
  let sumSq = 0;
  let n = 0;
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const lap = gray[i - width]! + gray[i + width]! + gray[i - 1]! + gray[i + 1]! - 4 * gray[i]!;
      sum += lap;
      sumSq += lap * lap;
      n++;
    }
  }
  if (n === 0) return 0;
  const mean = sum / n;
  return sumSq / n - mean * mean;
}

export function meanBrightness(gray: Float32Array): number {
  let total = 0;
  for (const v of gray) total += v;
  return gray.length ? total / gray.length : 0;
}

export type QualityVerdict = { ok: boolean; reason?: "blurry" | "dark"; sharpness: number };

export function judgeQuality(gray: Float32Array, width: number, height: number): QualityVerdict {
  const sharpness = laplacianVariance(gray, width, height);
  if (meanBrightness(gray) < DARK_THRESHOLD) return { ok: false, reason: "dark", sharpness };
  if (sharpness < BLUR_THRESHOLD) return { ok: false, reason: "blurry", sharpness };
  return { ok: true, sharpness };
}
