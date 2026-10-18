/**
 * Critical journeys (guide §12): upload → result happy path, and the unreadable-photo path.
 * The API is mocked at the network layer so the suite is fast, free and deterministic; the
 * backend has its own end-to-end API tests.
 */
import { expect, test, type Page } from "@playwright/test";

const SCAN_ID = "5f1c2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f";

// 1×1 white JPEG — enough for the client pipeline to compress and preview.
const JPEG = Buffer.from(
  "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==",
  "base64",
);

const base = {
  id: SCAN_ID,
  score: null,
  band: null,
  verdict: null,
  confidence: null,
  is_partial: false,
  is_beverage: false,
  user_corrected: false,
  from_cache: false,
  nova: null,
  product: { name: null, brand: null, barcode: null, category: null },
  penalties: [],
  positives: [],
  caps_applied: [],
  nutrition: null,
  ingredients: [],
  flagged_ingredients: [],
  unrated_additives: [],
  review_issues: [],
  field_confidence: {},
  error: null,
  created_at: "2026-10-18T10:00:00Z",
  completed_at: null,
  disclaimer: "For general information only. Not medical or dietary advice.",
};

const done = {
  ...base,
  status: "DONE",
  score: 39,
  band: "BAD",
  verdict: "Eat rarely — mainly high sugar and high saturated fat",
  confidence: 0.95,
  nova: 4,
  product: { name: "Choco Cream Biscuit", brand: "Acme Foods", barcode: null, category: "snack" },
  penalties: [
    {
      factor: "sugar",
      label: "High sugar",
      points: 18,
      reason: "Sugar 30 g/100 g is high (> 22.5 g)",
    },
  ],
  positives: [
    {
      factor: "protein",
      label: "Good source of protein",
      points: 2.4,
      reason: "Protein 6 g/100 g (≥ 5 g)",
    },
  ],
  nutrition: { basis: "per_100g", source: "llm", energy_kcal: 480, sugars_g: 30, salt_g: 0.6 },
  ingredients: ["Wheat flour", "Sugar", "Palm oil"],
  flagged_ingredients: ["Palm oil"],
  completed_at: "2026-10-18T10:00:09Z",
};

async function mockApi(page: Page, final: object) {
  await page.route("**/api/v1/auth/refresh", (r) =>
    r.fulfill({
      status: 401,
      json: { type: "x/unauthorized", title: "Unauthorized", status: 401 },
    }),
  );
  await page.route("**/api/v1/scans", (r) =>
    r.fulfill({ status: 202, json: { ...base, status: "QUEUED" } }),
  );
  let polls = 0;
  await page.route(`**/api/v1/scans/${SCAN_ID}`, (r) => {
    polls += 1;
    return r.fulfill({ json: polls < 2 ? { ...base, status: "PROCESSING" } : final });
  });
}

async function attachPhotos(page: Page) {
  const roles = ["front", "nutrition", "ingredients"];
  for (const [i, role] of roles.entries()) {
    await page
      .getByTestId(`input-${role}`)
      .setInputFiles({ name: `${role}.jpg`, mimeType: "image/jpeg", buffer: JPEG });
    // Wait for *this* photo to finish client-side preparation before the next one.
    await expect(page.getByAltText(/preview$/)).toHaveCount(i + 1);
  }
}

test("happy path: three photos → score with reasons", async ({ page }) => {
  await mockApi(page, done);
  await page.goto("/scan");
  await attachPhotos(page);
  await page.getByRole("button", { name: "Get my score" }).click();

  await expect(page).toHaveURL(new RegExp(`/result/${SCAN_ID}`), { timeout: 30_000 });
  await expect(page.getByLabel("Score 39 out of 100, Bad")).toBeVisible();
  await expect(page.getByText("Sugar 30 g/100 g is high (> 22.5 g)")).toBeVisible();
  await expect(
    page.getByText("Not medical or dietary advice", { exact: false }).first(),
  ).toBeVisible();
});

test("unreadable nutrition photo asks for that specific retake", async ({ page }) => {
  await mockApi(page, {
    ...base,
    status: "FAILED",
    error: {
      type: "https://foodscore.app/errors/unreadable-label",
      title: "Couldn't read the nutrition table",
      status: 422,
      detail: "The nutrition photo is unreadable: strong glare. Please retake it.",
      retake: ["nutrition"],
    },
  });
  await page.goto("/scan");
  await attachPhotos(page);
  await page.getByRole("button", { name: "Get my score" }).click();

  await expect(page.getByText("Couldn't read the nutrition table")).toBeVisible();
  await expect(page.getByText("nutrition table", { exact: false }).last()).toBeVisible();
  await expect(page.getByRole("link", { name: "Scan again" })).toBeVisible();
});

test("history requires sign-in", async ({ page }) => {
  await page.route("**/api/v1/auth/refresh", (r) =>
    r.fulfill({ status: 401, json: { type: "x", title: "x", status: 401 } }),
  );
  await page.goto("/history");
  await expect(page.getByText("Sign in to see your history")).toBeVisible();
});
