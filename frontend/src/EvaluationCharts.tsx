import { useState } from "react";
import { fmt, number, type Row } from "./api";

export function RainfallChart({ rows }: { rows: Row[] }) {
  const [selected, select] = useState<string | null>(null);
  const dates = rows.map((row) => Date.parse(row.date + "T00:00:00Z"));
  const observed = rows.flatMap((row, i) =>
    number(row.rainfall_mm) && row.rainfall_mm >= 0 && Number.isFinite(dates[i])
      ? [
          {
            date: String(row.date),
            rainfall_mm: row.rainfall_mm,
            day: dates[i],
          },
        ]
      : [],
  );
  if (!observed.length)
    return <div className="empty">표시할 검증된 강수 이력이 없습니다.</div>;
  const first = Math.min(...dates.filter(Number.isFinite));
  const last = Math.max(...dates.filter(Number.isFinite));
  const days = Math.max(1, (last - first) / 86400000);
  const width = Math.max(920, days * 30 + 120);
  const maximum = Math.max(1, ...observed.map((r) => r.rainfall_mm)) * 1.1;
  const x = (day: number) =>
    70 + ((day - first) / 86400000 / days) * (width - 120);
  const y = (value: number) => 185 - (value / maximum) * 150;
  const active = observed.find((r) => r.date === selected);
  return (
    <div className="rainfall-chart">
      <p className="footnote">
        {observed[0].date} ~ {observed.at(-1)!.date} · 관측 {observed.length}일
        <br />
        값이 있는 날짜만 표시합니다. 0mm는 점, 결측은 빈칸입니다. 긴 기간은
        가로로 이동하세요.
      </p>
      <div
        className="chart-scroll"
        tabIndex={0}
        role="region"
        aria-label="관측일별 강수량 그래프, 가로 스크롤"
      >
        <svg
          className="rain-svg"
          width={width}
          viewBox={`0 0 ${width} 280`}
          role="img"
          aria-label="관측일별 일 강수량"
        >
          {[0, 1, 2, 3].map((i) => (
            <g key={i}>
              <line
                x1="60"
                x2={width - 35}
                y1={y((maximum * i) / 3)}
                y2={y((maximum * i) / 3)}
                stroke="#244044"
              />
              <text x="50" y={y((maximum * i) / 3) + 4} textAnchor="end">
                {fmt((maximum * i) / 3, 1)}
              </text>
            </g>
          ))}
          {observed.map((r) => (
            <g
              key={r.date}
              tabIndex={0}
              role="img"
              aria-label={`${r.date}, 강수량 ${r.rainfall_mm} mm`}
              onFocus={() => select(r.date)}
              onMouseEnter={() => select(r.date)}
              onClick={() => select(r.date)}
            >
              <title>
                {r.date}: {r.rainfall_mm} mm
              </title>
              <rect
                x={x(r.day) - 12}
                y="28"
                width="24"
                height="170"
                fill="transparent"
              />
              {r.rainfall_mm === 0 ? (
                <circle cx={x(r.day)} cy="185" r="3" fill="#59b5c0" />
              ) : (
                <rect
                  x={x(r.day) - 7}
                  y={y(r.rainfall_mm)}
                  width="14"
                  height={185 - y(r.rainfall_mm)}
                  fill={selected === r.date ? "#9be5ec" : "#59b5c0"}
                />
              )}
              <line
                x1={x(r.day)}
                x2={x(r.day)}
                y1="190"
                y2="196"
                stroke="#8eae9e"
              />
              <text
                transform={`translate(${x(r.day)}, 210) rotate(-55)`}
                textAnchor="end"
              >
                {r.date.slice(5).replace("-", "/")}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <p className="chart-readout" aria-live="polite">
        {active
          ? `${active.date} · 일 강수량 ${active.rainfall_mm} mm`
          : "막대나 0mm 점에 마우스를 올리거나 선택하면 날짜와 강수량을 확인할 수 있습니다."}
      </p>
      <details>
        <summary>강수 관측 원자료 보기</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>관측일</th>
                <th>일 강수량 (mm)</th>
              </tr>
            </thead>
            <tbody>
              {observed.map((r) => (
                <tr key={r.date}>
                  <td>{r.date}</td>
                  <td>{r.rainfall_mm}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

export function CandidateEvaluation({
  evaluation: e,
  unit,
}: {
  evaluation: Row | null;
  unit?: string;
}) {
  const current = e?.metrics?.shadow_champion?.rmse;
  const candidate = e?.metrics?.shadow_candidate?.rmse;
  if (
    !e ||
    !number(current) ||
    !number(candidate) ||
    current < 0 ||
    candidate < 0
  )
    return (
      <div className="empty">
        {e?.status === "rejected"
          ? "후보가 평가 조건을 충족하지 못해 기존 모델을 유지합니다. 비교 가능한 오차 기록이 없습니다."
          : "후보 모델의 비교 평가가 아직 없습니다. 새 정답이 모이면 기존 모델과 후보 모델의 오차를 비교합니다."}
      </div>
    );
  const limit = number(e.gates?.future_improvement?.limit)
    ? e.gates.future_improvement.limit
    : current * 0.95;
  const max = Math.max(current, candidate, limit, Number.EPSILON) * 1.18;
  const scale = (v: number) => 155 + (v / max) * 430;
  const change = current > 0 ? ((current - candidate) / current) * 100 : null;
  const verdict =
    e.status === "promoted"
      ? "후보 모델로 교체 완료"
      : e.status === "rejected"
        ? "기존 모델 유지"
        : e.gate_passed === true
          ? "평가 기준 충족 · 교체 상태 확인 필요"
          : "평가 진행 중";
  return (
    <div className="candidate-evaluation">
      <div className="evaluation-heading">
        <div>
          <span className="eyebrow">기존 모델 · 후보 모델 비교</span>
          <h3>{verdict}</h3>
        </div>
        <strong
          className={change !== null && change > 0 ? "improvement" : "muted"}
        >
          {change === null
            ? "기존 오차 0 · 개선율 계산 불가"
            : change === 0
              ? "예측 오차 동일"
              : `예측 오차 ${Math.abs(change).toFixed(1)}% ${change > 0 ? "감소" : "증가"}`}
        </strong>
      </div>
      <p className="footnote">
        같은 평가 구간의 예측 오차(RMSE) · 막대가 짧을수록 정확합니다. 단위:{" "}
        {unit || "수위 단위 미확인"}
      </p>
      <div
        className="chart-scroll"
        tabIndex={0}
        role="region"
        aria-label="기존 모델과 후보 모델의 예측 오차 비교"
      >
        <svg
          className="evaluation-svg"
          viewBox="0 0 720 245"
          role="img"
          aria-label={`기존 모델 RMSE ${current}, 후보 모델 RMSE ${candidate}. ${verdict}`}
        >
          {[0, 1, 2, 3, 4].map((i) => (
            <g key={i}>
              <line
                x1={scale((max * i) / 4)}
                x2={scale((max * i) / 4)}
                y1="30"
                y2="176"
                stroke="#244044"
              />
              <text x={scale((max * i) / 4)} y="198" textAnchor="middle">
                {fmt((max * i) / 4, 4)}
              </text>
            </g>
          ))}
          {[
            { name: "기존 모델", value: current, color: "#8ab8ff", y: 48 },
            {
              name: `후보 모델 v${e.candidate_version || "—"}`,
              value: candidate,
              color: "#73e5c2",
              y: 120,
            },
          ].map((r) => (
            <g key={r.name}>
              <text x="140" y={r.y + 24} textAnchor="end">
                {r.name}
              </text>
              <rect
                x="155"
                y={r.y}
                width={Math.max(0, scale(r.value) - 155)}
                height="36"
                rx="3"
                fill={r.color}
              />
              {r.value === 0 && (
                <circle cx="155" cy={r.y + 18} r="3" fill={r.color} />
              )}
              <text x="680" y={r.y + 24} textAnchor="end">
                {r.value === 0
                  ? "0"
                  : r.value < 0.0001
                    ? r.value.toExponential(2)
                    : fmt(r.value, 4)}
              </text>
            </g>
          ))}
          <line
            x1={scale(limit)}
            x2={scale(limit)}
            y1="105"
            y2="168"
            stroke="#edbf7a"
            strokeWidth="2"
            strokeDasharray="4 3"
          />
          <text x="155" y="230" className="threshold-label">
            ┄ 후보 교체를 위한 오차 기준 (기존보다 5% 이상 감소)
          </text>
        </svg>
      </div>
      <p className="footnote">
        평가 기간 {e.shadow_start || "미확인"} ~ {e.shadow_end || "미확인"} ·
        정답 {e.metrics.shadow_candidate.count ?? "미확인"}개
        <br />
        모델 교체에는 오차 개선과 기존 구간 검증이 모두 필요합니다.{" "}
        {e.gate_passed === true
          ? "전체 평가 기준 충족."
          : e.gate_passed === false
            ? "전체 평가 기준 미충족."
            : "전체 평가 결과 미확인."}
      </p>
      <details>
        <summary>상세 평가 수치 보기</summary>
        <pre>{JSON.stringify(e, null, 2)}</pre>
      </details>
    </div>
  );
}
