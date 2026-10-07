"""학습·재생 요청을 영속 작업으로 실행하는 도메인 API."""
from datetime import date, timedelta
from typing import Literal
from fastapi import APIRouter, File, HTTPException, UploadFile, Query
from pydantic import BaseModel, Field, ConfigDict
from data.groundwater import DISTRICT_CODES
from serving_app.groundwater_store import now
from serving_app.groundwater_service import today
from fastapi.responses import JSONResponse

class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class TrainRequest(StrictBody):
    dataset_id: str = Field(min_length=1)
    district_code: str | None = None

class IngestionRequest(StrictBody):
    start_date: date
    end_date: date
    seoul_station: str = Field(min_length=1, max_length=100)
    weather_station: str = Field(pattern=r'^\d{1,3}$')

class SnapshotRequest(StrictBody):
    station_id: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    start_date: date
    end_date: date

class LiveJobRequest(StrictBody):
    snapshot_id: str = Field(min_length=1)
    replay_start: date | None = None

class ReplayRequest(StrictBody):
    dataset_id: str
    start_date: date
    end_date: date | None = None
    scenario: Literal['historical', 'level_shift'] = 'historical'
    shift_start: date | None = None
    shift_amount: float = 0
    presentation_start_date: date | None = None

class AdvanceRequest(StrictBody):
    days: int = Field(default=1, ge=1, le=180)

class ReasonRequest(StrictBody):
    reason: str = Field(min_length=1, max_length=1000)
    note: str | None = None
    version: str | None = None

class ObservationInput(StrictBody):
    station_id: str = Field(min_length=1)
    date: date
    groundwater_level: float
    rainfall_mm: float = Field(ge=0)
    level_unit: str = Field(min_length=1)

class PredictRequest(StrictBody):
    sequence: list[ObservationInput] = Field(min_length=20, max_length=20)
    replay_id: str | None = None

def checked_code(code):
    if code not in DISTRICT_CODES:
        raise HTTPException(422, '유효한 서울시 구 코드를 사용하세요.')
    return code

