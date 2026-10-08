"""Weather display tests with explicit missing/zero values, not model performance."""
import json
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from serving_app.rainfall_network import RainfallNetwork
from serving_app.national_api import router_for


def fixture(tmp_path):
    path=tmp_path/'rain.json'
    path.write_text(json.dumps({'source_kind':'observed','unit':'mm','source':'TEST FIXTURE',
        'source_url':'https://example.org','collected_at':'2026-10-08T00:00:00Z',
        'available_dates':['2026-07-01','2026-07-02'],
        'stations':[{'station_id':'a','name':'A','latitude':35.,'longitude':127.},
                    {'station_id':'b','name':'B','latitude':36.,'longitude':128.}],
        'observations':[{'station_id':'a','date':'2026-07-01','rainfall_mm':0},
                        {'station_id':'a','date':'2026-07-02','rainfall_mm':10}]}))
    return RainfallNetwork(path)


def test_zero_missing_dates_and_model_readiness_are_independent(tmp_path):
    weather=fixture(tmp_path)
    day=weather.network('2026-07-01')
    assert day['counts']=={'stations':2,'observed':1,'missing':1,'zero':1}
    assert day['stations'][1]['rainfall_mm'] is None
    assert all(s['model_ready'] is False for s in day['stations'])
    assert weather.history('b')['history'][0]['quality_status']=='missing'
    with pytest.raises(LookupError):weather.network('2026-07-03')
    with pytest.raises(KeyError):weather.history('unknown')


def test_weather_http_status_and_boundary_contract(monkeypatch,tmp_path):
    weather=fixture(tmp_path)
    monkeypatch.setattr('serving_app.national_api.RainfallNetwork',lambda:weather)
    app=FastAPI(); app.include_router(router_for(SimpleNamespace(root=tmp_path/'runtime'/'national')))
    with TestClient(app) as client:
        assert client.get('/api/v2/rainfall/network').status_code==200
        assert client.get('/api/v2/rainfall/network?date=bad').status_code==422
        assert client.get('/api/v2/rainfall/network?date=2026-07-03').status_code==404
        assert client.get('/api/v2/rainfall/stations/unknown/history').status_code==404
        boundary=client.get('/api/v2/rainfall/boundary')
        assert boundary.status_code==200
        assert boundary.json()['features'][0]['geometry']['type']=='MultiPolygon'


def test_daily_feed_isolation_and_instant_snapshot_are_separate(monkeypatch,tmp_path):
    asos=fixture(tmp_path)
    daily_path=tmp_path/'national_aws_daily.json'
    data=asos.load()
    data['available_dates']=['2026-10-07']
    data['stations']=[{'station_id':'aws-1','name':'TEST AWS','latitude':35.,'longitude':127.}]
    data['observations']=[{'station_id':'aws-1','date':'2026-10-07','rainfall_mm':0}]
    daily_path.write_text(json.dumps(data))
    (tmp_path/'national_aws_snapshot.json').write_text(json.dumps({
        'temporal_contract':'minute_snapshot_accumulations_not_completed_daily_rainfall',
        'observed_at':'2026-10-07T12:00:00+09:00','observations':[]}))
    monkeypatch.setattr('serving_app.national_api.DATA',tmp_path)
    monkeypatch.setattr('serving_app.national_api.RainfallNetwork',lambda path=None:RainfallNetwork(path) if path else asos)
    app=FastAPI();app.include_router(router_for(SimpleNamespace(root=tmp_path/'runtime'/'national')))
    with TestClient(app) as client:
        day=client.get('/api/v2/rainfall/aws-daily/network').json()
        assert day['counts']=={'stations':1,'observed':1,'missing':0,'zero':1}
        assert day['stations'][0]['station_id']=='aws-1'
        assert client.get('/api/v2/rainfall/aws-daily/stations/a/history').status_code==404
        assert client.get('/api/v2/rainfall/stations/aws-1/history').status_code==404
        assert client.get('/api/v2/rainfall/aws-daily/network?date=2026-07-01').status_code==404
        instant=client.get('/api/v2/rainfall/aws-snapshot').json()
        assert instant['temporal_contract']=='minute_snapshot_accumulations_not_completed_daily_rainfall'


