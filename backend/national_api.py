"""Additive station routes, separate from the fixed Seoul v1 contract."""
from datetime import date
import json
from backend.rainfall_network import RainfallNetwork, DATA
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class StationInput(StrictBody):
    station_id: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=100)
    source_station_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    region_code: str = Field(min_length=1, max_length=100)
    level_unit: str = Field(min_length=1, max_length=100)
    level_reference: str = Field(min_length=1, max_length=200)
    verified: bool = False
    source_contract_verified: bool = False
    mapping_status: Literal['unverified', 'experimental', 'approved'] = 'unverified'
    operational_approved: bool | None = None
    mapping_version: str | None = None
    evidence: list[str] = Field(default_factory=list)
    source_kind: Literal['observed', 'synthetic'] = 'observed'
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    rainy_region: str | None = None


class ObservationInput(StrictBody):
    station_id: str | None = None
    date: date
    groundwater_level: float
    rainfall_mm: float = Field(ge=0)
    level_unit: str
    level_reference: str
    available_at: str
    collected_at: str
    revision_id: str
    quality_status: Literal['valid', 'invalid', 'missing'] = 'valid'
    source_sha256: str
    source_revisions: list[str] = Field(default_factory=list)


class ObservationBatch(StrictBody):
    rows: list[ObservationInput] = Field(min_length=1, max_length=10000)


class TrainInput(StrictBody):
    variant: Literal['M0', 'M1'] = 'M0'
    validation_targets: int | None = Field(default=None, ge=21, le=3650)
    holdout_targets: int | None = Field(default=None, ge=30, le=3650)
    max_epochs: int | None = Field(default=None, ge=1, le=100)


class PredictInput(StrictBody):
    input_end_date: date | None = None


class RainyPeriodInput(StrictBody):
    year: int = Field(ge=1900, le=2200)
    region_code: str
    start_date: date
    end_date: date
    source_sha256: str
    evidence: list[str] = Field(min_length=1)


class CandidateInput(StrictBody):
    version: str = Field(min_length=1, max_length=100)


class RollbackInput(CandidateInput):
    reason: str = Field(min_length=1, max_length=1000)


