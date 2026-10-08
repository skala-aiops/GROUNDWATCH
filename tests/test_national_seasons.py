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
