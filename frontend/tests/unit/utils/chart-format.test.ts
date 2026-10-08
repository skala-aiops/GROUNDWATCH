import { describe, it, expect } from "vitest";
import { comparison, chartSegments } from "../../../src/utils/chart";
import { fmt } from "../../../src/utils/format";
describe("signed groundwater comparisons", () => {
  it("keeps signed values and the three-decimal display threshold", () => {
    expect(comparison(-21.3, -21.5)).toBe("above");
    expect(comparison(-21.7, -21.5)).toBe("below");
    expect(comparison(-21.50001, -21.5)).toBe("");
  });
  it("does not invent values or comparisons for missing truth", () => {
    for (const v of [null, undefined, NaN, Infinity, "0"]) {
      expect(comparison(v, -21)).toBe("");
      expect(fmt(v)).toBe("—");
    }
    expect(fmt(0)).toBe("0.000");
    expect(comparison(null, -21)).toBe("");
  });
});
describe("calendar gap rendering", () => {
  it("breaks the line at absent dates and missing values", () => {
    const rows = [
      { date: "2026-10-01", level: -1 },
      { date: "2026-10-02", level: -2 },
      { date: "2026-10-04", level: -3 },
      { date: "2026-10-05", level: null },
      { date: "2026-10-06", level: -4 },
    ];
    expect(
      chartSegments(rows, "level").map((s) => s.map((p) => p.index)),
    ).toEqual([[0, 1], [2], [4]]);
  });
  it("does not replace an unavailable future truth with a forecast", () => {
    const rows = [
      { date: "2026-10-08", level: -2, prediction: -2.1 },
      { date: "2026-10-09", level: null, prediction: -2.2 },
    ];
    expect(chartSegments(rows, "level").flat()).toHaveLength(1);
    expect(chartSegments(rows, "prediction").flat()).toHaveLength(2);
  });
});