def router_for(service):
    router = APIRouter(prefix='/api/v2', tags=['national-stations'])

    weather = RainfallNetwork()

    def weather_path(name):
        live = service.root.parent / "weather" / name
        return live if live.exists() else DATA / name

    def aws_daily_reader():
        history = DATA / 'national_aws_history.json.gz'
        latest = weather_path('national_aws_daily.json')
        return RainfallNetwork(history, additional_path=latest) if history.exists() else RainfallNetwork(latest)

    @router.get('/rainfall/network')
    def rainfall_network(date: date | None = None):
        try:
            return weather.network(date.isoformat() if date else None)
        except LookupError:
            raise HTTPException(404, '확보하지 않은 관측 날짜입니다.')
        except ValueError as exc:
            raise HTTPException(503, str(exc))

    @router.get('/rainfall/stations/{station_id}/history')
    def rainfall_history(station_id: str):
        try:
            return weather.history(station_id)
        except KeyError:
            raise HTTPException(404, '기상 관측지점을 찾을 수 없습니다.')
        except ValueError as exc:
            raise HTTPException(503, str(exc))

    @router.get('/rainfall/boundary')
    def rainfall_boundary():
        path = DATA / 'korea_display_boundary.geojson'
        if not path.exists():
            raise HTTPException(503, '지도 배경 자료가 없습니다.')
        return json.loads(path.read_text())

    @router.get('/rainfall/aws-daily/network')
    def aws_daily_network(date: date | None = None):
        try:
            return aws_daily_reader().network(date.isoformat() if date else None)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get('/rainfall/aws-daily/stations/{station_id}/history')
    def aws_daily_history(station_id: str):
        try:
            return aws_daily_reader().history(station_id)
        except KeyError as exc:
            raise HTTPException(404, '확보하지 않은 관측소입니다.') from exc
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get('/rainfall/aws-snapshot')
    def aws_snapshot():
        path = weather_path('national_aws_snapshot.json')
        if not path.exists():
            raise HTTPException(503, 'AWS 시간 강수 자료가 없습니다.')
        return json.loads(path.read_text())

    @router.get('/rainfall/collection-status')
    def weather_collection_status():
        path = service.root.parent / 'weather' / 'weather_state.json'
        return json.loads(path.read_text()) if path.exists() else {'enabled': False, 'status': 'not_started', 'streams': {}}

    @router.get('/weather/warning-status')
    def warning_status():
        path = DATA / 'national_warning_status.json'
        if not path.exists():
            raise HTTPException(503, '특보 응답 검증 자료가 없습니다.')
        return json.loads(path.read_text())

    @router.get('/weather/forecast-sample')
    def forecast_sample():
        path = DATA / 'national_forecast_sample.json'
        if not path.exists():
            raise HTTPException(503, '강수 예보 샘플 검증 자료가 없습니다.')
        return json.loads(path.read_text())

    @router.get('/groundwater/samples')
    def groundwater_samples():
        path = DATA / 'national_groundwater_samples.json'
        if not path.exists():
            raise HTTPException(503, '전국 지하수 실측 샘플 자료가 없습니다.')
        return json.loads(path.read_text())

    @router.get('/groundwater/catalog')
    def groundwater_catalog():
        path = DATA / 'national_stations_gims.json'
        if not path.exists():
            raise HTTPException(503, '전국 지하수 관측소 목록이 없습니다.')
        return json.loads(path.read_text())

    @router.get('/sources')
    def sources():
        return {'scope': 'national_observed_v1', 'status': 'observations_collected_models_not_approved',
                'sources': [
                    {'name': '국가지하수', 'status': 'raw_samples_collected_station_validation_required'},
                    {'name': '기상청 ASOS', 'status': 'bundled_observations_collected'},
                    {'name': '장마 통계', 'status': 'bundled_historical_file'},
                    {'name': 'AWS 관측 강수', 'status': 'observations_collected_refresh_opt_in'},
                    {'name': '강수 예보', 'status': 'sample_response_collected_grid_mapping_required'},
                    {'name': '호우특보', 'status': 'empty_response_semantics_unverified'}],
                'note': '제공 경로 확인과 실제 자료 확보·전국 예측 준비는 다릅니다.'}

    @router.get('/stations')
    def stations(region_code: str | None = None, verified: bool | None = None,
                 cursor: str | None = None, limit: int = Query(50, ge=1, le=200)):
        return service.repo.list_stations(region_code=region_code, verified=verified, cursor=cursor, limit=limit)

    @router.post('/stations', status_code=201)
    def register(body: StationInput):
        return service.repo.register_station(body.model_dump())

    @router.get('/stations/{station_id}')
    def station(station_id: str):
        return service.station(station_id)

    @router.post('/stations/{station_id}/observations', status_code=201)
    def observations(station_id: str, body: ObservationBatch):
        service.station(station_id)
        if any(r.station_id is not None and r.station_id != station_id for r in body.rows):
            raise HTTPException(422, '관측소 식별자가 경로와 다릅니다.')
        # Validate the entire batch before writing so rejected batches are atomic.
        return service.repo.add_observations(station_id, [r.model_dump(mode='json', exclude_none=True) for r in body.rows])

    @router.get('/stations/{station_id}/history')
    def history(station_id: str, start: date | None = None, end: date | None = None):
        service.station(station_id)
        if start and end and start > end:
            raise HTTPException(422, '시작일은 종료일보다 늦을 수 없습니다.')
        return {'station_id': station_id, 'history': service.repo.observations(
            station_id, start.isoformat() if start else None, end.isoformat() if end else None)}

    @router.get('/stations/{station_id}/pipeline')
    def pipeline(station_id: str):
        return service.pipeline(station_id)

    @router.get('/stations/{station_id}/forecast')
    def forecast(station_id: str, target_date: date | None = None):
        rows = service.forecasts(station_id)
        rows = [r for r in rows if target_date is None or r['target_date'] == target_date.isoformat()]
        if not rows:
            raise HTTPException(503, '검증된 발행 예측이 없습니다.')
        return max(rows, key=lambda r: r['issued_at'])

    @router.post('/stations/{station_id}/training-jobs', status_code=202)
    def train(station_id: str, body: TrainInput):
        return service.enqueue('train', station_id, **body.model_dump(exclude_none=True))

    @router.post('/stations/{station_id}/fine-tuning-jobs', status_code=202)
    def fine_tune(station_id: str):
        return service.enqueue('fine_tune', station_id)

    @router.post('/stations/{station_id}/evaluation-jobs', status_code=202)
    def evaluate(station_id: str, body: CandidateInput):
        return service.enqueue('evaluate', station_id, version=body.version)

    @router.post('/stations/{station_id}/promotion-jobs', status_code=202)
    def promote(station_id: str, body: CandidateInput):
        return service.enqueue('promote', station_id, version=body.version)

    @router.post('/stations/{station_id}/rollback-jobs', status_code=202)
    def rollback(station_id: str, body: RollbackInput):
        return service.enqueue('rollback', station_id, **body.model_dump())

    @router.post('/stations/{station_id}/prediction-jobs', status_code=202)
    def predict(station_id: str, body: PredictInput):
        return service.enqueue('predict', station_id,
                               input_end_date=body.input_end_date.isoformat() if body.input_end_date else None)

    @router.get('/jobs/{job_id}')
    def job(job_id: str):
        return service.store.job(job_id)

    @router.post('/jobs/{job_id}/retry', status_code=202)
    def retry(job_id: str):
        old = service.store.job(job_id)
        if old['status'] not in ('failed', 'interrupted'):
            raise HTTPException(409, '실패·중단 작업만 다시 요청할 수 있습니다.')
        p = dict(old['payload'])
        station_id = p.pop('station_id')
        return service.enqueue(old['kind'], station_id, **p)

    @router.get('/rainy-periods')
    def rainy_periods(year: int | None = Query(None, ge=1900, le=2200), region_code: str | None = None):
        return {'items': service.repo.rainy_periods(year, region_code)}

    @router.post('/rainy-periods', status_code=201)
    def register_rainy_period(body: RainyPeriodInput):
        return service.repo.add_rainy_period(body.model_dump(mode='json'))

    return router
