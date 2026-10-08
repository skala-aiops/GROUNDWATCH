import { Button } from "@/components/atoms/button";
import {
  Component,
  useEffect,
  useMemo,
  useState,
  useLayoutEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Line, OrbitControls, Html } from "@react-three/drei";
import { Color, InstancedMesh, Object3D } from "three";
import type { RainStation, GroundStation } from "../../../types/domain";

type Geo = {
  features: Array<{ geometry: { type: string; coordinates: any } }>;
};
const project = (lon: number, lat: number): [number, number, number] => [
  (lon - 127.5) * 1.4,
  0,
  -(lat - 36) * 1.7,
];
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="national-map-fallback">
        3D 지도를 표시할 수 없습니다. 아래 관측소 목록에서 같은 자료를
        확인하세요.
      </div>
    ) : (
      this.props.children
    );
  }
}
function Coast({ url }: { url: string }) {
  const [geo, setGeo] = useState<Geo | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(url, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then(setGeo)
      .catch(() => {});
    return () => controller.abort();
  }, [url]);
  const lines = useMemo(
    () =>
      (geo?.features || []).flatMap((f) => {
        const g = f.geometry;
        const rings =
          g.type === "Polygon"
            ? g.coordinates
            : g.type === "MultiPolygon"
              ? g.coordinates.flat()
              : g.type === "LineString"
                ? [g.coordinates]
                : g.type === "MultiLineString"
                  ? g.coordinates
                  : [];
        return rings
          .filter((r: any[]) =>
            r.some(
              (p) => p[0] >= 123 && p[0] <= 132 && p[1] >= 32 && p[1] <= 40,
            ),
          )
          .map((r: any[]) => r.map((p) => project(p[0], p[1])));
      }),
    [geo],
  );
  return (
    <>
      {lines.map((points: any, i: number) => (
        <Line key={i} points={points} color="#779b99" lineWidth={1.2} />
      ))}
    </>
  );
}
function GroundPoints({
  portal,
  stations,
  selected,
  onSelect,
}: {
  portal: RefObject<HTMLDivElement>;
  stations: GroundStation[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  return (
    <>
      {stations.map((station) => (
        <Html
          key={station.station_id}
          portal={portal}
          position={project(station.longitude, station.latitude)}
          center
          zIndexRange={[10, 0]}
        >
          <Button
            style={{ pointerEvents: "auto" }}
            className={
              "ground-map-marker" +
              (station.station_id === selected ? " active" : "")
            }
            aria-label={station.name + " 관측소 선택"}
            aria-pressed={station.station_id === selected}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(station.station_id);
            }}
          >
            <span aria-hidden="true">●</span>
            {station.name}
          </Button>
        </Html>
      ))}
    </>
  );
}

