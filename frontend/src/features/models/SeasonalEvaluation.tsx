import Panel from "@/components/molecules/Panel";
import React, { useEffect, useState } from "react";
import { fmt, label, number } from "../../utils/format";
import { post, request } from "../../api/client";
import { useResource } from "../../hooks/useResource";
import { type Row } from "../../types/domain";
import Badge from "../../components/molecules/Badge";
import Json from "../../components/molecules/Json";
import { CollectionStatus } from "../../components/organisms/data/SourceInfo";
import { CandidateEvaluation } from "../../components/organisms/charts/EvaluationCharts";
export default function SeasonalEvaluation({
  value,
  unit,
}: {
  value: Row | undefined | null;
  unit: string;
}) {
  if (!value) return null;
  const groups: Record<string, string> = {
    overall: "전체",
    rainy: "장마",
    non_rainy: "비장마",
    heavy_rain: "강한 강수",
  };
  const split = value.split || {};
  return (
    <Panel className="panel">
      <div className="panel-top">
        <div>
          <span className="eyebrow">SEASONAL EVALUATION / RETROSPECTIVE</span>
          <h2>같은 관측소의 장마 성능 비교</h2>
        </div>
        <Badge status={value.status} />
      </div>
      <p className="footnote">
        과거 자료를 시간순으로 분리한 평가입니다. 운영 승격 근거나 후속 30일
        실시간 평가가 아닙니다.
      </p>
      {value.status !== "completed" ? (
        <p>
          {value.status === "running"
            ? "계절 성능을 평가하는 중입니다."
            : "계절 평가가 완료되지 않았습니다. 확인되지 않은 성능은 표시하지 않습니다."}
        </p>
      ) : (
        <>
          <p className="footnote">
            학습 종료 {split.train_end || "미확인"} · 검증 종료{" "}
            {split.validation_end || "미확인"} · 공통 평가{" "}
            {split.holdout_start || "미확인"} — {split.holdout_end || "미확인"}{" "}
            ({split.holdout_targets ?? "—"}개 정답)
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>평가 구간</th>
                  <th>M0 RMSE</th>
                  <th>M1 RMSE</th>
                  <th>Persistence RMSE</th>
                  <th>M1의 M0 대비 감소율</th>
                  <th>최소 표본</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(groups).map(([key, name]) => {
                  const m0 = value.variants?.M0?.comparisons?.[key];
                  const m1 = value.variants?.M1?.comparisons?.[key];
                  const paired = value.m1_vs_m0?.[key];
                  const percent = number(paired?.rmse_reduction_ratio)
                    ? (paired.rmse_reduction_ratio * 100).toFixed(2) + "%"
                    : "—";
                  return (
                    <tr key={key}>
                      <td>{name}</td>
                      <td>
                        {fmt(m0?.model?.rmse, 5)}
                        <small>{m0?.model?.count ?? "—"}개 정답</small>
                      </td>
                      <td>
                        {fmt(m1?.model?.rmse, 5)}
                        <small>{m1?.model?.count ?? "—"}개 정답</small>
                      </td>
                      <td>
                        {fmt(m0?.persistence?.rmse, 5)}
                        <small>{m0?.persistence?.count ?? "—"}개 정답</small>
                      </td>
                      <td>{percent}</td>
                      <td>
                        {paired?.minimum_30_targets_met === true
                          ? "30개 이상"
                          : paired?.minimum_30_targets_met === false
                            ? "30개 미만 · 표본 부족"
                            : "미확인"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="footnote">
            RMSE 단위 {unit || "원천 단위 확인 필요"} · 작을수록 좋습니다. M0는
            수위·강수, M1은 누적 강수·계절 정보를 추가한 모델입니다.
            Persistence는 직전 관측 수위를 그대로 사용하는 비교 기준입니다.
          </p>
          <p className="footnote">
            장마 정답이 26개처럼 최소 30개에 못 미치면 성능을 측정해 표시할 수는
            있지만 계절 승격 조건 통과로 판단하지 않습니다. 감소율이 음수면 M1의
            오차가 더 큽니다.
          </p>
        </>
      )}
    </Panel>
  );
}
