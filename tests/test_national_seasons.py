"""Synthetic fixtures check time separation, never real seasonal performance."""
import json
from datetime import date,timedelta
from types import SimpleNamespace
import pytest
from scripts.evaluate_national_seasons import run,chronological_split
from serving_app.national_models import NationalModelManager
from tests.test_national_models import LearnedDeltaBackend


def fixture():
    metadata={'station_id':'kwater-1','name':'시험','source_kind':'observed','verified':False,
        'source_contract_verified':True,'mapping_status':'experimental','operational_approved':False,
        'mapping_version':'fixture-v1','evidence':['synthetic contract test'],
        'level_unit':'m','level_reference':'elevation'}
    rows=[{'station_id':'kwater-1','date':(date(2026,1,1)+timedelta(days=i)).isoformat(),
        'groundwater_level':i*.01,'rainfall_mm':float(i%5)} for i in range(280)]
    labels={r['date']:['rainy' if '2026-07-01'<=r['date']<='2026-07-26' else 'non_rainy'] for r in rows}
    service=SimpleNamespace(repo=SimpleNamespace(list_stations=lambda **kw:{'items':[metadata],'next_cursor':None},
        observations=lambda sid:rows),seasonal_labels=lambda sid,records:labels)
    return service,rows


def test_same_heldout_dates_and_no_operational_store_writes(tmp_path):
    service,rows=fixture()
    rows[-1]['rainfall_mm']=100000.
    factory=lambda path:NationalModelManager(path,LearnedDeltaBackend())
    result=run(service,tmp_path,manager_factory=factory)
    assert result['status']=='completed'
    assert result['evaluation_mode']=='retrospective'
    assert result['operational_promotion_evidence'] is False
    entry=result['stations'][0]
    assert entry['split']['train_end']=='2026-05-31'
    for variant in ('M0','M1'):
        evaluated=entry['variants'][variant]
        assert evaluated['evaluation']['start']=='2026-07-01'
        assert evaluated['evaluation']['end']=='2026-10-07'
        assert evaluated['comparisons']['overall']['model']['count']==99
        assert evaluated['comparisons']['rainy']['model']['count']==26
        assert evaluated['comparisons']['non_rainy']['model']['count']==73
        assert evaluated['heavy_rain_threshold_mm']==4.
    bundles=list((tmp_path/'seasonal-evaluations').glob('*/national_observed_v1/*/*/bundle.json'))
    assert len(bundles)==2
    for path in bundles:
        bundle=json.loads(path.read_text())
        assert bundle['scaler']['fit_through']=='2026-05-31'
        assert bundle['scaler']['maximum'][1]==4.
        assert bundle['training_target_ranges']==[['2026-01-21','2026-05-31']]
    def cannot_retrain(path):
        manager=factory(path)
        manager.train=lambda *a,**kw:pytest.fail('completed unchanged experiment retrained')
        return manager
    assert run(service,tmp_path,manager_factory=cannot_retrain)['status']=='completed'
    assert not (tmp_path/'national').exists()  # no registry/job/issued-prediction state


def test_split_rejects_missing_or_duplicate_days():
    _,rows=fixture()
    with pytest.raises(ValueError):chronological_split(rows[:-1])
    rows[100]['date']=rows[99]['date']
    with pytest.raises(ValueError):chronological_split(rows)


def test_failed_unchanged_source_is_not_retrained_automatically(tmp_path):
    service,_=fixture()
    class FailingManager:
        def train(self,*args,**kwargs):raise RuntimeError('synthetic controlled failure')
    result=run(service,tmp_path,manager_factory=lambda path:FailingManager())
    assert result['status']=='partial'
    assert result['stations'][0]['status']=='failed'
    def must_not_run(path):pytest.fail('unchanged failed experiment retried')
    again=run(service,tmp_path,manager_factory=must_not_run)
    assert again['stations'][0]['status']=='failed'