function RainColumns({
  stations,
  selected,
  onSelect,
  maximum,
}: {
  stations: RainStation[];
  selected: string;
  onSelect: (id: string) => void;
  maximum: number;
}) {
  const mesh = useRef<InstancedMesh>(null);
  const invalidate = useThree((s) => s.invalidate);
  const rows = useMemo(
    () =>
      stations.filter(
        (s) =>
          Number.isFinite(s.latitude) &&
          Number.isFinite(s.longitude) &&
          (s.station_id === selected ||
            (typeof s.rainfall_mm === "number" && s.rainfall_mm > 0)),
      ),
    [stations, selected],
  );
  useLayoutEffect(() => {
    if (!mesh.current) return;
    const dummy = new Object3D();
    rows.forEach((s, i) => {
      const [x, , z] = project(s.longitude, s.latitude);
      const has =
        typeof s.rainfall_mm === "number" &&
        Number.isFinite(s.rainfall_mm) &&
        s.rainfall_mm >= 0;
      const height =
        has && s.rainfall_mm! > 0 ? (s.rainfall_mm! / maximum) * 4.2 : 0.025;
      dummy.position.set(x, height / 2, z);
      dummy.scale.set(
        s.station_id === selected ? 0.09 : 0.055,
        height,
        s.station_id === selected ? 0.09 : 0.055,
      );
      dummy.updateMatrix();
      mesh.current!.setMatrixAt(i, dummy.matrix);
      mesh.current!.setColorAt(
        i,
        new Color(
          s.station_id === selected ? "#edbf7a" : has ? "#65dcc3" : "#607679",
        ),
      );
    });
    mesh.current.instanceMatrix.needsUpdate = true;
    if (mesh.current.instanceColor)
      mesh.current.instanceColor.needsUpdate = true;
    mesh.current.computeBoundingSphere();
    invalidate();
  }, [rows, selected, maximum, invalidate]);
  const active = rows.find((s) => s.station_id === selected);
  if (!rows.length) return null;
  return (
    <>
      <instancedMesh
        ref={mesh}
        args={[undefined, undefined, rows.length]}
        onClick={(e) => {
          if (e.delta > 4) return;
          if (e.instanceId !== undefined && rows[e.instanceId]) {
            e.stopPropagation();
            onSelect(rows[e.instanceId].station_id);
          }
        }}
      >
        <cylinderGeometry args={[1, 1, 1, 10]} />
        <meshStandardMaterial roughness={0.65} />
      </instancedMesh>
      {active && (
        <mesh
          position={project(active.longitude, active.latitude)}
          rotation={[-Math.PI / 2, 0, 0]}
        >
          <ringGeometry args={[0.13, 0.17, 20]} />
          <meshBasicMaterial color="#edbf7a" side={2} />
        </mesh>
      )}
    </>
  );
}
export default function NationalRainScene({
  stations,
  selected,
  onSelect,
  boundariesUrl,
  groundStations = [],
  groundSelected = "",
  onGroundSelect = () => {},
  groundwaterOnly = false,
  simulation = false,
}: {
  stations: RainStation[];
  selected: string;
  onSelect: (id: string) => void;
  boundariesUrl?: string | null;
  groundStations?: GroundStation[];
  groundSelected?: string;
  onGroundSelect?: (id: string) => void;
  groundwaterOnly?: boolean;
  simulation?: boolean;
}) {
  const markerPortal = useRef<HTMLDivElement>(null!);
  const actualMax = Math.max(
    0,
    ...stations.flatMap((s) =>
      typeof s.rainfall_mm === "number" && Number.isFinite(s.rainfall_mm)
        ? [s.rainfall_mm]
        : [],
    ),
  );
  const max = Math.max(1, actualMax);
  return (
    <Boundary>
      <div className="national-map">
        {/* Drei owns only children of this empty portal, separate from React's Canvas siblings. */}
        <div
          ref={markerPortal}
          className="ground-map-marker-portal"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            zIndex: 10,
          }}
        />
        <Canvas
          frameloop="demand"
          dpr={[1, 1.25]}
          gl={{ antialias: false, powerPreference: "high-performance" }}
          camera={{ position: [0, 12, 10], fov: 36 }}
          fallback={
            <div>
              지도 대체 보기 · 아래 관측소 목록에서도 같은 자료를 확인할 수
              있습니다.
            </div>
          }
        >
          <color attach="background" args={["#0b2023"]} />
          <ambientLight intensity={1.8} />
          <directionalLight position={[4, 12, 6]} intensity={2.8} />
          {boundariesUrl && <Coast url={boundariesUrl} />}
          {!!groundStations.length && (
            <GroundPoints
              portal={markerPortal}
              stations={groundStations}
              selected={groundSelected}
              onSelect={onGroundSelect}
            />
          )}
          <RainColumns
            stations={stations}
            selected={selected}
            onSelect={onSelect}
            maximum={max}
          />
          {[33, 34, 35, 36, 37, 38, 39].map((lat) => (
            <Line
              key={"lat" + lat}
              points={[project(124, lat), project(131, lat)]}
              color="#193d42"
              lineWidth={0.7}
            />
          ))}
          {[124, 125, 126, 127, 128, 129, 130, 131].map((lon) => (
            <Line
              key={"lon" + lon}
              points={[project(lon, 33), project(lon, 39)]}
              color="#193d42"
              lineWidth={0.7}
            />
          ))}
          <OrbitControls
            target={[0, 0, 1]}
            enablePan
            enableDamping={false}
            minDistance={6}
            maxDistance={30}
            maxPolarAngle={Math.PI / 2.1}
          />
        </Canvas>
        <div className="national-map-note">
          {groundwaterOnly
            ? simulation ? "합성 시뮬레이션 관측소 · 실제 관측 위치·수위가 아님" : "실측 이력이 있는 관측소만 표시 · 이름을 누르면 선택"
            : `일강수 실측 · ${actualMax > 0 ? "기둥 높이 0–" + actualMax.toFixed(1) + "mm" : "양의 강수 관측값 없음"}`}
          <br />
          회전·확대 가능 · 강수 0mm·결측 지점은 기둥 생략
        </div>
        <div className="national-map-legend">
          {!groundwaterOnly && (
            <>
              <span>● 강수 관측</span>
            </>
          )}
          <span className="gold">● 선택 지점</span>
          {!!groundStations.length && (
            <span style={{ color: "#80a7e6" }}>{simulation ? "● 시뮬레이션 관측소" : "● 실측 관측소"}</span>
          )}
        </div>
      </div>
    </Boundary>
  );
}
