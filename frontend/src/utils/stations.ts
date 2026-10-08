import type { Row } from "../types/domain";
import { number } from "./format";
// Keep a user's selection; choose the freshest prepared model only on first load.
export function initialStationId(rows: Row[], selected: string) {
  const existing = rows.find(
    (r) =>
      r.station_id === selected ||
      (!!selected && r.legacy_district_code === selected),
  );
  if (existing) return existing.station_id;
  const rank = (r: Row) =>
    number(r.prediction) &&
    (r.model_ready === true || r.model_status === "active") &&
    r.prediction_method !== "persistence"
      ? 3
      : r.capabilities?.predict
        ? 2
        : number(r.latest_actual_level) || number(r.latest_comparison?.actual)
          ? 1
          : 0;
  return (
    [...rows].sort(
      (a, b) =>
        rank(b) - rank(a) ||
        String(b.observed_date || "").localeCompare(
          String(a.observed_date || ""),
        ) ||
        String(a.station_id).localeCompare(String(b.station_id)),
    )[0]?.station_id || ""
  );
}
export function confirmedUnit(value: unknown) {
  return typeof value === "string" &&
    value.trim() &&
    !["unknown", "unverified", "none", "null"].includes(
      value.trim().toLowerCase(),
    )
    ? value
    : "";
}

export function serviceStations(rows: Row[], scope: string): Row[] {
  return rows.filter((r) =>
    scope === "simulation"
      ? r.provider === "groundwatch_simulation" && r.source_kind === "synthetic"
      : scope === "seoul-history"
      ? r.provider === "seoul"
      : r.source_kind !== "synthetic" && r.provider !== "groundwatch_simulation" &&
        r.source_contract_verified === true &&
        r.data_status === "observations_available" &&
        !!r.observed_date &&
        number(r.latest_actual_level),
  );
}

// Label against actual issuance time, independently of the model input date.
export function predictionLabel(row: Row): string {
  if (row.prediction_method === "persistence") return "직전 관측값 기준 비교";
  const target = row.forecast_date || row.target_date;
  const issued = row.prediction_issued_at || row.issued_at;
  if (target && issued) {
    const timestamp = Date.parse(issued);
    if (Number.isFinite(timestamp)) {
      const issuedDay = new Date(timestamp + 9 * 60 * 60 * 1000)
        .toISOString()
        .slice(0, 10);
      if (target === issuedDay) return "당일 수위 추정";
      if (target < issuedDay) return "저장된 수위 추정";
      return "다음 날 수위 예측";
    }
  }
  if (row.forecast_timing === "same_day_estimate") return "당일 수위 추정";
  if (row.legacy_district_code) return "다음 날 수위 예측";
  return "저장된 수위 추정";
}

export function measurementLabel(row: Row): string {
  return row.source_kind === "synthetic" || row.provider === "groundwatch_simulation" ? "시뮬레이션 수위" : "최근 실측 수위";
}

export function stationDataStatus(row: Row): string {
  if (row.source_kind === "synthetic" || row.provider === "groundwatch_simulation") return "synthetic_available";
  return row.quality_status || row.data_status || "data_required";
}

export function selectedNetworkStationId(rows: Row[], selected: string): string | null {
 return rows.some(row => row.station_id === selected) ? selected : null;
}

// Bridge native API observations into the existing Seoul selection contract.
export function nativeApiStation(row: Row): Row {
  return {...row, station_id: "seoul:" + row.district_code, provider: "seoul",
    legacy_district_code: row.district_code, region_code: "서울특별시", region_name: "서울특별시",
    level_reference: "unverified_api_native", model_ready: number(row.prediction),
    prediction_method: number(row.prediction) ? "lstm" : null};
}
