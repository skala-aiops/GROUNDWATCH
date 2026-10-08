import { fmt, number } from "../../../utils/format";
import { predictionLabel, measurementLabel } from "../../../utils/stations";
import { type Row } from "../../../types/domain";

export function levelDiagramData(row: Row) {
  const actual = number(row.latest_actual_level)
    ? row.latest_actual_level
    : number(row.latest_comparison?.actual)
      ? row.latest_comparison.actual
      : null;
  const prediction = number(row.prediction) ? row.prediction : null;
  const reference = row.level_reference || row.reference_status;
  const groundRelative = String(row.unit || row.level_unit)
    .toLowerCase()
    .includes("gl");
  const elevation =
    reference === "elevation" && (row.unit || row.level_unit) === "m";
  const simulated = row.source_kind === "synthetic" && row.level_reference === "simulation_relative_datum" && (row.unit || row.level_unit) === "m";
  const known = groundRelative || elevation || simulated;
  const values = [actual, prediction].filter(number) as number[];
  if (groundRelative) values.push(0);
  const min = Math.min(...values),
    max = Math.max(...values);
  const pad = values.length ? Math.max((max - min) * 0.25, 0.1) : 1;
  return {
    simulated,
    actual,
    prediction,
    known,
    groundRelative,
    low: values.length ? min - pad : -1,
    high: values.length ? max + pad : 1,
  };
}

export default function WaterLevelDiagram({ row }: { row: Row }) {
  const d = levelDiagramData(row);
  const y = (value: number) => 210 - ((value - d.low) / (d.high - d.low)) * 170;
  const forecast = predictionLabel(row);
  return (
    <div className="water-level-diagram">
      <p className="footnote">
        {d.simulated ? "시뮬레이션 상대 기준면(m) · 실제 해발·지표 기준이 아닙니다." : d.groundRelative
          ? "지표 기준(GL) · 지표 0m"
          : d.known
            ? "원천 해발 수위 기준 · 지표 높이는 표시하지 않습니다."
            : "수위 단위·기준면 미확인 · 공간 위치로 변환하지 않습니다."}
      </p>
      {d.known && (number(d.actual) || number(d.prediction)) ? (
        <svg
          viewBox="0 0 520 260"
          role="img"
          aria-label={`${row.station_name || row.name} 수위 비교도`}
        >
          {[0, 0.5, 1].map((t) => {
            const v = d.low + (d.high - d.low) * t;
            return (
              <g key={t}>
                <line x1="85" x2="485" y1={y(v)} y2={y(v)} stroke="#315052" />
                <text
                  x="75"
                  y={y(v) + 4}
                  textAnchor="end"
                  fill="#b4c9c4"
                  fontSize="12"
                >
                  {fmt(v)} m
                </text>
              </g>
            );
          })}
          {d.groundRelative && (
            <g>
              <line x1="85" x2="485" y1={y(0)} y2={y(0)} stroke="#a8b79a" />
              <text x="90" y={y(0) - 8} fill="#a8b79a" fontSize="12">
                지표 0m
              </text>
            </g>
          )}
          {number(d.actual) && (
            <g>
              <line
                x1="85"
                x2="285"
                y1={y(d.actual)}
                y2={y(d.actual)}
                stroke="#78ddbf"
                strokeWidth="3"
              />
              <circle cx="180" cy={y(d.actual)} r="5" fill="#78ddbf" />
              <text
                x="180"
                y="242"
                textAnchor="middle"
                fill="#78ddbf"
                fontSize="12"
              >
                {measurementLabel(row)} {fmt(d.actual)}
              </text>
            </g>
          )}
          {number(d.prediction) && (
            <g>
              <line
                x1="285"
                x2="485"
                y1={y(d.prediction)}
                y2={y(d.prediction)}
                stroke="#edbf7a"
                strokeWidth="3"
                strokeDasharray="7 5"
              />
              <circle cx="385" cy={y(d.prediction)} r="5" fill="#edbf7a" />
              <text
                x="385"
                y="242"
                textAnchor="middle"
                fill="#edbf7a"
                fontSize="12"
              >
                {forecast} {fmt(d.prediction)}
              </text>
            </g>
          )}
        </svg>
      ) : (
        <div className="empty">
          비교도에 표시할 기준면 또는 수위가 없습니다.
        </div>
      )}
      <p className="footnote">
        {measurementLabel(row)} {row.observed_date || "날짜 미확인"} · {forecast}{" "}
        {row.forecast_date || "날짜 미확인"}. 세로축은 두 값의 차이를 보여주는
        표시 축척입니다.
      </p>
      <p className="footnote">
        실제 지층·관정 시공 도면은 확보되지 않았습니다. 이 그림은 수위
        비교용이며 지층 두께·관정 깊이·지하수 분포를 나타내지 않습니다.
      </p>
    </div>
  );
}
