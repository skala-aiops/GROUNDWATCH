"""Synthetic, deterministic checks; these are not national performance evidence."""
import json
import math
from datetime import date, timedelta

import pytest

from backend.national_models import NationalModelManager, build_features


from backend.tests.support.national_models import LearnedDeltaBackend, rows, metadata, manager

def test_m1_uses_only_twenty_days_and_one_day_horizon():
    observed = rows(20)
    feature = build_features(observed, 'M1')
    assert feature['summary'][:3] == [sum(r['rainfall_mm'] for r in observed[-n:]) for n in (3, 7, 14)]
    assert len(feature['sequence']) == 20 and len(feature['summary']) == 6
    assert feature['target_date'] == '2020-01-21'
    with pytest.raises(ValueError, match='one day'):
        build_features(observed, 'M1', '2020-01-22')
    with pytest.raises(ValueError, match='M2'):
        build_features(observed, 'M2')


def test_train_only_scaler_persistent_initial_and_contract_identity(tmp_path):
    service = manager(tmp_path)
    observed = rows()
    observed[-1]['rainfall_mm'] = 100000
    result = service.train('kwater:one', observed, metadata())
    assert result['status'] == 'active'
    assert result['scaler']['maximum'][1] == 3
    assert result['scaler']['fit_scope'] == 'train_only'
    prediction = manager(tmp_path).predict('kwater:one', observed[-20:], metadata())
    assert prediction['target_date'] == '2020-06-09'
    assert math.isfinite(prediction['predicted_level'])
    assert prediction['level_reference'] == 'ground_level'
    with pytest.raises(ValueError, match='level_reference'):
        service.predict('kwater:one', observed[-20:], metadata(level_reference='sea_level'))
    with pytest.raises(ValueError, match='observed'):
        service.train('kwater:one', observed, metadata(source_kind='synthetic'))


def test_missing_days_and_unknown_units_block_training(tmp_path):
    service = manager(tmp_path)
    observed = rows()
    del observed[50]
    with pytest.raises(ValueError, match='consecutive'):
        service.train('kwater:one', observed, metadata())
    with pytest.raises(ValueError, match='verified'):
        service.train('kwater:one', rows(), metadata(verified=False))
    with pytest.raises(ValueError, match='at least'):
        service.train('kwater:one', rows(100), metadata())


def test_m1_requires_baseline_and_seasonal_evidence(tmp_path):
    service = manager(tmp_path)
    first = service.train('kwater:one', rows(), metadata(), variant='M1')
    assert first['status'] == 'baseline_required'
    with pytest.raises(ValueError, match='not ready'):
        service.predict('kwater:one', rows()[-20:], metadata())
    baseline = service.train('kwater:one', rows(), metadata())
    candidate = service.train('kwater:one', rows(), metadata(), variant='M1')
    assert candidate['status'] == 'awaiting_shadow'
    pending = service.evaluate_candidate('kwater:one', candidate['version'], rows(189))
    assert pending['status'] == 'awaiting_shadow' and pending['count'] == 29
    result = service.evaluate_candidate('kwater:one', candidate['version'], rows(190))
    assert result['status'] == 'retrospective_evaluation'
    assert not result['gates']['seasonal']
    with pytest.raises(ValueError, match='quality gates'):
        service.promote('kwater:one', candidate['version'])
    assert service.predict('kwater:one', rows()[-20:], metadata())['model_version'] == baseline['version']


def test_changed_champion_blocks_stale_candidate(tmp_path):
    service = manager(tmp_path)
    service.train('kwater:one', rows(), metadata())
    candidate = service.train('kwater:one', rows(), metadata())
    state = service._state('kwater:one')
    state['generation'] += 1
    (service._station('kwater:one')/'state.json').write_text(json.dumps(state))
    result = service.evaluate_candidate('kwater:one', candidate['version'], rows(190))
    assert result['status'] == 'blocked'
    assert service.list_models('kwater:one')


