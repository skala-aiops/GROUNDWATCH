import { describe, expect, it } from "vitest";
import { serviceStations } from "./api";

describe("data-backed service scope", () => {
  const observed = {
    station_id: "kwater:real",
    source_contract_verified: true,
    data_status: "observations_available",
    observed_date: "2026-10-07",
    latest_actual_level: 0,
  };
  it("keeps actual observations including valid zero water levels, without requiring a successful model", () => {
    expect(serviceStations([observed], "observed")).toEqual([observed]);
  });
  it("excludes coordinates-only catalogs and unverified or missing measurements", () => {
    expect(
      serviceStations(
        [
          { station_id: "catalog", latitude: 37, longitude: 127 },
          { ...observed, source_contract_verified: false },
          { ...observed, latest_actual_level: null },
          { ...observed, latest_actual_level: NaN },
        ],
        "observed",
      ),
    ).toEqual([]);
  });
  it("keeps Seoul historical and synthetic replay records accessible only in the explicit history scope", () => {
    const historic = {
      station_id: "seoul:fixture",
      provider: "seoul",
      partitions: {},
      source_kind: "synthetic",
    };
    expect(serviceStations([observed, historic], "observed")).toEqual([
      observed,
    ]);
    expect(serviceStations([observed, historic], "seoul-history")).toEqual([
      historic,
    ]);
  });
});
