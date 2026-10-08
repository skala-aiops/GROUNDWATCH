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
} from "./state";
import {
  chartSegments,
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
import { CandidateEvaluation, RainfallChart } from "./EvaluationCharts";
const Scene = lazy(() => import("./Scene"));
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
function Chart({ rows, rain = false }: { rows: Row[]; rain?: boolean }) {
  if (rain) return <RainfallChart rows={rows} />;
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
    [reduced, setReduced] = useAtom(reducedAtom);
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
  const pipeline = useResource(
    "/pipeline?district_code=" + selected + (suffix ? "&" + suffix : ""),
    view === "operations" ? 3000 : 30000,
    revision,
  );
  const pending =
    !!replay &&
    mode === "historical_replay" &&
    pipeline.data?.replay_status !== "ready";
  const fq = new URLSearchParams(scope);
  fq.set("mode", mode);
  if (date && mode !== "current") fq.set("as_of", date);
  const forecasts = useResource(
    pending ? null : "/forecasts?" + fq,
    30000,
    revision,
  );
  const districts = useResource("/districts", 30000, revision),
    replays = useResource("/replays", 3000, revision);
  const rows: Row[] = forecasts.data?.forecasts || [];
  const choices: Row[] = rows.length ? rows : districts.data?.districts || [];
  const row = choices.find((r) => r.district_code === selected) || {};
  const hq = new URLSearchParams(scope);
  if (row.source_dataset_id && !replay)
    hq.set("dataset_id", row.source_dataset_id);
  const history = useResource(
    view === "detail" && !pending
      ? "/districts/" + selected + "/history?" + hq
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
  const p = pipeline.data || {};
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
        <div className="rail-caption">WORKSPACE / SEOUL</div>
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
          <span>25 DISTRICTS · ONE VIEW</span>
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
            서울 관측 네트워크 <ChevronRight size={13} />
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
            <label>
              <input
                type="checkbox"
                checked={three}
                onChange={(e) => setThree(e.target.checked)}
              />
              3D 보기
            </label>
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
                서울 25개 구 대표 관측소의 수위 변화와 예측 모델을 확인합니다.
              </p>
            </div>
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
                          {r.scenario === "level_shift" ? "드리프트" : "기본"} ·{" "}
                          {r.as_of} · {r.id.slice(0, 6)}
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
          </div>
          <div className="provenance">
            <span className="dot" />
            과제 시연 환경
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
                  <span>예측 준비 관측소</span>
                  <strong>
                    {forecasts.data?.ready_count ?? "—"}
                    <small> / 25</small>
                  </strong>
                  <div className="track">
                    <i
                      style={{
                        width:
                          ((forecasts.data?.ready_count || 0) / 25) * 100 + "%",
                      }}
                    />
                  </div>
                </article>
                <article>
                  <span>입력 기준일</span>
                  <strong className="date">
                    {forecasts.data?.as_of || "—"}
                  </strong>
                  <small>자료의 마지막 입력 날짜</small>
                </article>
                <article>
                  <span>예측 대상일</span>
                  <strong className="date">
                    {rows[0]?.forecast_date || "—"}
                  </strong>
                  <small>연속 20일 입력 → 다음 날 수위</small>
                </article>
              </div>
              <div className="overview-grid">
                <section className="panel map-panel">
                  <div className="panel-top">
                    <div>
                      <span className="eyebrow">SPATIAL OVERVIEW</span>
                      <h2>서울 관측 네트워크</h2>
                    </div>
                    <span className="pill">
                      <Box size={13} /> {three ? "3D" : "2D"} VIEW
                    </span>
                  </div>
                  {three ? (
                    <Suspense
                      fallback={
                        <div className="empty">3D 지도를 준비합니다.</div>
                      }
                    >
                      <Scene rows={choices} />
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
                          {r.district_name}
                          <small>{fmt(r.prediction)}</small>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="map-credit">
                    구역 선택용 경계 · 2013 KOSTAT / southkorea/seoul-maps ·
                    실제 관측소 좌표 표시 아님
                  </div>
                </section>
                <section className="panel station-card">
                  <span className="eyebrow">SELECTED STATION</span>
                  <div className="station-title">
                    <span className="station-number">{selected}</span>
                    <h2>{row.district_name || "관측소 선택"}</h2>
                    <p>{row.station_name || "관측소 정보 없음"}</p>
                  </div>
                  <div className="hero-value">
                    <span>다음 날 예측 수위</span>
                    <strong>{fmt(row.prediction)}</strong>
                    <small>{row.unit || "단위 미확인"}</small>
                  </div>
                  <dl>
                    <div>
                      <dt>예측 대상일</dt>
                      <dd>{row.forecast_date || "—"}</dd>
                    </div>
                    <div>
                      <dt>자료 · 예측</dt>
                      <dd>
                        <Badge status={row.quality_status} />
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
                      구별 관측소 <small>{choices.length}</small>
                    </h2>
                  </div>
                  <input
                    className="search"
                    aria-label="구 또는 관측소 검색"
                    placeholder="구 · 관측소 검색"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>자치구 / 고정 관측소</th>
                        <th>최근 입력 · 예측 비교</th>
                        <th>예측 대상일</th>
                        <th>예측 수위</th>
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
                            </td>
                            <td>
                              <Badge status={r.quality_status} />
                            </td>
                            <td>
                              <Badge
                                status={
                                  r.model_evaluation_status ||
                                  "evaluation_pending"
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
                    <h2>관측정 · 수위 단면</h2>
                    <span className="pill">CONCEPT SECTION</span>
                  </div>
                  {three ? (
                    <Suspense
                      fallback={
                        <div className="empty">지하 단면을 준비합니다.</div>
                      }
                    >
                      <Scene rows={[row]} section />
                    </Suspense>
                  ) : (
                    <div className="empty">
                      입력 {fmt(row.latest_comparison?.actual)} / 다음 날 예측{" "}
                      {fmt(row.prediction)} {row.unit}
                    </div>
                  )}
                </section>
                <section className="panel station-card">
                  <span className="eyebrow">NEXT DAY FORECAST</span>
                  <div className="hero-value">
                    <strong>{fmt(row.prediction)}</strong>
                    <small>{row.unit || "단위 미확인"}</small>
                  </div>
                  <dl>
                    <div>
                      <dt>입력 종료일</dt>
                      <dd>{row.observed_date || "—"}</dd>
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
                  <Badge status={row.quality_status} />
                  <p className="footnote">
                    {row.reason ||
                      "지표 기준 단위와 원자료의 부호를 유지합니다. 예측 대상일의 정답 확보 전에는 예측을 평가하지 않습니다."}
                  </p>
                  <details>
                    <summary>자료·모델 근거</summary>
                    <Json value={row} />
                  </details>
                </section>
              </div>
              <section className="panel">
                <div className="panel-top">
                  <h2>최근 수위와 다음 날 예측</h2>
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
                  <Chart
                    rows={(history.data?.history || []).slice(-range - 1)}
                  />
                )}
                <p className="footnote">
                  단위 {history.data?.unit || row.unit || "미확인"} ·{" "}
                  결측값을 이어 그리지 않습니다.
                </p>
              </section>
              <section className="panel">
                <h2>
                  일 강수량 <small>mm</small>
                </h2>
                <Chart
                  rows={(history.data?.history || []).slice(-range - 1)}
                  rain
                />
              </section>
            </>
          )}
          {view === "operations" && (
            <>
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
                  {(p.stages || []).map((s: Row, i: number) => (
                    <li key={s.key} className={s.status}>
                      <div className="stage-index">
                        {String(i + 1).padStart(2, "0")}
                      </div>
                      <h3>{s.title}</h3>
                      <Badge status={s.status} />
                      <p>{s.detail}</p>
                    </li>
                  ))}
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
              <Operations
                scope={suffix}
                revision={revision}
                busy={busy || !!active}
                action={action}
                choices={choices}
                setSession={setSession}
              />
            </>
          )}
          <footer>
            <span>
              GROUNDWATCH <b>서울 지하수 관측</b>
            </span>
            <span>관측 → 예측 → 품질 감시</span>
          </footer>
        </div>
      </main>
    </div>
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