def test_issued_prediction_promotion_and_validated_rollback(tmp_path):
    class ImprovingBackend(LearnedDeltaBackend):
        def __init__(self):
            self.count = 0

        def train(self, *args, **kwargs):
            self.count += 1
            result = super().train(*args, **kwargs)
            return {'delta': 0} if self.count == 1 else result

    service = NationalModelManager(tmp_path, ImprovingBackend())
    initial = service.train('kwater:one', rows(), metadata())
    candidate = service.train('kwater:one', rows(), metadata())
    future = rows(190)
    proofs = []
    for i in range(160, 190):
        future[i]['available_at'] = future[i]['date']+'T23:59:00+09:00'
        proofs.append({'target_date': future[i]['date'], 'candidate_version': candidate['version'],
                       'champion_version': initial['version'], 'snapshot_id': f'test-synthetic-{i}',
                       'issued_at': future[i]['date']+'T11:30:00+09:00',
                       'candidate_prediction': future[i]['groundwater_level'],
                       'champion_prediction': future[i-1]['groundwater_level']})
    retrospective = service.evaluate_candidate('kwater:one', candidate['version'], future)
    assert retrospective['status'] == 'retrospective_evaluation'
    with pytest.raises(ValueError, match='quality gates'):
        service.promote('kwater:one', candidate['version'])
    result = service.evaluate_candidate('kwater:one', candidate['version'], future, issued_predictions=proofs)
    assert result['status'] == 'gate_passed'
    assert result['forecast_timing'] == ['same_day_estimate']
    service.promote('kwater:one', candidate['version'])
    assert service.predict('kwater:one', rows()[-20:], metadata())['model_version'] == candidate['version']
    assert service.rollback('kwater:one', initial['version'], 'synthetic test')['status'] == 'rolled_back'
    assert service.predict('kwater:one', rows()[-20:], metadata())['model_version'] == initial['version']
    unknown = service.train('kwater:one', rows(), metadata())
    with pytest.raises(ValueError, match='history'):
        service.rollback('kwater:one', unknown['version'], 'not previously active')


def test_fine_tune_retains_contract_scaler_and_exactly_twenty_one_labels(tmp_path):
    service = manager(tmp_path)
    initial = service.train('kwater:one', rows(), metadata())
    candidate = service.fine_tune('kwater:one', rows(41, offset=140), metadata())
    assert candidate['fine_tuning_targets_count'] == 21
    assert candidate['scaler'] == initial['scaler']
    assert candidate['feature_contract_id'] == initial['feature_contract_id']
    with pytest.raises(ValueError, match='cutoff'):
        service.fine_tune('kwater:one', rows(41), metadata())
    with pytest.raises(ValueError, match='identity'):
        service.fine_tune('kwater:one', rows(41, offset=140), metadata(level_reference='sea_level'))
    invalid = rows(41, offset=140)
    invalid[-1]['quality_status'] = 'conflict'
    with pytest.raises(ValueError, match='valid observations'):
        service.fine_tune('kwater:one', invalid, metadata())


def test_explicit_experimental_contract_can_train_but_never_promote(tmp_path):
    service = manager(tmp_path)
    experimental = metadata(verified=False, source_contract_verified=True,
        mapping_status='experimental', operational_approved=False,
        mapping_version='test-experimental-v1', evidence=['TEST source field contract'])
    trained = service.train('kwater:one', rows(), experimental)
    assert trained['operational_approved'] is False
    assert trained['verified'] is False
    assert service.predict('kwater:one', rows()[-20:], experimental)['predicted_level'] is not None
    with pytest.raises(ValueError, match='operational mapping approval'):
        service.promote('kwater:one', trained['version'])
    with pytest.raises(ValueError, match='verified unit'):
        manager(tmp_path/'invalid').train('kwater:one', rows(), metadata(verified=False))


