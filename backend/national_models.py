"""Observed-only station models; explicit contracts and immutable evaluation data.

TensorFlow is loaded only when training/predicting. National artifacts never reuse
the Seoul registry. M1 is a sequence plus a summary vector, not extra history.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

NAMESPACE = 'national_observed_v1'
SYNTHETIC_NAMESPACE = 'national_synthetic_v1'
SUMMARY_ORDER = ['rain_3d', 'rain_7d', 'rain_14d', 'wet_streak_capped_20', 'year_sin', 'year_cos']
_LOCK = threading.RLock()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
    os.replace(temporary, path)


def _read(path):
    return json.loads(path.read_text())


def _rows(station_id, records, length=None, allow_synthetic=False):
    rows = [dict(r) for r in records]
    if length is not None and len(rows) != length:
        raise ValueError(f'exactly {length} consecutive daily rows required')
    if not rows:
        raise ValueError('observations required')
    for row in rows:
        date.fromisoformat(row['date'])
        if row.get('station_id', station_id) != station_id:
            raise ValueError('station identity mismatch')
        if row.get('source_kind', 'observed') not in (('synthetic',) if allow_synthetic else ('observed', 'observed_api')):
            raise ValueError('national models require explicit synthetic data' if allow_synthetic else 'national models require observed data')
        if row.get('quality_status', 'valid') != 'valid':
            raise ValueError('only valid observations may enter model input')
        for field in ('groundwater_level', 'rainfall_mm'):
            row[field] = float(row[field])
            if not math.isfinite(row[field]):
                raise ValueError('finite observations required')
        if row['rainfall_mm'] < 0:
            raise ValueError('negative rainfall')
    if any(date.fromisoformat(b['date']) - date.fromisoformat(a['date']) != timedelta(days=1)
           for a, b in zip(rows, rows[1:])):
        raise ValueError('ordered, unique consecutive daily rows required')
    return rows


def _metadata(station_id, metadata, allow_synthetic=False):
    metadata = dict(metadata or {})
    if metadata.get('source_kind') not in (('synthetic',) if allow_synthetic else ('observed', 'observed_api')):
        raise ValueError('source_kind must be synthetic' if allow_synthetic else 'source_kind must be observed')
    if metadata.get('station_id', metadata.get('id', station_id)) != station_id:
        raise ValueError('station metadata mismatch')
    experimental = (metadata.get('source_contract_verified') is True and
                    metadata.get('mapping_status') == ('synthetic' if allow_synthetic else 'experimental') and
                    metadata.get('operational_approved') is False and
                    bool(metadata.get('mapping_version')) and bool(metadata.get('evidence') or metadata.get('contract_evidence')))
    if allow_synthetic and (not experimental or metadata.get('verified') is not False):
        raise ValueError('explicit unapproved synthetic contract required')
    if (metadata.get('verified') is not True and not experimental) or not metadata.get('level_unit') or not metadata.get('level_reference'):
        raise ValueError('verified unit and level_reference required')
    return {'station_id': station_id, 'source_kind': metadata['source_kind'],
            'level_unit': metadata['level_unit'], 'level_reference': metadata['level_reference'],
            'mapping_version': metadata.get('mapping_version'), 'verified': metadata.get('verified') is True,
            'source_contract_verified': metadata.get('source_contract_verified', metadata.get('verified') is True),
            'mapping_status': metadata.get('mapping_status', 'approved' if metadata.get('verified') else 'unverified'),
            'operational_approved': (metadata.get('verified') is True if metadata.get('operational_approved') is None else metadata['operational_approved'])}


def _score(actual, predicted):
    if not actual or len(actual) != len(predicted):
        raise ValueError('nonempty paired predictions required')
    residuals = [float(a) - float(b) for a, b in zip(actual, predicted)]
    if not all(math.isfinite(r) for r in residuals):
        raise ValueError('nonfinite prediction')
    return {'count': len(actual), 'rmse': math.sqrt(sum(r*r for r in residuals)/len(actual)),
            'mae': sum(abs(r) for r in residuals)/len(actual)}


def _summary(rows, target_date):
    rain = [r['rainfall_mm'] for r in rows]
    streak = 0
    for value in reversed(rain):
        if value <= 0:
            break
        streak += 1
    target = date.fromisoformat(target_date)
    year_days = (date(target.year+1, 1, 1)-date(target.year, 1, 1)).days
    angle = 2*math.pi*(target.timetuple().tm_yday-1)/year_days
    return [sum(rain[-3:]), sum(rain[-7:]), sum(rain[-14:]), streak, math.sin(angle), math.cos(angle)]


def build_features(records, variant='M0', target_date=None, allow_synthetic=False):
    """Unscaled twenty-day sequence and M1 target-time summary (no future rain)."""
    if variant not in ('M0', 'M1'):
        raise ValueError('only M0/M1 supported; M2 requires archived forecasts')
    rows = _rows(records[0].get('station_id', '') if records else '', records, 20, allow_synthetic=allow_synthetic)
    expected = (date.fromisoformat(rows[-1]['date'])+timedelta(days=1)).isoformat()
    if target_date is not None and target_date != expected:
        raise ValueError('target must be one day after input_end_date')
    return {'sequence': [[r['groundwater_level'], r['rainfall_mm']] for r in rows],
            'summary': _summary(rows, expected) if variant == 'M1' else [], 'target_date': expected}


class NationalTensorFlowBackend:
    """Separate national LSTM supporting sequence + optional static summary."""
    def train(self, sequence, summary, targets, validation, variant, max_epochs=30,
              initial=None, learning_rate=.001):
        import numpy as np
        import tensorflow as tf
        tf.keras.utils.set_random_seed(42)
        if initial is None:
            tf.keras.backend.clear_session()
            import gc
            gc.collect()
            seq = tf.keras.Input((20, 2), name='daily_observations')
            hidden = tf.keras.layers.LSTM(32)(seq)
            inputs = [seq]
            if variant == 'M1':
                extra = tf.keras.Input((6,), name='past_rain_and_calendar_summary')
                hidden = tf.keras.layers.Concatenate()([hidden, extra])
                inputs.append(extra)
            hidden = tf.keras.layers.Dense(16, activation='relu')(hidden)
            delta = tf.keras.layers.Dense(1, kernel_initializer='zeros', bias_initializer='zeros')(hidden)
            last = tf.keras.layers.Flatten()(tf.keras.layers.Cropping1D((19, 0))(seq))
            persistence = tf.keras.layers.Dense(1, use_bias=False, trainable=False,
                kernel_initializer=tf.keras.initializers.Constant([[1.0], [0.0]]))(last)
            output = tf.keras.layers.Add()([persistence, delta])
            model = tf.keras.Model(inputs=inputs, outputs=output)
        else:
            model = tf.keras.models.clone_model(initial)
            model.set_weights(initial.get_weights())
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate), loss='mse')
        options = tf.data.Options()
        options.threading.private_threadpool_size = 1
        options.threading.max_intra_op_parallelism = 1
        def dataset(sequences, summaries, ys):
            features = {'daily_observations': np.asarray(sequences, dtype='float32')}
            if variant == 'M1':
                features['past_rain_and_calendar_summary'] = np.asarray(summaries, dtype='float32')
            return tf.data.Dataset.from_tensor_slices((features, np.asarray(ys, dtype='float32'))).batch(32).with_options(options)
        kwargs = {}
        if validation is not None:
            kwargs.update(validation_data=dataset(*validation),
                          callbacks=[tf.keras.callbacks.EarlyStopping(patience=5, restore_best_weights=True)])
        model.fit(dataset(sequence, summary, targets), epochs=max_epochs,
                  shuffle=False, verbose=0, **kwargs)
        return model

    def predict(self, model, sequence, summary, variant):
        import numpy as np
        features = {'daily_observations': np.asarray(sequence, dtype='float32')}
        if variant == 'M1':
            features['past_rain_and_calendar_summary'] = np.asarray(summary, dtype='float32')
        return [float(v[0]) for v in model(features, training=False).numpy()]

    def save(self, model, path):
        model.save(path)

    def load(self, path):
        import tensorflow as tf
        return tf.keras.models.load_model(path)


class NationalModelManager:
    namespace = NAMESPACE

    def __init__(self, root, backend=None, namespace=NAMESPACE, source_kind='observed'):
        if (namespace,source_kind) not in ((NAMESPACE,'observed'),(SYNTHETIC_NAMESPACE,'synthetic')):
            raise ValueError('model namespace/source contract mismatch')
        self.namespace=namespace
        self.source_kind=source_kind
        self.root = Path(root)/namespace
        self.root.mkdir(parents=True, exist_ok=True)
        self.backend = backend or NationalTensorFlowBackend()

    def _rows(self, station_id, records, length=None):
        return _rows(station_id,records,length,allow_synthetic=self.source_kind=='synthetic')

    def _metadata(self, station_id, metadata):
        return _metadata(station_id,metadata,allow_synthetic=self.source_kind=='synthetic')

    def _station(self, station_id):
        return self.root/hashlib.sha256(station_id.encode()).hexdigest()

    @contextmanager
    def _mutation(self, station_id):
        # OS file lock also serializes separate local worker processes. The lock
        # is appropriate for the current single-host Compose volume, not NFS.
        import fcntl
        directory = self._station(station_id)
        directory.mkdir(parents=True, exist_ok=True)
        with _LOCK, (directory/'mutation.lock').open('a') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _state(self, station_id):
        path = self._station(station_id)/'state.json'
        return _read(path) if path.exists() else {'station_id': station_id, 'generation': 0, 'active_version': None, 'history': []}

    def _bundle(self, station_id, version):
        if not isinstance(version, str) or len(version) != 32 or any(c not in '0123456789abcdef' for c in version):
            raise ValueError('invalid version')
        bundle = _read(self._station(station_id)/version/'bundle.json')
        if bundle['station_id'] != station_id or bundle['namespace'] != self.namespace:
            raise ValueError('artifact identity mismatch')
        return bundle

    @staticmethod
    def _inputs(rows, bundle):
        feature = build_features(rows, bundle['variant'], allow_synthetic=bundle['source_kind']=='synthetic')
        scale = bundle['scaler']
        sequence = [[(v-scale['minimum'][i])/(scale['maximum'][i]-scale['minimum'][i] or 1)
                     for i, v in enumerate(pair)] for pair in feature['sequence']]
        summary = [(v-scale['summary_minimum'][i])/(scale['summary_maximum'][i]-scale['summary_minimum'][i] or 1)
                   for i, v in enumerate(feature['summary'])]
        return sequence, summary

    def _predictions(self, station_id, version, rows, indices):
        bundle = self._bundle(station_id, version)
        model = self.backend.load(self._station(station_id)/version/'model.keras')
        pairs = [self._inputs(rows[i-20:i], bundle) for i in indices]
        if not pairs:
            return []
        values = self.backend.predict(model, [p[0] for p in pairs], [p[1] for p in pairs], bundle['variant'])
        if len(values) != len(pairs) or not all(math.isfinite(float(v)) for v in values):
            raise ValueError('invalid backend predictions')
        scale = bundle['scaler']
        return [float(v)*(scale['maximum'][0]-scale['minimum'][0] or 1)+scale['minimum'][0] for v in values]

    def train(self, station_id, records, metadata=None, variant='M0', validation_targets=30,
              holdout_targets=30, max_epochs=30):
        identity = self._metadata(station_id, metadata)
        rows = self._rows(station_id, records)
        for row in rows:
            for field in ('level_unit', 'level_reference'):
                if row.get(field) is not None and row[field] != identity[field]:
                    raise ValueError(f'observation metadata mismatch: {field}')
        if variant not in ('M0', 'M1'):
            raise ValueError('M2 unavailable without historical forecast snapshots')
        if validation_targets < 21 or holdout_targets < 30:
            raise ValueError('validation>=21 and holdout>=30 required')
        train_count = len(rows)-20-validation_targets-holdout_targets
        if train_count < 60:
            raise ValueError(f'at least {80+validation_targets+holdout_targets} consecutive observations required')
        train_end = 20+train_count
        fit = rows[:train_end]
        pairs = [[r['groundwater_level'], r['rainfall_mm']] for r in fit]
        summary = [_summary(rows[i-20:i], rows[i]['date']) for i in range(20, train_end)] if variant == 'M1' else []
        scaler = {'minimum': [min(p[i] for p in pairs) for i in range(2)],
                  'maximum': [max(p[i] for p in pairs) for i in range(2)],
                  'summary_minimum': [min(p[i] for p in summary) for i in range(6)] if summary else [],
                  'summary_maximum': [max(p[i] for p in summary) for i in range(6)] if summary else [],
                  'fit_scope': 'train_only', 'fit_through': rows[train_end-1]['date']}
        state = self._state(station_id)
        if state['active_version']:
            incumbent = self._bundle(station_id, state['active_version'])
            for field in ('level_unit', 'level_reference', 'source_kind', 'mapping_version'):
                if identity[field] != incumbent[field]:
                    raise ValueError(f'comparison identity mismatch: {field}')
        version = uuid.uuid4().hex
        directory = self._station(station_id)/version
        directory.mkdir(parents=True)
        bundle = {**identity, 'contract_evidence': (metadata or {}).get('evidence', []), 'namespace': self.namespace, 'version': version, 'variant': variant,
                  'kind': 'initial_train',
                  'initial_reference_version': version,
                  'feature_contract_id': f'national-{variant.lower()}-v1', 'dtype': 'float32',
                  'feature_order': ['groundwater_level', 'rainfall_mm'],
                  'summary_order': SUMMARY_ORDER if variant == 'M1' else [],
                  'window': 20, 'scaler': scaler, 'trained_through': rows[train_end-1]['date'],
                  'initial_trained_through': rows[train_end-1]['date'],
                  'training_target_ranges': [[rows[20]['date'], rows[train_end-1]['date']]],
                  'shadow_after': rows[-1]['date'], 'snapshot_hash': _digest(rows),
                  'comparison_version': state['active_version'], 'comparison_generation': state['generation'],
                  'guard_rows': rows[train_end+validation_targets-20:],
                  'holdout_start': rows[train_end+validation_targets]['date'],
                  'holdout_end': rows[-1]['date'], 'status': 'training',
                  'created_at': datetime.now(timezone.utc).isoformat()}
        ordered_rain = sorted(r['rainfall_mm'] for r in fit)
        percentile_index = (len(ordered_rain)-1)*.95
        lower = int(percentile_index)
        bundle['heavy_rain_threshold_mm'] = ordered_rain[lower]+(ordered_rain[min(lower+1,len(ordered_rain)-1)]-ordered_rain[lower])*(percentile_index-lower)
        def arrays(indices):
            features = [self._inputs(rows[i-20:i], bundle) for i in indices]
            targets = [(rows[i]['groundwater_level']-scaler['minimum'][0])/(scaler['maximum'][0]-scaler['minimum'][0] or 1) for i in indices]
            return [p[0] for p in features], [p[1] for p in features], targets
        model = self.backend.train(*arrays(range(20, train_end)),
                                   validation=arrays(range(train_end, train_end+validation_targets)),
                                   variant=variant, max_epochs=max_epochs)
        self.backend.save(model, directory/'model.keras')
        _write(directory/'bundle.json', bundle)
        indices = list(range(train_end+validation_targets, len(rows)))
        actual = [rows[i]['groundwater_level'] for i in indices]
        measured = _score(actual, self._predictions(station_id, version, rows, indices))
        persistence = _score(actual, [rows[i-1]['groundwater_level'] for i in indices])
        passed = measured['rmse'] <= persistence['rmse']*1.10+1e-12
        bundle.update(status='awaiting_shadow' if state['active_version'] else ('initial_gate_passed' if passed else 'rejected'),
                      metrics={'holdout': measured, 'holdout_persistence': persistence}, initial_gate_passed=passed)
        _write(directory/'bundle.json', bundle)
        if state['active_version'] is None and passed and variant == 'M0':
            self.activate_initial(station_id, version)
        elif state['active_version'] is None and variant == 'M1':
            bundle['status'] = 'baseline_required'
            _write(directory/'bundle.json', bundle)
        return self._public(self._bundle(station_id, version))

    def activate_initial(self, station_id, version):
        with self._mutation(station_id):
            state = self._state(station_id)
            bundle = self._bundle(station_id, version)
            if state['active_version'] is not None or state['generation'] != bundle['comparison_generation']:
                raise ValueError('champion_changed')
            if bundle['variant'] != 'M0' or not bundle.get('initial_gate_passed'):
                raise ValueError('initial gate failed')
            self._predictions(station_id, version, bundle['guard_rows'], [20])
            state.update(active_version=version, generation=state['generation']+1)
            state.setdefault('history', []).append({'from': None, 'to': version, 'kind': 'initial', 'at': datetime.now(timezone.utc).isoformat()})
            _write(self._station(station_id)/'state.json', state)
            bundle['status'] = 'active'
            _write(self._station(station_id)/version/'bundle.json', bundle)

    def predict(self, station_id, records, metadata=None, version=None, target_date=None):
        rows = self._rows(station_id, records, 20)
        version = version or self._state(station_id)['active_version']
        if version is None:
            raise ValueError('national model not ready')
        bundle = self._bundle(station_id, version)
        identity = self._metadata(station_id, metadata)
        bundle_identity = self._metadata(station_id, bundle)
        for key in identity:
            if identity[key] != bundle_identity[key]:
                raise ValueError(f'model metadata mismatch: {key}')
        for row in rows:
            for field in ('level_unit', 'level_reference'):
                if row.get(field) is not None and row[field] != bundle[field]:
                    raise ValueError(f'observation metadata mismatch: {field}')
        expected = build_features(rows, bundle['variant'], target_date, allow_synthetic=self.source_kind=='synthetic')['target_date']
        # Append a placeholder target only for index selection; it is never an input.
        prediction = self._predictions(station_id, version, rows+[{'date': expected}], [20])[0]
        return {'station_id': station_id, 'namespace': self.namespace, 'model_version': version,
                'feature_contract_id': bundle['feature_contract_id'], 'input_end_date': rows[-1]['date'],
                'target_date': expected, 'predicted_level': prediction, 'level_unit': bundle['level_unit'],
                'level_reference': bundle['level_reference'], 'variant': bundle['variant'],
                'mapping_status': bundle_identity['mapping_status'],
                'operational_approved': bundle_identity['operational_approved'],
                'prediction_scope': 'synthetic' if self.source_kind=='synthetic' else 'operational' if bundle_identity['operational_approved'] else 'experimental'}

    def evaluate(self, station_id, version, records, seasonal_labels=None, heavy_rain_threshold_mm=None):
        rows = self._rows(station_id, records)
        bundle = self._bundle(station_id, version)
        if len(rows) < 21:
            raise ValueError('evaluation requires context plus at least one target')
        indices = list(range(20, len(rows)))
        actual = [rows[i]['groundwater_level'] for i in indices]
        predicted = self._predictions(station_id, version, rows, indices)
        result = {'metrics': _score(actual, predicted), 'evaluation_hash': _digest(rows),
                  'start': rows[20]['date'], 'end': rows[-1]['date'], 'groups': {}}
        threshold = bundle['heavy_rain_threshold_mm'] if heavy_rain_threshold_mm is None else heavy_rain_threshold_mm
        for group in ('rainy', 'non_rainy', 'heavy_rain'):
            selected = [j for j, i in enumerate(indices)
                        if (rows[i]['rainfall_mm'] >= threshold and rows[i]['rainfall_mm'] > 0
                            if group == 'heavy_rain' else group in (seasonal_labels or {}).get(rows[i]['date'], []))]
            result['groups'][group] = _score([actual[j] for j in selected], [predicted[j] for j in selected]) if selected else {'count': 0, 'rmse': None, 'mae': None}
        return result

    def fine_tune(self, station_id, records, metadata=None, max_epochs=10):
        """Exactly twenty context days plus twenty-one new labels, unchanged contract."""
        rows = self._rows(station_id, records, 41)
        identity = self._metadata(station_id, metadata)
        state = self._state(station_id)
        if not state['active_version']:
            raise ValueError('national model not ready')
        old = self._bundle(station_id, state['active_version'])
        for field in identity:
            if identity[field] != old[field]:
                raise ValueError(f'fine-tuning cannot change identity: {field}')
        for field in ('feature_contract_id', 'dtype', 'feature_order', 'summary_order', 'window'):
            if field in (metadata or {}) and metadata[field] != old[field]:
                raise ValueError(f'fine-tuning cannot change contract: {field}')
        for row in rows:
            for field in ('level_unit', 'level_reference'):
                if row.get(field) is not None and row[field] != old[field]:
                    raise ValueError(f'observation metadata mismatch: {field}')
        if rows[20]['date'] <= old['shadow_after']:
            raise ValueError('all fine-tuning targets must follow previous training/evaluation cutoff')
        version = uuid.uuid4().hex
        directory = self._station(station_id)/version
        directory.mkdir(parents=True)
        bundle = {**old, 'version': version, 'kind': 'fine_tune',
                  'comparison_version': state['active_version'], 'comparison_generation': state['generation'],
                  'trained_through': rows[-1]['date'], 'shadow_after': rows[-1]['date'],
                  'snapshot_hash': _digest(rows), 'fine_tuning_rows_count': 41,
                  'training_target_ranges': old.get('training_target_ranges', [])+[[rows[20]['date'], rows[-1]['date']]],
                  'fine_tuning_targets_count': 21, 'status': 'awaiting_shadow',
                  'created_at': datetime.now(timezone.utc).isoformat()}
        pairs = [self._inputs(rows[i-20:i], bundle) for i in range(20, 41)]
        scaler = old['scaler']
        targets = [(r['groundwater_level']-scaler['minimum'][0])/(scaler['maximum'][0]-scaler['minimum'][0] or 1) for r in rows[20:]]
        previous = self.backend.load(self._station(station_id)/state['active_version']/'model.keras')
        model = self.backend.train([p[0] for p in pairs], [p[1] for p in pairs], targets,
                                   validation=None, variant=old['variant'], max_epochs=max_epochs,
                                   initial=previous, learning_rate=.0001)
        self.backend.save(model, directory/'model.keras')
        _write(directory/'bundle.json', bundle)
        return self._public(bundle)

    def expire_candidate(self, station_id, version, as_of, max_wait_days=90, seasonal_labels=None):
        """Close immutable insufficient guards or timed-out shadow evidence; never switch."""
        if type(max_wait_days) is not int or max_wait_days<30:
            raise ValueError('candidate timeout must be at least thirty days')
        day=date.fromisoformat(as_of)
        with self._mutation(station_id):
            state=self._state(station_id)
            bundle=self._bundle(station_id,version)
            if state['active_version']==version:
                return {'status':'active','expired':False,'model_version':version}
            if bundle['status'].startswith('expired_'):
                return {'status':bundle['status'],'expired':True,'model_version':version,
                        'reason':bundle.get('expiration_reason'),'expired_as_of':bundle.get('expired_as_of')}
            evaluation_path=self._station(station_id)/version/'evaluation.json'
            evaluation=_read(evaluation_path) if evaluation_path.exists() else {}
            if bundle['status']!='awaiting_shadow' or evaluation.get('status') in ('gate_passed','experimental_gate_passed','synthetic_gate_passed','rejected'):
                return {'status':evaluation.get('status',bundle['status']),'expired':False,'model_version':version}
            after=date.fromisoformat(bundle['shadow_after'])
            if day<after:
                raise ValueError('expiration date precedes candidate cutoff')
            counts=None
            reason=None
            if bundle['variant']=='M1' and seasonal_labels is not None:
                targets=bundle['guard_rows'][20:]
                counts={group:sum(group in seasonal_labels.get(r['date'],[]) for r in targets)
                        for group in ('rainy','non_rainy')}
                counts['heavy_rain']=sum(r['rainfall_mm']>0 and r['rainfall_mm']>=bundle['heavy_rain_threshold_mm'] for r in targets)
                if any(count<30 for count in counts.values()):
                    reason='immutable_guard_seasonal_counts_below_30'
            if reason:
                status='expired_insufficient_seasonal_evidence'
            elif (day-after).days>=max_wait_days:
                status='expired_shadow_timeout';reason='prospective_evidence_timeout'
            else:
                return {'status':'awaiting_shadow','expired':False,'model_version':version,
                        'elapsed_days':(day-after).days,'timeout_days':max_wait_days}
            bundle.update(status=status,expired_as_of=as_of,expiration_reason=reason,
                expiration_policy={'timeout_days':max_wait_days,'seasonal_minimum':30},
                expiration_seasonal_counts=counts)
            _write(self._station(station_id)/version/'bundle.json',bundle)
            return {'status':status,'expired':True,'model_version':version,'reason':reason,
                    'expired_as_of':as_of,'seasonal_counts':counts,'active_version':state['active_version']}

    def evaluate_candidate(self, station_id, version, records, seasonal_labels=None, issued_predictions=None):
        """Thirty fresh consecutive targets and frozen untouched holdout; never auto-promote."""
        bundle = self._bundle(station_id, version)
        if bundle['status'].startswith('expired_'):
            return {'status':bundle['status'],'reason':bundle.get('expiration_reason'),'operational_promotion_evidence':False}
        rows = self._rows(station_id, records)
        existing = self._station(station_id)/version/'evaluation.json'
        if existing.exists():
            previous = _read(existing)
            if previous.get('status') in ('gate_passed', 'experimental_gate_passed', 'synthetic_gate_passed', 'rejected'):
                return previous
        state = self._state(station_id)
        if not bundle.get('comparison_version') or state['active_version'] != bundle['comparison_version'] or state['generation'] != bundle['comparison_generation']:
            return {'status': 'blocked', 'reason': 'champion_changed_or_missing'}
        eligible = [i for i in range(20, len(rows)) if rows[i]['date'] > bundle['shadow_after']]
        if len(eligible) < 30:
            return {'status': 'awaiting_shadow', 'count': len(eligible), 'required': 30}
        selected = eligible[:30]
        first_expected = (date.fromisoformat(bundle['shadow_after'])+timedelta(days=1)).isoformat()
        if rows[selected[0]]['date'] != first_expected:
            return {'status': 'blocked', 'reason': 'shadow_calendar_gap'}
        prediction_scope = 'synthetic' if self.source_kind=='synthetic' else 'experimental' if bundle.get('operational_approved') is False else 'operational'
        prospective = bool(issued_predictions)
        if prospective:
            proofs = list(issued_predictions)
            if len(proofs) < 30:
                return {'status': 'awaiting_issued_predictions', 'count': len(proofs), 'required': 30,
                        'evaluation_mode': 'simulated_prospective' if self.source_kind=='synthetic' else 'prospective'}
            by_date = {p['target_date']: p for p in proofs}
            if len(proofs) != 30 or len(by_date) != 30:
                raise ValueError('exactly thirty unique issued prediction pairs required')
            candidate_values, champion_values = [], []
            for i in selected:
                row = rows[i]
                proof = by_date.get(row['date'], {})
                if proof.get('prediction_scope','operational') != prediction_scope:
                    raise ValueError('issued prediction scope mismatch')
                if prediction_scope in ('experimental','synthetic'):
                    expected_end = (date.fromisoformat(row['date'])-timedelta(days=1)).isoformat()
                    if (proof.get('input_end_date') != expected_end or proof.get('horizon_days') != 1 or
                        proof.get('namespace') != self.namespace or proof.get('mapping_version') != bundle.get('mapping_version') or
                        proof.get('feature_contract_id') != bundle['feature_contract_id']):
                        raise ValueError('experimental issuance input contract mismatch')
                if (proof.get('candidate_version'), proof.get('champion_version')) != (version, state['active_version']):
                    raise ValueError('issued prediction version/date mismatch')
                if not proof.get('snapshot_id') or not row.get('available_at'):
                    raise ValueError('issuance snapshot and observation availability required')
                issued = datetime.fromisoformat(proof['issued_at'].replace('Z', '+00:00'))
                available = datetime.fromisoformat(row['available_at'].replace('Z', '+00:00'))
                if proof.get('actual_available_at'):
                    first_available = datetime.fromisoformat(proof['actual_available_at'].replace('Z','+00:00'))
                    if first_available.tzinfo is None:
                        raise ValueError('label availability timezone required')
                    available = min(available, first_available)
                target_end = datetime.fromisoformat(row['date']+'T00:00:00+09:00')+timedelta(days=1)
                if issued.tzinfo is None or available.tzinfo is None or issued >= available or issued >= target_end:
                    raise ValueError('predictions must precede label availability and target day end')
                candidate_values.append(proof['candidate_prediction'])
                champion_values.append(proof['champion_prediction'])
        else:
            candidate_values = self._predictions(station_id, version, rows, selected)
            champion_values = self._predictions(station_id, state['active_version'], rows, selected)
        candidate = _score([rows[i]['groundwater_level'] for i in selected], candidate_values)
        champion = _score([rows[i]['groundwater_level'] for i in selected], champion_values)
        guard = bundle['guard_rows']
        incumbent_bundle = self._bundle(station_id, state['active_version'])
        # Fine-tuned incumbents retain a frozen original holdout, which is older
        # than their newest targets but has never been a training target.
        ranges = incumbent_bundle.get('training_target_ranges', [[guard[0]['date'], incumbent_bundle['trained_through']]])
        if any(start <= row['date'] <= end for start, end in ranges for row in guard[20:]):
            return {'status': 'blocked', 'reason': 'guard_overlaps_incumbent_training'}
        guard_indices = list(range(20, len(guard)))
        guard_candidate = _score([r['groundwater_level'] for r in guard[20:]], self._predictions(station_id, version, guard, guard_indices))
        guard_champion = _score([r['groundwater_level'] for r in guard[20:]], self._predictions(station_id, state['active_version'], guard, guard_indices))
        seasonal = self.evaluate(station_id, version, guard, seasonal_labels)
        seasonal_old = self.evaluate(station_id, state['active_version'], guard, seasonal_labels,
                                     heavy_rain_threshold_mm=bundle['heavy_rain_threshold_mm'])
        enough = all(seasonal['groups'][g]['count'] >= 30 for g in ('rainy', 'non_rainy', 'heavy_rain'))
        seasonal_passed = enough and all(
            (seasonal_old['groups'][g]['rmse'] > 0 and seasonal['groups'][g]['rmse'] <= seasonal_old['groups'][g]['rmse']*.95)
            if g == 'rainy' else seasonal['groups'][g]['rmse'] <= seasonal_old['groups'][g]['rmse']*1.10+1e-12
            for g in ('rainy', 'non_rainy', 'heavy_rain'))
        gates = {'future': champion['rmse'] > 0 and candidate['rmse'] <= champion['rmse']*.95,
                 'guard': guard_candidate['rmse'] <= guard_champion['rmse']*1.10+1e-12,
                 'seasonal': seasonal_passed if bundle['variant'] == 'M1' else True}
        status = 'insufficient_seasonal_evidence' if bundle['variant'] == 'M1' and not enough else ('gate_passed' if all(gates.values()) else 'rejected')
        if status == 'gate_passed' and prediction_scope in ('experimental','synthetic'):
            status = 'synthetic_gate_passed' if prediction_scope=='synthetic' else 'experimental_gate_passed'
        if not prospective:
            status = 'retrospective_evaluation'
        result = {'status': status, 'gates': gates, 'candidate': candidate, 'champion': champion,
                  'evaluation_mode': ('simulated_prospective' if prospective else 'retrospective_simulation') if self.source_kind=='synthetic' else ('prospective' if prospective else 'retrospective'),
                  'simulation':self.source_kind=='synthetic',
                  'prediction_scope':prediction_scope,'operational_promotion_evidence':prediction_scope == 'operational' and prospective,
                  'guard_candidate': guard_candidate, 'guard_champion': guard_champion,
                  'seasonal': seasonal, 'comparison_version': state['active_version'],
                  'comparison_generation': state['generation'], 'evaluation_hash': _digest(rows),
                  'seasonal_labels_hash': _digest(seasonal_labels or {}),
                  'issued_predictions_hash': _digest(issued_predictions or []),
                  'forecast_timing': sorted({('same_day_estimate' if datetime.fromisoformat(p['issued_at'].replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=9))).date().isoformat() == p['target_date'] else 'next_day_forecast') for p in (issued_predictions or [])}),
                  'shadow_start': rows[selected[0]]['date'], 'shadow_end': rows[selected[-1]]['date']}
        with self._mutation(station_id):
            if self._state(station_id) != state:
                return {'status': 'blocked', 'reason': 'champion_changed'}
            _write(self._station(station_id)/version/'evaluation.json', result)
        return result

    def promote(self, station_id, version):
        with self._mutation(station_id):
            state = self._state(station_id)
            bundle = self._bundle(station_id, version)
            if bundle.get('operational_approved') is False:
                raise ValueError('operational mapping approval required for promotion')
            if bundle['status'].startswith('expired_'):
                raise ValueError('expired candidate cannot be promoted')
            evaluation = _read(self._station(station_id)/version/'evaluation.json')
            champion_rmse=evaluation.get('champion',{}).get('rmse')
            candidate_rmse=evaluation.get('candidate',{}).get('rmse')
            improvement_valid=(all(isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0
                                   for value in (champion_rmse,candidate_rmse)) and
                               champion_rmse>0 and candidate_rmse<=champion_rmse*.95)
            if evaluation['status'] != 'gate_passed' or evaluation.get('evaluation_mode') != 'prospective' or not all(evaluation['gates'].values()) or not improvement_valid:
                raise ValueError('quality gates not passed')
            if (state['active_version'], state['generation']) != (evaluation['comparison_version'], evaluation['comparison_generation']):
                raise ValueError('champion_changed')
            self._predictions(station_id, version, bundle['guard_rows'], [20])
            state.update(active_version=version, generation=state['generation']+1)
            state.setdefault('history', []).append({'from': evaluation['comparison_version'], 'to': version,
                                                   'kind': 'promotion', 'at': datetime.now(timezone.utc).isoformat()})
            _write(self._station(station_id)/'state.json', state)
            bundle['status'] = 'active'
            _write(self._station(station_id)/version/'bundle.json', bundle)
            return {'status': 'promoted', 'model_version': version, 'generation': state['generation']}

    def rollback(self, station_id, version, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('rollback reason required')
        with self._mutation(station_id):
            state = self._state(station_id)
            if version not in {item['to'] for item in state.get('history', [])}:
                raise ValueError('rollback requires previously activated history')
            bundle = self._bundle(station_id, version)
            self._predictions(station_id, version, bundle['guard_rows'], [20])
            previous = state['active_version']
            state.update(active_version=version, generation=state['generation']+1)
            state.setdefault('history', []).append({'from': previous, 'to': version, 'kind': 'rollback',
                                                    'reason': reason.strip(), 'at': datetime.now(timezone.utc).isoformat()})
            _write(self._station(station_id)/'state.json', state)
            return {'status': 'rolled_back', 'model_version': version, 'previous_version': previous,
                    'generation': state['generation'], 'reason': reason.strip()}

    @staticmethod
    def _public(bundle):
        return {k: v for k, v in bundle.items() if k != 'guard_rows'}

    def list_models(self, station_id=None):
        directories = [self._station(station_id)] if station_id else list(self.root.iterdir())
        result = []
        for directory in directories:
            if not directory.is_dir():
                continue
            for path in directory.glob('*/bundle.json'):
                bundle = _read(path)
                state = self._state(bundle['station_id'])
                evaluation = path.with_name('evaluation.json')
                if evaluation.exists():
                    evaluation_result = _read(evaluation)
                    bundle['evaluation_status'] = evaluation_result['status']
                    if evaluation_result['status'] == 'rejected':
                        bundle['status'] = 'rejected'
                result.append({**self._public(bundle), 'active': state['active_version'] == bundle['version']})
        return result
