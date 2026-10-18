import { describe, expect, it } from "vitest";

import { Scan } from "@/lib/api/schemas";
import { bandFor, bandInfo } from "@/lib/bands";
import { judgeQuality, laplacianVariance } from "@/lib/image/blur";
import { ImagePrepError, isHeic, validateFile } from "@/lib/image/prepare";
import { formatValue, trafficLight } from "@/lib/nutrition";

import { doneScan } from "./fixtures";

describe("bands mirror the backend", () => {
  it.each([
    [0, "VERY_BAD"],
    [20, "VERY_BAD"],
    [21, "BAD"],
    [40, "BAD"],
    [41, "GOOD"],
    [60, "GOOD"],
    [61, "VERY_GOOD"],
    [80, "VERY_GOOD"],
    [81, "EXCELLENT"],
    [100, "EXCELLENT"],
  ] as const)("%i → %s", (score, band) => {
    expect(bandFor(score)).toBe(band);
  });

  it("has a text label for every band (colour is never the only signal)", () => {
    expect(bandInfo("VERY_GOOD").label).toBe("Very Good");
  });
});

describe("traffic lights use FSA thresholds", () => {
  it("food", () => {
    expect(trafficLight("sugars_g", 5, false)).toBe("low"); // inclusive low
    expect(trafficLight("sugars_g", 22.5, false)).toBe("medium"); // exclusive high
    expect(trafficLight("sugars_g", 22.6, false)).toBe("high");
  });
  it("drinks", () => {
    expect(trafficLight("sugars_g", 10.6, true)).toBe("medium");
    expect(trafficLight("sugars_g", 12, true)).toBe("high");
  });
  it("no light for nutrients without thresholds or missing values", () => {
    expect(trafficLight("protein_g", 10, false)).toBeNull();
    expect(trafficLight("salt_g", null, false)).toBeNull();
  });
  it("formats values", () => {
    expect(formatValue(30)).toBe("30");
    expect(formatValue(0.25)).toBe("0.25");
    expect(formatValue(3.071)).toBe("3.1");
    expect(formatValue(null)).toBe("—");
  });
});

describe("blur check", () => {
  const w = 64;
  const h = 64;
  it("flat image has zero sharpness → blurry", () => {
    const flat = new Float32Array(w * h).fill(128);
    expect(laplacianVariance(flat, w, h)).toBe(0);
    expect(judgeQuality(flat, w, h)).toMatchObject({ ok: false, reason: "blurry" });
  });
  it("high-contrast stripes are sharp", () => {
    const stripes = new Float32Array(w * h).map((_, i) => ((i % w) % 2 === 0 ? 255 : 60));
    expect(judgeQuality(stripes, w, h).ok).toBe(true);
  });
  it("dark image is flagged as dark", () => {
    const dark = new Float32Array(w * h).map((_, i) => (i % 2 ? 10 : 30));
    expect(judgeQuality(dark, w, h)).toMatchObject({ ok: false, reason: "dark" });
  });
});

describe("file validation", () => {
  const file = (name: string, type: string, size = 1000) =>
    new File([new Uint8Array(size)], name, { type });

  it("accepts photos including HEIC", () => {
    expect(() => validateFile(file("a.jpg", "image/jpeg"))).not.toThrow();
    expect(() => validateFile(file("IMG_1.HEIC", ""))).not.toThrow();
    expect(isHeic(file("IMG_1.heic", ""))).toBe(true);
  });
  it("rejects non-images and huge files", () => {
    expect(() => validateFile(file("doc.pdf", "application/pdf"))).toThrow(ImagePrepError);
    expect(() => validateFile(file("big.jpg", "image/jpeg", 26 * 1024 * 1024))).toThrow(
      ImagePrepError,
    );
  });
});

describe("response schemas", () => {
  it("accept a real scan response", () => {
    expect(Scan.parse(doneScan).score).toBe(39);
  });
  it("reject an out-of-range score (runtime drift guard)", () => {
    expect(() => Scan.parse({ ...doneScan, score: 140 })).toThrow();
  });
});
