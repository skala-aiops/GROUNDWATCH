import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import WaterLevelDiagram from "./WaterLevelDiagram";
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

it("keeps synthetic relative datum separate from physical ground or sea level", () => {
 const d = levelDiagramData({source_kind:"synthetic",level_reference:"simulation_relative_datum",unit:"m",latest_actual_level:0,prediction:1});
 expect(d.known).toBe(true); expect(d.simulated).toBe(true); expect(d.groundRelative).toBe(false);
});

it("labels synthetic dates and levels without observed claims in the 2D fallback", () => {
 const html=renderToStaticMarkup(createElement(WaterLevelDiagram,{row:{source_kind:"synthetic",level_reference:"simulation_relative_datum",unit:"m",latest_actual_level:0,prediction:1,observed_date:"2026-10-07"}}));
 expect(html).toContain("시뮬레이션 수위"); expect(html).not.toContain("실측");
});
