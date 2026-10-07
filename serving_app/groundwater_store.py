"""SQLite 영속 작업·예측·운영 이벤트 저장소."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS objects (
                    kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, scope TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS active_job_scope ON jobs(scope)
                    WHERE status IN ('queued','running');
                CREATE TABLE IF NOT EXISTS request_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                    method TEXT NOT NULL, route TEXT NOT NULL, status INTEGER NOT NULL,
                    latency REAL NOT NULL, request_id TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS metrics_at ON request_metrics(at);
                CREATE TABLE IF NOT EXISTS forecasts (
                    namespace TEXT NOT NULL, district_code TEXT NOT NULL,
                    model_version TEXT NOT NULL, target_date TEXT NOT NULL,
                    body TEXT NOT NULL, actual REAL,
                    PRIMARY KEY(namespace,district_code,model_version,target_date));
                CREATE TABLE IF NOT EXISTS forecasts_v2 (
                    namespace TEXT NOT NULL, district_code TEXT NOT NULL,
                    model_version TEXT NOT NULL, target_date TEXT NOT NULL,
                    source_dataset_id TEXT NOT NULL, body TEXT NOT NULL, actual REAL,
                    PRIMARY KEY(namespace,district_code,model_version,target_date,source_dataset_id));
                INSERT OR IGNORE INTO forecasts_v2
                    SELECT namespace,district_code,model_version,target_date,
                    COALESCE(json_extract(body,'$.source_dataset_id'),''),body,actual FROM forecasts;
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def put(self, kind, value, object_id=None):
        object_id = object_id or value.get('id') or uuid.uuid4().hex
        value = {**value, 'id': object_id}
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO objects VALUES(?,?,?)',
                       (kind, object_id, encode(value)))
        return value

    def get(self, kind, object_id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM objects WHERE kind=? AND id=?',
                             (kind, object_id)).fetchone()
        if not row:
            raise KeyError(f'{kind} {object_id} not found')
        return json.loads(row['body'])

    def list(self, kind):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM objects WHERE kind=? ORDER BY rowid DESC',
                              (kind,)).fetchall()
        return [json.loads(r['body']) for r in rows]

    def _insert_job(self, db, kind, payload, scope=None):
        job_id, timestamp = uuid.uuid4().hex, now()
        scope = scope or f'{kind}:{job_id}'
        if scope.startswith('model:'):
            prefix, code = scope.rsplit(':', 1)
            active = [r['scope'] for r in db.execute("SELECT scope FROM jobs WHERE status IN ('queued','running')")]
            if any(s.rsplit(':', 1)[0] == prefix and (code == 'all' or s.rsplit(':', 1)[1] in ('all', code)) for s in active):
                raise ValueError('같은 구 또는 재생의 작업이 이미 대기·실행 중입니다.')
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',
                   (job_id, kind, scope, encode(payload), 'queued', None, None, timestamp, timestamp))
        return job_id

    def enqueue(self, kind, payload, scope=None):
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                job_id = self._insert_job(db, kind, payload, scope)
        except sqlite3.IntegrityError as exc:
            raise ValueError('같은 구 또는 재생의 작업이 이미 대기·실행 중입니다.') from exc
        return self.job(job_id)

    def register_dataset(self, entry, auto_train=False):
        """Dataset and validation job are one transaction; repeats are immutable."""
        digest = entry['id']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute("SELECT body FROM objects WHERE kind='dataset' AND id=?", (digest,)).fetchone()
            if old:
                entry = json.loads(old['body'])
                job = db.execute("SELECT id FROM jobs WHERE kind='validate' AND scope=? ORDER BY created_at DESC LIMIT 1", (f'validate:{digest}',)).fetchone()
                job_id = job['id'] if job else None
            else:
                db.execute('INSERT INTO objects VALUES(?,?,?)', ('dataset', digest, encode(entry)))
                job_id = self._insert_job(db, 'validate', {'dataset_id':digest, 'auto_train':auto_train}, f'validate:{digest}')
        return {**entry, 'dataset_id':digest, 'job_id':job_id}

    def commit_monitor(self, state_id, state, event=None, job=None):
        """Commit one target's counter, alert and job exactly once across retries."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute("SELECT body FROM objects WHERE kind='monitor' AND id=?", (state_id,)).fetchone()
            previous_state=json.loads(old['body']) if old else {}
            same_model=previous_state.get('version')==state.get('version') and previous_state.get('feature_contract_id')==state.get('feature_contract_id')
            if old and same_model and previous_state.get('last_processed_target_date', '') >= state['last_processed_target_date']:
                return False
            if job:
                try:
                    self._insert_job(db, *job)
                except (ValueError, sqlite3.IntegrityError):
                    # Keep the daily observation, but retry the action on the next date.
                    state['last_trigger'] = json.loads(old['body']).get('last_trigger') if old else None
                    event = None
            if event:
                event = {**event, 'id':uuid.uuid4().hex, 'created_at':now(), 'status':'RECORDED' if event['kind']=='model' else 'OPEN'}
                db.execute('INSERT INTO objects VALUES(?,?,?)', ('event', event['id'], encode(event)))
            db.execute('INSERT OR REPLACE INTO objects VALUES(?,?,?)', ('monitor', state_id, encode({**state,'id':state_id})))
        return True

    def request_metric(self, method, route, status, latency, request_id):
        from datetime import timedelta
        with self.connect() as db:
            db.execute('INSERT INTO request_metrics(at,method,route,status,latency,request_id) VALUES(?,?,?,?,?,?)',
                       (now(),method,route,status,latency,request_id))
            db.execute('DELETE FROM request_metrics WHERE at<?', ((datetime.now(timezone.utc)-timedelta(days=7)).isoformat(),))

    def metric_summary(self, seconds=300):
        import math
        from datetime import timedelta
        since = (datetime.now(timezone.utc)-timedelta(seconds=seconds)).isoformat()
        with self.connect() as db:
            rows = db.execute('SELECT status,latency FROM request_metrics WHERE at>=?', (since,)).fetchall()
        values = sorted(r['latency'] for r in rows)
        errors = sum(r['status'] >= 500 for r in rows)
        return {'window_seconds':seconds, 'count':len(rows), 'http_5xx_count':errors,
                'http_4xx_count':sum(400 <= r['status'] < 500 for r in rows),
                'error_rate':errors/len(rows) if rows else None,
                'success_rate':1-errors/len(rows) if rows else None,
                'throughput_per_second':len(rows)/seconds,
                'p95_seconds':values[max(0,math.ceil(len(values)*.95)-1)] if values else None}

    @staticmethod
    def _job(row):
        value = dict(row)
        value['payload'] = json.loads(value['payload'])
        value['result'] = json.loads(value['result']) if value['result'] else None
        return value

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if row is None:
            raise KeyError(f'job {job_id} not found')
        return self._job(row)

    def jobs(self, namespace=None):
        with self.connect() as db:
            if namespace:
                rows = db.execute("SELECT * FROM jobs WHERE json_extract(payload,'$.namespace')=? OR json_extract(payload,'$.replay_id')=? ORDER BY created_at DESC LIMIT 100",(namespace,namespace)).fetchall()
            else:
                rows = db.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100').fetchall()
        return [self._job(row) for row in rows]

    def claim(self, kind=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE status='queued'" +
                             (' AND kind=?' if kind else '') + ' ORDER BY created_at LIMIT 1',
                             (kind,) if kind else ()).fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=?", (now(), row['id']))
            result = self._job(row)
            result['status'] = 'running'
            return result

    def finish(self, job_id, result=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,result=?,error=?,updated_at=? WHERE id=?',
                       ('failed' if error else 'completed', encode(result) if result is not None else None,
                        error, now(), job_id))

    def progress(self, job_id, result):
        with self.connect() as db:
            db.execute('UPDATE jobs SET result=?,updated_at=? WHERE id=?', (encode(result), now(), job_id))

    def recover(self):
        with self.connect() as db:
            return db.execute("UPDATE jobs SET status='interrupted',error='worker restart; explicit retry required',updated_at=? WHERE status='running'", (now(),)).rowcount

    def forecast(self, namespace, value):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO forecasts_v2 VALUES(?,?,?,?,?,?,NULL)',
                       (namespace, value['district_code'], str(value['model_version']),
                        value['forecast_date'], value.get('source_dataset_id', ''), encode(value)))

    def label(self, namespace, district_code, target_date, actual):
        with self.connect() as db:
            db.execute('UPDATE forecasts_v2 SET actual=? WHERE namespace=? AND district_code=? AND target_date=? AND actual IS NULL',
                       (actual, namespace, district_code, target_date))

    def cached_forecast(self, namespace, code, version, target_date, source_dataset_id=''):
        with self.connect() as db:
            row = db.execute('SELECT body FROM forecasts_v2 WHERE namespace=? AND district_code=? AND model_version=? AND target_date=? AND source_dataset_id=?',
                             (namespace, code, str(version), target_date, source_dataset_id)).fetchone()
        return json.loads(row['body']) if row else None

    def forecasts(self, namespace, district_code, version=None, labelled=False, source_dataset_id=None):
        query = 'SELECT body,actual FROM forecasts_v2 WHERE namespace=? AND district_code=?'
        args = [namespace, district_code]
        if version is not None:
            query += ' AND model_version=?'
            args.append(str(version))
        if source_dataset_id is not None:
            query += ' AND source_dataset_id=?'
            args.append(source_dataset_id)
        if labelled:
            query += ' AND actual IS NOT NULL'
        query += ' ORDER BY target_date'
        with self.connect() as db:
            rows = db.execute(query, args).fetchall()
        return [{**json.loads(r['body']), 'actual': r['actual']} for r in rows]

    def event(self, district_code, kind, message, namespace='historical', **extra):
        return self.put('event', {'district_code': district_code, 'kind': kind,
                                  'status': 'OPEN' if kind in ('quality','inspection','service','job') else 'RECORDED', 'message': message,
                                  'namespace': namespace, 'created_at': now(), **extra})