def test_experimental_prospective_quality_pass_never_operational_promotion(tmp_path):
    class ImprovingBackend(LearnedDeltaBackend):
        def __init__(self):self.count=0
        def train(self,*args,**kwargs):
            self.count+=1
            result=super().train(*args,**kwargs)
            return {'delta':0} if self.count==1 else result
    meta=metadata(verified=False,source_contract_verified=True,mapping_status='experimental',
        operational_approved=False,mapping_version='synthetic-scope-test',evidence=['synthetic test'])
    service=NationalModelManager(tmp_path,ImprovingBackend())
    initial=service.train('kwater:one',rows(),meta)
    candidate=service.train('kwater:one',rows(),meta)
    future=rows(190)
    proofs=[]
    for i in range(160,190):
        future[i]['available_at']=future[i]['date']+'T23:59:00+09:00'
        proofs.append({'target_date':future[i]['date'],'candidate_version':candidate['version'],
            'champion_version':initial['version'],'snapshot_id':f'synthetic-exp-{i}',
            'issued_at':future[i]['date']+'T11:30:00+09:00','input_end_date':future[i-1]['date'],
            'candidate_prediction':future[i]['groundwater_level'],'champion_prediction':future[i-1]['groundwater_level'],
            'prediction_scope':'experimental','namespace':'national_observed_v1','horizon_days':1,
            'mapping_version':meta['mapping_version'],'feature_contract_id':candidate['feature_contract_id']})
    bad=[{**p,'prediction_scope':'operational'} for p in proofs]
    with pytest.raises(ValueError,match='scope'):
        service.evaluate_candidate('kwater:one',candidate['version'],future,issued_predictions=bad)
    result=service.evaluate_candidate('kwater:one',candidate['version'],future,issued_predictions=proofs)
    assert result['status']=='experimental_gate_passed'
    assert result['evaluation_mode']=='prospective'
    assert result['operational_promotion_evidence'] is False
    assert all(result['gates'].values())
    with pytest.raises(ValueError,match='operational'):
        service.promote('kwater:one',candidate['version'])
    assert service._state('kwater:one')['active_version']==initial['version']


def test_zero_error_tie_fails_future_improvement(tmp_path):
    service=manager(tmp_path)
    observed=[{**r,'groundwater_level':0.} for r in rows()]
    initial=service.train('kwater:one',observed,metadata())
    candidate=service.train('kwater:one',observed,metadata())
    future=[{**r,'groundwater_level':0.,'available_at':r['date']+'T23:59:00+09:00'} for r in rows(190)]
    proofs=[{'target_date':r['date'],'candidate_version':candidate['version'],
        'champion_version':initial['version'],'snapshot_id':'synthetic-zero-'+r['date'],
        'issued_at':r['date']+'T11:30:00+09:00','candidate_prediction':0.,'champion_prediction':0.}
        for r in future[160:]]
    result=service.evaluate_candidate('kwater:one',candidate['version'],future,issued_predictions=proofs)
    assert result['candidate']['rmse']==result['champion']['rmse']==0.
    assert result['status']=='rejected'
    assert result['gates']['future'] is False
    with pytest.raises(ValueError,match='quality gates'):
        service.promote('kwater:one',candidate['version'])
    assert service._state('kwater:one')['active_version']==initial['version']
    result.update(status='gate_passed')
    result['gates']['future']=True
    (service._station('kwater:one')/candidate['version']/'evaluation.json').write_text(json.dumps(result))
    with pytest.raises(ValueError,match='quality gates'):
        service.promote('kwater:one',candidate['version'])


def synthetic_metadata():
    return metadata(source_kind='synthetic',verified=False,source_contract_verified=True,
        mapping_status='synthetic',operational_approved=False,mapping_version='synthetic-v1',evidence=['synthetic fixture'])


def test_synthetic_manager_requires_explicit_namespace_and_keeps_artifacts_isolated(tmp_path):
    synthetic=[{**r,'source_kind':'synthetic'} for r in rows()]
    simulated=NationalModelManager(tmp_path,LearnedDeltaBackend(),namespace='national_synthetic_v1',source_kind='synthetic')
    trained=simulated.train('kwater:one',synthetic,synthetic_metadata())
    assert trained['namespace']=='national_synthetic_v1'
    assert trained['source_kind']=='synthetic'
    predicted=simulated.predict('kwater:one',synthetic[-20:],synthetic_metadata())
    assert predicted['prediction_scope']=='synthetic'
    assert manager(tmp_path).list_models('kwater:one')==[]
    with pytest.raises(ValueError,match='observed'):
        manager(tmp_path).train('kwater:one',synthetic,synthetic_metadata())
    with pytest.raises(ValueError,match='synthetic'):
        simulated.train('kwater:one',rows(),synthetic_metadata())
    with pytest.raises(ValueError,match='namespace'):
        NationalModelManager(tmp_path,namespace='national_observed_v1',source_kind='synthetic')


