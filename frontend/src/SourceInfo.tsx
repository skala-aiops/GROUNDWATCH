import { type Row, useResource } from "./api";

export function sourceLabel(kind: unknown) {
  return ({ observed: "저장 관측 자료", synthetic: "합성 자료 포함", observed_api: "외부 API 실측" } as Record<string, string>)[String(kind)] || "출처 확인 필요";
}

export function SourceInfo({ row }: { row: Row }) {
  const s = row.data_source || {};
  if (s.kind === "observed_api") return <details>
    <summary>{row.district_name || "선택 관측소"} · API 관측 출처</summary>
    <p>서울시 VTsSec · 최근 관측일 {s.observed_through || "수집 대기"} · 수집 시각 {s.collected_at || "수집 대기"}</p>
    <p>강수: 기상청 ASOS 서울 108 · 같은 날짜로 결합 · 빈 강수는 결측으로 유지합니다.</p>
    <p>수위는 API 원값 그대로 별도 모델로 학습·예측하며 기존 gl.-m와 혼합하지 않습니다. 강수 결측은 모델 입력에서만 학습 구간 중앙값과 결측 표시로 처리합니다. 관측일·예측 대상일·수집 시각을 구분합니다.</p>
  </details>;
  return <details>
    <summary>{row.district_name || "선택 관측소"} · 자료 출처와 기간</summary>
    <p>{sourceLabel(s.kind || row.source_kind)} · 실제 관측 종료 {s.observed_through || "확인 필요"} · 예측 입력 종료 {s.input_through || "확인 필요"}</p>
    <p>합성 입력 {s.synthetic_from && s.synthetic_through ? `${s.synthetic_from} ~ ${s.synthetic_through}` : "해당 기간 없음 또는 확인 필요"} · 자료 생성 시각 {s.generated_at || "확인 필요"}</p>
    <p>이 시연 모델은 저장 자료를 사용합니다. 실제 API 학습·예측은 ‘실제 API 관측·예측’ 모드에서 확인하세요. 입력 종료일은 실시간 수집을 뜻하지 않습니다.</p>
  </details>;
}

export function CollectionStatus({ revision }: { revision: number }) {
  const { data, error, loading } = useResource("/external-sources", 30000, revision);
  const collection = data?.collection || {};
  const counts = data?.forecast_integration?.counts || {};
  const names: Record<string, string> = { mapping_required: "매핑 검증 필요", input_required: "입력 부족", model_required: "모델 준비 필요", publish_ready: "발행 가능", published: "발행 완료" };
  return <details>
    <summary>외부 수집과 예측 발행 상태</summary>
    {error ? <p role="alert">상태 조회 실패: {error}</p> : loading ? <p>수집 상태 확인 중</p> : <>
      <p>수집 {collection.enabled ? "활성" : "비활성"} · {collection.timezone} {collection.schedule_hour}시 이후 하루 1회 · 최근 {collection.lookback_days}일 ~ 어제 확인</p>
      <p>{Object.entries(names).map(([key, name]) => `${name} ${counts[key] ?? "—"}곳`).join(" · ")}</p>
      <p>최근 점검 {collection.worker?.checked_at || collection.worker?.updated_at || "기록 없음"}</p>
      {Object.entries(collection.timing || {}).map(([source, timing]) => <p key={source}>{source} · 최근 성공 {(timing as Row).last_success_at || "기록 없음"} · 최근 실패 {(timing as Row).last_failure_at || "기록 없음"}</p>)}
      <p>최근 수집 실패와 기존 정상 자료의 예측 준비 상태는 별개입니다. 수집 성공만으로 기본 화면에 반영되지 않습니다.</p>
    </>}
  </details>;
}