def test_runtime_weather_priority_fallback_and_failed_refresh_last_good(monkeypatch,tmp_path):
    from serving_app.weather_worker import WeatherCollector
    from tests.test_weather_worker import FakeWeather
    from datetime import timedelta
    bundled = tmp_path/'bundled'
    bundled.mkdir()
    asos = fixture(bundled)
    (bundled/'national_aws_daily.json').write_text(json.dumps(asos.load()))
    (bundled/'national_aws_snapshot.json').write_text(json.dumps({'observed_at':'BUNDLED TEST ONLY'}))
    monkeypatch.setattr('serving_app.national_api.DATA',bundled)
    monkeypatch.setattr('serving_app.national_api.RainfallNetwork',lambda path=None:RainfallNetwork(path) if path else asos)
    monkeypatch.setenv('KMA_APIHUB_KEY','TEST-SECRET')
    state_root = tmp_path/'runtime'
    service = SimpleNamespace(root=state_root/'national')
    metadata = tmp_path/'test-metadata.csv'
    metadata.write_text('Synthetic fixture only')
    fake = FakeWeather()

    def daily(*args):
        result = fake.daily(*args)
        return {**result,'source':'TEST AWS RUNTIME','source_url':'https://example.org',
            'collected_at':fake.instant.isoformat(),'stations':[{'station_id':'test-aws-runtime'}],
            'observations':[{'station_id':'test-aws-runtime','date':result['available_dates'][0], 'rainfall_mm':0.}]}

    collector = WeatherCollector(state_root,enabled=True,metadata_path=metadata,clock=lambda:fake.instant,
        snapshot_fetch=fake.snapshot,daily_fetch=daily)
    app = FastAPI()
    app.include_router(router_for(service))
    with TestClient(app) as client:
        assert client.get('/api/v2/rainfall/collection-status').json()['status'] == 'not_started'
        assert client.get('/api/v2/rainfall/aws-snapshot').json()['observed_at'] == 'BUNDLED TEST ONLY'
        assert client.get('/api/v2/rainfall/aws-daily/network').json()['date'] == '2026-07-02'
        collector.tick()
        assert client.get('/api/v2/rainfall/collection-status').json()['status'] == 'ready'
        assert client.get('/api/v2/rainfall/aws-daily/network').json()['stations'][0]['station_id'] == 'test-aws-runtime'
        instant = client.get('/api/v2/rainfall/aws-snapshot').json()
        assert instant['observed_at'] == '2026-10-08T11:20:00+09:00'
        fake.fail = True
        fake.instant += timedelta(minutes=10)
        collector.tick()
        # Failure changes status, preserving the last good runtime observation.
        assert client.get('/api/v2/rainfall/aws-snapshot').json() == instant
        status = client.get('/api/v2/rainfall/collection-status').json()
        assert status['status'] == 'degraded' and status['streams']['snapshot']['status'] == 'failed'
        assert 'TEST-SECRET' not in json.dumps(status)
        assert client.get('/api/v2/rainfall/aws-daily/network').json()['date'] == '2026-10-07'
        assert client.get('/api/v2/rainfall/network').json()['date'] == '2026-07-02'


def test_gzip_history_uses_same_day_coordinates_and_runtime_replaces_only_its_day(tmp_path):
    import gzip
    base=fixture(tmp_path).load()
    base['available_dates']=['2026-07-01','2026-07-02']
    base['stations']=[{'station_id':'a','name':'A'}]
    base['station_metadata_by_date']={
        day:[{'station_id':'a','name':'A','latitude':lat,'longitude':127.}]
        for day,lat in [('2026-07-01',35.),('2026-07-02',36.)]}
    base['observations']=[{'station_id':'a','date':'2026-07-01','rainfall_mm':0},
                          {'station_id':'a','date':'2026-07-02','rainfall_mm':2}]
    archive=tmp_path/'history.json.gz'
    archive.write_bytes(gzip.compress(json.dumps(base).encode(),mtime=0))
    fresh={**base,'available_dates':['2026-07-02'],
           'stations':[{'station_id':'a','name':'A','latitude':37.,'longitude':127.}],
           'observations':[{'station_id':'a','date':'2026-07-02','rainfall_mm':3}]}
    fresh.pop('station_metadata_by_date')
    latest=tmp_path/'latest.json';latest.write_text(json.dumps(fresh))
    reader=RainfallNetwork(archive,additional_path=latest)
    assert reader.network('2026-07-01')['stations'][0]['latitude']==35.
    assert reader.network()['stations'][0]['latitude']==37.
    assert [r['rainfall_mm'] for r in reader.history('a')['history']]==[0,3]