def test_candidate_immutable_seasonal_shortage_expires_without_switching(tmp_path):
    service=manager(tmp_path)
    initial=service.train('kwater:one',rows(),metadata())
    candidate=service.train('kwater:one',rows(),metadata(),variant='M1')
    result=service.expire_candidate('kwater:one',candidate['version'],candidate['shadow_after'],seasonal_labels={})
    assert result['status']=='expired_insufficient_seasonal_evidence'
    assert result['expired'] is True
    assert result['seasonal_counts']['rainy']==0
    assert service._state('kwater:one')['active_version']==initial['version']
    assert service.evaluate_candidate('kwater:one',candidate['version'],[])['status']==result['status']
    assert service.expire_candidate('kwater:one',candidate['version'],candidate['shadow_after'])['status']==result['status']
    with pytest.raises(ValueError,match='expired'):
        service.promote('kwater:one',candidate['version'])
    assert next(m for m in service.list_models('kwater:one') if m['version']==candidate['version'])['status']==result['status']


def test_shadow_timeout_is_terminal_and_does_not_expire_active_model(tmp_path):
    service=manager(tmp_path)
    initial=service.train('kwater:one',rows(),metadata())
    candidate=service.train('kwater:one',rows(),metadata())
    after=date.fromisoformat(candidate['shadow_after'])
    assert service.expire_candidate('kwater:one',candidate['version'],(after+timedelta(days=89)).isoformat())['expired'] is False
    assert service.expire_candidate('kwater:one',candidate['version'],(after+timedelta(days=90)).isoformat())['status']=='expired_shadow_timeout'
    assert service.expire_candidate('kwater:one',initial['version'],(after+timedelta(days=100)).isoformat())['status']=='active'
    assert service._state('kwater:one')['active_version']==initial['version']


def test_sufficient_frozen_seasonal_counts_do_not_expire_before_timeout(tmp_path):
    service=manager(tmp_path)
    observed=[{**r,'rainfall_mm':1.} for r in rows(240)]
    service.train('kwater:one',observed,metadata(),holdout_targets=90)
    candidate=service.train('kwater:one',observed,metadata(),variant='M1',holdout_targets=90)
    guard=service._bundle('kwater:one',candidate['version'])['guard_rows'][20:]
    labels={r['date']:['rainy' if i<30 else 'non_rainy'] for i,r in enumerate(guard)}
    result=service.expire_candidate('kwater:one',candidate['version'],candidate['shadow_after'],seasonal_labels=labels)
    assert result['expired'] is False
    assert result['status']=='awaiting_shadow'


def test_synthetic_shadow_quality_pass_is_explicitly_simulated_and_not_operational(tmp_path):
    class ImprovingBackend(LearnedDeltaBackend):
        def __init__(self):self.count=0
        def train(self,*args,**kwargs):
            self.count+=1
            learned=super().train(*args,**kwargs)
            return {'delta':0.} if self.count==1 else learned
    service=NationalModelManager(tmp_path,ImprovingBackend(),namespace='national_synthetic_v1',source_kind='synthetic')
    observed=[{**r,'source_kind':'synthetic'} for r in rows()]
    initial=service.train('kwater:one',observed,synthetic_metadata())
    candidate=service.train('kwater:one',observed,synthetic_metadata())
    future=[{**r,'source_kind':'synthetic','available_at':r['date']+'T23:59:00+09:00'} for r in rows(190)]
    proofs=[{'target_date':r['date'],'candidate_version':candidate['version'],
        'champion_version':initial['version'],'snapshot_id':'synthetic-clock-'+r['date'],
        'issued_at':r['date']+'T11:30:00+09:00','input_end_date':future[i-1]['date'],
        'candidate_prediction':r['groundwater_level'],'champion_prediction':future[i-1]['groundwater_level'],
        'namespace':'national_synthetic_v1','horizon_days':1,'prediction_scope':'synthetic',
        'mapping_version':synthetic_metadata()['mapping_version'],'feature_contract_id':candidate['feature_contract_id']}
        for i,r in enumerate(future) if i>=160]
    result=service.evaluate_candidate('kwater:one',candidate['version'],future,issued_predictions=proofs)
    assert result['status']=='synthetic_gate_passed'
    assert result['evaluation_mode']=='simulated_prospective'
    assert result['simulation'] is True
    assert result['operational_promotion_evidence'] is False
    with pytest.raises(ValueError,match='operational'):
        service.promote('kwater:one',candidate['version'])
