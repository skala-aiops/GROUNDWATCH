"""Verify bundled data preparation and restart semantics, not model quality."""
from pathlib import Path
from datetime import date
import pytest
from scripts.bootstrap_national_models import bootstrap
from serving_app.national_models import NationalModelManager
from serving_app.national_service import NationalService
from tests.test_national_models import LearnedDeltaBackend


@pytest.mark.parametrize('monitoring_enabled',[False,True])
def test_bundled_experiments_are_idempotent_and_preserve_unapproved_state(tmp_path,monkeypatch,monitoring_enabled):
    # Compose flags and wall clocks must not change this experiment's contract.
    monkeypatch.setenv('GROUNDWATCH_EXPERIMENTAL_MONITORING_ENABLED',str(monitoring_enabled).lower())
    monkeypatch.setattr('serving_app.national_service.kst_today',lambda:date(2026,10,8))
    monkeypatch.setattr('serving_app.national_service.now',lambda:'2026-10-08T20:00:00+09:00')
    service=NationalService(tmp_path,NationalModelManager(tmp_path/'national'/'models',LearnedDeltaBackend()))
    source=Path(__file__).resolve().parents[1]/'data'/'national_experimental_joined.json'
    first=bootstrap(service,source,max_epochs=1)
    assert len(first)==3 and all(len(s['queued'])==1 for s in first)
    bootstrap(service,source,max_epochs=1)
    assert len(service.store.jobs())==3
    for _ in range(12):
        if not service.execute_one():break
        bootstrap(service,source,max_epochs=1)
    trains=[j for j in service.store.jobs() if j['kind']=='train']
    assert len(trains)==6 and all(j['status']=='completed' for j in trains)
    assert {j['payload']['variant'] for j in trains}=={'M0','M1'}
    previous=len(service.store.jobs())
    bootstrap(service,source,max_epochs=1)
    assert len(service.store.jobs())==previous
    for station in first:
        meta=service.station(station['station_id'])
        assert meta['verified'] is False and meta['operational_approved'] is False
        assert meta['source_contract_verified'] is True and meta['mapping_status']=='experimental'
    pairs=service.store.list('paired_prediction')
    if not monitoring_enabled:
        assert pairs==[]
    else:
        assert pairs
        for pair in pairs:
            assert pair['prediction_scope']=='experimental'
            assert pair['operational_promotion_evidence'] is False
            assert pair['target_date']=='2026-10-08'
            assert pair['input_end_date']=='2026-10-07'
            assert pair['horizon_days']==1
            assert service.repo.observations(pair['station_id'],start=pair['target_date'],end=pair['target_date'],cutoff=pair['issued_at'])==[]
            with pytest.raises(ValueError,match='operational'):
                service.manager.promote(pair['station_id'],pair['candidate_version'])
