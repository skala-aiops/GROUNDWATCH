import { useEffect, useState } from "react";
export type Row = Record<string, any>;
export const number = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);
export const fmt = (v: unknown, digits = 3) =>
  number(v) ? v.toFixed(digits) : "—";
export const labels: Record<string, string> = {
  normal: "예측 준비",
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
  observed_api: "외부 API 관측",
  unit_verification_required: "수위 기준 대조 필요",
  blocked: "준비 조건 미충족",
  quality_rejected: "품질 기준 미달",
};
export const label = (s: unknown) =>
  labels[String(s || "").toLowerCase()] || String(s || "—");
export async function request(path: string, init: RequestInit = {}) {
  const r = await fetch(
    path.startsWith("/health") ? path : "/api/v1" + path,
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
