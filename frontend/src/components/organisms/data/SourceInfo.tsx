import { type Row } from "../../../types/domain";
import { useResource } from "../../../hooks/useResource";

export function sourceLabel(kind: unknown) {
  return (
    (
      {
        observed: "저장 관측 자료",
        synthetic: "합성·시뮬레이션 자료",
        observed_api: "외부 API 실측",
      } as Record<string, string>
    )[String(kind)] || "출처 확인 필요"
  );
}

export function SourceInfo({ row }: { row: Row }) {
  const s = row.data_source || {};
  if (s.kind === "observed_api") return <details>
    <summary>{row.district_name || "선택 관측소"} · API 관측 출처</summary>
    <p>서울시 VTsSec · 최근 관측일 {s.observed_through || "수집 대기"} · 수집 시각 {s.collected_at || "수집 대기"}</p>
    <p>강수: 기상청 ASOS 서울 108 · 같은 날짜로 결합 · 빈 강수는 결측으로 유지합니다.</p>
    <p>수위는 API 원값 그대로 별도 모델로 학습·예측하며 기존 gl.-m와 혼합하지 않습니다. 강수 결측은 모델 입력에서만 학습 구간 중앙값과 결측 표시로 처리합니다. 관측일·예측 대상일·수집 시각을 구분합니다.</p>
  </details>;
  if (row.provider === "groundwatch_simulation")
    return <details><summary>{row.station_name || row.name} · 시뮬레이션 출처</summary><p>합성 수위·강수 · 기준일 {row.observed_date || "확인 필요"} · 시뮬레이션 상대 기준면(m)</p><p>실제 관측·해발 높이·관정 시공 도면이 아닙니다. 생성 시나리오의 모델·이력을 실측과 분리하며 운영 승인으로 해석하지 않습니다.</p></details>;
  if (row.provider === "kwater")
    return (
      <details>
        <summary>
          {row.station_name || row.name || "선택 관측소"} · 자료 출처와 기간
        </summary>
        <p>
          전국 지하수 실측 · 확보 날짜 {row.observed_date || "이력 미확보"} ·
          단위 {row.unit || "미확인"}
        </p>
        <p>
          기준면 {row.level_reference || row.reference_status || "확인 필요"} ·
          강수 연결 {row.mapping_status || "미승인"} ·{" "}
          {row.prediction_scope === "experimental" ||
          row.operational_approved === false
            ? "실험 검증 / 운영 미승인"
            : "모델 준비 확인 필요"}
        </p>
        <p>
          위치 목록과 실측 이력·학습·예측 발행은 별도 상태입니다. 관측소의
          수위를 지역 전체 수위로 해석하지 않습니다.
        </p>
      </details>
    );
  return (
    <details>
      <summary>{row.district_name || "선택 관측소"} · 자료 출처와 기간</summary>
      <p>
        {sourceLabel(s.kind || row.source_kind)} · 실제 관측 종료{" "}
        {s.observed_through || "확인 필요"} · 예측 입력 종료{" "}
        {s.observation_display_only ? "모델 미연결" : s.input_through || "확인 필요"}
      </p>
      <p>
        합성 입력{" "}
        {s.synthetic_from && s.synthetic_through
          ? `${s.synthetic_from} ~ ${s.synthetic_through}`
          : "해당 기간 없음 또는 확인 필요"}{" "}
        · 자료 생성 시각 {s.generated_at || "확인 필요"}
      </p>
      <p>
        {s.observation_display_only
          ? `${s.observation_source}의 추가 실측을 조회합니다. 수집 시각 ${s.observation_collected_at || "확인 필요"}. 기존 모델의 추가 실측 평가·승격은 완료되지 않았습니다.`
          : "외부 API 실측은 기본 예측 화면에 적용하지 않습니다. 입력 종료일은 실시간 수집을 뜻하지 않습니다."}
      </p>
    </details>
  );
}

export function CollectionStatus({ revision }: { revision: number }) {
  const { data, error, loading } = useResource(
    "/external-sources",
    30000,
    revision,
  );
  const collection = data?.collection || {};
  const counts = data?.forecast_integration?.counts || {};
  const names: Record<string, string> = {
    mapping_required: "매핑 검증 필요",
    input_required: "입력 부족",
    model_required: "모델 준비 필요",
    publish_ready: "발행 가능",
    published: "발행 완료",
  };
  return (
    <details>
      <summary>외부 수집과 예측 발행 상태</summary>
      {error ? (
        <p role="alert">상태 조회 실패: {error}</p>
      ) : loading ? (
        <p>수집 상태 확인 중</p>
      ) : (
        <>
          <p>
            수집 {collection.enabled ? "활성" : "비활성"} ·{" "}
            {collection.timezone} {collection.schedule_hour}시 이후 하루 1회 ·
            최근 {collection.lookback_days}일 ~ 어제 확인
          </p>
          <p>
            {Object.entries(names)
              .map(([key, name]) => `${name} ${counts[key] ?? "—"}곳`)
              .join(" · ")}
          </p>
          <p>
            최근 점검{" "}
            {collection.worker?.checked_at ||
              collection.worker?.updated_at ||
              "기록 없음"}
          </p>
          {Object.entries(collection.timing || {}).map(([source, timing]) => (
            <p key={source}>
              {source} · 최근 성공{" "}
              {(timing as Row).last_success_at || "기록 없음"} · 최근 실패{" "}
              {(timing as Row).last_failure_at || "기록 없음"}
            </p>
          ))}
          <p>
            최근 수집 실패와 기존 정상 자료의 예측 준비 상태는 별개입니다. 수집
            성공만으로 기본 화면에 반영되지 않습니다.
          </p>
        </>
      )}
    </details>
  );
}
