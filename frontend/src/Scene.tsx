import {
  Component,
  Suspense,
  useEffect,
  useMemo,
  useState,
  useRef,
  type ReactNode,
} from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Line, Edges } from "@react-three/drei";
import { Shape, ExtrudeGeometry, Group, MathUtils } from "three";
import { useAtom } from "jotai";
import { districtAtom, reducedAtom } from "./state";
import { type Row, number, fmt } from "./api";
class Boundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    return this.state.error ? (
      <div className="scene-fallback">
        3D를 사용할 수 없습니다. 관측소 목록에서 계속 조회하세요.
      </div>
    ) : (
      this.props.children
    );
  }
}
function District({ feature, rows }: { feature: Row; rows: Row[] }) {
  const [selected, setSelected] = useAtom(districtAtom);
  const [hover, setHover] = useState(false);
  const [reduced] = useAtom(reducedAtom);
  const group = useRef<Group>(null);
  const invalidate = useThree((s) => s.invalidate);
  const row = rows.find((r) => r.district_name === feature.properties.name);
  const active = row?.district_code === selected;
  useEffect(() => invalidate(), [active, reduced, invalidate]);
  useFrame((_, dt) => {
    if (!group.current) return;
    const target = active ? 0.18 : 0;
    const next = reduced
      ? target
      : MathUtils.damp(group.current.position.y, target, 9, dt);
    if (Math.abs(next - target) > 0.001) {
      group.current.position.y = next;
      invalidate();
    } else group.current.position.y = target;
  });
  const { geometries, center } = useMemo(() => {
    const polys =
      feature.geometry.type === "Polygon"
        ? [feature.geometry.coordinates]
        : feature.geometry.coordinates;
    const coords = polys.flat(2) as number[][];
    const project = (p: number[]) => [
      (p[0] - 126.978) * 21,
      (p[1] - 37.565) * 26,
    ];
    const all = coords.map(project);
    const center = [
      all.reduce((s, p) => s + p[0], 0) / all.length,
      all.reduce((s, p) => s + p[1], 0) / all.length,
    ];
    const geometries = polys.map((poly: number[][][]) => {
      const shape = new Shape();
      poly[0].forEach((p, i) => {
        const [x, y] = project(p);
        if (i === 0) shape.moveTo(x, y);
        else shape.lineTo(x, y);
      });
      shape.closePath();
      return new ExtrudeGeometry(shape, { depth: 0.3, bevelEnabled: false });
    });
    return { geometries, center };
  }, [feature]);
  useEffect(
    () => () => geometries.forEach((g: ExtrudeGeometry) => g.dispose()),
    [geometries],
  );
  return (
    <group ref={group} rotation={[-Math.PI / 2, 0, 0]}>
      {geometries.map((g: ExtrudeGeometry, i: number) => (
        <mesh
          key={i}
          geometry={g}
          onPointerOver={(e) => {
            e.stopPropagation();
            setHover(true);
          }}
          onPointerOut={() => setHover(false)}
          onClick={(e) => {
            e.stopPropagation();
            if (row) setSelected(row.district_code);
          }}
        >
          <meshStandardMaterial
            color={active ? "#73e5c2" : hover ? "#438978" : "#244d4a"}
            roughness={0.55}
            metalness={0.2}
            emissive={active ? "#1a7764" : "#000000"}
            emissiveIntensity={0.3}
          />
          <Edges color={active ? "#a5f4d7" : "#548c7e"} threshold={25} />
        </mesh>
      ))}
    </group>
  );
}
function Section({ row }: { row: Row }) {
  const actual = row.latest_comparison?.actual;
  const prediction = row.prediction;
  const max = Math.max(
    5,
    number(actual) ? Math.abs(actual) * 1.3 : 0,
    number(prediction) ? Math.abs(prediction) * 1.3 : 0,
  );
  const y = (v: number) => 1.25 + (v / max) * 2.5;
  return (
    <group>
      <mesh position={[0, -0.1, 0]}>
        <boxGeometry args={[3, 2.7, 1.7]} />
        <meshStandardMaterial
          color="#293f38"
          transparent
          opacity={0.32}
          depthWrite={false}
        />
      </mesh>
      <mesh position={[0, 1.29, 0]}>
        <boxGeometry args={[3.15, 0.08, 1.85]} />
        <meshStandardMaterial color="#8aa987" />
      </mesh>
      <mesh position={[0, -0.12, 0]}>
        <cylinderGeometry args={[0.08, 0.08, 2.8, 24]} />
        <meshStandardMaterial color="#cfddd4" />
      </mesh>
      {number(actual) && (
        <mesh position={[0, y(actual), 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[3, 1.7]} />
          <meshStandardMaterial
            color="#4ad9bc"
            transparent
            opacity={0.6}
            side={2}
          />
        </mesh>
      )}
      {number(prediction) && (
        <Line
          points={[
            [-1.5, y(prediction), 0.9],
            [1.5, y(prediction), 0.9],
          ]}
          color="#edbf7a"
          lineWidth={2}
          dashed
          dashSize={0.12}
          gapSize={0.08}
        />
      )}
    </group>
  );
}
export default function Scene({
  rows,
  section = false,
}: {
  rows: Row[];
  section?: boolean;
}) {
  const [selected] = useAtom(districtAtom);
  const selectedRow = section
    ? rows[0] || {}
    : rows.find((r) => r.district_code === selected) || {};
  const [geo, setGeo] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [reduced] = useAtom(reducedAtom);
  useEffect(() => {
    if (section) return;
    const c = new AbortController();
    fetch(import.meta.env.BASE_URL + "geo/seoul.json", { signal: c.signal })
      .then((r) => {
        if (!r.ok) throw Error("지도 자료 조회 실패");
        return r.json();
      })
      .then(setGeo)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, [section]);
  return (
    <Boundary>
      <div className="scene">
        {error ? (
          <div className="scene-fallback">
            {error} · 아래 관측소 목록을 이용하세요.
          </div>
        ) : (
          <Canvas
            frameloop="demand"
            dpr={[1, 1.5]}
            camera={{ position: section ? [4, 2.6, 5] : [0, 10, 12], fov: 40 }}
            fallback={<div>WebGL 미지원 · 관측소 목록을 이용하세요.</div>}
          >
            <color attach="background" args={["#0c2224"]} />
            <ambientLight intensity={1.4} />
            <directionalLight position={[4, 8, 4]} intensity={2.3} />
            <Suspense fallback={null}>
              {section ? (
                <Section row={rows[0] || {}} />
              ) : (
                geo?.features.map((f: Row) => (
                  <District key={f.properties.name} feature={f} rows={rows} />
                ))
              )}
            </Suspense>
            <gridHelper
              args={[18, 24, "#234246", "#183235"]}
              position={[0, -1.6, 0]}
            />
            <OrbitControls
              enablePan={false}
              enableDamping={!reduced}
              minDistance={section ? 4 : 7}
              maxDistance={section ? 10 : 26}
              minPolarAngle={0.25}
              maxPolarAngle={Math.PI / 2.1}
            />
          </Canvas>
        )}
        <div className="scene-overlay" aria-live="polite">
          <strong>{selectedRow.district_name || "관측소 선택"}</strong>
          {section && (
            <span>
              지표 기준 0 · 입력 {fmt(selectedRow.latest_comparison?.actual)}{" "}
              {selectedRow.unit || ""}
            </span>
          )}
          <span className="gold">
            다음 날 예측 {fmt(selectedRow.prediction)} {selectedRow.unit || ""}
          </span>
        </div>
        <div className="scene-note">
          {section
            ? "개념도 · 실제 지질 구조 아님 · 수직 축은 표시용 축척"
            : "서울 25개 구 · 구역 선택 / 드래그 회전 / 스크롤 확대"}
        </div>
      </div>
    </Boundary>
  );
}
