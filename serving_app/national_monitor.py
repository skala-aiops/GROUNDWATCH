"""Pure, observed-only national daily error monitoring; no jobs or I/O.

The caller persists the returned state and enqueues a trigger atomically. A
trigger means eligibility, never proof that a training job succeeded.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from serving_app.national_models import NAMESPACE, _rows


def _finite(value, label):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{label}: finite value required')
    return value


def reference_threshold(actual, predicted):
    """Frozen held-out reference: rolling21 RMSE P95 ×1.5, minimum1e-6.

    Call with consecutive, same-model frozen holdout observations only. This
    function deliberately does not estimate a new threshold from live errors.
    """
    if len(actual) != len(predicted) or len(actual) < 21:
        raise ValueError('at least twenty-one paired reference values required')
    squared = [(_finite(a, 'actual')-_finite(p, 'prediction'))**2 for a, p in zip(actual, predicted)]
    scores = sorted(math.sqrt(sum(squared[i-20:i+1])/21) for i in range(20, len(squared)))
    position = (len(scores)-1)*.95
    lower = int(position)
    p95 = scores[lower]+(scores[min(lower+1, len(scores)-1)]-scores[lower])*(position-lower)
    return max(1e-6, p95*1.5)


def evaluate_monitor(pairs, threshold, state=None, candidate_pending=False,
                     latest_input_rows=None, as_of=None, namespace=NAMESPACE, source_kind='observed'):
    """Evaluate one completed target date, preserving idempotency and cooldown.

    Pairs require target_date, model_version, station_id, prediction and actual.
    predicted_level/groundwater_level are accepted value aliases. ``as_of`` is a
    completed observation date, not the scheduler's wall clock. Missing days
    reset the two-day breach run. First detection has no extra cooldown.
    """
    if (namespace,source_kind) not in ((NAMESPACE,'observed'),('national_synthetic_v1','synthetic')):
        raise ValueError('monitor namespace/source contract mismatch')
    threshold = _finite(threshold, 'threshold')
    if threshold <= 0:
        raise ValueError('threshold must be positive')
    current = dict(state or {})
    records = []
    for item in pairs:
        item = dict(item)
        date.fromisoformat(item['target_date'])
        if item.get('namespace', namespace) != namespace or item.get('source_kind', 'observed') not in (('synthetic',) if source_kind=='synthetic' else ('observed','observed_api')):
            raise ValueError('national monitoring requires observed namespace')
        if item.get('quality_status', 'valid') != 'valid':
            raise ValueError('monitor pairs must have valid observations')
        if not item.get('station_id') or item.get('model_version') is None:
            raise ValueError('station and version required')
        item['model_version'] = str(item['model_version'])
        item['prediction'] = _finite(item.get('prediction', item.get('predicted_level')), 'prediction')
        item['actual'] = _finite(item.get('actual', item.get('groundwater_level')), 'actual')
        records.append(item)
    if as_of is None:
        if not records:
            return {'state': current, 'trigger': False, 'reason': 'no_labelled_prediction', 'rmse': None}
        as_of = max(p['target_date'] for p in records)
    day = date.fromisoformat(as_of)
    records = [p for p in records if p['target_date'] <= as_of]
    scopes = {p.get('prediction_scope','operational') for p in records}
    if len(scopes)>1 or any(scope not in (('synthetic',) if source_kind=='synthetic' else ('operational','experimental')) for scope in scopes):
        raise ValueError('monitor prediction scope mismatch')
    scope=next(iter(scopes),'operational')
    if current.get('prediction_scope',scope) != scope:
        raise ValueError('monitor state prediction scope mismatch')
    current['prediction_scope']=scope
    station_ids = {p['station_id'] for p in records}
    if len(station_ids) > 1:
        raise ValueError('monitor is station isolated')
    today = [p for p in records if p['target_date'] == as_of]
    if not today:
        return {'state': current, 'trigger': False, 'reason': 'no_labelled_prediction', 'rmse': None}
    if len(today) != 1:
        raise ValueError('exactly one issued model prediction per target day required')
    station_id, version = today[0]['station_id'], today[0]['model_version']
    if current.get('station_id') not in (None, station_id):
        raise ValueError('monitor state station mismatch')
    if current.get('namespace', namespace) != namespace:
        raise ValueError('monitor state namespace mismatch')
    changed = current.get('version') is not None and str(current['version']) != version
    if changed:
        current.update(breaches=0, last_processed_target_date=None, last_trigger=as_of, rmse=None)
    current.update(station_id=station_id, namespace=namespace, version=version, threshold=threshold)
    previous = current.get('last_processed_target_date')
    if previous and as_of <= previous:
        return {'state': current, 'trigger': False, 'reason': 'already_processed', 'rmse': current.get('rmse')}
    if previous != (day-timedelta(days=1)).isoformat():
        current['breaches'] = 0
    current['last_processed_target_date'] = as_of
    labelled = [p for p in records if p['model_version'] == version]
    unique = {p['target_date']: p for p in labelled}
    if len(unique) != len(labelled):
        raise ValueError('duplicate model target dates')
    dates = [(day-timedelta(days=offset)).isoformat() for offset in reversed(range(21))]
    if any(target not in unique for target in dates):
        current.update(breaches=0, rmse=None)
        return {'state': current, 'trigger': False, 'reason': 'insufficient_consecutive_labels', 'rmse': None}
    rmse = math.sqrt(sum((unique[target]['actual']-unique[target]['prediction'])**2 for target in dates)/21)
    current.update(rmse=rmse, breaches=current.get('breaches', 0)+1 if rmse > threshold else 0)

    def result(reason, trigger=False):
        return {'state': current, 'trigger': trigger, 'reason': reason, 'rmse': rmse}

    if candidate_pending:
        return result('candidate_pending')
    if current['breaches'] < 2:
        return result('below_threshold' if rmse <= threshold else 'awaiting_second_breach')
    last_trigger = current.get('last_trigger')
    if last_trigger and (day-date.fromisoformat(last_trigger)).days < 21:
        return result('cooldown')
    input_rows = [r for r in (latest_input_rows or []) if r['date'] <= as_of]
    if len(input_rows) < 41:
        return result('insufficient_fine_tuning_rows')
    try:
        training = _rows(station_id, input_rows[-41:], 41, allow_synthetic=source_kind=='synthetic')
    except (ValueError, TypeError, KeyError):
        return result('invalid_fine_tuning_rows')
    if training[-1]['date'] != as_of:
        return result('stale_fine_tuning_rows')
    current.update(last_trigger=as_of, breaches=0)
    return result('fine_tuning_eligible', trigger=True)
