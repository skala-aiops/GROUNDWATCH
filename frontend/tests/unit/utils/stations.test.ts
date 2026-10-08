import { afterEach, describe, expect, it, vi } from "vitest";
import { predictionLabel, selectedNetworkStationId, confirmedUnit, initialStationId } from "../../../src/utils/stations";

afterEach(() => vi.unstubAllGlobals());
describe("station readiness display", () => {
  const rows = [
    {
      station_id: "seoul:test",
      legacy_district_code: "11110",
      model_ready: true,
      model_status: "active",
      prediction: 1,
      observed_date: "2024-03-18",
    },
    {
      station_id: "kwater:test",
      model_ready: true,
      model_status: "active",
      prediction: 2,
      prediction_method: "lstm",
      observed_date: "2026-10-07",
    },
  ];
  it("starts on the freshest ready model and preserves subsequent user selection", () => {
    expect(initialStationId(rows, "")).toBe("kwater:test");
    expect(initialStationId(rows, "seoul:test")).toBe("seoul:test");
    expect(initialStationId(rows, "11110")).toBe("seoul:test");
  });
  it("does not present unknown unit markers as physical units", () => {
    expect(confirmedUnit("unverified")).toBe("");
    expect(confirmedUnit("unknown")).toBe("");
    expect(confirmedUnit("el.m")).toBe("el.m");
  });
});

describe("prediction issuance timing labels", () => {
  it("compares the target with the KST issuance date rather than the input date", () => {
    expect(
      predictionLabel({
        forecast_date: "2026-10-08",
        prediction_issued_at: "2026-10-08T02:30:00Z",
      }),
    ).toBe("당일 수위 추정");
    expect(
      predictionLabel({
        forecast_date: "2026-10-08",
        prediction_issued_at: "2026-10-07T16:00:00Z",
      }),
    ).toBe("당일 수위 추정");
    expect(
      predictionLabel({
        forecast_date: "2026-10-09",
        prediction_issued_at: "2026-10-08T02:30:00Z",
      }),
    ).toBe("다음 날 수위 예측");
    expect(
      predictionLabel({
        forecast_date: "2026-10-07",
        prediction_issued_at: "2026-10-08T02:30:00Z",
      }),
    ).toBe("저장된 수위 추정");
  });
  it("does not imply issuance for persistence or missing issuance evidence", () => {
    expect(predictionLabel({ prediction_method: "persistence" })).toBe(
      "직전 관측값 기준 비교",
    );
    expect(predictionLabel({ forecast_date: "2026-10-08" })).toBe(
      "저장된 수위 추정",
    );
  });
});

it("waits for an exact listed network station before requesting station endpoints", () => {
 const rows=[{station_id:"seoul:SU-JNO",legacy_district_code:"11110"},{station_id:"sim-gims-11"}];
 expect(selectedNetworkStationId([],"11110")).toBeNull();
 expect(selectedNetworkStationId(rows,"11110")).toBeNull();
 expect(initialStationId(rows,"11110")).toBe("seoul:SU-JNO");
 expect(selectedNetworkStationId(rows,initialStationId(rows,"11110"))).toBe("seoul:SU-JNO");
 expect(selectedNetworkStationId(rows,"sim-gims-11")).toBe("sim-gims-11");
 expect(selectedNetworkStationId(rows,"unknown")).toBeNull();
});

import { nativeApiStation } from "../../../src/utils/stations";
it("keeps native API datum unverified while sharing Seoul selection", () => {
  const row = nativeApiStation({district_code: "11110", unit: "API 원값", prediction: 0,
    observed_date: "2026-08-31", source_kind: "observed_api", rainfall_mm: null});
  expect(row.station_id).toBe("seoul:11110");
  expect(row.legacy_district_code).toBe("11110");
  expect(row.level_reference).toBe("unverified_api_native");
  expect(row.model_ready).toBe(true);
  expect(row.rainfall_mm).toBeNull();
  expect(row.observed_date).toBe("2026-08-31");
});
it("does not claim native model readiness without a prediction", () => {
  expect(nativeApiStation({district_code:"11350",prediction:null}).model_ready).toBe(false);
});
