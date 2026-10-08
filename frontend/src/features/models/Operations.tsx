import Panel from "@/components/molecules/Panel";
import { Button } from "@/components/atoms/button";
import { Input } from "@/components/atoms/input";
import { NativeSelect } from "@/components/atoms/native-select";
import React, { useEffect, useState } from "react";
import { fmt, label, number } from "../../utils/format";
import { post, request } from "../../api/client";
import { useResource } from "../../hooks/useResource";
import { type Row } from "../../types/domain";
import Badge from "../../components/molecules/Badge";
import Json from "../../components/molecules/Json";
import { CollectionStatus } from "../../components/organisms/data/SourceInfo";
import { CandidateEvaluation } from "../../components/organisms/charts/EvaluationCharts";
export default function Operations({
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
      <NativeSelect name="dataset_id" required defaultValue="">
        <option value="" disabled>
          자료 선택
        </option>
        {(datasets.data?.datasets || []).map((d: Row) => (
          <option value={d.id} key={d.id} disabled={d.status !== "ready"}>
            {d.id.slice(0, 12)} · {label(d.source_kind)} · {label(d.status)}
          </option>
        ))}
      </NativeSelect>
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
      <Panel className="panel">
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
                  <Button
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
                  </Button>
                ))}
              </div>
            )}
          </div>
        ))}
        {!events.data?.events?.length && (
          <p className="muted">등록된 알림이 없습니다.</p>
        )}
      </Panel>
      <div className="two-col">
        <Panel className="panel">
          <h2>학습 작업</h2>
          {jobs.error && <p role="alert">{jobs.error}</p>}
          {(jobs.data?.jobs || []).map((j: Row) => (
            <details key={j.id}>
              <summary>
                {j.kind} · {label(j.status)} · {j.id.slice(0, 10)}
              </summary>
              <Json value={j} />
              {["failed", "interrupted"].includes(j.status) && (
                <Button
                  disabled={busy}
                  onClick={() =>
                    action(() => post("/jobs/" + j.id + "/retry", {}))
                  }
                >
                  다시 요청
                </Button>
              )}
            </details>
          ))}
          {!jobs.data?.jobs?.length && (
            <p className="muted">등록된 작업이 없습니다.</p>
          )}
        </Panel>
        <Panel className="panel">
          <h2>현재 모델 · 이전 모델 복귀</h2>
          {models.error && <p role="alert">{models.error}</p>}
          {(models.data?.models || []).map((m: Row) => (
            <details key={m.district_code || m.name}>
              <summary>
                {m.district_name || m.district_code} · v
                {m.model_version || m.version || "—"}
              </summary>
              <Json value={m} />
              <Button
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
              </Button>
            </details>
          ))}
        </Panel>
      </div>
      <Panel className="panel">
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
                <Input type="file" name="file" accept=".csv" required />
              </label>
              <label>
                관측소·단위 manifest JSON
                <Input type="file" name="manifest" accept=".json" required />
              </label>
              <Button className="primary" disabled={busy}>
                자료 검증 · 등록
              </Button>
            </form>
            <form onSubmit={(e) => submit(e, "train")}>
              <h3>초기 학습 요청</h3>
              {datasetSelect}
              <label>
                대상 자치구
                <NativeSelect name="district_code">
                  <option value="">전체 관측소</option>
                  {choices.map((r) => (
                    <option key={r.district_code} value={r.district_code}>
                      {r.district_name}
                    </option>
                  ))}
                </NativeSelect>
              </label>
              <Button disabled={busy}>학습 작업 등록</Button>
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
                <Input type="date" name="start_date" required />
              </label>
              <label>
                종료일
                <Input type="date" name="end_date" />
              </label>
            </div>
            <label>
              시나리오
              <NativeSelect
                name="scenario"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              >
                <option value="historical">등록 자료 그대로</option>
                <option value="level_shift">수위 변화 상황</option>
              </NativeSelect>
            </label>
            {scenario === "level_shift" && (
              <div className="two-col">
                <label>
                  변화 시작일
                  <Input name="shift_start" type="date" required />
                </label>
                <label>
                  수위 변화량
                  <Input
                    name="shift_amount"
                    type="number"
                    step="any"
                    required
                  />
                </label>
              </div>
            )}
            <Button disabled={busy}>설정한 자료로 시연 시작</Button>
          </form>
        </details>
      </Panel>
    </>
  );
}
