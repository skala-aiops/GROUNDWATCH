"""SQLite 영속 저장소. 원본 CSV와 관측값을 하나의 트랜잭션으로 저장합니다."""
from contextlib import contextmanager
import fcntl
import sqlite3

from .core import WELL_ID, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS well (
 id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 depth_reference TEXT NOT NULL, timezone TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset (
 id TEXT PRIMARY KEY, well_id TEXT NOT NULL REFERENCES well(id),
 parent_dataset_id TEXT REFERENCES dataset(id), original_name TEXT NOT NULL,
 checksum TEXT NOT NULL, source_kind TEXT NOT NULL CHECK(source_kind IN ('simulated','measured')),
 scenario TEXT NOT NULL CHECK(scenario IN ('baseline','drift','')),
 schema_version TEXT NOT NULL, row_count INTEGER NOT NULL CHECK(row_count>=41),
 start_date TEXT NOT NULL, end_date TEXT NOT NULL, uploaded_at TEXT NOT NULL,
 raw_csv BLOB NOT NULL,
 UNIQUE(well_id,checksum,schema_version,source_kind,scenario)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_dataset_child ON dataset(parent_dataset_id)
 WHERE parent_dataset_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS observation (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES dataset(id),
 observed_date TEXT NOT NULL, groundwater_depth_cm REAL NOT NULL CHECK(groundwater_depth_cm>0),
 rainfall_mm REAL NOT NULL CHECK(rainfall_mm>=0), UNIQUE(dataset_id,observed_date)
);
CREATE TABLE IF NOT EXISTS model_version (
 id TEXT PRIMARY KEY, well_id TEXT NOT NULL REFERENCES well(id), registry_name TEXT NOT NULL,
 registry_version TEXT NOT NULL, feature_contract TEXT NOT NULL,
 training_dataset_id TEXT REFERENCES dataset(id), training_end_date TEXT,
 evaluation_end_date TEXT, training_run_id TEXT REFERENCES pipeline_run(id), created_at TEXT NOT NULL,
 UNIQUE(registry_name,registry_version)
);
CREATE TABLE IF NOT EXISTS pipeline_run (
 id TEXT PRIMARY KEY, well_id TEXT NOT NULL REFERENCES well(id), dataset_id TEXT NOT NULL REFERENCES dataset(id),
 kind TEXT NOT NULL CHECK(kind IN ('analysis','retrain')), mode TEXT NOT NULL CHECK(mode IN ('live','replay')),
 status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','interrupted')),
 parent_run_id TEXT UNIQUE REFERENCES pipeline_run(id), trigger_check_id TEXT UNIQUE REFERENCES monitoring_check(id),
 input_model_version_id TEXT NOT NULL REFERENCES model_version(id), output_model_version_id TEXT REFERENCES model_version(id),
 from_date TEXT NOT NULL, to_date TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL, policy_snapshot TEXT NOT NULL, result TEXT, error_code TEXT,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run_per_well ON pipeline_run(well_id)
 WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS forecast (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES dataset(id), model_version_id TEXT NOT NULL REFERENCES model_version(id),
 run_id TEXT REFERENCES pipeline_run(id), idempotency_key TEXT UNIQUE, request_hash TEXT,
 input_start_date TEXT NOT NULL, input_end_date TEXT NOT NULL, target_date TEXT NOT NULL,
 predicted_depth_cm REAL NOT NULL CHECK(predicted_depth_cm>0), actual_observation_id TEXT REFERENCES observation(id),
 mode TEXT NOT NULL CHECK(mode IN ('live','replay')), created_at TEXT NOT NULL,
 UNIQUE(dataset_id,model_version_id,input_end_date,mode)
);
CREATE TABLE IF NOT EXISTS monitoring_check (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES dataset(id), model_version_id TEXT NOT NULL REFERENCES model_version(id),
 run_id TEXT NOT NULL REFERENCES pipeline_run(id), as_of_date TEXT NOT NULL, mode TEXT NOT NULL,
 sample_count INTEGER NOT NULL CHECK(sample_count BETWEEN 0 AND 21), rmse_cm REAL, threshold_cm REAL,
 state TEXT NOT NULL CHECK(state IN ('within_threshold','drift','insufficient_data','not_evaluated','data_invalid')),
 policy_snapshot TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS check_member (
 check_id TEXT NOT NULL REFERENCES monitoring_check(id), forecast_id TEXT NOT NULL REFERENCES forecast(id),
 position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 21),
 PRIMARY KEY(check_id,forecast_id), UNIQUE(check_id,position)
);
CREATE TABLE IF NOT EXISTS pipeline_event (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES pipeline_run(id), sequence INTEGER NOT NULL,
 stage TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL, occurred_at TEXT NOT NULL,
 UNIQUE(run_id,sequence)
);
CREATE INDEX IF NOT EXISTS forecast_target ON forecast(target_date,model_version_id,mode);
CREATE INDEX IF NOT EXISTS check_dataset ON monitoring_check(dataset_id,created_at);
PRAGMA user_version=1;
"""


class Database:
    def __init__(self, path):
        self.path = path
        self._lock_file = None

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = open(str(self.path) + "-lock", "a+")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock_file.close()
            self._lock_file = None
            raise RuntimeError("GroundWatch MVP는 DB당 단일 서버 프로세스로 실행하세요.")
        try:
            with self.connect() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise RuntimeError("지원하지 않는 GroundWatch DB 버전입니다.")
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(SCHEMA)
                db.execute("INSERT OR IGNORE INTO well VALUES(?,?,?,?,?,?)", (
                    WELL_ID, "DEMO-01", "개발용 관측정 (실제 현장 미등록)", "ground_surface", "Asia/Seoul", now()))
                db.execute("UPDATE pipeline_run SET status='interrupted',finished_at=?,error_code='PROCESS_INTERRUPTED' "
                           "WHERE status IN ('queued','running')", (now(),))
        except Exception:
            self.close()
            raise

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def close(self):
        if self._lock_file:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None
