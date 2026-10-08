import { describe, it, expect } from "vitest";
import geo from "../../public/geo/seoul.json";
import fs from "node:fs";
describe("district geometry contract", () => {
  it("contains all 25 distinct API district names without equating code systems", () => {
    const names = geo.features.map((f) => f.properties.name);
    expect(names).toHaveLength(25);
    expect(new Set(names).size).toBe(25);
    const manifest = JSON.parse(
      fs.readFileSync(
        new URL("../../../data/representatives.json", import.meta.url),
        "utf8",
      ),
    );
    expect(new Set(names)).toEqual(
      new Set(manifest.stations.map((s: any) => s.district_name)),
    );
  });
});
