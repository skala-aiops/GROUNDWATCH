import { Component, type ReactNode } from "react";
import { Canvas } from "@react-three/fiber";
import { Line, OrbitControls } from "@react-three/drei";
import WaterLevelDiagram, { levelDiagramData } from "./WaterLevelDiagram";
import { fmt, number, predictionLabel, measurementLabel, type Row } from "./api";

class Boundary extends Component<
  { row: Row; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <WaterLevelDiagram row={this.props.row} />
    ) : (
      this.props.children
    );
  }
}
export default function WaterLevelScene({ row }: { row: Row }) {
  const d = levelDiagramData(row);
  if (!d.known || (!number(d.actual) && !number(d.prediction)))
    return <WaterLevelDiagram row={row} />;
  const y = (value: number) =>
    -1.4 + ((value - d.low) / (d.high - d.low)) * 2.8;
  const forecast = predictionLabel(row);
  const label = `${row.station_name || row.name} · ${measurementLabel(row)} ${fmt(d.actual)} ${row.unit || "m"} · ${forecast} ${fmt(d.prediction)} ${row.unit || "m"}`;
  return (
    <Boundary row={row}>
      <div className="water-level-three">
        <div className="water-level-three-canvas" role="img" aria-label={label}>
          <Canvas
            frameloop="demand"
            dpr={[1, 1.5]}
            camera={{ position: [4, 3.5, 6], fov: 40 }}
            fallback={<WaterLevelDiagram row={row} />}
          >
            <color attach="background" args={["#0c2224"]} />
            <ambientLight intensity={1.5} />
            <directionalLight position={[3, 7, 5]} intensity={2} />
            {[0, 0.5, 1].map((t) => (
              <group key={t} position={[0, -1.4 + t * 2.8, 0]}>
                <Line
                  points={[
                    [-1.9, 0, -1.15],
                    [1.9, 0, -1.15],
                    [1.9, 0, 1.15],
                    [-1.9, 0, 1.15],
                    [-1.9, 0, -1.15],
                  ]}
                  color="#4d7471"
                  lineWidth={1}
                />
              </group>
            ))}
            <Line
              points={[
                [-1.9, -1.4, -1.15],
                [-1.9, 1.4, -1.15],
              ]}
              color="#b3c6bf"
              lineWidth={2}
            />
            {number(d.actual) && (
              <mesh
                position={[-0.95, y(d.actual), 0]}
                rotation={[-Math.PI / 2, 0, 0]}
              >
                <planeGeometry args={[1.7, 2.2]} />
                <meshStandardMaterial
                  color="#66dbb9"
                  transparent
                  opacity={0.8}
                  side={2}
                />
              </mesh>
            )}
            {number(d.prediction) && (
              <group position={[0.95, y(d.prediction), 0]}>
                <mesh rotation={[-Math.PI / 2, 0, 0]}>
                  <planeGeometry args={[1.7, 2.2]} />
                  <meshStandardMaterial
                    color="#edbf7a"
                    transparent
                    opacity={0.4}
                    side={2}
                  />
                </mesh>
                <Line
                  points={[
                    [-0.85, 0, -1.1],
                    [0.85, 0, -1.1],
                    [0.85, 0, 1.1],
                    [-0.85, 0, 1.1],
                    [-0.85, 0, -1.1],
                  ]}
                  color="#edbf7a"
                  lineWidth={2}
                  dashed
                  dashSize={0.12}
                  gapSize={0.08}
                />
              </group>
            )}
            <OrbitControls
              target={[0, 0, 0]}
              enablePan={false}
              enableDamping={false}
              minDistance={5}
              maxDistance={12}
              maxPolarAngle={Math.PI / 2.05}
            />
          </Canvas>
          <div className="water-level-three-range">
            상단 {fmt(d.high)} m<br />중간 {fmt((d.high + d.low) / 2)} m<br />하단{" "}
            {fmt(d.low)} m
          </div>
        </div>
        <div className="water-level-three-values">
          <span>
            ● {measurementLabel(row)} {fmt(d.actual)} {row.unit}
          </span>
          <span>
            {forecast} {fmt(d.prediction)} {row.unit}
          </span>
        </div>
        <p className="footnote">
          {measurementLabel(row)} {row.observed_date || "날짜 미확인"} · 비교 대상{" "}
          {row.forecast_date || "날짜 미확인"}. 드래그 회전 · 스크롤 확대.
        </p>
        <p className="footnote">
          {d.simulated ? "시뮬레이션 상대 기준면 · 실제 해발·지표 아님" : d.groundRelative ? "지표 기준(GL)" : "원천 해발 수위 기준"} ·
          세로축은 표시용 축척이며 위·중간·아래 경계값을 표시합니다. 두 면은
          같은 관측소의 값 비교용입니다.
        </p>
        <p className="footnote">
          실제 지층·관정 도면 미확보 · 지표 높이·지층 두께·지하수의 공간 분포를
          나타내지 않습니다.
        </p>
      </div>
    </Boundary>
  );
}
