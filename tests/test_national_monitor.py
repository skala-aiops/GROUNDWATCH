"""Synthetic monitor fixtures; no live source or model performance claims."""
from datetime import date, timedelta

import pytest

from serving_app.national_monitor import evaluate_monitor, reference_threshold


def records(count=70):
    return [{'date': (date(2020, 1, 1)+timedelta(days=i)).isoformat(),
             'station_id': 'kwater:one', 'groundwater_level': 10., 'rainfall_mm': 0.}
            for i in range(count)]


def pairs(count=70):
    return [{'target_date': r['date'], 'station_id': r['station_id'], 'model_version': 'v1',
             'actual': 10., 'prediction': 8., 'namespace': 'national_observed_v1'}
            for r in records(count)]


def run(day, state=None, **kwargs):
    return evaluate_monitor(kwargs.pop('pairs', pairs()), 1., state,
                            latest_input_rows=kwargs.pop('latest_input_rows', records()),
                            as_of=records()[day]['date'], **kwargs)


def test_two_daily_breaches_then_idempotency_and_twenty_one_day_cooldown():
    first = run(40)
    assert first['reason'] == 'awaiting_second_breach'
    second = run(41, first['state'])
    assert second['trigger'] and second['rmse'] == 2.
    duplicate = run(41, second['state'])
    assert not duplicate['trigger'] and duplicate['reason'] == 'already_processed'
    current = second['state']
    for day in range(42, 62):
        result = run(day, current)
        assert not result['trigger']
        current = result['state']
    assert result['reason'] == 'cooldown'
    assert run(62, current)['trigger']


def test_consecutive_days_and_same_version_required():
    first = run(40)
    missing = pairs()
    del missing[30]
    result = run(41, first['state'], pairs=missing)
    assert result['reason'] == 'insufficient_consecutive_labels'
    assert result['state']['breaches'] == 0
    changed = pairs()
    changed[41]['model_version'] = 'v2'
    result = run(41, first['state'], pairs=changed)
    assert result['state']['version'] == 'v2'
    assert result['reason'] == 'insufficient_consecutive_labels'
    assert result['state']['last_trigger'] == records()[41]['date']
    # Skipping a processed date breaks two consecutive *evaluations* even if
    # the available rolling window is complete.
    assert run(42, first['state'])['reason'] == 'awaiting_second_breach'


def test_pending_candidate_and_unverified_training_rows_block_triggers():
    first = run(40)
    result = run(41, first['state'], candidate_pending=True)
    assert not result['trigger'] and result['reason'] == 'candidate_pending'
    result = run(41, first['state'], latest_input_rows=records()[22:42])
    assert result['reason'] == 'insufficient_fine_tuning_rows'
    invalid = records()
    invalid[35]['quality_status'] = 'conflict'
    assert run(41, first['state'], latest_input_rows=invalid)['reason'] == 'invalid_fine_tuning_rows'
    # Future rows are not silently used to train a historical trigger.
    assert run(41, first['state'], latest_input_rows=records()[2:])['reason'] == 'insufficient_fine_tuning_rows'


def test_scopes_and_nonfinite_values_are_rejected():
    observed = pairs()
    observed[0]['source_kind'] = 'synthetic'
    with pytest.raises(ValueError, match='observed'):
        run(40, pairs=observed)
    observed = pairs()
    observed[0]['station_id'] = 'another'
    with pytest.raises(ValueError, match='isolated'):
        run(40, pairs=observed)
    observed = pairs()
    observed[0]['actual'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        run(40, pairs=observed)
    with pytest.raises(ValueError, match='positive'):
        evaluate_monitor(pairs(), 0, as_of=records()[40]['date'])


def test_frozen_reference_uses_rolling_rmse_p95_not_live_errors():
    assert reference_threshold([2.]*30, [0.]*30) == 3.
    assert reference_threshold([0.]*30, [0.]*30) == 1e-6
    with pytest.raises(ValueError, match='twenty-one'):
        reference_threshold([1.]*20, [0.]*20)


def test_experimental_scope_isolated_from_operational_errors_and_state():
    observed=[{**p,'prediction_scope':'experimental'} for p in pairs()]
    result=run(40,pairs=observed)
    assert result['state']['prediction_scope']=='experimental'
    observed[0]['prediction_scope']='operational'
    with pytest.raises(ValueError,match='scope'):
        run(41,pairs=observed)
    with pytest.raises(ValueError,match='scope'):
        run(41,state=result['state'])


def test_explicit_synthetic_monitor_is_isolated_and_runs_same_policy():
    simulated_pairs=[{**p,'namespace':'national_synthetic_v1','source_kind':'synthetic','prediction_scope':'synthetic'} for p in pairs()]
    inputs=[{**r,'source_kind':'synthetic'} for r in records()]
    options={'namespace':'national_synthetic_v1','source_kind':'synthetic','latest_input_rows':inputs}
    first=evaluate_monitor(simulated_pairs,1.,as_of=records()[40]['date'],**options)
    second=evaluate_monitor(simulated_pairs,1.,state=first['state'],as_of=records()[41]['date'],**options)
    assert second['trigger'] is True
    assert second['state']['namespace']=='national_synthetic_v1'
    assert second['state']['prediction_scope']=='synthetic'
    with pytest.raises(ValueError,match='observed'):
        evaluate_monitor(simulated_pairs,1.,as_of=records()[41]['date'])
