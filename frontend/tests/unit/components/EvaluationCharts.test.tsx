import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CandidateEvaluation, RainfallChart } from "../../../src/components/organisms/charts/EvaluationCharts";

describe("daily rainfall observations", () => {
  it("labels every observed date including zero, while leaving missing and future truth blank", () => {
    const html = renderToStaticMarkup(
      <RainfallChart
        rows={[
          { date: "2026-10-01", rainfall_mm: 0 },
          { date: "2026-10-02", rainfall_mm: null },
          { date: "2026-10-03", rainfall_mm: 12 },
          { date: "2026-10-04", rainfall_mm: undefined },
        ]}
      />,
    );
    expect(html).toContain("10/01</text>");
    expect(html).toContain("10/03</text>");
    expect(html).not.toContain("10/02</text>");
    expect(html).not.toContain("10/04</text>");
    expect(html).toContain("2026-10-01, 강수량 0 mm");
    expect(html).not.toContain("NaN");
    const positions = [...html.matchAll(/translate\(([\d.]+), 210\)/g)].map(
      (match) => Number(match[1]),
    );
    expect(positions).toHaveLength(2);
    expect(positions[1]).toBeGreaterThan(positions[0]);
    expect(positions[1]).toBeLessThan(920);
  });
  it("shows an empty state when no measured rainfall exists", () => {
    expect(
      renderToStaticMarkup(
        <RainfallChart rows={[{ date: "2026-10-01", rainfall_mm: null }]} />,
      ),
    ).toContain("강수 이력이 없습니다");
  });
});

describe("candidate quality comparison", () => {
  const evaluation = {
    status: "rejected",
    candidate_version: "2",
    gate_passed: false,
    metrics: {
      shadow_champion: { rmse: 0.02 },
      shadow_candidate: { rmse: 0.018, count: 30 },
    },
  };
  it("does not describe a lower error as model promotion when the overall gate rejected it", () => {
    const html = renderToStaticMarkup(
      <CandidateEvaluation evaluation={evaluation} unit="gl.-m" />,
    );
    expect(html).toContain("예측 오차 10.0% 감소");
    expect(html).toContain("기존 모델 유지");
    expect(html).toContain("전체 평가 기준 미충족");
    expect(html).not.toContain("교체 완료");
  });
  it("does not divide by a zero reference error", () => {
    const e = {
      ...evaluation,
      metrics: { shadow_champion: { rmse: 0 }, shadow_candidate: { rmse: 0 } },
    };
    const html = renderToStaticMarkup(<CandidateEvaluation evaluation={e} />);
    expect(html).toContain("개선율 계산 불가");
    expect(html).not.toMatch(/NaN|Infinity/);
  });
  it("does not manufacture comparison metrics for a candidate rejected before scoring", () => {
    expect(
      renderToStaticMarkup(
        <CandidateEvaluation
          evaluation={{ status: "rejected", reason: "champion_changed" }}
        />,
      ),
    ).toContain("비교 가능한 오차 기록이 없습니다");
  });
});
