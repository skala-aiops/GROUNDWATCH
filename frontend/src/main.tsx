import React, { Suspense, lazy, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Provider, useAtom } from "jotai";
import {
  Activity,
  ArrowUpRight,
  Box,
  ChevronRight,
  Database,
  Layers3,
  LayoutDashboard,
  RefreshCw,
  Waves,
} from "lucide-react";
import {
  viewAtom,
  districtAtom,
  modeAtom,
  replayAtom,
  dateAtom,
  searchAtom,
  rangeAtom,
  threeAtom,
  reducedAtom,
  regionAtom,
  mapLayerAtom,
} from "./state";
import {
  chartSegments,
  initialStationId,
  serviceStations,
  stationDataStatus,
  measurementLabel,
  selectedNetworkStationId,
  predictionLabel,
  confirmedUnit,
  comparison,
  fmt,
  label,
  number,
  post,
  request,
  useResource,
  type Row,
} from "./api";
import "./style.css";
import { SourceInfo, CollectionStatus, sourceLabel } from "./SourceInfo";
import ServiceGuide, { GuideButton } from "./ServiceGuide";
import WaterLevelDiagram from "./WaterLevelDiagram";
import { CandidateEvaluation, RainfallChart, RainyBands } from "./EvaluationCharts";
import "./national.css";
const NationalRainScene = lazy(() => import("./NationalRainScene"));
const Scene = lazy(() => import("./Scene"));
const WaterLevelScene = lazy(() => import("./WaterLevelScene"));
const titles = {
  overview: "관측소 현황",
  detail: "관측소 상세",
  operations: "모델 관리 · 시연",
};
function Badge({ status }: { status: unknown }) {
  return (
    <span className={"badge " + String(status || "pending").toLowerCase()}>
      {label(status)}
    </span>
  );
}
function Json({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}
function Chart({ rows, rain = false, periods = [] }: { rows: Row[]; rain?: boolean; periods?: Row[] }) {
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
function App() {
  const [view, setView] = useAtom(viewAtom),
    [selected, setSelected] = useAtom(districtAtom),
    [mode, setMode] = useAtom(modeAtom),
    [replay, setReplay] = useAtom(replayAtom),
    [date, setDate] = useAtom(dateAtom),
    [search, setSearch] = useAtom(searchAtom),
    [range, setRange] = useAtom(rangeAtom),
    [three, setThree] = useAtom(threeAtom),
    [reduced, setReduced] = useAtom(reducedAtom),
    [region, setRegion] = useAtom(regionAtom),
    [mapLayer, setMapLayer] = useAtom(mapLayerAtom);
  const [weatherSource, setWeatherSource] = useState("aws-daily");
  const [dataScope, setDataScope] = useState("seoul-history");
  const [weatherDate, setWeatherDate] = useState("");
  const [weatherSelected, setWeatherSelected] = useState("");
  const weatherBase =
    weatherSource === "asos"
      ? "/api/v2/rainfall"
      : "/api/v2/rainfall/aws-daily";
  const weather = useResource(
    weatherBase + "/network" + (weatherDate ? "?date=" + weatherDate : ""),
    30000,
  );
  const weatherHistory = useResource(
    weatherSelected
      ? weatherBase +
          "/stations/" +
          encodeURIComponent(weatherSelected) +
          "/history"
      : null,
    30000,
  );
  const [directoryLimit, setDirectoryLimit] = useState(100);
  const [revision, bump] = useState(0),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [all, setAll] = useState(false);
  const advanceRef = useRef(false);
  useEffect(() => {
    if (replay) setMode("historical_replay");
  }, []);
  const scope = new URLSearchParams();
  if (mode === "historical_replay" && replay) scope.set("replay_id", replay);
  const suffix = scope.toString();
  const fq = new URLSearchParams(scope);
  fq.set("mode", mode);
  if (date && mode !== "current") fq.set("as_of", date);
  const forecasts = useResource(
    "/api/v2/network/stations?" + fq,
    30000,
    revision,
  );
  const replays = useResource("/replays", 3000, revision);
  const rows: Row[] = serviceStations(
    forecasts.data?.stations || [],
    dataScope,
  ).map((r: Row) => ({
    ...r,
    district_code: r.station_id,
    district_name:
      r.provider === "seoul"
        ? r.district_name
        : r.region_name || r.region_code || r.district_name,
    station_name:
      r.provider === "seoul"
        ? r.station_name || r.name
        : r.name || r.station_name,
    unit: confirmedUnit(r.unit || r.level_unit),
  }));
  const networkSelected = selectedNetworkStationId(rows, selected);
  const pipeline = useResource(
    networkSelected
      ? "/api/v2/network/pipeline?station_id=" +
          encodeURIComponent(networkSelected) +
          "&mode=" +
          mode +
          (date && mode !== "current" ? "&as_of=" + date : "") +
          (suffix ? "&" + suffix : "")
      : null,
    view === "operations" ? 3000 : 30000,
    revision,
  );
  const pending =
    !!replay &&
    mode === "historical_replay" &&
    pipeline.data?.replay_status !== "ready";
  const choices: Row[] = rows.filter(
    (r) =>
      (!region || r.region_code === region || r.district_name === region) &&
      (r.district_name + " " + r.station_name).includes(search.trim()),
  );
  useEffect(() => {
    if (!rows.length) return;
    if (!rows.some((r) => r.station_id === selected)) {
      setSelected(initialStationId(rows, selected));
    }
  }, [forecasts.data, selected, dataScope]);
  useEffect(() => {
    if (choices.length && !choices.some((r) => r.station_id === selected)) {
      setSelected(choices[0].station_id);
    }
  }, [region, search, dataScope, forecasts.data]);
  const row =
    (view === "overview" ? choices : rows).find(
      (r) => r.district_code === selected,
    ) || {};
  const legacySelected = row.legacy_district_code;
  const hq = new URLSearchParams(scope);
  hq.set("mode", mode);
  if (date && mode !== "current") hq.set("as_of", date);
  if (row.source_dataset_id && !replay)
    hq.set("dataset_id", row.source_dataset_id);
  const history = useResource(
    view === "detail" && !pending && !!networkSelected
      ? "/api/v2/network/stations/" +
          encodeURIComponent(selected) +
          "/history?" +
          hq
      : null,
    30000,
    revision,
  );
  const setSession = (id: string) => {
    setReplay(id);
    setDate("");
    setMode(id ? "historical_replay" : "current");
    setAll(false);
    bump((n) => n + 1);
    const url = new URL(location.href);
    id
      ? url.searchParams.set("replay_id", id)
      : url.searchParams.delete("replay_id");
    historyReplace(url);
  };
  async function action(fn: () => Promise<any>) {
    setBusy(true);
    setMessage("");
    try {
      const r = await fn();
      setMessage("요청이 접수되었습니다." + " " + (r.job_id || r.id || ""));
      bump((n) => n + 1);
      return r;
    } catch (e) {
      setMessage("요청 실패: " + (e as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (dataScope !== "seoul-history" && replay) setSession("");
  }, [selected, replay]);
  const p = pipeline.data || {};
  const experimental =
    row.prediction_scope === "experimental" ||
    row.mapping_status === "experimental" ||
    row.operational_approved === false;
  const persistence = row.prediction_method === "persistence";
  const context = history.data?.weather_context || {};
  const linkedRain = (history.data?.history || []).some((r: Row) =>
    number(r.rainfall_mm),
  );
  const weatherStation = (weather.data?.stations || []).find(
    (s: Row) => s.station_id === weatherSelected,
  );
  const active =
    busy ||
    p.advance_active ||
    p.active_jobs?.length > 0 ||
    p.replay_status === "initializing";
  async function advance(days: number) {
    return action(() =>
      post("/replays/" + encodeURIComponent(replay) + "/advance", { days }),
    );
  }
  useEffect(() => {
    if (
      !all ||
      view !== "operations" ||
      !replay ||
      active ||
      pipeline.loading ||
      pipeline.error ||
      advanceRef.current
    )
      return;
    if (
      p.latest_advance_job &&
      ["failed", "interrupted"].includes(p.latest_advance_job.status)
    ) {
      setAll(false);
      setMessage("자료 진행 실패·중단: " + (p.latest_advance_job.error || ""));
      return;
    }
    if (p.replay_status !== "ready" || !p.remaining_days) {
      setAll(false);
      return;
    }
    advanceRef.current = true;
    advance(Math.min(21, p.remaining_days))
      .then((r) => {
        if (!r) setAll(false);
      })
      .finally(() => {
        advanceRef.current = false;
      });
  }, [all, pipeline.data, active, view, replay]);
  async function start(scenario: string) {
    if (replay && (p.drift_demo ? "level_shift" : "historical") === scenario) {
      setMessage(
        "선택한 시연을 유지합니다. 처음부터는 별도 버튼을 사용하세요.",
      );
      return;
    }
    await createReplay(scenario);
  }
  async function createReplay(scenario: string) {
    if (!p.defaults) {
      setMessage("기본 자료가 준비되지 않았습니다.");
      return;
    }
    const d = p.defaults;
    const body: Row = {
      dataset_id: d.dataset_id,
      start_date: d.start_date,
      end_date: d.end_date,
      scenario,
    };
    if (scenario === "level_shift") {
      body.shift_start = d.shift_start;
      body.shift_amount = d.shift_amount;
    }
    const r = await action(() => post("/replays", body));
    if (r) {
      setSession(r.replay_id || r.id);
      setView("operations");
    }
  }
  const choose = (
    <select
      aria-label="관측소 선택"
      value={selected}
      onChange={(e) => setSelected(e.target.value)}
    >
      {choices.map((r) => (
        <option key={r.district_code} value={r.district_code}>
          {r.district_name} · {r.station_name}
        </option>
      ))}
    </select>
  );
  return (
    <div className={reduced ? "app reduced" : "app"}>
      <aside className="rail">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setView("overview");
          }}
        >
          <span className="brand-icon">
            <Waves size={23} />
          </span>
          <span>
            GROUNDWATCH<small>GROUNDWATER INTELLIGENCE</small>
          </span>
        </a>
        <div className="rail-caption">WORKSPACE / GROUNDWATCH</div>
        <nav>
          {(
            [
              ["overview", LayoutDashboard],
              ["detail", Layers3],
              ["operations", Activity],
            ] as const
          ).map(([v, Icon], i) => (
            <button
              key={v}
              className={view === v ? "nav active" : "nav"}
              onClick={() => {
                setView(v);
                setAll(false);
              }}
            >
              <Icon size={18} />
              <span>{titles[v]}</span>
              <small>0{i + 1}</small>
            </button>
          ))}
        </nav>

        <div className="rail-foot">
          <div className="orbit-logo">
            <Waves size={40} />
          </div>
          <p>
            지표 아래의 변화를
            <br />
            데이터로 이해합니다.
          </p>
          <span>GROUNDWATER · ONE NETWORK</span>
          <hr />
          <p className="muted">
            관측소 단위 예측입니다.
            <br />
            안전 등급을 제공하지 않습니다.
          </p>
          <a href="/docs" target="_blank" rel="noreferrer">
            API 명세 <ArrowUpRight size={14} />
          </a>
        </div>
      </aside>
      <ServiceGuide />
      <main>
        <header>
          <div className="breadcrumb">
            {dataScope === "seoul-history"
              ? "서울 구별 대표 관측소"
              : dataScope === "simulation" ? "전국 시뮬레이션" : "전국 추가 관측소"}{" "}
            <ChevronRight size={13} />
            <b>{titles[view]}</b>
          </div>
          <div className="header-tools">
            <GuideButton />
            <button
              className="icon-button"
              aria-label="새로고침"
              onClick={() => bump((n) => n + 1)}
            >
              <RefreshCw size={15} />
            </button>
            {(view === "overview" || view === "detail") && (
              <label>
                <input
                  type="checkbox"
                  checked={three}
                  onChange={(e) => setThree(e.target.checked)}
                />
                3D 보기
              </label>
            )}
            <label>
              <input
                type="checkbox"
                checked={reduced}
                onChange={(e) => setReduced(e.target.checked)}
              />
              동작 줄이기
            </label>
          </div>
        </header>
        <div className="content">
          <div className="heading">
            <div>
              <span className="eyebrow">GROUNDWATCH / OBSERVATORY</span>
              <h1>{titles[view]}</h1>
              <p>
                {dataScope === "seoul-history"
                  ? "서울 25개 구별 대표 관측소의 수위·강수와 모델 품질을 확인합니다."
                  : dataScope === "simulation" ? "합성 수위·강수로 전국 관제와 모델 운영 흐름을 검증합니다. 실제 관측값이 아닙니다." : "추가로 확보된 전국 실측 관측소의 수위·강수와 모델 품질을 확인합니다."}
              </p>
            </div>
            <label className="data-scope-control">
              자료 범위
              <select
                aria-label="자료 범위"
                value={dataScope}
                onChange={(e) => {
                  setDataScope(e.target.value);
                  setRegion("");
                  setSearch("");
                  setSelected("");
                  setAll(false);
                  setDate("");
                  setSelected(
                    e.target.value === "seoul-history" ? "11110" : "",
                  );
                  setSession("");
                }}
              >
                <option value="seoul-history">
                  서울 25개 구별 대표 관측소
                </option>
                <option value="observed">전국 추가 실측 관측소</option>
                <option value="simulation">전국 시뮬레이션 · 합성 자료</option>
              </select>
            </label>
            {legacySelected && (
              <div className="mode-panel">
                <label>
                  조회 모드
                  <select
                    value={mode}
                    onChange={(e) => {
                      setMode(e.target.value);
                      setDate("");
                      setAll(false);
                      if (e.target.value === "current") setSession("");
                    }}
                  >
                    <option value="current">오늘 기준 예측</option>
                    <option value="historical_replay">저장 자료로 검증</option>
                  </select>
                </label>
                {mode !== "current" && (
                  <>
                    <label>
                      검증 기록
                      <select
                        value={replay}
                        onChange={(e) => setSession(e.target.value)}
                      >
                        <option value="">기본 등록 자료</option>
                        {(replays.data?.replays || []).map((r: Row) => (
                          <option key={r.id} value={r.id}>
                            {r.scenario === "level_shift" ? "드리프트" : "기본"}{" "}
                            · {r.as_of} · {r.id.slice(0, 6)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      입력 기준일
                      <input
                        type="date"
                        value={date}
                        onChange={(e) => setDate(e.target.value)}
                        max={replay ? p.as_of : undefined}
                      />
                    </label>
                  </>
                )}
              </div>
            )}
          </div>
          <p className="footnote service-scope-note">
            {dataScope === "simulation" ? "전국 시뮬레이션: 생성된 수위·강수이며 현장 실측·지역 대표값이 아닙니다. 실측 모델·이력과 분리되고 운영 승격에 사용하지 않습니다." : dataScope === "observed"
              ? forecasts.loading
                ? "실측 자료 범위를 조회하고 있습니다."
                : `실측 이력이 확보된 ${rows.length}곳만 제공합니다. 위치만 있는 관측소는 표시하지 않습니다. 모델 사용 여부는 관측소마다 다르며 운영 미승인 실험입니다.`
              : "구별 대표 관측소의 수위이며 구 전체 평균이 아닙니다. 서울 확보 자료의 실제 날짜와 오늘 기준 준비 상태를 확인하세요. 저장 자료 검증·합성 시연은 조회 모드에서 구분합니다."}
          </p>
          <div className="provenance">
            <span className="dot" />
            {legacySelected
              ? "관측소 모델 · 저장 자료 모드"
              : "관측소 · 자료와 모델 준비 상태"}
            <SourceInfo row={row} />
          </div>
          {message && (
            <div className="notice" role="status">
              {message}
              <button onClick={() => setMessage("")} aria-label="알림 닫기">
                ×
              </button>
            </div>
          )}
          {(forecasts.error || pipeline.error) && (
            <div className="notice error" role="alert">
              조회 실패: {forecasts.error || pipeline.error}{" "}
              <button onClick={() => bump((n) => n + 1)}>다시 조회</button>
            </div>
          )}
          {pending && (
            <div className="notice">
              검증 기록 상태: {label(p.replay_status || "pending")} · 초기 모델
              준비 후 예측을 조회합니다.
            </div>
          )}
          {view === "overview" && (
            <>
              <div className="stats">
                <article>
                  <span>모델 준비 관측소</span>
                  <strong>
                    {forecasts.loading
                      ? "—"
                      : rows.filter((r) => r.model_ready).length}
                    <small> / {forecasts.loading ? "—" : rows.length}</small>
                  </strong>
                  <div className="track">
                    <i
                      style={{
                        width:
                          (rows.filter((r) => r.model_ready).length /
                            Math.max(1, rows.length)) *
                            100 +
                          "%",
                      }}
                    />
                  </div>
                </article>
                <article>
                  <span>{row.source_kind === "synthetic" ? "시뮬레이션 입력일" : "최근 실측일"}</span>
                  <strong className="date">{row.observed_date || "—"}</strong>
                  <small>선택 관측소의 마지막 확보 날짜</small>
                </article>
                <article>
                  <span>예측 대상일</span>
                  <strong className="date">
                    {row.forecast_date || "미준비"}
                  </strong>
                  <small>
                    {persistence
                      ? "직전 관측값 기준(persistence)"
                      : "연속 20일 입력 → 입력 기준일의 1일 후 수위"}
                  </small>
                </article>
              </div>
              <div className="overview-grid">
                <section className="panel map-panel">
                  <div className="panel-top">
                    <div>
                      <span className="eyebrow">SPATIAL OVERVIEW</span>
                      <h2>
                        {dataScope === "observed"
                          ? "실측 관측소 · 전국 위치"
                          : dataScope === "simulation" ? "시뮬레이션 관측소 · 전국 위치"
                          : "서울 25개 구별 대표 관측소"}
                      </h2>
                    </div>
                    <span className="pill">
                      <Box size={13} /> {three ? "3D" : "목록"} VIEW
                    </span>
                  </div>
                  <div className="network-map-tools">
                    <label>
                      지역
                      <select
                        value={region}
                        onChange={(e) => {
                          setRegion(e.target.value);
                        }}
                      >
                        <option value="">
                          {dataScope === "seoul-history" ? "서울 전체" : "전국"}
                        </option>
                        {[
                          ...new Set(
                            rows
                              .map((r) => r.region_code || r.district_name)
                              .filter(Boolean),
                          ),
                        ]
                          .sort()
                          .map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                      </select>
                    </label>
                    {three && dataScope === "observed" && (
                      <label>
                        지도 정보
                        <select
                          value={mapLayer}
                          onChange={(e) => setMapLayer(e.target.value)}
                        >
                          <option value="groundwater">확보 실측 관측소</option>
                          <option value="rainfall">
                            실측 관측소 + 전국 강수
                          </option>
                        </select>
                      </label>
                    )}
                    {three &&
                      dataScope === "observed" &&
                      mapLayer === "rainfall" && (
                        <>
                          <label>
                            강수 원천
                            <select
                              value={weatherSource}
                              onChange={(e) => {
                                setWeatherSource(e.target.value);
                                setWeatherDate("");
                                setWeatherSelected("");
                              }}
                            >
                              <option value="aws-daily">지상·AWS 일자료</option>
                              <option value="asos">ASOS 일자료</option>
                            </select>
                          </label>
                          <label>
                            강수 날짜
                            <select
                              value={weatherDate || weather.data?.date || ""}
                              onChange={(e) => setWeatherDate(e.target.value)}
                            >
                              {weather.data?.available_dates.map(
                                (d: string) => (
                                  <option key={d} value={d}>
                                    {d}
                                  </option>
                                ),
                              )}
                            </select>
                          </label>
                        </>
                      )}
                  </div>
                  {three &&
                    dataScope === "observed" &&
                    mapLayer === "rainfall" && (
                      <p className="footnote">
                        일강수 실측 {weather.data?.counts?.observed ?? "—"} /{" "}
                        {weather.data?.counts?.stations ?? "—"} 지점 · 기상지점
                        선택은 지하수 관측소 선택과 별개입니다. {weather.error}
                      </p>
                    )}
                  {three &&
                    dataScope === "observed" &&
                    mapLayer === "rainfall" &&
                    weatherStation && (
                      <div className="weather-map-selection" role="status">
                        <strong>선택 기상지점 · {weatherStation.name}</strong>
                        <span>
                          {weather.data?.date} ·{" "}
                          {fmt(weatherStation.rainfall_mm)} mm
                        </span>
                        <small>
                          지하수 관측소 선택과 별개의 강수 관측값입니다.
                        </small>
                      </div>
                    )}
                  {three && dataScope === "seoul-history" ? (
                    <Suspense
                      fallback={
                        <div className="empty">
                          서울 구별 지도를 준비합니다.
                        </div>
                      }
                    >
                      <Scene rows={choices} />
                    </Suspense>
                  ) : three && dataScope !== "seoul-history" ? (
                    <Suspense
                      fallback={
                        <div className="empty">3D 지도를 준비합니다.</div>
                      }
                    >
                      <NationalRainScene
                        stations={
                          dataScope === "observed" && mapLayer === "rainfall"
                            ? weather.data?.stations || []
                            : []
                        }
                        selected={weatherSelected}
                        onSelect={setWeatherSelected}
                        boundariesUrl="/api/v2/rainfall/boundary"
                        groundStations={
                          choices
                            .filter(
                              (r) => number(r.latitude) && number(r.longitude),
                            )
                            .map((r) => ({ ...r, name: r.station_name })) as any
                        }
                        groundSelected={selected}
                        onGroundSelect={setSelected}
                        groundwaterOnly={dataScope === "simulation" || mapLayer !== "rainfall"}
                        simulation={dataScope === "simulation"}
                      />
                    </Suspense>
                  ) : (
                    <div className="district-grid">
                      {choices.map((r) => (
                        <button
                          className={
                            selected === r.district_code ? "selected" : ""
                          }
                          key={r.district_code}
                          onClick={() => setSelected(r.district_code)}
                        >
                          {dataScope === "seoul-history"
                            ? r.district_name
                            : r.station_name || r.district_name}
                          <small>{fmt(r.prediction)}</small>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="map-credit">
                    {dataScope === "seoul-history"
                      ? "서울 구 경계는 구 선택용입니다. 구별 대표 관측소 수위이며 구 전체 평균·위험 등급이 아닙니다. 경계 높이는 수위가 아닙니다."
                      : "Natural Earth 위치 참고 경계 · 공식 행정경계 아님. 확인된 좌표만 표시하며 기상·지하수 관측소를 자동 연결하지 않습니다."}
                  </div>
                </section>
                <section className="panel station-card">
                  <span className="eyebrow">SELECTED STATION</span>
                  <div className="station-title">
                    <span className="station-number">
                      {row.station_id || "선택 없음"}
                    </span>
                    <h2>{row.district_name || "관측소 선택"}</h2>
                    <p>{row.station_name || "관측소 정보 없음"}</p>
                  </div>
                  <div className="hero-value">
                    <span>
                      {number(row.prediction)
                        ? predictionLabel(row)
                        : measurementLabel(row)}
                      {experimental ? " · 실험 검증" : ""}
                    </span>
                    <strong>
                      {fmt(
                        number(row.prediction)
                          ? row.prediction
                          : (row.latest_actual_level ??
                              row.latest_comparison?.actual),
                      )}
                    </strong>
                    <small>
                      {row.unit ||
                        (number(row.prediction) ||
                        number(row.latest_actual_level) ||
                        number(row.latest_comparison?.actual)
                          ? "단위 미확인"
                          : "—")}
                    </small>
                  </div>
                  {persistence && (
                    <p className="footnote">
                      직전 관측값 기준(persistence)입니다. LSTM 모델 예측이나
                      발행·승격 결과가 아닙니다.
                    </p>
                  )}
                  {experimental && (
                    <p className="footnote">
                      {row.source_kind === "synthetic" ? "합성 시뮬레이션의 모델 결과입니다. 실제 관측 정확도나 운영 승격을 뜻하지 않습니다." : "실험용 예측입니다. 운영 승인과 자동 승격은 별도이며 현재 허용하지 않습니다."}
                    </p>
                  )}
                  <dl>
                    <div>
                      <dt>예측 대상일</dt>
                      <dd>{row.forecast_date || "—"}</dd>
                    </div>
                    <div>
                      <dt>자료 · 예측</dt>
                      <dd>
                        <Badge status={stationDataStatus(row)} />
                      </dd>
                    </div>
                    <div>
                      <dt>현재 모델</dt>
                      <dd>
                        {row.model_version ? "v" + row.model_version : "미준비"}
                      </dd>
                    </div>
                  </dl>
                  <button
                    className="primary wide"
                    disabled={!row.station_id}
                    onClick={() => setView("detail")}
                  >
                    관측소 상세 보기 <ArrowUpRight size={17} />
                  </button>
                  <p className="footnote">
                    구 전체 평균이나 싱크홀 발생 확률이 아닙니다.
                  </p>
                </section>
              </div>
              <section className="panel">
                <div className="panel-top">
                  <div>
                    <span className="eyebrow">STATION DIRECTORY</span>
                    <h2>
                      관측소 목록 <small>{choices.length}</small>
                    </h2>
                  </div>
                  <input
                    className="search"
                    aria-label="지역 또는 관측소 검색"
                    placeholder="지역 · 관측소 검색"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>지역 / 관측소</th>
                        <th>최근 입력 · 예측 비교</th>
                        <th>예측 대상일</th>
                        <th>예측 / 비교 수위</th>
                        <th>자료 · 예측 상태</th>
                        <th>오차 평가</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {choices
                        .filter((r) =>
                          (r.district_name + " " + r.station_name).includes(
                            search,
                          ),
                        )
                        .slice(0, directoryLimit)
                        .map((r) => (
                          <tr
                            className={
                              selected === r.district_code ? "selected" : ""
                            }
                            key={r.district_code}
                          >
                            <td>
                              <button
                                className="text-button"
                                onClick={() => setSelected(r.district_code)}
                              >
                                {r.district_name}
                              </button>
                              <small>{r.station_name}</small>
                            </td>
                            <td>
                              <span
                                className={comparison(
                                  r.latest_comparison?.actual,
                                  r.latest_comparison?.prediction,
                                )}
                              >
                                {fmt(r.latest_comparison?.actual)}
                              </span>
                              <small>
                                저장 예측 {fmt(r.latest_comparison?.prediction)}
                              </small>
                            </td>
                            <td>{r.forecast_date || "—"}</td>
                            <td className="numeric">
                              {fmt(r.prediction)} <small>{r.unit}</small>
                              {r.prediction_method === "persistence" && (
                                <small>직전 관측값 기준(persistence)</small>
                              )}
                            </td>
                            <td>
                              <Badge
                                status={
                                  stationDataStatus(r)
                                }
                              />
                              <small>
                                {label(r.model_status || "not_ready")}
                                {r.mapping_status
                                  ? " · " + label(r.mapping_status)
                                  : ""}
                              </small>
                            </td>
                            <td>
                              <Badge
                                status={
                                  r.model_evaluation_status ||
                                  (r.model_status === "not_ready"
                                    ? "model_not_ready"
                                    : "evaluation_pending")
                                }
                              />
                            </td>
                            <td>
                              <button
                                className="icon-button"
                                aria-label={r.district_name + " 상세 보기"}
                                onClick={() => {
                                  setSelected(r.district_code);
                                  setView("detail");
                                }}
                              >
                                <ArrowUpRight size={17} />
                              </button>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  {choices.filter((r) =>
                    (r.district_name + " " + r.station_name).includes(search),
                  ).length > directoryLimit && (
                    <button onClick={() => setDirectoryLimit((n) => n + 100)}>
                      관측소 100개 더 보기
                    </button>
                  )}
                  {!choices.length && (
                    <div className="empty">
                      {forecasts.loading
                        ? "자료를 조회하고 있습니다."
                        : "등록된 관측소 자료가 없습니다."}
                    </div>
                  )}
                </div>
                <p className="footnote">
                  같은 날짜 저장 예측보다 입력이 높으면 빨강, 낮으면 파랑입니다.
                  위험 등급이나 드리프트 경보가 아닙니다.
                </p>
              </section>
            </>
          )}
          {view === "detail" && (
            <>
              <div className="section-heading">
                <h2>
                  {row.district_name}{" "}
                  <span className="muted">/ {row.station_name}</span>
                </h2>
                {choose}
              </div>
              <div className="overview-grid">
                <section className="panel">
                  <div className="panel-top">
                    <h2>
                      {legacySelected
                        ? "관측정 · 수위 개념도"
                        : dataScope === "simulation" ? "시뮬레이션 · 수위 개념 비교도" : "관측소 · 수위 비교도"}
                    </h2>
                    <span className="pill">
                      {three
                        ? legacySelected
                          ? "3D CONCEPT"
                          : "3D WATER LEVEL"
                        : "2D WATER LEVEL"}
                    </span>
                  </div>
                  {forecasts.loading ? (
                    <div className="empty">
                      관측소 자료를 조회하고 있습니다.
                    </div>
                  ) : three ? (
                    <Suspense
                      fallback={
                        <div className="empty">수위 시각화를 준비합니다.</div>
                      }
                    >
                      {legacySelected && String(row.unit).includes("gl") ? (
                        <Scene rows={[row]} section />
                      ) : (
                        <WaterLevelScene row={row} />
                      )}
                    </Suspense>
                  ) : (
                    <WaterLevelDiagram row={row} />
                  )}
                </section>
                <section className="panel station-card">
                  <span className="eyebrow">
                    {persistence
                      ? "PERSISTENCE / 비교 기준"
                      : experimental
                        ? "실험 수위 추정·예측 / 운영 미승인"
                        : predictionLabel(row)}
                  </span>
                  <div className="hero-value">
                    <strong>{fmt(row.prediction)}</strong>
                    <small>
                      {row.unit ||
                        (number(row.prediction) ||
                        number(row.latest_actual_level) ||
                        number(row.latest_comparison?.actual)
                          ? "단위 미확인"
                          : "—")}
                    </small>
                  </div>
                  {persistence && (
                    <p className="footnote">
                      직전 관측값 기준(persistence)입니다. LSTM 모델 예측이나
                      발행·승격 결과가 아닙니다.
                    </p>
                  )}
                  {experimental && (
                    <p className="footnote">
                      {row.source_kind === "synthetic" ? "합성 시뮬레이션의 모델 결과입니다. 실제 관측 정확도나 운영 승격을 뜻하지 않습니다." : "실험용 예측입니다. 운영 승인과 자동 승격은 별도이며 현재 허용하지 않습니다."}
                    </p>
                  )}
                  <dl>
                    <div>
                      <dt>예측 입력 종료일</dt>
                      <dd>
                        {row.prediction_input_end_date ||
                          row.input_end_date ||
                          "—"}
                      </dd>
                    </div>
                    <div>
                      <dt>예측 대상일</dt>
                      <dd>{row.forecast_date || "—"}</dd>
                    </div>
                    <div>
                      <dt>최근 입력</dt>
                      <dd
                        className={comparison(
                          row.latest_comparison?.actual,
                          row.latest_comparison?.prediction,
                        )}
                      >
                        {fmt(row.latest_comparison?.actual)}
                      </dd>
                    </div>
                    <div>
                      <dt>자료 출처</dt>
                      <dd>{sourceLabel(row.source_kind)}</dd>
                    </div>
                    <div>
                      <dt>모델 버전</dt>
                      <dd>{row.model_version || "미준비"}</dd>
                    </div>
                  </dl>
                  <Badge status={stationDataStatus(row)} />
                  <p className="footnote">
                    {row.reason ||
                      "관측소별 수위 기준과 원자료의 부호를 유지합니다. 예측 대상일의 정답 확보 전에는 예측을 평가하지 않습니다."}
                  </p>
                  <details>
                    <summary>자료·모델 근거</summary>
                    <Json value={row} />
                  </details>
                </section>
              </div>
              <section className="panel">
                <div className="panel-top">
                  <h2>{measurementLabel(row)}와 {predictionLabel(row)}</h2>
                  <select
                    aria-label="차트 표시 기간"
                    value={range}
                    onChange={(e) => setRange(Number(e.target.value))}
                  >
                    {[30, 90, 180].map((n) => (
                      <option key={n} value={n}>
                        최근 {n}일
                      </option>
                    ))}
                  </select>
                </div>
                <p className="legend">
                  <span>● 입력 자료</span>
                  <span className="gold">┄ 저장 예측</span>
                  <span className="above">● 예측보다 높음</span>
                  <span className="below">● 예측보다 낮음</span>
                </p>
                {history.error ? (
                  <div role="alert">이력 조회 실패: {history.error}</div>
                ) : history.loading ? (
                  <div className="empty">이력을 조회합니다.</div>
                ) : (
                  <Chart rows={(history.data?.history || []).slice(-range)} periods={context.rainy_period || []} />
                )}
                <p className="footnote">
                  단위 {history.data?.unit || row.unit || "미확인"} · 기준{" "}
                  {row.level_reference || row.reference_status || "확인 필요"} ·
                  결측값을 이어 그리지 않습니다. {dataScope === "simulation" ? "합성 시나리오이며 실제 관측·공식 장마 판정이 아닙니다." : "금색 배경은 공식 장마 기간(사후 평가용)이며 해당 구간이 있을 때만 표시합니다."}
                </p>
              </section>
              <section className="panel">
                <h2>
                  {dataScope === "simulation" ? "시뮬레이션 일 강수량" : "일 강수량"}{" "}
                  <small>
                    mm ·{" "}
                    {history.loading
                      ? "자료 조회 중"
                      : linkedRain
                        ? "관측소 입력 자료"
                        : "기상 참고 자료"}
                  </small>
                </h2>
                {history.loading ? (
                  <div className="empty">강수 이력을 조회하고 있습니다.</div>
                ) : history.error ? (
                  <div role="alert">강수 이력 조회 실패: {history.error}</div>
                ) : (
                  <Chart
                    rows={(linkedRain
                      ? history.data?.history || []
                      : weatherHistory.data?.history || []
                    ).slice(-range)}
                    periods={linkedRain ? context.rainy_period || [] : []}
                    rain
                  />
                )}
                <p className="footnote">
                  강수 연결:{" "}
                  {history.loading
                    ? "조회 중"
                    : (context.mapping_status
                        ? label(context.mapping_status)
                        : "") ||
                      (legacySelected ? "서울 원천 날짜 결합" : "미승인")}
                  .{" "}
                  {row.source_kind === "synthetic" ? "합성 시나리오 입력입니다. 실제 기상 관측소 연결이 아닙니다." : experimental
                    ? "실험용 연결이며 운영 승인 전입니다."
                    : context.note || ""}
                </p>
                {!linkedRain && !history.loading && !history.error && (
                  <>
                    <label>
                      참고 기상 관측소 (모델 입력 미연결)
                      <select
                        value={weatherSelected}
                        onChange={(e) => setWeatherSelected(e.target.value)}
                      >
                        <option value="">기상지점 선택</option>
                        {(weather.data?.stations || []).map((s: Row) => (
                          <option key={s.station_id} value={s.station_id}>
                            {s.name} · {s.station_id}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="footnote">
                      {weatherStation?.name || "선택 없음"} · 지도에서 선택한
                      기상지점을 참고로 조회합니다. 강수 매핑 승인이나 학습 입력
                      연결을 뜻하지 않습니다.
                    </p>
                  </>
                )}
                <details>
                  <summary>{row.source_kind === "synthetic" ? "장마 시나리오 · 합성 평가 기준" : "공식 장마 기간 · 과거 평가 기준"}</summary>
                  <p className="footnote">
                    {row.source_kind === "synthetic" ? "합성 자료를 평가하기 위해 생성한 장마 시나리오입니다. 공식 장마 통계나 실시간 판정이 아닙니다." : "장마 기간은 사후 확정된 통계이며 실시간 장마 판정이 아닙니다."}
                  </p>
                  {Array.isArray(context.rainy_period) &&
                  context.rainy_period.length ? (
                    <>
                      <p className="footnote">
                        {row.source_kind === "synthetic" ? "합성 장마·강수 시나리오 · 시뮬레이션 평가용" : legacySelected ? "서울 기상지점 108 장마 통계 · 강수 입력 교체 없음" : `공식 기상지점 ${context.source_station_id} · 매핑 ${label(context.mapping_status)}`} · 과거 평가용
                      </p>
                      {context.rainy_period.slice(-5).map((r: Row) => (
                        <p
                          key={r.id || r.year + r.region_code}
                          className="footnote"
                        >
                          {r.year}년 · {r.start_date} — {r.end_date}
                        </p>
                      ))}
                    </>
                  ) : (
                    <p className="footnote">
                      {history.loading
                        ? "장마 기간 연결을 조회하고 있습니다."
                        : history.error
                          ? "이력 조회 실패로 장마 기간을 확인할 수 없습니다."
                          : "선택 관측소에 연결된 확인된 장마 기간이 없습니다."}
                    </p>
                  )}
                </details>
              </section>
            </>
          )}
          {view === "operations" && (
            <>
              {legacySelected ? (
                <section className="panel">
                  <div className="panel-top">
                    <div>
                      <span className="eyebrow">MODEL LIFECYCLE</span>
                      <h2>예측 모델 품질 현황</h2>
                    </div>
                    {choose}
                  </div>
                  <div className="scenario">
                    <div>
                      <h3>
                        {replay
                          ? p.drift_demo
                            ? "드리프트 시연"
                            : "기본 상황 시연"
                          : "선택된 시연 없음"}
                      </h3>
                      <p>
                        기준일 {p.as_of || "—"} · 남은 자료{" "}
                        {p.remaining_days ?? "—"}일 · {label(p.replay_status)}
                      </p>
                    </div>
                    <div className="button-row">
                      <button
                        disabled={!!active || !p.defaults}
                        aria-pressed={!!replay && !p.drift_demo}
                        onClick={() => start("historical")}
                      >
                        기본 상황 선택
                      </button>
                      <button
                        disabled={!!active || !p.defaults}
                        aria-pressed={!!replay && !!p.drift_demo}
                        onClick={() => start("level_shift")}
                      >
                        드리프트 시연 선택
                      </button>
                      <button
                        disabled={!!active || !replay}
                        onClick={() =>
                          createReplay(
                            p.drift_demo ? "level_shift" : "historical",
                          )
                        }
                      >
                        선택한 상황으로 처음부터
                      </button>
                    </div>
                  </div>
                  <p className="footnote">
                    {p.drift_demo
                      ? `드리프트 시연: ${p.drift_demo.shift_start}부터 수위 +${p.drift_demo.shift_amount} 적용 (${row.unit || row.level_unit || "자료의 수위 단위"}).`
                      : replay
                        ? "기본 상황은 추가 수위 변화 없이 저장 자료를 공개합니다. 기본 자료에서도 오차 경보가 발생할 수 있습니다."
                        : `새 드리프트 시연 설정: ${p.defaults?.shift_start || "자료 준비 후 확인"}부터 +${p.defaults?.shift_amount ?? "—"} 적용.`}{" "}
                    원본은 보존합니다. 정답 21일 → 연속 2회 초과 → 재학습 → 후속
                    정답 30일 평가 후 기준 통과 시 교체합니다. 21일 진행만으로
                    경보·교체를 보장하지 않습니다.
                  </p>
                  <div className="button-row">
                    <button
                      disabled={
                        !!active ||
                        !replay ||
                        p.replay_status !== "ready" ||
                        !p.remaining_days
                      }
                      onClick={() => advance(1)}
                    >
                      저장 자료 1일 진행
                    </button>
                    <button
                      disabled={
                        !!active ||
                        !replay ||
                        p.replay_status !== "ready" ||
                        !p.remaining_days
                      }
                      onClick={() => advance(Math.min(21, p.remaining_days))}
                    >
                      저장 자료 21일 진행
                    </button>
                    <button
                      disabled={
                        !!active ||
                        !replay ||
                        p.replay_status !== "ready" ||
                        !p.remaining_days ||
                        all
                      }
                      onClick={() => setAll(true)}
                    >
                      남은 자료 끝까지 진행
                    </button>
                    {all && (
                      <button onClick={() => setAll(false)}>
                        추가 진행 중지
                      </button>
                    )}
                  </div>
                  {!!p.active_jobs?.length && (
                    <div className="notice" role="status">
                      {p.active_jobs
                        .map(
                          (j: Row) =>
                            `${j.kind}: ${label(j.status)} ${j.result?.processed ?? ""}/${j.result?.total ?? ""}`,
                        )
                        .join(" · ")}
                    </div>
                  )}
                  <ol className="pipeline">
                    {(Array.isArray(p.stages) ? p.stages : []).map(
                      (s: Row, i: number) => (
                        <li key={s.key} className={s.status}>
                          <div className="stage-index">
                            {String(i + 1).padStart(2, "0")}
                          </div>
                          <h3>{s.title}</h3>
                          <Badge status={s.status} />
                          <p>{s.detail}</p>
                        </li>
                      ),
                    )}
                  </ol>
                  <p className="footnote">{p.note}</p>
                  <details>
                    <summary>감지 · 작업 · 평가 기록</summary>
                    <Json value={p.log} />
                  </details>
                  <details>
                    <summary>후보 모델 상세 평가</summary>
                    <CandidateEvaluation
                      evaluation={p.evaluation}
                      unit={row.unit}
                    />
                  </details>
                </section>
              ) : (
                <NationalModelPanel
                  key={selected}
                  row={row}
                  pipeline={p}
                  refresh={() => bump((n) => n + 1)}
                />
              )}
              <SeasonalEvaluation
                value={p.seasonal_evaluation}
                unit={row.unit}
              />
              {legacySelected ? (
                <Operations
                  scope={suffix}
                  revision={revision}
                  busy={busy || !!active}
                  action={action}
                  choices={rows
                    .filter((r) => r.legacy_district_code)
                    .map((r) => ({
                      ...r,
                      district_code: r.legacy_district_code,
                    }))}
                  setSession={setSession}
                />
              ) : null}
            </>
          )}
          <footer>
            <span>
              GROUNDWATCH <b>지하수 관측</b>
            </span>
            <span>관측 → 예측 → 품질 감시</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
function NationalModelPanel({
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
    <section className="panel">
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
        <button
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
        </button>
        <button
          disabled={
            running || !row.capabilities?.predict || !row.operation_station_id
          }
          onClick={() => void submit("prediction")}
        >
          검증 모델 예측 요청
        </button>
        <button disabled>운영 승격 미승인</button>
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
    </section>
  );
}
function SeasonalEvaluation({
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
    <section className="panel">
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
    </section>
  );
}
function historyReplace(url: URL) {
  window.history.replaceState(null, "", url);
}
function Operations({
  scope,
  revision,
  busy,
  action,
  choices,
  setSession,
}: {
  scope: string;
  revision: number;
  busy: boolean;
  action: (fn: () => Promise<any>) => Promise<any>;
  choices: Row[];
  setSession: (id: string) => void;
}) {
  const query = scope ? "?" + scope : "";
  const jobs = useResource("/jobs" + query, 3000, revision),
    models = useResource("/models" + query, 3000, revision),
    events = useResource("/events" + query, 3000, revision),
    datasets = useResource("/datasets", 3000, revision),
    runtime = useResource("/health/runtime", 30000, revision),
    metrics = useResource("/metrics/summary", 30000, revision);
  const [scenario, setScenario] = useState("historical");
  const datasetSelect = (
    <label>
      등록 데이터
      <select name="dataset_id" required defaultValue="">
        <option value="" disabled>
          자료 선택
        </option>
        {(datasets.data?.datasets || []).map((d: Row) => (
          <option value={d.id} key={d.id} disabled={d.status !== "ready"}>
            {d.id.slice(0, 12)} · {label(d.source_kind)} · {label(d.status)}
          </option>
        ))}
      </select>
    </label>
  );
  async function submit(e: React.FormEvent<HTMLFormElement>, kind: string) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    await action(async () => {
      if (kind === "upload")
        return request("/datasets", { method: "POST", body: data });
      const body: Row = Object.fromEntries(data.entries());
      for (const k of Object.keys(body))
        if (
          body[k] === "" ||
          (body.scenario === "historical" && k.startsWith("shift_"))
        )
          delete body[k];
      if (body.shift_amount) body.shift_amount = Number(body.shift_amount);
      const r = await post(kind === "train" ? "/jobs/train" : "/replays", body);
      if (kind === "replay") setSession(r.replay_id || r.id);
      return r;
    });
  }
  return (
    <>
      <section className="panel">
        <h2>최근 알림</h2>
        {events.error && <p role="alert">{events.error}</p>}
        {(events.data?.events || []).map((e: Row) => (
          <div className="record" key={e.id}>
            <div>
              <strong>
                {e.district_code || "공통"} · {e.kind}
              </strong>
              <p>{e.message}</p>
              <small>{e.created_at}</small>
            </div>
            <Badge status={e.status} />
            {["OPEN", "ACKNOWLEDGED"].includes(
              String(e.status).toUpperCase(),
            ) && (
              <div className="button-row">
                {(String(e.status).toUpperCase() === "OPEN"
                  ? ["ack", "resolve"]
                  : ["resolve"]
                ).map((a) => (
                  <button
                    key={a}
                    disabled={busy}
                    onClick={() => {
                      const reason = prompt(
                        a === "ack"
                          ? "확인 담당자와 내용을 입력하세요."
                          : "조치 내용을 입력하세요.",
                      );
                      if (reason?.trim())
                        action(() =>
                          post("/events/" + e.id + "/" + a, {
                            reason: reason.trim(),
                            note: reason.trim(),
                          }),
                        );
                    }}
                  >
                    {a === "ack" ? "확인 중" : "조치 완료"}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {!events.data?.events?.length && (
          <p className="muted">등록된 알림이 없습니다.</p>
        )}
      </section>
      <div className="two-col">
        <section className="panel">
          <h2>학습 작업</h2>
          {jobs.error && <p role="alert">{jobs.error}</p>}
          {(jobs.data?.jobs || []).map((j: Row) => (
            <details key={j.id}>
              <summary>
                {j.kind} · {label(j.status)} · {j.id.slice(0, 10)}
              </summary>
              <Json value={j} />
              {["failed", "interrupted"].includes(j.status) && (
                <button
                  disabled={busy}
                  onClick={() =>
                    action(() => post("/jobs/" + j.id + "/retry", {}))
                  }
                >
                  다시 요청
                </button>
              )}
            </details>
          ))}
          {!jobs.data?.jobs?.length && (
            <p className="muted">등록된 작업이 없습니다.</p>
          )}
        </section>
        <section className="panel">
          <h2>현재 모델 · 이전 모델 복귀</h2>
          {models.error && <p role="alert">{models.error}</p>}
          {(models.data?.models || []).map((m: Row) => (
            <details key={m.district_code || m.name}>
              <summary>
                {m.district_name || m.district_code} · v
                {m.model_version || m.version || "—"}
              </summary>
              <Json value={m} />
              <button
                disabled={busy}
                onClick={() =>
                  action(() =>
                    post("/models/" + m.district_code + "/rollback" + query, {
                      reason: "화면에서 이전 모델 복귀 요청",
                    }),
                  )
                }
              >
                이전 검증 모델로 복귀
              </button>
            </details>
          ))}
        </section>
      </div>
      <section className="panel">
        <details>
          <summary>서버 진단과 요청 지표</summary>
          <CollectionStatus revision={revision} />
          {runtime.error || metrics.error ? (
            <p>{runtime.error || metrics.error}</p>
          ) : (
            <>
              <Json value={runtime.data} />
              <Json value={metrics.data} />
            </>
          )}
        </details>
        <details>
          <summary>관리자용 · 자료 등록과 학습</summary>
          <p>
            등록하면 기본 조회 자료가 변경됩니다. 학습 접수는 완료를 뜻하지
            않습니다.
          </p>
          <div className="two-col">
            <form onSubmit={(e) => submit(e, "upload")}>
              <h3>검증 자료 등록</h3>
              <label>
                관측자료 CSV
                <input type="file" name="file" accept=".csv" required />
              </label>
              <label>
                관측소·단위 manifest JSON
                <input type="file" name="manifest" accept=".json" required />
              </label>
              <button className="primary" disabled={busy}>
                자료 검증 · 등록
              </button>
            </form>
            <form onSubmit={(e) => submit(e, "train")}>
              <h3>초기 학습 요청</h3>
              {datasetSelect}
              <label>
                대상 자치구
                <select name="district_code">
                  <option value="">전체 관측소</option>
                  {choices.map((r) => (
                    <option key={r.district_code} value={r.district_code}>
                      {r.district_name}
                    </option>
                  ))}
                </select>
              </label>
              <button disabled={busy}>학습 작업 등록</button>
            </form>
          </div>
          <Json value={datasets.data || datasets.error} />
        </details>
        <details>
          <summary>관리자용 · 시연 기간 설정</summary>
          <form onSubmit={(e) => submit(e, "replay")}>
            {datasetSelect}
            <div className="two-col">
              <label>
                시작일
                <input type="date" name="start_date" required />
              </label>
              <label>
                종료일
                <input type="date" name="end_date" />
              </label>
            </div>
            <label>
              시나리오
              <select
                name="scenario"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              >
                <option value="historical">등록 자료 그대로</option>
                <option value="level_shift">수위 변화 상황</option>
              </select>
            </label>
            {scenario === "level_shift" && (
              <div className="two-col">
                <label>
                  변화 시작일
                  <input name="shift_start" type="date" required />
                </label>
                <label>
                  수위 변화량
                  <input
                    name="shift_amount"
                    type="number"
                    step="any"
                    required
                  />
                </label>
              </div>
            )}
            <button disabled={busy}>설정한 자료로 시연 시작</button>
          </form>
        </details>
      </section>
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Provider>
      <App />
    </Provider>
  </React.StrictMode>,
);