def test_multiyear_synthetic_comparison_has_same_frozen_holdout_and_separate_namespace(tmp_path):
    metadata={'station_id':'sim-gims-test','name':'합성 시험','source_kind':'synthetic','verified':False,
        'source_contract_verified':True,'mapping_status':'synthetic','operational_approved':False,
        'mapping_version':'synthetic-v1','evidence':['synthetic generator test'],
        'level_unit':'m','level_reference':'elevation'}
    begin=date(2022,1,1);finish=date(2025,12,31)
    rows=[{'station_id':metadata['station_id'],'date':(begin+timedelta(days=i)).isoformat(),
        'source_kind':'synthetic','groundwater_level':10+.01*i,
        'rainfall_mm':50. if i%10==0 else float(i%3)} for i in range((finish-begin).days+1)]
    labels={r['date']:['rainy' if '-06-15'<=r['date'][4:]<='-07-25' else 'non_rainy'] for r in rows}
    svc=SimpleNamespace(repo=SimpleNamespace(list_stations=lambda **kw:{'items':[metadata],'next_cursor':None},
        observations=lambda sid:rows),seasonal_labels=lambda sid,records:labels)
    factory=lambda path:NationalModelManager(path,LearnedDeltaBackend(),namespace='national_synthetic_v1',source_kind='synthetic')
    split={'start':'2022-01-01','train_end':'2023-12-31','validation_end':'2024-03-31','holdout_end':'2025-12-31'}
    svc.seasonal_labels=lambda *a:pytest.fail('synthetic scenario used official seasonal labels')
    result=run(svc,tmp_path,manager_factory=factory,source_kind='synthetic',split_config=split)
    assert result['status']=='completed'
    assert result['source_kind']=='synthetic' and result['simulation'] is True
    assert result['namespace']=='national_synthetic_v1'
    assert result['seasonal_label_scope']=='synthetic_scenario'
    assert result['operational_promotion_evidence'] is False
    assert (tmp_path/'synthetic_seasonal_evaluation.json').exists()
    assert not (tmp_path/'seasonal_evaluation.json').exists()
    entry=result['stations'][0]
    assert entry['split']['holdout_targets']==640
    for variant in ('M0','M1'):
        evaluation=entry['variants'][variant]['evaluation']
        assert evaluation['start']=='2024-04-01' and evaluation['end']=='2025-12-31'
        assert evaluation['metrics']['count']==640
        assert evaluation['groups']['rainy']['count']==72
        assert evaluation['groups']['non_rainy']['count']==568
        assert all(evaluation['groups'][g]['count']>=30 for g in ('rainy','non_rainy','heavy_rain'))
    bundles=list((tmp_path/'synthetic-seasonal-evaluations').glob('*/national_synthetic_v1/*/*/bundle.json'))
    assert len(bundles)==2
    for path in bundles:
        bundle=json.loads(path.read_text())
        assert bundle['scaler']['fit_through']=='2023-12-31'
        assert bundle['source_kind']=='synthetic'
        assert bundle['operational_approved'] is False


def test_variant_budget_resumes_completed_models_without_retraining(tmp_path):
    service,_=fixture()
    factory=lambda path:NationalModelManager(path,LearnedDeltaBackend())
    first=run(service,tmp_path,manager_factory=factory,max_variants=1)
    assert first['status']=='running'
    m0=first['stations'][0]['variants']['M0']['model_version']
    assert 'M1' not in first['stations'][0]['variants']
    second=run(service,tmp_path,manager_factory=factory,max_variants=1)
    assert second['status']=='running'
    assert second['stations'][0]['variants']['M0']['model_version']==m0
    assert second['stations'][0]['variants']['M1']['status']=='completed'
    final=run(service,tmp_path,manager_factory=factory,max_variants=1)
    assert final['status']=='completed'
    assert len(list((tmp_path/'seasonal-evaluations').glob('*/national_observed_v1/*/*/bundle.json')))==2


def test_interrupted_seasonal_variant_is_retained_without_automatic_retry(tmp_path):
    from scripts.evaluate_national_seasons import mark_interrupted
    service,_=fixture()
    factory=lambda path:NationalModelManager(path,LearnedDeltaBackend())
    first=run(service,tmp_path,manager_factory=factory,max_variants=1)
    first['stations'][0]['variants']['M1']={'status':'running'}
    path=tmp_path/'seasonal_evaluation.json';path.write_text(json.dumps(first))
    mark_interrupted(path)
    marked=json.loads(path.read_text())
    assert marked['status']=='interrupted'
    assert marked['stations'][0]['variants']['M0']['status']=='completed'
    assert marked['stations'][0]['variants']['M1']['status']=='interrupted'
    def may_not_retrain(path):pytest.fail('interrupted seasonal work retried')
    result=run(service,tmp_path,manager_factory=may_not_retrain,max_variants=1)
    assert result['stations'][0]['status']=='interrupted'


def test_new_experiment_archives_interrupted_report_immutably(tmp_path):
    from scripts.evaluate_national_seasons import mark_interrupted
    service,_=fixture()
    factory=lambda path:NationalModelManager(path,LearnedDeltaBackend())
    first=run(service,tmp_path,max_epochs=1,manager_factory=factory,max_variants=1)
    path=tmp_path/'seasonal_evaluation.json'
    mark_interrupted(path)
    historical=json.loads(path.read_text())
    new=run(service,tmp_path,max_epochs=2,manager_factory=factory)
    assert new['status']=='completed' and new['max_epochs']==2
    archives=list((tmp_path/'seasonal-evaluation-reports'/'seasonal_evaluation').glob('*.json'))
    assert len(archives)==1
    assert json.loads(archives[0].read_text())==historical
    assert historical['status']=='interrupted'
    original=archives[0].read_bytes()
    run(service,tmp_path,max_epochs=2,manager_factory=factory)
    assert archives[0].read_bytes()==original
