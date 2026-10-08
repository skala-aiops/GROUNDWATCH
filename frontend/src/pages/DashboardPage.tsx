import Panel from "@/components/molecules/Panel";
import { Button } from "@/components/atoms/button";
import { Input } from "@/components/atoms/input";
import { NativeSelect } from "@/components/atoms/native-select";
import DashboardLayout from "../components/templates/DashboardLayout";
import { nativeApiStation } from "../utils/stations";
import React, { Suspense, lazy, useEffect, useRef, useState } from "react";
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
} from "../store/dashboard";
import { chartSegments, comparison } from "../utils/chart";
import { initialStationId, serviceStations, stationDataStatus, measurementLabel, selectedNetworkStationId, predictionLabel, confirmedUnit } from "../utils/stations";
import { fmt, label, number } from "../utils/format";
import { post, request } from "../api/client";
import { useResource } from "../hooks/useResource";
import { type Row } from "../types/domain";
import "../styles/global.css";
import { SourceInfo, CollectionStatus, sourceLabel } from "../components/organisms/data/SourceInfo";
import ServiceGuide, { GuideButton } from "../components/organisms/guide/ServiceGuide";
import WaterLevelDiagram from "../components/organisms/water/WaterLevelDiagram";
import { CandidateEvaluation, RainfallChart, RainyBands } from "../components/organisms/charts/EvaluationCharts";
import "../styles/national.css";
const NationalRainScene = lazy(() => import("../components/organisms/maps/NationalRainScene"));
const Scene = lazy(() => import("../components/organisms/maps/Scene"));
const WaterLevelScene = lazy(() => import("../components/organisms/water/WaterLevelScene"));
const titles = {
  overview: "관측소 현황",
  detail: "관측소 상세",
  operations: "모델 관리 · 시연",
};
import Badge from "../components/molecules/Badge";
import Json from "../components/molecules/Json";
import Chart from "../components/organisms/charts/WaterLevelChart";
import NationalModelPanel from "../features/models/NationalModelPanel";
import SeasonalEvaluation from "../features/models/SeasonalEvaluation";
import Operations from "../features/models/Operations";
export default function DashboardPage() {
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
    mode === "api" && dataScope === "seoul-history" ? "/api-observations" : "/api/v2/network/stations?" + fq,
    30000,
    revision,
  );
  const replays = useResource("/replays", 3000, revision);
  const rows: Row[] = serviceStations(
    forecasts.data?.stations || (forecasts.data?.forecasts || []).map(nativeApiStation),
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
    mode === "api" && dataScope === "seoul-history" && networkSelected ? "/api-observations/" + networkSelected.replace(/^seoul:/, "") + "/pipeline" : networkSelected
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
      ? mode === "api" && dataScope === "seoul-history" ? "/api-observations/" + selected.replace(/^seoul:/, "") + "/history" : "/api/v2/network/stations/" +
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
  const collectionJobs = useResource(mode === "api" && view === "operations" ? "/api-observations/collection-jobs" : null, 3000, revision);
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
    <NativeSelect
      aria-label="관측소 선택"
      value={selected}
      onChange={(e) => setSelected(e.target.value)}
    >
      {choices.map((r) => (
        <option key={r.district_code} value={r.district_code}>
          {r.district_name} · {r.station_name}
        </option>
      ))}
    </NativeSelect>
  );
  return (
    <DashboardLayout reduced={reduced}>
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
            <Button
              key={v}
              variant={view === v ? "default" : "ghost"}
              className={view === v ? "nav active" : "nav"}
              onClick={() => {
                setView(v);
                setAll(false);
              }}
            >
              <Icon size={18} />
              <span>{titles[v]}</span>
              <small>0{i + 1}</small>
            </Button>
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
            <Button
              className="icon-button"
              aria-label="새로고침"
              onClick={() => bump((n) => n + 1)}
            >
              <RefreshCw size={15} />
            </Button>
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
              <NativeSelect
                aria-label="자료 범위"
                value={dataScope}
                onChange={(e) => {
                  setDataScope(e.target.value);
                  setMode("current");
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
              </NativeSelect>
            </label>
            {legacySelected && (
              <div className="mode-panel">
                <label>
                  조회 모드
                  <NativeSelect
                    value={mode}
                    onChange={(e) => {
                      if (e.target.value !== "historical_replay") setSession("");
                      setMode(e.target.value);
                      setDate("");
                      setAll(false);
                    }}
                  >
                    <option value="current">오늘 기준 예측</option>
                    <option value="api">서울 실제 API 관측·예측 · 원값</option>
                    <option value="historical_replay">저장 자료로 검증</option>
                  </NativeSelect>
                </label>
                {mode === "historical_replay" && (
                  <>
                    <label>
                      검증 기록
                      <NativeSelect
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
                      </NativeSelect>
                    </label>
                    <label>
                      입력 기준일
                      <Input
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
            {mode === "api" ? "서울 실제 API 원값 · 관측일과 수집 시각 확인" : legacySelected
              ? "관측소 모델 · 저장 자료 모드"
              : "관측소 · 자료와 모델 준비 상태"}
            <SourceInfo row={row} />
          </div>
          {message && (
            <div className="notice" role="status">
              {message}
              <Button onClick={() => setMessage("")} aria-label="알림 닫기">
                ×
              </Button>
            </div>
          )}
          {(forecasts.error || pipeline.error) && (
            <div className="notice error" role="alert">
              조회 실패: {forecasts.error || pipeline.error}{" "}
              <Button onClick={() => bump((n) => n + 1)}>다시 조회</Button>
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
                <Panel className="panel map-panel">
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
                      <NativeSelect
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
                      </NativeSelect>
                    </label>
                    {three && dataScope === "observed" && (
                      <label>
                        지도 정보
                        <NativeSelect
                          value={mapLayer}
                          onChange={(e) => setMapLayer(e.target.value)}
                        >
                          <option value="groundwater">확보 실측 관측소</option>
                          <option value="rainfall">
                            실측 관측소 + 전국 강수
                          </option>
                        </NativeSelect>
                      </label>
                    )}
                    {three &&
                      dataScope === "observed" &&
                      mapLayer === "rainfall" && (
                        <>
                          <label>
                            강수 원천
                            <NativeSelect
                              value={weatherSource}
                              onChange={(e) => {
                                setWeatherSource(e.target.value);
                                setWeatherDate("");
                                setWeatherSelected("");
                              }}
                            >
                              <option value="aws-daily">지상·AWS 일자료</option>
                              <option value="asos">ASOS 일자료</option>
                            </NativeSelect>
                          </label>
                          <label>
                            강수 날짜
                            <NativeSelect
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
                            </NativeSelect>
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
                        <Button
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
                        </Button>
                      ))}
                    </div>
                  )}
                  <div className="map-credit">
                    {dataScope === "seoul-history"
                      ? "서울 구 경계는 구 선택용입니다. 구별 대표 관측소 수위이며 구 전체 평균·위험 등급이 아닙니다. 경계 높이는 수위가 아닙니다."
                      : "Natural Earth 위치 참고 경계 · 공식 행정경계 아님. 확인된 좌표만 표시하며 기상·지하수 관측소를 자동 연결하지 않습니다."}
                  </div>
                </Panel>
                <Panel className="panel station-card">
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
                  <Button
                    className="primary wide"
                    disabled={!row.station_id}
                    onClick={() => setView("detail")}
                  >
                    관측소 상세 보기 <ArrowUpRight size={17} />
                  </Button>
                  <p className="footnote">
                    구 전체 평균이나 싱크홀 발생 확률이 아닙니다.
                  </p>
                </Panel>
              </div>
              <Panel className="panel">
                <div className="panel-top">
                  <div>
                    <span className="eyebrow">STATION DIRECTORY</span>
                    <h2>
                      관측소 목록 <small>{choices.length}</small>
                    </h2>
                  </div>
                  <Input
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
                              <Button
                                className="text-button"
                                onClick={() => setSelected(r.district_code)}
                              >
                                {r.district_name}
                              </Button>
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
                              <Button
                                className="icon-button"
                                aria-label={r.district_name + " 상세 보기"}
                                onClick={() => {
                                  setSelected(r.district_code);
                                  setView("detail");
                                }}
                              >
                                <ArrowUpRight size={17} />
                              </Button>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  {choices.filter((r) =>
                    (r.district_name + " " + r.station_name).includes(search),
                  ).length > directoryLimit && (
                    <Button onClick={() => setDirectoryLimit((n) => n + 100)}>
                      관측소 100개 더 보기
                    </Button>
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
              </Panel>
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
                <Panel className="panel">
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
                </Panel>
                <Panel className="panel station-card">
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
                </Panel>
              </div>
              <Panel className="panel">
                <div className="panel-top">
                  <h2>{measurementLabel(row)}와 {predictionLabel(row)}</h2>
                  <NativeSelect
                    aria-label="차트 표시 기간"
                    value={range}
                    onChange={(e) => setRange(Number(e.target.value))}
                  >
                    {[30, 90, 180].map((n) => (
                      <option key={n} value={n}>
                        최근 {n}일
                      </option>
                    ))}
                  </NativeSelect>
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
                  {(mode === "api" ? "unverified_api_native" : row.level_reference || row.reference_status) || "확인 필요"} ·
                  결측값을 이어 그리지 않습니다. {dataScope === "simulation" ? "합성 시나리오이며 실제 관측·공식 장마 판정이 아닙니다." : "금색 배경은 공식 장마 기간(사후 평가용)이며 해당 구간이 있을 때만 표시합니다."}
                </p>
              </Panel>
              <Panel className="panel">
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
                      <NativeSelect
                        value={weatherSelected}
                        onChange={(e) => setWeatherSelected(e.target.value)}
                      >
                        <option value="">기상지점 선택</option>
                        {(weather.data?.stations || []).map((s: Row) => (
                          <option key={s.station_id} value={s.station_id}>
                            {s.name} · {s.station_id}
                          </option>
                        ))}
                      </NativeSelect>
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
              </Panel>
            </>
          )}
          {view === "operations" && mode === "api" && (
            <Panel className="panel"><div className="panel-top"><h2>실제 API 학습·예측·드리프트 관리</h2>{choose}</div>
              <p>최근 지하수 관측일 {forecasts.data?.as_of || "수집 대기"} · 관측 확보 {forecasts.data?.observation_count ?? 0}/25곳</p>
              <p>현재 관측소: {row.reason || "수집 대기"}. 실제 수위 원값과 강수를 날짜별 결합해 별도 LSTM으로 학습합니다. 강수 결측은 학습 구간 중앙값과 결측 여부로 입력하며 원본은 보존합니다. 실제 발행 예측의 정답이 수집되면 드리프트 감지와 재학습·평가·교체가 자동 진행됩니다. 별도 시연은 ‘저장 자료로 검증’ 모드에서 진행합니다.</p>
              <p>예측 준비 {forecasts.data?.ready_count ?? 0}/25곳 · 학습 상태 {label(forecasts.data?.training?.status)}</p>
              <Button disabled={busy || forecasts.data?.training?.status === "running"}
                onClick={() => action(() => post("/api-observations/train", {}))}>미준비 모델 학습 다시 시도</Button>
              <Button disabled={busy || (collectionJobs.data?.jobs || []).some((j: Row) => ["queued", "running"].includes(j.status))}
                onClick={() => action(() => post("/api-observations/refresh", {}))}>실제 API 자료 다시 수집</Button>
              <Button disabled={busy} onClick={() => action(() => post("/api-observations/check", {}))}>새 정답·드리프트 확인</Button>
              <Button disabled={busy || !p.can_rollback || (p.jobs || []).some((j: Row) => ["queued", "running"].includes(j.status))}
                onClick={() => action(() => post("/api-observations/" + selected.replace(/^seoul:/, "") + "/rollback", {reason: "화면에서 이전 검증 API 모델 복귀 요청"}))}>이전 검증 API 모델로 복귀</Button>
              <p>{p.note || "운영 상태 확인 중"}</p>
              {pipeline.error && <p role="alert">{pipeline.error}</p>}
              <ol className="pipeline">{(p.stages || []).map((s: Row, i: number) => <li key={s.key} className={s.status}>
                <span>{String(i + 1).padStart(2, "0")}</span><h3>{s.title}</h3><Badge status={s.status} /><p>{s.detail}</p>
              </li>)}</ol>
              <details><summary>드리프트·후보 평가 결과</summary><Json value={{monitor:p.monitor,evaluation:p.evaluation,policy:p.policy}} /></details>
              <h3>실제 API 경보·운영 이력</h3>
              {(p.events || []).map((e: Row) => <div className="record" key={e.id}><strong>{e.message}</strong><p>{e.created_at} · {label(e.status)}</p>
                {e.kind === "quality" && e.status !== "RESOLVED" && <Button disabled={busy} onClick={() => action(() => post("/events/" + e.id + (e.status === "OPEN" ? "/ack" : "/resolve"), {reason: "화면에서 실제 API 경보 확인", note: "자동 재학습·후보 평가 상태 확인"}))}>{e.status === "OPEN" ? "경보 확인" : "조치 완료"}</Button>}
              </div>)}
              {!(p.events || []).length && <p>기록된 드리프트 경보가 없습니다. 발행 예측 정답이 연속 21일 쌓여야 오차를 판정합니다.</p>}
              <details><summary>작업·수집 진행 상태</summary>{[...(p.jobs || []), ...(collectionJobs.data?.jobs || [])].map((j: Row) => <div key={j.id}>
                <p>{j.kind} · {label(j.status)} · {j.error || j.id}</p>
                {["failed", "interrupted"].includes(j.status) && j.kind !== "refresh_api_feed" && <Button disabled={busy} onClick={() => action(() => post("/jobs/" + j.id + "/retry", {}))}>실패 작업 다시 시도</Button>}
              </div>)}</details>
              <h3>현재 모델 평가</h3>
              <p>학습 종료 {row.api_model?.trained_through || "—"} · 검증 RMSE {fmt(row.api_model?.metrics?.validation?.rmse, 5)} · 시험 RMSE {fmt(row.api_model?.metrics?.test?.rmse, 5)} ({row.api_model?.metrics?.test?.count ?? 0}일)</p>
              <p>시험 구간의 전일 수위 유지 기준 RMSE {fmt(row.api_model?.metrics?.test_persistence?.rmse, 5)} · 최근 20일 중 강수 결측 입력 {row.api_model?.imputed_rain_days ?? "—"}일</p>
              <details><summary>모델·평가 상세</summary><Json value={row.api_model || {status: "모델 준비 중"}} /></details>
              <details><summary>수집 상태</summary><Json value={forecasts.data?.collection || {}} /></details>
            </Panel>
          )}
          {view === "operations" && mode !== "api" && (
            <>
              {legacySelected ? (
                <Panel className="panel">
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
                      <Button
                        disabled={!!active || !p.defaults}
                        aria-pressed={!!replay && !p.drift_demo}
                        onClick={() => start("historical")}
                      >
                        기본 상황 선택
                      </Button>
                      <Button
                        disabled={!!active || !p.defaults}
                        aria-pressed={!!replay && !!p.drift_demo}
                        onClick={() => start("level_shift")}
                      >
                        드리프트 시연 선택
                      </Button>
                      <Button
                        disabled={!!active || !replay}
                        onClick={() =>
                          createReplay(
                            p.drift_demo ? "level_shift" : "historical",
                          )
                        }
                      >
                        선택한 상황으로 처음부터
                      </Button>
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
                    <Button
                      disabled={
                        !!active ||
                        !replay ||
                        p.replay_status !== "ready" ||
                        !p.remaining_days
                      }
                      onClick={() => advance(1)}
                    >
                      저장 자료 1일 진행
                    </Button>
                    <Button
                      disabled={
                        !!active ||
                        !replay ||
                        p.replay_status !== "ready" ||
                        !p.remaining_days
                      }
                      onClick={() => advance(Math.min(21, p.remaining_days))}
                    >
                      저장 자료 21일 진행
                    </Button>
                    <Button
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
                    </Button>
                    {all && (
                      <Button onClick={() => setAll(false)}>
                        추가 진행 중지
                      </Button>
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
                </Panel>
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
    </DashboardLayout>
  );
}

function historyReplace(url: URL) { window.history.replaceState(null, "", url); }