def router_for(service):
    router = APIRouter()

    from serving_app.external_observations import ExternalObservations
    external = ExternalObservations(service.root)
    from serving_app.live_observations import LiveObservations
    live_service=LiveObservations(service)

    @router.get('/api/v1/external-sources', tags=['external-data'])
    def external_sources():
        return external.status()

    @router.post('/api/v1/ingestions', status_code=202, tags=['external-data'])
    def ingest(body: IngestionRequest):
        return external.enqueue(body.start_date.isoformat(), body.end_date.isoformat(),
                                body.seoul_station, body.weather_station)

    @router.get('/api/v1/ingestions/{job_id}', tags=['external-data'])
    def ingestion(job_id: str):
        return external.store.job(job_id)

    @router.post('/api/v1/ingestions/{job_id}/retry', status_code=202, tags=['external-data'])
    def ingestion_retry(job_id: str):
        return external.retry(job_id)

    @router.get('/api/v1/data-freshness', tags=['external-data'])
    def freshness(target_date: date | None = None):
        return live_service.freshness(target_date.isoformat() if target_date else None)

    @router.get('/api/v1/live/forecasts', tags=['live'])
    def live_forecasts(target_date: date | None = None):
        return live_service.forecasts(target_date.isoformat() if target_date else None)

    @router.get('/api/v1/live/mappings', tags=['live'])
    def live_mappings():
        return {'mappings':live_service.repo.mappings()}

    @router.get('/api/v1/live/jobs', tags=['live'])
    def live_jobs():
        return {'jobs':service.store.jobs('observed_api_v1')}

    @router.get('/api/v1/live/models', tags=['live'])
    def live_models():
        return {'models':service.manager('observed_api_v1').list_models()}

    @router.post('/api/v1/live/models/{code}/rollback', status_code=202, tags=['live'])
    def live_rollback(code: str, body: ReasonRequest):
        code=checked_code(code)
        return service.store.enqueue('rollback',{'district_code':code,'namespace':'observed_api_v1',
            'reason':body.reason,'version':body.version},f'model:observed_api_v1:{code}')

    @router.get('/api/v1/live/events', tags=['live'])
    def live_events():
        return {'events':[e for e in service.store.list('event') if e.get('namespace')=='observed_api_v1']}

    @router.get('/api/v1/live/monitoring', tags=['live'])
    def live_monitoring():
        return {'monitors':[m for m in service.store.list('monitor') if m['id'].startswith('observed_api_v1:')]}

    @router.get('/api/v1/live/pipeline', tags=['live'])
    def live_pipeline(district_code: str='11110'):
        return live_service.pipeline(checked_code(district_code))

    @router.get('/api/v1/live/districts/{code}/history', tags=['live'])
    def live_history(code: str):
        return live_service.history(checked_code(code))

    @router.post('/api/v1/live/snapshots', status_code=201, tags=['live'])
    def publish_snapshot(body: SnapshotRequest):
        return live_service.repo.publish_snapshot(body.station_id,body.mapping_version,
            body.start_date.isoformat(),body.end_date.isoformat())

    @router.post('/api/v1/live/snapshots/{snapshot_id}/activate', tags=['live'])
    def activate_snapshot(snapshot_id: str):
        return live_service.repo.activate(snapshot_id)

    @router.post('/api/v1/live/training-jobs', status_code=202, tags=['live'])
    def train_live(body: LiveJobRequest):
        s=live_service.repo.snapshot(body.snapshot_id)
        if not body.replay_start:
            raise HTTPException(422,'시간 분리 검증을 위한 replay_start가 필요합니다.')
        return service.store.enqueue('train_live',{'snapshot_id':s['id'],
            'replay_start':body.replay_start.isoformat(),'namespace':'observed_api_v1'},
            f"model:observed_api_v1:{s['rows'][0]['district_code']}")

    @router.post('/api/v1/live/prediction-jobs', status_code=202, tags=['live'])
    def predict_live(body: LiveJobRequest):
        s=live_service.repo.snapshot(body.snapshot_id)
        if s['end_date']!=(today()-timedelta(days=1)).isoformat() or len(s['rows'])<20:
            raise HTTPException(422,'전일까지 연속20일 API snapshot이 필요합니다.')
        return service.store.enqueue('predict_live',{'snapshot_id':s['id'],'namespace':'observed_api_v1'},
            f"live:{s['station_id']}:{today().isoformat()}")

    @router.get('/health/live', tags=['health'])
    def live():
        return {'status': 'alive', 'service': 'GroundWatch'}

    @router.get('/health/runtime', tags=['health'])
    def runtime():
        import os, socket
        from pathlib import Path
        workers=[]
        if Path('/proc').exists():
            for item in Path('/proc').iterdir():
                if not item.name.isdigit():
                    continue
                try:
                    command=(item/'cmdline').read_bytes().split(b'\x00')
                    if b'serving_app.groundwater_worker' in command:
                        workers.append(int(item.name))
                except (OSError,ValueError):
                    continue
        return {'container':Path('/.dockerenv').exists(),'hostname':socket.gethostname(),
                'api_pid':os.getpid(),'worker_pids':workers,'worker_running':bool(workers),
                'checked_at':now(),'note':'process presence; not a cloud availability guarantee'}

    @router.get('/health/ready', tags=['health'])
    @router.get('/health', tags=['health'])
    def ready():
        result = service.readiness()
        return JSONResponse(status_code=200 if result['status']=='ready' else 503,content=result)

    @router.get('/metrics/summary',tags=['monitoring'])
    @router.get('/api/v1/metrics/summary',tags=['monitoring'])
    def summary(seconds: int = Query(default=300,ge=1,le=86400)):
        metrics = service.store.metric_summary(seconds)
        return {**metrics,'minimum_samples':20,'sufficient_samples':metrics['count']>=20,
                'thresholds':{'p95_seconds':1,'http_5xx_rate':.01},'evaluation_interval_seconds':60,
                'availability_note':'request success rate; not time-based uptime SLA',
                'service_alerts':[e for e in service.store.list('event') if e['kind']=='service'][:20]}

    @router.get('/api/v1/monitoring',tags=['monitoring'])
    def monitoring(replay_id: str | None = None):
        return service.monitoring(replay_id)

    @router.get('/api/v1/pipeline',tags=['monitoring'])
    def pipeline(district_code: str = '11110', replay_id: str | None = None):
        checked_code(district_code)
        return service.pipeline(district_code,replay_id)

    @router.post('/api/v1/datasets', status_code=202, tags=['datasets'])
    async def upload(file: UploadFile = File(...), manifest: UploadFile = File(...)):
        async def bounded(part, limit):
            data = bytearray()
            while chunk := await part.read(1024 * 1024):
                data.extend(chunk)
                if len(data) > limit:
                    raise HTTPException(413, '업로드 크기 제한을 초과했습니다.')
            return bytes(data)
        source = await bounded(file, 150 * 1024 * 1024)
        mapping = await bounded(manifest, 1024 * 1024)
        if not source or not mapping:
            raise HTTPException(422, 'CSV와 대표 관측소 JSON이 필요합니다.')
        import csv, io, json
        from data.groundwater import REQUIRED_COLUMNS, validate_manifest
        try:
            fields = next(csv.reader(io.StringIO(source.decode('utf-8-sig'))))
            if not set(REQUIRED_COLUMNS) <= set(fields):
                raise ValueError('canonical CSV 열이 필요합니다: ' + ', '.join(REQUIRED_COLUMNS))
            validate_manifest(json.loads(mapping.decode('utf-8-sig')))
        except (ValueError, UnicodeError, StopIteration) as exc:
            raise HTTPException(422, str(exc)) from exc
        return service.queue_upload(source, mapping, file.filename or 'dataset.csv')

    @router.get('/api/v1/datasets', tags=['datasets'])
    def datasets():
        return {'datasets': [{k: v for k, v in d.items() if k not in ('path', 'manifest_path')} for d in service.store.list('dataset')]}

    @router.get('/api/v1/districts', tags=['forecasts'])
    def districts(dataset_id: str | None = None):
        return service.districts(dataset_id)

    @router.get('/api/v1/forecasts', tags=['forecasts'])
    def forecasts(as_of: date | None = None, mode: Literal['historical_replay', 'current'] = 'historical_replay',
                  replay_id: str | None = None, dataset_id: str | None = None):
        return service.forecasts(as_of.isoformat() if as_of else None, mode, replay_id, dataset_id)

    @router.get('/api/v1/districts/{code}/history', tags=['forecasts'])
    def history(code: str, dataset_id: str | None = None, replay_id: str | None = None):
        return service.history(checked_code(code), dataset_id, replay_id)

    @router.post('/api/v1/districts/{code}/predict', tags=['forecasts'])
    def predict(code: str, body: PredictRequest):
        checked_code(code)
        namespace = body.replay_id or service.default_namespace()
        rows = [{**r.model_dump(mode='json'), 'district_code': code} for r in body.sequence]
        if any(r['date'] > today().isoformat() for r in rows):
            raise HTTPException(422, '미래 관측값을 입력할 수 없습니다.')
        if body.replay_id:
            replay = service.store.get('replay', body.replay_id)
            if rows[-1]['date'] > replay['as_of']:
                raise HTTPException(422, '재생 시계 이후 입력을 사용할 수 없습니다.')
        model = next((m for m in service.manager(namespace).list_models() if m['district_code'] == code), None)
        if model and model.get('trained_through') and rows[-1]['date'] < model['trained_through']:
            raise HTTPException(422, '현재 모델 학습일 이전 입력으로 과거 예측을 재계산하지 않습니다.')
        replay_start = (model or {}).get('splits', {}).get('replay', {}).get('start')
        if replay_start and rows[-1]['date'] < (date.fromisoformat(replay_start)-timedelta(days=1)).isoformat():
            raise HTTPException(422, '학습·검증·테스트 이후 입력이 필요합니다.')
        try:
            return service.manager(namespace).predict(code, rows)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.post('/api/v1/jobs/train', status_code=202, tags=['jobs'])
    def train(body: TrainRequest):
        if body.district_code:
            checked_code(body.district_code)
        return service.train_job(body.dataset_id, body.district_code)

    @router.get('/api/v1/jobs', tags=['jobs'])
    def jobs(replay_id: str | None = None, all_namespaces: bool = False):
        namespace = replay_id or service.default_namespace()
        if replay_id:
            service.store.get('replay',replay_id)
        def in_scope(job):
            payload = job['payload']
            if payload.get('replay_id') or payload.get('namespace'):
                return payload.get('replay_id',payload.get('namespace')) == namespace
            if payload.get('dataset_id'):
                return service.store.get('dataset',payload['dataset_id']).get('namespace','historical') == namespace
            return False
        candidates={j['id']:j for j in service.store.jobs()}
        if not all_namespaces:
            candidates.update({j['id']:j for j in service.store.jobs(namespace)})
        return {'jobs':sorted([j for j in candidates.values() if all_namespaces or in_scope(j)],key=lambda j:j['created_at'],reverse=True)[:100],'namespace':namespace}

    @router.get('/api/v1/jobs/{job_id}', tags=['jobs'])
    def job(job_id: str):
        return service.store.job(job_id)

    @router.post('/api/v1/jobs/{job_id}/retry', status_code=202, tags=['jobs'])
    def retry(job_id: str):
        old = service.store.job(job_id)
        if old['status'] not in ('failed', 'interrupted'):
            raise HTTPException(409, '실패·중단 작업만 재시도할 수 있습니다.')
        return service.store.enqueue(old['kind'], old['payload'], old['scope'])

    @router.get('/api/v1/models', tags=['models'])
    def models(replay_id: str | None = None):
        if replay_id:
            service.store.get('replay', replay_id)
        return {'models': service.manager(replay_id or service.default_namespace()).list_models()}

    @router.post('/api/v1/models/{code}/rollback', status_code=202, tags=['models'])
    def rollback(code: str, body: ReasonRequest, replay_id: str | None = None):
        checked_code(code)
        if replay_id:
            service.store.get('replay', replay_id)
        namespace = replay_id or service.default_namespace()
        return service.store.enqueue('rollback', {'district_code': code, 'version': body.version,
            'reason': body.reason, 'namespace': namespace}, f'model:{namespace}:{code}')

    @router.get('/api/v1/events', tags=['events'])
    def events(replay_id: str | None = None, all_namespaces: bool = False):
        namespace = replay_id or service.default_namespace()
        if replay_id:
            service.store.get('replay',replay_id)
        return {'events':[e for e in service.store.list('event') if all_namespaces or e.get('namespace') == namespace], 'namespace':namespace}

    def transition(event_id, body, status):
        event = service.store.get('event', event_id)
        if event['status'] in ('RESOLVED','RECORDED'):
            raise HTTPException(409, '이미 해제한 이벤트입니다.')
        event.update(status=status, reason=body.reason, updated_at=now())
        return service.store.put('event', event)

    @router.post('/api/v1/events/{event_id}/ack', tags=['events'])
    def acknowledge(event_id: str, body: ReasonRequest):
        return transition(event_id, body, 'ACKNOWLEDGED')

    @router.post('/api/v1/events/{event_id}/resolve', tags=['events'])
    def resolve(event_id: str, body: ReasonRequest):
        return transition(event_id, body, 'RESOLVED')

    @router.get('/api/v1/replays', tags=['replays'])
    def replays():
        return {'replays': service.store.list('replay')}

    @router.post('/api/v1/replays', status_code=202, tags=['replays'])
    def create_replay(body: ReplayRequest):
        return service.create_replay(**body.model_dump(mode='json'))

    @router.post('/api/v1/replays/{replay_id}/advance', status_code=202, tags=['replays'])
    def advance(replay_id: str, body: AdvanceRequest):
        return service.advance_job(replay_id, body.days)

    return router
