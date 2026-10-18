import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IngredientList } from "@/components/IngredientList";
import { NutritionTable } from "@/components/NutritionTable";
import { PenaltyList } from "@/components/PenaltyList";
import { ScoreDial } from "@/components/ScoreDial";

import { doneScan } from "./fixtures";

describe("ScoreDial", () => {
  it("announces score and band as text", () => {
    render(<ScoreDial score={39} band="BAD" />);
    expect(screen.getByLabelText("Score 39 out of 100, Bad")).toBeInTheDocument();
    expect(screen.getByText("Bad")).toBeInTheDocument();
  });
  it("marks partial scores", () => {
    render(<ScoreDial score={60} band="GOOD" partial />);
    expect(screen.getByText("Good · Partial")).toBeInTheDocument();
  });
});

describe("PenaltyList", () => {
  it("lists penalties in the given (descending) order with points", () => {
    render(<PenaltyList items={doneScan.penalties} kind="penalty" />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(within(items[0]!).getByText("High sugar")).toBeInTheDocument();
    expect(within(items[0]!).getByText("18.0")).toBeInTheDocument();
  });
  it("renders extracted text safely (no HTML injection)", () => {
    render(
      <PenaltyList
        kind="penalty"
        items={[{ factor: "x", label: "<img src=x onerror=alert(1)>", points: 1, reason: "r" }]}
      />,
    );
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("NutritionTable", () => {
  it("shows per-100 g values with traffic lights and unsure markers", () => {
    render(
      <NutritionTable
        nutrition={doneScan.nutrition!}
        isBeverage={false}
        fieldConfidence={doneScan.field_confidence}
      />,
    );
    expect(screen.getByText("Per 100 g")).toBeInTheDocument();
    const sugarRow = screen.getByText("Total sugars").closest("tr")!;
    expect(within(sugarRow).getByText("high")).toBeInTheDocument();
    const saltRow = screen.getByText("Salt").closest("tr")!;
    expect(within(saltRow).getByText("(unsure)")).toBeInTheDocument();
  });
});

describe("IngredientList", () => {
  it("highlights flagged ingredients for screen readers too", () => {
    render(
      <IngredientList ingredients={doneScan.ingredients} flagged={doneScan.flagged_ingredients} />,
    );
    expect(screen.getAllByText("(flagged)", { exact: false })).toHaveLength(2);
  });
});
