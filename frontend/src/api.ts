import { useEffect, useState } from "react";
export type Row = Record<string, any>;
export const number = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);
export const fmt = (v: unknown, digits = 3) =>
  number(v) ? v.toFixed(digits) : "—";
export const labels: Record<string, string> = {
  normal: "예측 준비",
  observations_available: "실측 자료 확보",
  experimental: "실험 연결",
  seoul_source_date_join: "서울 원천 날짜 결합",
  unapproved: "매핑 미승인",
  unverified: "확인 필요",
  verified: "확인 완료",
  experimental_gate_passed: "실험 기준 충족 · 운영 미승인",
  catalog_only: "위치 정보만 확보",
  active: "모델 사용 가능",
  experimental_ready: "실험 학습 준비",
  not_ready: "모델 미준비",
  ready: "준비 완료",
  pending: "대기",
  queued: "대기",
  running: "실행 중",
  completed: "완료",
  failed: "실패",
  interrupted: "중단",
  promoted: "교체 완료",
  rejected: "기존 유지",
  warn: "확인 필요",
  warning: "확인 필요",
  open: "미확인",
  acknowledged: "확인 중",
  resolved: "조치 완료",
  recorded: "기록",
  data_required: "자료 필요",
  model_not_ready: "모델 준비 필요",
  data_gap: "연속 자료 부족",
  stale_data: "자료 갱신 필요",
  evaluation_pending: "평가 대기",
  evaluation_passed: "평가 기준 충족",
  synthetic: "합성 자료",
  observed: "실측 자료",
};
export const label = (s: unknown) =>
  labels[String(s || "").toLowerCase()] || String(s || "—");
export async function request(path: string, init: RequestInit = {}) {
  const r = await fetch(
    path.startsWith("/health") || path.startsWith("/api/")
      ? path
      : "/api/v1" + path,
    init,
  );
  const d = await r.json().catch(() => ({}));
  if (!r.ok)
    throw Error(
      typeof d.detail === "string"
        ? d.detail
        : JSON.stringify(d.detail || `HTTP ${r.status}`),
    );
  return d;
}
export const post = (path: string, body: unknown) =>
  request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export function useResource(
  path: string | null,
  interval = 30000,
  revision = 0,
) {
  const [state, set] = useState<{
    data: Row | null;
    error: string;
    loading: boolean;
  }>({ data: null, error: "", loading: true });
  useEffect(() => {
    let alive = true;
    let controller: AbortController;
    let timer: ReturnType<typeof setTimeout>;
    set({ data: null, error: "", loading: !!path });
    const load = async () => {
      if (!path) return;
      controller = new AbortController();
      try {
        const data = await request(path, { signal: controller.signal });
        if (alive) set({ data, error: "", loading: false });
      } catch (e) {
        if (alive && !(e instanceof DOMException && e.name === "AbortError"))
          set({
            data: null,
            error: String((e as Error).message),
            loading: false,
          });
      } finally {
        if (alive && path) timer = setTimeout(load, interval);
      }
    };
    load();
    return () => {
      alive = false;
      controller?.abort();
      clearTimeout(timer);
    };
  }, [path, interval, revision]);
  return state;
}
export function comparison(actual: unknown, predicted: unknown) {
  if (!number(actual) || !number(predicted)) return "";
  const a = Number(actual.toFixed(3)),
    p = Number(predicted.toFixed(3));
  return a > p ? "above" : a < p ? "below" : "";
}

// A missing calendar date is a gap even when no null row was returned.
export function chartSegments(rows: Row[], key: string) {
  const segments: { index: number; value: number }[][] = [];
  let current: { index: number; value: number }[] = [];
  let previous = NaN;
  rows.forEach((row, index) => {
    const day = Date.parse(row.date + "T00:00:00Z");
    if (!number(row[key]) || !Number.isFinite(day)) {
      if (current.length) segments.push(current);
      current = [];
      previous = NaN;
      return;
    }
    if (current.length && day - previous !== 86400000) {
      segments.push(current);
      current = [];
    }
    current.push({ index, value: row[key] });
    previous = day;
  });
  if (current.length) segments.push(current);
  return segments;
}

export type RainStation = {
  station_id: string;
  name: string;
  latitude: number;
  longitude: number;
  rainfall_mm: number | null;
  quality_status: string;
  groundwater_station_id?: string | null;
  model_ready?: boolean;
  region_name?: string;
};
export type GroundStation = {
  station_id: string;
  name: string;
  region_code: string;
  district_name?: string;
  latitude: number;
  longitude: number;
  verified: boolean;
  level_unit: string;
  level_reference: string;
  blockers: string[];
  evidence: string[];
  source_layer_quality?: string;
};

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
    scope === "seoul-history"
      ? r.provider === "seoul" && !!r.partitions
      : r.source_contract_verified === true &&
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
