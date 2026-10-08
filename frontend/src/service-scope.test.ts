import { describe, expect, it } from "vitest";
import { serviceStations, stationDataStatus, label } from "./api";

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

describe("national simulation isolation", () => {
  const synthetic = { station_id: "sim-gims-1", provider: "groundwatch_simulation", source_kind: "synthetic", source_contract_verified: false };
  it("shows explicit synthetic stations only in simulation scope", () => {
    expect(serviceStations([synthetic], "simulation")).toEqual([synthetic]);
    expect(serviceStations([synthetic], "observed")).toEqual([]);
    expect(serviceStations([synthetic], "seoul-history")).toEqual([]);
  });
  it("does not treat accidentally verified synthetic values as observations", () => {
    expect(serviceStations([{...synthetic, source_contract_verified:true, data_status:"observations_available", observed_date:"2026-10-07", latest_actual_level:0}], "observed")).toEqual([]);
  });
});

it("always labels synthetic row status as simulated even when provider status says observed", () => {
  const row={source_kind:"synthetic",quality_status:"normal",data_status:"observations_available"};
  expect(label(stationDataStatus(row))).toBe("시뮬레이션 자료 확보");
  expect(stationDataStatus({data_status:"observations_available"})).toBe("observations_available");
});

it("accepts Seoul live-network rows without dataset partition metadata", () => {
 const live={station_id:"seoul:SU-JNO-G1-0007",provider:"seoul",legacy_district_code:"11110",source_kind:"observed",latest_actual_level:-22.1};
 expect(serviceStations([live],"seoul-history")).toEqual([live]);
 expect(serviceStations([live],"simulation")).toEqual([]);
});
