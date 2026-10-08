"""Service fixtures are synthetic; exercise observed contracts, not data evidence."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from serving_app.national_models import NationalModelManager
from serving_app.national_service import NationalService
from tests.test_national_models import LearnedDeltaBackend


STATION = {'station_id':'test-national-one','provider':'SYNTHETIC-TEST-FIXTURE',
    'source_station_id':'test-one','name':'TEST ONLY','region_code':'test',
    'level_unit':'m','level_reference':'ground_surface_signed','verified':True,
    'source_kind':'observed','evidence':['Synthetic fixture exercising observed contract only']}


def rows(count=160):
    first = date(2020,1,1)
    return [{'station_id':STATION['station_id'],'date':(first+timedelta(days=i)).isoformat(),
             'groundwater_level':-5+i*.01,'rainfall_mm':float(i%4),
             'level_unit':'m','level_reference':'ground_surface_signed',
             'revision_id':f'TEST-{i}','source_sha256':'synthetic-test-only',
             'available_at':(first+timedelta(days=i+1)).isoformat()+'T00:00:00+09:00',
             'collected_at':(first+timedelta(days=i+1)).isoformat()+'T00:00:00+09:00',
             'quality_status':'valid'} for i in range(count)]


def clock(day):
    current = date(2020,1,1)+timedelta(days=day)
    return patch.multiple('serving_app.national_service',
        kst_today=lambda:current, now=lambda:current.isoformat()+'T11:30:00+09:00')


def service(tmp_path, count=160):
    manager = NationalModelManager(tmp_path/'models',LearnedDeltaBackend())
    result = NationalService(tmp_path,manager)
    result.repo.register_station(STATION)
    result.repo.add_observations(STATION['station_id'],rows(count))
    return result


def train(svc):
    job = svc.enqueue('train',STATION['station_id'])
    svc.execute_one()
    result = svc.store.job(job['id'])
    assert result['status'] == 'completed', result
    return result['result']


def test_training_uses_latest_contiguous_block_and_failed_scope_releases(tmp_path):
    svc = service(tmp_path,180)
    missing = rows(180)
    missing[10]['quality_status'] = 'invalid'
    selected = svc.contiguous_segment(missing,STATION)
    assert selected[0]['date'] == missing[11]['date'] and len(selected) == 169
    with clock(180):
        trained = train(svc)
    assert trained['status'] == 'active'
    assert len(svc.manager.list_models(STATION['station_id'])) == 1


def test_prediction_retry_does_not_reconstruct_candidate_issuance(tmp_path):
    svc = service(tmp_path)
    with clock(160):
        train(svc)
        job = svc.enqueue('predict',STATION['station_id'])
        svc.execute_one()
        assert svc.store.job(job['id'])['status'] == 'completed'
        original = svc.forecasts(STATION['station_id'])[0]
        # A candidate created after incumbent issuance must not acquire fake
        # paired evidence by retrying that incumbent's stored prediction.
        train(svc)
        repeated = svc.enqueue('predict',STATION['station_id'])
        svc.execute_one()
        assert svc.store.job(repeated['id'])['status'] == 'completed'
        assert svc.store.list('paired_prediction') == []
        assert svc.forecasts(STATION['station_id'])[0]['issued_at'] == original['issued_at']


def test_pair_proofs_first_thirty_and_gap_is_not_bridged(tmp_path):
    svc = service(tmp_path)
    all_rows = rows(200)
    for i in range(160,195):
        svc.store.put('paired_prediction',{'station_id':STATION['station_id'],
            'target_date':all_rows[i]['date'],'candidate_version':'candidate-test',
            'champion_version':'champion-test','issued_at':all_rows[i]['date']+'T00:00:00+09:00'})
    proofs = svc.issuance_proofs(STATION['station_id'],'candidate-test',all_rows)
    assert len(proofs) == 30
    assert proofs[0]['target_date'] == all_rows[160]['date']
    assert proofs[-1]['target_date'] == all_rows[189]['date']
    del all_rows[180]
    assert svc.contiguous_segment(all_rows,STATION)[0]['date'] == rows(200)[181]['date']


def test_live_monitor_atomic_trigger_and_pending_candidate_block(tmp_path):
    svc = service(tmp_path,182)
    with clock(160):
        initial = train(svc)
    for row in rows(182)[160:]:
        svc.store.put('prediction', {'station_id':STATION['station_id'],'model_version':initial['version'],
            'target_date':row['date'],'prediction':row['groundwater_level']-2,
            'issued_at':row['date']+'T00:00:00+09:00','mode':'live'})
    with clock(182):
        monitor = svc.monitor_station(STATION['station_id'])
        assert monitor['trigger']
        jobs = [j for j in svc.store.jobs() if j['kind'] == 'fine_tune']
        assert len(jobs) == 1
        assert jobs[0]['payload']['input_end_date'] == rows(182)[-1]['date']
        svc.monitor_station(STATION['station_id'])
        assert len([j for j in svc.store.jobs() if j['kind'] == 'fine_tune']) == 1
        svc.execute_one()
        assert svc.store.job(jobs[0]['id'])['status'] == 'completed'
        assert len(svc.pending_candidates(STATION['station_id'])) == 1
        duplicate = svc.enqueue('fine_tune',STATION['station_id'])
        svc.execute_one()
        assert svc.store.job(duplicate['id'])['status'] == 'failed'


def test_scheduler_requires_ready_observed_station_and_is_idempotent(tmp_path):
    svc = service(tmp_path)
    with clock(160):
        assert svc.schedule_once('2020-06-09T11:00:00+09:00') == []
        assert svc.schedule_once('2020-06-09T11:30:00+09:00') == []  # No automatic initial train.
        train(svc)
        scheduled = svc.schedule_once('2020-06-09T11:30:00+09:00')
        assert len(scheduled) == 1 and scheduled[0]['kind'] == 'predict'
        assert svc.schedule_once('2020-06-09T11:30:00+09:00') == []
        svc.execute_one()
        assert svc.schedule_once('2020-06-09T12:00:00+09:00') == []
    # Data stale for the next calendar day: no guessed prediction.
    with clock(161):
        assert svc.schedule_once('2020-06-10T11:30:00+09:00') == []


def test_synthetic_registry_cannot_execute_observed_jobs(tmp_path):
    svc = NationalService(tmp_path,NationalModelManager(tmp_path/'models',LearnedDeltaBackend()))
    synthetic = {**STATION,'source_kind':'synthetic'}
    svc.repo.register_station(synthetic)
    svc.repo.add_observations(STATION['station_id'],rows())
    with clock(160):
        job = svc.enqueue('train',STATION['station_id'])
        svc.execute_one()
        assert svc.store.job(job['id'])['status'] == 'failed'
        assert svc.manager.list_models(STATION['station_id']) == []


def experimental_service(tmp_path,count=182):
    station={**STATION,'verified':False,'source_contract_verified':True,'mapping_status':'experimental',
        'operational_approved':False,'mapping_version':'synthetic-experiment-v1'}
    svc=NationalService(tmp_path,NationalModelManager(tmp_path/'models',LearnedDeltaBackend()))
    svc.repo.register_station(station)
    svc.repo.add_observations(station['station_id'],rows(count))
    return svc


def test_experimental_auto_schedule_opt_in_and_scoped_genuine_pairs(tmp_path,monkeypatch):
    svc=experimental_service(tmp_path)
    with clock(160):
        train(svc);train(svc)
        monkeypatch.delenv('GROUNDWATCH_EXPERIMENTAL_MONITORING_ENABLED',raising=False)
        assert svc.schedule_once('2020-06-09T11:30:00+09:00')==[]
        monkeypatch.setenv('GROUNDWATCH_EXPERIMENTAL_MONITORING_ENABLED','true')
        scheduled=svc.schedule_once('2020-06-09T11:30:00+09:00')
        assert scheduled[0]['kind']=='predict'
        svc.execute_one()
        prediction=svc.forecasts(STATION['station_id'])[0]
        assert prediction['mode']=='live'
        assert prediction['prediction_scope']=='experimental'
        proofs=svc.store.list('paired_prediction')
        assert len(proofs)==1 and proofs[0]['prediction_scope']=='experimental'
        assert proofs[0]['horizon_days']==1
        assert proofs[0]['input_end_date']==rows(160)[-1]['date']
        assert svc.schedule_once('2020-06-09T12:00:00+09:00')==[]
    with clock(161):
        # A retrospective request is explicitly historical even for experiments.
        job=svc.enqueue('predict',STATION['station_id'],input_end_date=rows(160)[-2]['date'])
        svc.execute_one()
        assert svc.store.job(job['id'])['result']['mode']=='historical_replay'
        assert len(svc.store.list('paired_prediction'))==1


def test_experimental_monitor_requires_flag_and_never_mixes_operational_scope(tmp_path,monkeypatch):
    svc=experimental_service(tmp_path)
    with clock(160):initial=train(svc)
    for row in rows(182)[160:]:
        for scope in ('operational','experimental'):
            svc.store.put('prediction',{'station_id':STATION['station_id'],'model_version':initial['version'],
                'target_date':row['date'],'prediction':row['groundwater_level']-(2 if scope=='experimental' else 0),
                'issued_at':row['date']+'T00:00:00+09:00','mode':'live','prediction_scope':scope})
    with clock(182):
        monkeypatch.delenv('GROUNDWATCH_EXPERIMENTAL_MONITORING_ENABLED',raising=False)
        assert svc.monitor_station(STATION['station_id'])['status']=='experimental_monitoring_disabled'
        monkeypatch.setenv('GROUNDWATCH_EXPERIMENTAL_MONITORING_ENABLED','true')
        result=svc.monitor_station(STATION['station_id'])
        assert result['trigger'] and result['rmse']==2.
        assert result['state']['prediction_scope']=='experimental'
        labels=svc.store.list('national_label')
        assert len(labels)==22 and all(p['prediction_scope']=='experimental' for p in labels)
        assert len([j for j in svc.store.jobs() if j['kind']=='fine_tune'])==1
        svc.monitor_station(STATION['station_id'])
        assert len([j for j in svc.store.jobs() if j['kind']=='fine_tune'])==1


def test_later_revision_cannot_hide_label_already_available_at_issue(tmp_path):
    svc=service(tmp_path,182)
    with clock(160):initial=train(svc)
    target=rows(182)[160]
    revised={**target,'revision_id':'LATER-REVISION','groundwater_level':100.,
        'available_at':'2020-06-12T00:00:00+09:00','collected_at':'2020-06-12T00:00:00+09:00'}
    svc.repo.add_observation(STATION['station_id'],revised)
    svc.store.put('prediction',{'station_id':STATION['station_id'],'model_version':initial['version'],
        'target_date':target['date'],'prediction':0.,'issued_at':'2020-06-11T00:00:00+09:00','mode':'live'})
    with clock(182):
        assert svc.monitor_station(STATION['station_id'])['status']=='no_labelled_prediction'
        assert svc.store.list('national_label')==[]
