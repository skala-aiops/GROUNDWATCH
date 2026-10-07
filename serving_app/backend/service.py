"""자료 버전, 예측, 판정, 비동기 실행을 연결하는 웹 업무 서비스."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import base64
import hashlib
import json
import logging
import math
import threading
from uuid import UUID

from .adapter import ExistingModelGateway, ModelInfo
from .core import APIError, FEATURE_CONTRACT, SCHEMA_VERSION, Settings, canonical, digest, now, parse_csv, uid
from .database import Database

log = logging.getLogger(__name__)


def one(db, table, identity):
    # table names are internal constants, never request parameters.
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
    if row is None:
        raise APIError(404, "NOT_FOUND", "대상 자료를 찾을 수 없습니다.")
    return dict(row)


def page(items, scope, limit, cursor):
    start = 0
    if cursor:
        try:
            token = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if token["scope"] != digest(scope):
                raise ValueError()
            start = next(i + 1 for i, item in enumerate(items) if item["id"] == token["after"])
        except (ValueError, KeyError, StopIteration, TypeError, UnicodeError) as exc:
            raise APIError(422, "INVALID_DATA", "조회 조건과 cursor가 일치하지 않습니다.") from exc
    subset = items[start:start + limit]
    following = None
    if start + limit < len(items):
        following = base64.urlsafe_b64encode(canonical({"scope": digest(scope), "after": subset[-1]["id"]}).encode()).decode()
    return subset, following


def dataset_public(row):
    return {key: (row[key] or None if key == "scenario" else row[key]) for key in (
        "id", "well_id", "parent_dataset_id", "original_name", "checksum", "source_kind", "scenario",
        "schema_version", "row_count", "start_date", "end_date", "uploaded_at")}


def run_public(row):
    keys = ("id", "dataset_id", "kind", "mode", "status", "parent_run_id", "trigger_check_id",
            "input_model_version_id", "output_model_version_id", "from_date", "to_date", "created_at", "started_at", "finished_at")
    return {**{key: row[key] for key in keys}, "result": json.loads(row["result"]) if row["result"] else None,
            "error": {"code": row["error_code"]} if row["error_code"] else None}


class BackendService:
    def __init__(self, settings=None, gateway=None):
        self.settings = settings or Settings.from_env()
        self.db = Database(self.settings.db_path)
        if gateway is None:
            from serving_app.groundwater.gateway import default_gateway
            gateway = default_gateway()
        self.gateway = gateway
        self._mutations = threading.RLock()
        self._executor = None
        self._busy_forecasts = {}

    def start(self):
        self.db.start()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="groundwatch")
        if callable(getattr(self.gateway, "bootstrap", None)):
            self.gateway.bootstrap(self)

    def close(self):
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
        self.db.close()

    def _dataset(self, db, identity, well_id=None):
        row = one(db, "dataset", identity)
        if well_id is not None and row["well_id"] != well_id:
            raise APIError(422, "INVALID_DATA", "관측정과 데이터 버전이 일치하지 않습니다.")
        return row

    def _lineage(self, db, dataset_id):
        identities = []
        while dataset_id:
            identities.append(dataset_id)
            dataset_id = self._dataset(db, dataset_id)["parent_dataset_id"]
        return identities

    def _rows(self, db, dataset_id):
        return [dict(r) for r in db.execute("SELECT * FROM observation WHERE dataset_id=? ORDER BY observed_date,id", (dataset_id,))]

    def _idle(self, db, well_id):
        if well_id in self._busy_forecasts:
            raise APIError(409, "RUN_IN_PROGRESS", "단건 예측이 실행 중입니다.")
        row = db.execute("SELECT id FROM pipeline_run WHERE well_id=? AND status IN ('queued','running')", (well_id,)).fetchone()
        if row:
            raise APIError(409, "RUN_IN_PROGRESS", "이미 실행 중인 작업이 있습니다.", [{"existing_run_id": row["id"]}])

    def _model(self, db, info):
        try:
            UUID(info.id)
            if info.feature_contract != FEATURE_CONTRACT or not info.registry_name or not info.registry_version:
                raise ValueError()
            one(db, "well", info.well_id)
            for cutoff in (info.training_end_date, info.evaluation_end_date):
                if cutoff is not None and date.fromisoformat(cutoff).isoformat() != cutoff:
                    raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise APIError(422, "CONTRACT_MISMATCH", "모델 메타데이터를 확인하세요.") from exc
        old = db.execute("SELECT * FROM model_version WHERE registry_name=? AND registry_version=?", (info.registry_name, info.registry_version)).fetchone()
        if old:
            if any(old[key] != value for key, value in asdict(info).items()):
                raise APIError(422, "CONTRACT_MISMATCH", "기존 모델 버전의 메타데이터가 변경되었습니다.")
            return
        db.execute("INSERT INTO model_version(id,well_id,registry_name,registry_version,feature_contract,training_end_date,evaluation_end_date,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (info.id, info.well_id, info.registry_name, info.registry_version, info.feature_contract, info.training_end_date, info.evaluation_end_date, now()))

    def _info(self, db, model_id):
        row = one(db, "model_version", model_id)
        return ModelInfo(**{key: row[key] for key in ModelInfo.__dataclass_fields__})

    def _cutoff(self, info, target):
        if info.training_end_date is None or info.evaluation_end_date is None:
            raise APIError(422, "CONTRACT_MISMATCH", "학습·평가 종료일이 없는 모델은 분석할 수 없습니다.")
        if target <= max(info.training_end_date, info.evaluation_end_date):
            raise APIError(422, "INVALID_DATA", "학습·Gate에 사용하지 않은 날짜부터 분석하세요.")

    def wells(self):
        with self.db.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,code,name,depth_reference,timezone FROM well ORDER BY id")]

    def dataset(self, identity):
        with self.db.connect() as db:
            return dataset_public(self._dataset(db, identity))

    def datasets(self, well_id):
        with self.db.connect() as db:
            one(db, "well", well_id)
            return [dataset_public(dict(r)) for r in db.execute("SELECT * FROM dataset WHERE well_id=? ORDER BY uploaded_at DESC,id DESC", (well_id,))]

    def upload(self, well_id, raw, filename, source_kind, scenario, parent_id):
        if len(raw) > self.settings.max_upload_bytes:
            raise APIError(413, "FILE_TOO_LARGE", "CSV 크기는 10 MiB 이하여야 합니다.")
        if (source_kind == "simulated" and scenario not in ("baseline", "drift")) or (source_kind == "measured" and scenario is not None):
            raise APIError(422, "INVALID_DATA", "시뮬레이션은 시나리오가 필요하고 실측 자료에는 시나리오를 지정하지 않습니다.")
        rows = parse_csv(raw)
        checksum = hashlib.sha256(raw).hexdigest()
        run_id = None
        with self._mutations, self.db.connect() as db:
            one(db, "well", well_id)
            old = db.execute("SELECT * FROM dataset WHERE well_id=? AND checksum=? AND schema_version=? AND source_kind=? AND scenario=?",
                             (well_id, checksum, SCHEMA_VERSION, source_kind, scenario or "")).fetchone()
            if old:
                if old["parent_dataset_id"] != parent_id:
                    raise APIError(409, "DATASET_CONFLICT", "동일 파일에 다른 부모 버전을 지정할 수 없습니다.")
                return dataset_public(dict(old)), False
            self._idle(db, well_id)
            if parent_id:
                parent = self._dataset(db, parent_id, well_id)
                if db.execute("SELECT id FROM dataset WHERE parent_dataset_id=?", (parent_id,)).fetchone():
                    raise APIError(409, "LINEAGE_CONFLICT", "이 자료에는 이미 연장본이 있습니다. 최신 연장본을 부모로 지정하세요.")
                old_rows = self._rows(db, parent_id)
                old_values = [{k: r[k] for k in rows[0]} for r in old_rows]
                if (parent["source_kind"] != source_kind or parent["scenario"] != (scenario or "")
                        or len(rows) <= len(old_rows) or rows[:len(old_rows)] != old_values):
                    raise APIError(422, "INVALID_DATA", "기존 값이 동일하고 날짜만 추가된 연장 자료만 허용합니다.")
            identity = uid()
            # Keeping the original bytes in the DB makes the upload atomic with all observations.
            safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1][:255] or "upload.csv"
            db.execute("INSERT INTO dataset VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                identity, well_id, parent_id, safe_name, checksum, source_kind, scenario or "", SCHEMA_VERSION,
                len(rows), rows[0]["observed_date"], rows[-1]["observed_date"], now(), raw))
            db.executemany("INSERT INTO observation VALUES(?,?,?,?,?)", [
                (uid(), identity, r["observed_date"], r["groundwater_depth_cm"], r["rainfall_mm"]) for r in rows])
            if parent_id:
                lineage = self._lineage(db, parent_id)
                placeholders = ",".join("?" for _ in lineage)
                db.execute(f"UPDATE forecast SET actual_observation_id=(SELECT id FROM observation WHERE dataset_id=? AND observed_date=forecast.target_date) "
                           f"WHERE dataset_id IN ({placeholders}) AND mode='live' AND actual_observation_id IS NULL "
                           "AND target_date IN (SELECT observed_date FROM observation WHERE dataset_id=?)",
                           [identity, *lineage, identity])
                latest = db.execute(f"SELECT * FROM forecast WHERE dataset_id IN ({placeholders}) AND mode='live' "
                                    "AND target_date>? AND target_date<=? AND actual_observation_id IS NOT NULL ORDER BY target_date DESC,created_at DESC LIMIT 1",
                                    [*lineage, parent["end_date"], rows[-1]["observed_date"]]).fetchone()
                if latest:
                    info = self._info(db, latest["model_version_id"])
                    run_id = self._insert_run(db, identity, info, "analysis", "live", (date.fromisoformat(parent["end_date"]) + timedelta(days=1)).isoformat(), rows[-1]["observed_date"], uid(), digest({"upload": identity}))
            result = dataset_public(self._dataset(db, identity))
        if run_id:
            self._submit(run_id)
        return result, True

    def observations(self, well_id, dataset_id, start=None, end=None):
        with self.db.connect() as db:
            dataset = self._dataset(db, dataset_id, well_id)
            start, end = self._range(dataset, start, end)
            return [{k: r[k] for k in ("id", "observed_date", "groundwater_depth_cm", "rainfall_mm")} for r in self._rows(db, dataset_id)
                    if start <= r["observed_date"] <= end]

    def _range(self, dataset, start, end):
        end = end or dataset["end_date"]
        start = start or (date.fromisoformat(end) - timedelta(days=59)).isoformat()
        span = (date.fromisoformat(end) - date.fromisoformat(start)).days
        if span < 0 or span >= 756:
            raise APIError(422, "INVALID_DATA", "조회 범위는 시작일 이후 최대 756일입니다.")
        return start, end

    def _forecast(self, db, row):
        model = self._info(db, row["model_version_id"])
        actual = one(db, "observation", row["actual_observation_id"])["groundwater_depth_cm"] if row["actual_observation_id"] else None
        keys = ("id", "dataset_id", "input_start_date", "input_end_date", "target_date", "predicted_depth_cm", "actual_observation_id", "mode", "created_at")
        return {**{k: row[k] for k in keys}, "model": model.public(), "actual_depth_cm": actual,
                "residual_cm": actual - row["predicted_depth_cm"] if actual is not None else None}

    def _predict_value(self, info, sequence):
        value = float(self.gateway.predict(info, [{k: row[k] for k in ("observed_date", "groundwater_depth_cm", "rainfall_mm")} for row in sequence]))
        if not math.isfinite(value) or value <= 0:
            raise APIError(500, "INVALID_MODEL_OUTPUT", "모델이 유효한 깊이를 반환하지 않았습니다.")
        if self.gateway.active_model(info.well_id) != info:
            raise APIError(409, "MODEL_CHANGED", "예측 도중 서빙 모델이 변경되었습니다.")
        return value

    def _save_forecast(self, db, dataset_id, info, sequence, value, mode, run_id=None, actual=None, key=None, request_hash=None):
        target = (date.fromisoformat(sequence[-1]["observed_date"]) + timedelta(days=1)).isoformat()
        identity = uid()
        db.execute("INSERT INTO forecast VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            identity, dataset_id, info.id, run_id, key, request_hash, sequence[0]["observed_date"], sequence[-1]["observed_date"],
            target, value, actual, mode, now()))
        return one(db, "forecast", identity)

    def predict(self, well_id, dataset_id, input_end_date, key):
        request_hash = digest({"well_id": well_id, "dataset_id": dataset_id, "input_end_date": input_end_date})
        with self._mutations, self.db.connect() as db:
            previous = db.execute("SELECT * FROM forecast WHERE idempotency_key=?", (key,)).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise APIError(409, "IDEMPOTENCY_CONFLICT", "같은 키로 다른 요청을 보낼 수 없습니다.")
                return self._forecast(db, dict(previous)), False
            self._idle(db, well_id)
            dataset = self._dataset(db, dataset_id, well_id)
            if input_end_date != dataset["end_date"]:
                raise APIError(422, "INVALID_DATA", "최신 관측일을 입력 종료일로 지정하세요.")
            sequence = self._rows(db, dataset_id)[-20:]
            info = self.gateway.active_model(well_id)
            if info.well_id != well_id:
                raise APIError(422, "CONTRACT_MISMATCH", "다른 관측정의 모델입니다.")
            self._model(db, info)
            self._cutoff(info, (date.fromisoformat(input_end_date) + timedelta(days=1)).isoformat())
            exists = db.execute("SELECT id FROM forecast WHERE dataset_id=? AND model_version_id=? AND input_end_date=? AND mode='live'", (dataset_id, info.id, input_end_date)).fetchone()
            if exists:
                raise APIError(409, "FORECAST_EXISTS", "이 모델·자료·날짜의 예측이 이미 있습니다.", [{"forecast_id": exists["id"]}])
            self._busy_forecasts[well_id] = key
        try:
            value = self._predict_value(info, sequence)
            with self._mutations, self.db.connect() as db:
                row = self._save_forecast(db, dataset_id, info, sequence, value, "live", key=key, request_hash=request_hash)
                return self._forecast(db, row), True
        finally:
            with self._mutations:
                self._busy_forecasts.pop(well_id, None)

    def forecasts(self, well_id, dataset_id, mode, start=None, end=None, model_id=None):
        with self.db.connect() as db:
            dataset = self._dataset(db, dataset_id, well_id)
            # Include tomorrow's single forecast in the default range.
            end = end or (date.fromisoformat(dataset["end_date"]) + timedelta(days=1)).isoformat()
            start, end = self._range(dataset, start, end)
            identities = self._lineage(db, dataset_id)
            placeholders = ",".join("?" for _ in identities)
            rows = db.execute(f"SELECT * FROM forecast WHERE dataset_id IN ({placeholders}) AND mode=? AND target_date BETWEEN ? AND ? "
                              "ORDER BY target_date,id", [*identities, mode, start, end])
            return [self._forecast(db, dict(r)) for r in rows if model_id is None or r["model_version_id"] == model_id]

    def check(self, identity):
        with self.db.connect() as db:
            row = one(db, "monitoring_check", identity)
            row["policy_snapshot"] = json.loads(row["policy_snapshot"])
            members = db.execute("SELECT m.forecast_id,m.position,f.actual_observation_id,o.groundwater_depth_cm-f.predicted_depth_cm AS residual_cm "
                                 "FROM check_member m JOIN forecast f ON f.id=m.forecast_id JOIN observation o ON o.id=f.actual_observation_id "
                                 "WHERE m.check_id=? ORDER BY m.position", (identity,))
            row["members"] = [dict(r) for r in members]
            return row

    def runs(self, well_id, dataset_id, kind=None):
        with self.db.connect() as db:
            self._dataset(db, dataset_id, well_id)
            return [run_public(dict(r)) for r in db.execute("SELECT * FROM pipeline_run WHERE dataset_id=? ORDER BY created_at DESC,id DESC", (dataset_id,)) if kind is None or r["kind"] == kind]

    def run(self, identity):
        with self.db.connect() as db:
            return run_public(one(db, "pipeline_run", identity))

    def events(self, identity):
        with self.db.connect() as db:
            one(db, "pipeline_run", identity)
            return [dict(r) for r in db.execute("SELECT * FROM pipeline_event WHERE run_id=? ORDER BY sequence", (identity,))]

    def dashboard(self, well_id, dataset_id, mode):
        with self.db.connect() as db:
            dataset = self._dataset(db, dataset_id, well_id)
            rows = self._rows(db, dataset_id)
            last = {k: rows[-1][k] for k in ("id", "observed_date", "groundwater_depth_cm", "rainfall_mm")}
            lineage = self._lineage(db, dataset_id)
            placeholders = ",".join("?" for _ in lineage)
            forecast = db.execute(f"SELECT * FROM forecast WHERE dataset_id IN ({placeholders}) AND mode=? ORDER BY created_at DESC,id DESC LIMIT 1", [*lineage, mode]).fetchone()
            latest_check = db.execute(f"SELECT id FROM monitoring_check WHERE dataset_id IN ({placeholders}) AND mode=? ORDER BY created_at DESC,id DESC LIMIT 1", [*lineage, mode]).fetchone()
            run = db.execute(f"SELECT id FROM pipeline_run WHERE dataset_id IN ({placeholders}) AND mode=? ORDER BY created_at DESC,id DESC LIMIT 1", [*lineage, mode]).fetchone()
            latest_forecast = self._forecast(db, dict(forecast)) if forecast else None
        try:
            active = self.gateway.active_model(well_id).public()
        except APIError:
            active = None
        stale_days = self.settings.stale_after_days
        age = (datetime.now(ZoneInfo("Asia/Seoul")).date() - date.fromisoformat(dataset["end_date"])).days
        return {"well_id": well_id, "dataset_id": dataset_id, "source_kind": dataset["source_kind"],
                "as_of_date": dataset["end_date"], "last_observation": last, "latest_forecast": latest_forecast,
                "last_check": self.check(latest_check["id"]) if latest_check else None,
                "data_freshness": {"state": "unknown" if stale_days is None else ("stale" if age > stale_days else "fresh"),
                                   "last_observed_date": dataset["end_date"], "stale_after_days": stale_days},
                "active_model": active, "latest_run_id": run["id"] if run else None, "updated_at": now()}

    def _insert_run(self, db, dataset_id, info, kind, mode, start, end, key, request_hash, parent=None, check=None, policy=None):
        identity = uid()
        db.execute("INSERT INTO pipeline_run(id,well_id,dataset_id,kind,mode,status,parent_run_id,trigger_check_id,input_model_version_id,"
                   "from_date,to_date,idempotency_key,request_hash,policy_snapshot,created_at) VALUES(?,?,?,?,?,'queued',?,?,?,?,?,?,?,?,?)",
                   (identity, info.well_id, dataset_id, kind, mode, parent, check, info.id, start, end, key, request_hash,
                    canonical(policy or self.settings.policy()), now()))
        self._event(db, identity, "validate", "succeeded", "입력 자료와 실행 조건을 확인했습니다.")
        return identity

    def _event(self, db, run_id, stage, state, message):
        seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM pipeline_event WHERE run_id=?", (run_id,)).fetchone()[0]
        db.execute("INSERT INTO pipeline_event VALUES(?,?,?,?,?,?,?)", (uid(), run_id, seq, stage, state, message, now()))

    def analyse(self, well_id, dataset_id, start, end, key):
        request_hash = digest({"well_id": well_id, "dataset_id": dataset_id, "from": start, "to": end, "mode": "replay"})
        with self._mutations, self.db.connect() as db:
            previous = db.execute("SELECT * FROM pipeline_run WHERE idempotency_key=?", (key,)).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise APIError(409, "IDEMPOTENCY_CONFLICT", "같은 키로 다른 분석을 요청할 수 없습니다.")
                return run_public(dict(previous))
            dataset = self._dataset(db, dataset_id, well_id)
            self._range(dataset, start, end)
            if start < (date.fromisoformat(dataset["start_date"]) + timedelta(days=20)).isoformat() or end > dataset["end_date"]:
                raise APIError(422, "INSUFFICIENT_HISTORY", "대상일 이전 20일과 대상일의 실측이 필요합니다.")
            self._idle(db, well_id)
            info = self.gateway.active_model(well_id)
            if info.well_id != well_id:
                raise APIError(422, "CONTRACT_MISMATCH", "다른 관측정의 모델입니다.")
            self._model(db, info)
            self._cutoff(info, start)
            run_id = self._insert_run(db, dataset_id, info, "analysis", "replay", start, end, key, request_hash)
            result = run_public(one(db, "pipeline_run", run_id))
        self._submit(run_id)
        return result

    def _submit(self, run_id):
        if self._executor is None:
            raise RuntimeError("BackendService.start()가 필요합니다.")
        self._executor.submit(self._execute, run_id)

    def _execute(self, run_id):
        try:
            with self._mutations, self.db.connect() as db:
                run = one(db, "pipeline_run", run_id)
                db.execute("UPDATE pipeline_run SET status='running',started_at=? WHERE id=?", (now(), run_id))
                stage = "train" if run["kind"] == "retrain" else "predict"
                self._event(db, run_id, stage, "started", "작업을 시작했습니다.")
            if run["kind"] == "analysis":
                self._execute_analysis(run)
            else:
                self._execute_retrain(run)
        except Exception as exc:
            log.exception("GroundWatch run failed: %s", run_id)
            code = exc.code if isinstance(exc, APIError) else "INTERNAL_ERROR"
            with self._mutations, self.db.connect() as db:
                db.execute("UPDATE pipeline_run SET status='failed',finished_at=?,error_code=? WHERE id=? AND status IN ('queued','running')", (now(), code, run_id))
                self._event(db, run_id, "train" if run["kind"] == "retrain" else "evaluate", "failed", "작업에 실패했습니다. 오류 코드: " + code)

    def _evaluate(self, db, run, info, as_of):
        lineage = self._lineage(db, run["dataset_id"]) if run["mode"] == "live" else [run["dataset_id"]]
        placeholders = ",".join("?" for _ in lineage)
        # A single prediction per date, fixed model and mode; never mix unrelated uploads.
        candidates = db.execute(f"SELECT f.*,o.groundwater_depth_cm AS actual FROM forecast f "
                                "JOIN observation o ON o.id=f.actual_observation_id "
                                f"WHERE f.dataset_id IN ({placeholders}) AND f.model_version_id=? AND f.mode=? AND f.target_date<=? "
                                "ORDER BY f.target_date DESC,f.created_at ASC", [*lineage, info.id, run["mode"], as_of])
        members, expected = [], date.fromisoformat(as_of)
        for candidate in candidates:
            target = date.fromisoformat(candidate["target_date"])
            if target > expected:
                continue
            if target != expected:
                break
            members.append(dict(candidate))
            expected -= timedelta(days=1)
            if len(members) == 21:
                break
        members.reverse()
        policy = json.loads(run["policy_snapshot"])
        threshold = policy["rmse_threshold_cm"]
        rmse = None
        state = "insufficient_data"
        if len(members) == 21:
            # hypot avoids overflow when squaring large, but finite, measurements.
            rmse = math.hypot(*(r["actual"] - r["predicted_depth_cm"] for r in members)) / math.sqrt(21)
            if not math.isfinite(rmse):
                rmse, state = None, "data_invalid"
            else:
                state = "not_evaluated" if threshold is None else ("drift" if rmse > threshold else "within_threshold")
        identity = uid()
        db.execute("INSERT INTO monitoring_check VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            identity, run["dataset_id"], info.id, run["id"], as_of, run["mode"], len(members), rmse, threshold, state, run["policy_snapshot"], now()))
        db.executemany("INSERT INTO check_member VALUES(?,?,?)", [(identity, row["id"], i) for i, row in enumerate(members, 1)])
        return identity, state

    def _execute_analysis(self, run):
        with self.db.connect() as db:
            rows = self._rows(db, run["dataset_id"])
            info = self._info(db, run["input_model_version_id"])
        last_check, state, processed, count = None, None, None, 0
        for index, actual in enumerate(rows):
            target = actual["observed_date"]
            if not run["from_date"] <= target <= run["to_date"]:
                continue
            value = None
            with self.db.connect() as db:
                if run["mode"] == "replay":
                    previous = db.execute("SELECT id FROM forecast WHERE dataset_id=? AND model_version_id=? AND target_date=? AND mode='replay'", (run["dataset_id"], info.id, target)).fetchone()
                else:
                    previous = db.execute("SELECT id FROM forecast WHERE actual_observation_id=? AND model_version_id=? AND mode='live'", (actual["id"], info.id)).fetchone()
                    if not previous:
                        continue
            self._cutoff(info, target)
            if run["mode"] == "replay" and not previous:
                sequence = rows[index - 20:index]
                if len(sequence) != 20:
                    raise APIError(422, "INSUFFICIENT_HISTORY", "최근 20일 입력이 부족합니다.")
                value = self._predict_value(info, sequence)
            with self._mutations, self.db.connect() as db:
                if value is not None:
                    self._save_forecast(db, run["dataset_id"], info, sequence, value, "replay", run_id=run["id"], actual=actual["id"])
                count += 1
                last_check, state = self._evaluate(db, run, info, target)
                processed = target
                if state == "drift":
                    self._event(db, run["id"], "detect", "succeeded", "최근 21건의 예측오차가 설정 기준을 초과했습니다.")
                    break
        child = None
        with self._mutations, self.db.connect() as db:
            self._event(db, run["id"], "evaluate", "succeeded", f"{count}개 예측의 비교 작업을 마쳤습니다.")
            db.execute("UPDATE pipeline_run SET status='succeeded',finished_at=? WHERE id=?", (now(), run["id"]))
            policy = json.loads(run["policy_snapshot"])
            if state == "drift" and policy["auto_retrain"]:
                training_rows = [r for r in rows if r["observed_date"] <= processed][-41:]
                if len(training_rows) == 41:
                    child = self._insert_run(db, run["dataset_id"], info, "retrain", run["mode"], training_rows[0]["observed_date"],
                                             processed, uid(), digest({"trigger": last_check}), parent=run["id"], check=last_check, policy=policy)
            if state == "drift" and child is None:
                self._event(db, run["id"], "train", "skipped", "자동 재학습 정책 또는 41행 입력이 준비되지 않아 실행하지 않았습니다.")
            result = {"prediction_count": count, "processed_through_date": processed, "last_check_id": last_check,
                      "child_run_id": child, "stop_reason": "drift_detected" if state == "drift" else "range_complete"}
            db.execute("UPDATE pipeline_run SET result=? WHERE id=?", (canonical(result), run["id"]))
        if child:
            self._execute(child)

    def _execute_retrain(self, run):
        with self.db.connect() as db:
            info = self._info(db, run["input_model_version_id"])
            rows = [r for r in self._rows(db, run["dataset_id"]) if run["from_date"] <= r["observed_date"] <= run["to_date"]]
        policy = json.loads(run["policy_snapshot"])
        if len(rows) != 41 or self.gateway.active_model(info.well_id) != info:
            raise APIError(409, "MODEL_CHANGED", "재학습의 입력 또는 현재 모델이 바뀌었습니다.")

        def emit(stage, state, message):
            if stage not in ("train", "register", "gate", "deploy") or state not in ("started", "succeeded", "failed", "skipped"):
                raise ValueError("잘못된 AI 단계 이벤트")
            with self.db.connect() as db:
                self._event(db, run["id"], stage, state, str(message)[:500])

        clean_rows = [{k: r[k] for k in ("observed_date", "groundwater_depth_cm", "rainfall_mm")} for r in rows]
        result = self.gateway.retrain(info, clean_rows, policy, emit)
        expected_gate = math.isfinite(result.gate_rmse_cm) and result.gate_rmse_cm <= policy["gate_threshold_cm"]
        if (not math.isfinite(result.gate_rmse_cm) or result.gate_rmse_cm < 0 or result.gate_passed != expected_gate
                or result.promoted != result.gate_passed
                or (result.training_start_date, result.training_end_date, result.gate_start_date, result.gate_end_date)
                != (rows[20]["observed_date"], rows[35]["observed_date"], rows[36]["observed_date"], rows[40]["observed_date"])):
            raise APIError(500, "INVALID_TRAINING_RESULT", "재학습의 시간 분리 또는 Gate 결과가 계약과 다릅니다.")
        if result.candidate is not None and (
                result.candidate.id == info.id or result.candidate.well_id != info.well_id
                or result.candidate.training_end_date != result.training_end_date
                or result.candidate.evaluation_end_date != result.gate_end_date):
            raise APIError(500, "INVALID_TRAINING_RESULT", "후보 모델의 관측정·버전·학습 범위가 일치하지 않습니다.")
        if result.promoted:
            if (result.candidate is None or result.candidate.id == info.id or result.candidate.well_id != info.well_id
                    or result.candidate.training_end_date != result.training_end_date
                    or result.candidate.evaluation_end_date != result.gate_end_date
                    or self.gateway.active_model(info.well_id) != result.candidate):
                raise APIError(500, "INVALID_TRAINING_RESULT", "실제 서빙 모델 전환을 확인하지 못했습니다.")
        elif self.gateway.active_model(info.well_id) != info:
            raise APIError(500, "INVALID_TRAINING_RESULT", "Gate 미통과 시 기존 모델이 유지되어야 합니다.")
        with self._mutations, self.db.connect() as db:
            if result.candidate:
                self._model(db, result.candidate)
                db.execute("UPDATE model_version SET training_dataset_id=?,training_run_id=? WHERE id=?", (run["dataset_id"], run["id"], result.candidate.id))
            payload = {key: value for key, value in asdict(result).items() if key != "candidate"}
            payload.update({"gate_threshold_cm": policy["gate_threshold_cm"], "previous_model_version_id": info.id,
                            "candidate_model_version_id": result.candidate.id if result.candidate else None})
            db.execute("UPDATE pipeline_run SET status='succeeded',finished_at=?,result=?,output_model_version_id=? WHERE id=?",
                       (now(), canonical(payload), result.candidate.id if result.promoted else None, run["id"]))
            self._event(db, run["id"], "deploy", "succeeded" if result.promoted else "skipped",
                        "새 서빙 모델을 확인했습니다." if result.promoted else "Gate 미통과로 기존 모델을 유지합니다.")
