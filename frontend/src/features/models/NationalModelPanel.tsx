import Panel from "@/components/molecules/Panel";
import { Button } from "@/components/atoms/button";
import { stationDataStatus } from "../../utils/stations";
import React, { useEffect, useState } from "react";
import { fmt, label, number } from "../../utils/format";
import { post, request } from "../../api/client";
import { useResource } from "../../hooks/useResource";
import { type Row } from "../../types/domain";
import Badge from "../../components/molecules/Badge";
import Json from "../../components/molecules/Json";
import { CollectionStatus } from "../../components/organisms/data/SourceInfo";
import { CandidateEvaluation } from "../../components/organisms/charts/EvaluationCharts";
export default function NationalModelPanel({
  row,
  pipeline,
  refresh,
}: {
  row: Row;
  pipeline: Row;
  refresh: () => void;
}) {
  const [job, setJob] = useState("");
  const [error, setError] = useState("");
  const status = useResource(job ? "/api/v2/jobs/" + job : null, 3000);
  useEffect(() => {
    if (status.data?.status === "completed") refresh();
  }, [status.data?.status]);
  const running = ["queued", "running"].includes(status.data?.status || "");
  const policy = pipeline.monitoring_policy;
  const monitor = pipeline.monitor || {};
  const collection = pipeline.observation_collection;
  const collectionStation =
    collection?.stations?.[row.operation_station_id] || {};
  const monitoringLabels: Record<string, string> = {
    no_labelled_prediction: "정답이 연결된 발행 예측 대기",
    insufficient_consecutive_labels: "연속 정답 확보 대기",
    below_threshold: "임계값 이내",
    awaiting_second_breach: "연속 두 번째 초과 확인 대기",
    candidate_pending: "후보 평가 중",
    cooldown: "재학습 대기 기간",
    fine_tuning_eligible: "파인튜닝 조건 충족",
    already_processed: "확보 정답 평가 완료",
    insufficient_fine_tuning_rows: "파인튜닝 자료 부족",
    invalid_fine_tuning_rows: "파인튜닝 자료 확인 필요",
    stale_fine_tuning_rows: "최신 학습 자료 대기",
  };
  const collectionLabels: Record<string, string> = {
    ready: "수집 준비/확인 완료",
    disabled: "자동수집 비활성",
    waiting: "일별 수집 시각 대기",
    blocked: "자료·인증·연결 조건 확인 필요",
    degraded: "일부 관측소 수집 확인 필요",
    collecting: "수집 중",
    busy: "다른 수집 작업 실행 중",
  };

  async function submit(kind: string) {
    try {
      setError("");
      const result = await post(
        "/api/v2/stations/" +
          encodeURIComponent(row.operation_station_id) +
          "/" +
          kind +
          "-jobs",
        kind === "training"
          ? { variant: "M0" }
          : { input_end_date: row.observed_date },
      );
      setJob(result.id);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <Panel className="panel">
      <div className="panel-top">
        <div>
          <span className="eyebrow">MODEL LIFECYCLE</span>
          <h2>{row.station_name} · 모델 품질</h2>
        </div>
      </div>
      <p>
        자료 {label(stationDataStatus(row))} · 모델 {label(row.model_status)} ·{" "}
        {row.operational_approved
          ? "운영 승인"
          : row.source_kind === "synthetic"
            ? "시뮬레이션 검증 / 실측 운영 미승인"
            : row.mapping_status === "experimental"
            ? "실험 검증 / 운영 미승인"
            : "모델 준비 전 / 운영 미승인"}
      </p>
      <p className="footnote">
        실측은 자료 계약·실험 매핑을 확인한 지점에서 요청합니다. 시뮬레이션은
        합성 자료 전용 모델·이력으로 검증하며 실제 운영 승격과 분리합니다.
      </p>
      <div className="record">
        <h3>오차 감시 · 관측 수집</h3>
        {policy ? (
          <>
            <p className="footnote">
              {policy.prediction_scope === "experimental"
                ? policy.experimental_enabled || policy.enabled
                  ? "실험 자동감시 활성"
                  : "실험 자동감시 비활성"
                : "모델 오차 감시 정책"}{" "}
              · 최근 {policy.window_days}일 RMSE가 임계값을 연속{" "}
              {policy.consecutive_breaches}회 넘으면 재학습을 검토합니다. 대기
              기간 {policy.cooldown_days}일, 파인튜닝 자료{" "}
              {policy.fine_tuning_days}일, 후보 후속 정답{" "}
              {policy.candidate_shadow_days}일 기준입니다.
            </p>
            <p className="footnote">
              {policy.operational_promotion_allowed === false
                ? "실험 기준을 통과해도 운영 승격은 승인 전 차단합니다."
                : "운영 승격은 품질 게이트와 승인 상태를 따릅니다."}
            </p>
          </>
        ) : (
          <p className="footnote">감시 정책 준비 전입니다.</p>
        )}
        <p className="footnote">
          최근 오차 상태:{" "}
          {monitoringLabels[monitor.last_reason || monitor.status] ||
            "감시 결과 확인 대기"}{" "}
          · RMSE {fmt(monitor.rmse, 5)} {row.unit} · 임계값{" "}
          {fmt(monitor.threshold, 5)} · 연속 초과 {monitor.breaches ?? "—"}회 ·
          마지막 평가 {monitor.last_processed_target_date || "기록 없음"}
        </p>
        <p className="footnote">
          지하수 관측 자동수집:{" "}
          {collection
            ? (collection.enabled ? "활성" : "비활성") +
              " · " +
              (collectionLabels[
                collectionStation.status || collection.status
              ] || "상태 확인 필요")
            : "실행 기록 없음"}{" "}
          · 최근 점검 {collection?.checked_at?.replace("T", " ") || "기록 없음"}
        </p>
        <p className="footnote">
          선택 관측소 마지막 정상 수집{" "}
          {collectionStation.last_good_day || "기록 없음"}
          {collectionStation.last_good_collected_at
            ? " · " + collectionStation.last_good_collected_at.replace("T", " ")
            : ""}
          . 수집 상태와 모델 오차 감시는 별개입니다.
        </p>
      </div>
      <div className="button-row">
        <Button
          disabled={
            running ||
            !(
              row.capabilities?.train_experimental || row.capabilities?.train
            ) ||
            !row.operation_station_id
          }
          onClick={() => void submit("training")}
        >
          M0 학습 요청
        </Button>
        <Button
          disabled={
            running || !row.capabilities?.predict || !row.operation_station_id
          }
          onClick={() => void submit("prediction")}
        >
          검증 모델 예측 요청
        </Button>
        <Button disabled>운영 승격 미승인</Button>
      </div>
      {error && <p role="alert">{error}</p>}
      {status.data && (
        <p role="status">
          작업 {label(status.data.status)}
          {status.data.error ? " · " + status.data.error : ""}
        </p>
      )}
      {(pipeline.models || []).map((m: Row) => (
        <div className="record" key={m.version}>
          <strong>
            {m.variant} · {m.active ? "사용 모델" : "후보"}
          </strong>
          <p className="footnote">
            검증 RMSE {fmt(m.metrics?.holdout?.rmse, 5)} {row.unit} ·
            persistence {fmt(m.metrics?.holdout_persistence?.rmse, 5)} · 정답{" "}
            {m.metrics?.holdout?.count ?? "—"}개
          </p>
          <p className="footnote">
            모델 {m.version} · 상태 {label(m.status)}
          </p>
        </div>
      ))}
      <details>
        <summary>모델 평가 · 드리프트 · 후보 근거</summary>
        <Json
          value={{
            readiness: pipeline.readiness,
            models: pipeline.models,
            monitor: pipeline.monitor,
            limitations: pipeline.limitations,
          }}
        />
      </details>
    </Panel>
  );
}
