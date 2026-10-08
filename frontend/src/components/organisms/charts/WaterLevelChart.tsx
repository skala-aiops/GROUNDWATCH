import { label } from "../../../utils/format";
import { chartSegments, comparison } from "../../../utils/chart";
import { fmt, number } from "../../../utils/format";
import { type Row } from "../../../types/domain";
import { RainfallChart, RainyBands } from "./EvaluationCharts";
export default function Chart({ rows, rain = false, periods = [] }: { rows: Row[]; rain?: boolean; periods?: Row[] }) {
  if (rain) return <RainfallChart rows={rows} periods={periods} />;
  const values = rows
    .flatMap((r) =>
      rain ? [r.rainfall_mm] : [r.groundwater_level, r.prediction],
    )
    .filter(number);
  if (!values.length)
    return (
      <div className="empty">
        표시할 검증된 {rain ? "강수" : "수위"} 이력이 없습니다.
      </div>
    );
  const low = Math.min(...values),
    high = Math.max(...values),
    pad = Math.max((high - low) * 0.15, 0.05);
  const min = rain ? 0 : low - pad,
    max = high + pad;
  const times = rows.map((r) => Date.parse(r.date + "T00:00:00Z"));
  const first = times[0],
    span = Math.max(86400000, times.at(-1)! - first);
  const x = (i: number) => 64 + ((times[i] - first) / span) * 800;
  const y = (v: number) => 185 - ((v - min) / (max - min)) * 150;
  const segments = (key: string) =>
    chartSegments(rows, key).map((points) =>
      points
        .map((p, i) => (i ? "L" : "M") + x(p.index) + " " + y(p.value))
        .join(" "),
    );
  return (
    <>
      <svg
        className="chart"
        viewBox="0 0 920 230"
        role="img"
        aria-label={rain ? "일 강수량 차트" : "입력 수위와 저장 예측 차트"}
      >
        <RainyBands periods={periods} first={first} last={times.at(-1)!} x={(day) => 64 + ((day - first) / span) * 800} />
        {[0, 1, 2, 3].map((i) => {
          const v = min + ((max - min) * i) / 3;
          return (
            <g key={i}>
              <line x1="64" x2="870" y1={y(v)} y2={y(v)} stroke="#244044" />
              <text x="52" y={y(v) + 4} textAnchor="end">
                {fmt(v, 2)}
              </text>
            </g>
          );
        })}
        {rain ? (
          rows.map(
            (r, i) =>
              number(r.rainfall_mm) && (
                <rect
                  key={i}
                  x={x(i) - 2}
                  y={y(r.rainfall_mm)}
                  width="4"
                  height={185 - y(r.rainfall_mm)}
                  fill="#59b5c0"
                >
                  <title>
                    {r.date}: {r.rainfall_mm} mm
                  </title>
                </rect>
              ),
          )
        ) : (
          <>
            {segments("groundwater_level").map((d, i) => (
              <path
                key={"a" + i}
                d={d}
                fill="none"
                stroke="#73e5c2"
                strokeWidth="2"
              />
            ))}
            {segments("prediction").map((d, i) => (
              <path
                key={"p" + i}
                d={d}
                fill="none"
                stroke="#edbf7a"
                strokeWidth="2"
                strokeDasharray="5 4"
              />
            ))}
            {rows.map(
              (r, i) =>
                number(r.prediction) && (
                  <circle
                    key={"p" + i}
                    cx={x(i)}
                    cy={y(r.prediction)}
                    r={number(r.groundwater_level) ? 2 : 5}
                    fill="#edbf7a"
                  >
                    <title>
                      {r.date} 저장 예측 {fmt(r.prediction)}
                    </title>
                  </circle>
                ),
            )}
            {rows.map(
              (r, i) =>
                number(r.groundwater_level) && (
                  <circle
                    key={i}
                    cx={x(i)}
                    cy={y(r.groundwater_level)}
                    r="3"
                    fill={
                      comparison(r.groundwater_level, r.prediction) === "above"
                        ? "#f7958d"
                        : comparison(r.groundwater_level, r.prediction) ===
                            "below"
                          ? "#8ab8ff"
                          : "#73e5c2"
                    }
                  >
                    <title>
                      {r.date}: 입력 {fmt(r.groundwater_level)} / 예측{" "}
                      {fmt(r.prediction)}
                    </title>
                  </circle>
                ),
            )}
          </>
        )}
        <text x="64" y="218">
          {rows[0]?.date}
        </text>
        <text x="870" y="218" textAnchor="end">
          {rows.at(-1)?.date}
        </text>
      </svg>
      <details>
        <summary>차트 원자료 보기</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>날짜</th>
                <th>입력 수위</th>
                <th>저장 예측</th>
                <th>강수 mm</th>
                <th>출처</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>{r.date}</td>
                  <td>{fmt(r.groundwater_level)}</td>
                  <td>{fmt(r.prediction)}</td>
                  <td>{fmt(r.rainfall_mm)}</td>
                  <td>{label(r.origin)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
