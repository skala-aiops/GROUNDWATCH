import { describe, expect, it } from "vitest";
import { levelDiagramData } from "./WaterLevelDiagram";
describe("diagram datum and values", () => {
  it("keeps elevation above zero without inventing a ground surface", () => {
    const d = levelDiagramData({
      level_reference: "elevation",
      unit: "m",
      latest_actual_level: 108.15,
      prediction: 108.15,
    });
    expect(d.known).toBe(true);
    expect(d.groundRelative).toBe(false);
    expect(d.low).toBeGreaterThan(100);
    expect(d.high).toBeGreaterThan(d.low);
  });
  it("retains valid zero and includes the ground datum only for GL", () => {
    const d = levelDiagramData({
      unit: "gl.-m",
      latest_actual_level: 0,
      prediction: -2,
    });
    expect(d.actual).toBe(0);
    expect(d.groundRelative).toBe(true);
    expect(d.high).toBeGreaterThan(0);
  });
  it("does not invent missing observations or a reference", () => {
    const d = levelDiagramData({
      unit: "m",
      latest_actual_level: null,
      prediction: null,
    });
    expect(d.known).toBe(false);
    expect(d.actual).toBeNull();
    expect(d.prediction).toBeNull();
  });
  it("requires the original elevation unit before drawing a metric axis", () => {
    expect(
      levelDiagramData({
        level_reference: "elevation",
        latest_actual_level: 10,
      }).known,
    ).toBe(false);
    expect(
      levelDiagramData({
        level_reference: "elevation",
        unit: "ft",
        latest_actual_level: 10,
      }).known,
    ).toBe(false);
  });
});
