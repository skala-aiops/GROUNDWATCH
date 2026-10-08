"""District-isolated, chronological groundwater training and champion serving.

TensorFlow and MLflow are imported only by the production backend. No sample model
or invented observation is substituted when a model or dataset is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Any


class ModelNotReady(RuntimeError):
    pass


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def _row(record: Any) -> dict:
    item = dict(record) if isinstance(record, dict) else vars(record).copy()
    item['date'] = str(item['date'])
    for field in ('groundwater_level', 'rainfall_mm'):
        item[field] = float(item[field])
        if not math.isfinite(item[field]):
            raise ValueError(f'{field}: finite number required')
    if item['rainfall_mm'] < 0:
        raise ValueError('rainfall_mm: negative rainfall')
    date.fromisoformat(item['date'])
    return item


def validate_rows(records: list, length: int | None = None) -> list[dict]:
    rows = [_row(r) for r in records]
    if length is not None and len(rows) != length:
        raise ValueError(f'exactly {length} consecutive daily records required')
    for left, right in zip(rows, rows[1:]):
        if date.fromisoformat(right['date']) - date.fromisoformat(left['date']) != timedelta(days=1):
            raise ValueError('records must be ordered, unique, consecutive calendar days')
    for field in ('station_id', 'district_code', 'level_unit'):
        values = {r[field] for r in rows if r.get(field) is not None}
        if len(values) > 1:
            raise ValueError(f'{field}: mixed identity or unit')
    return rows


def metrics(actual: list[float], predicted: list[float]) -> dict:
    if len(actual) != len(predicted) or not actual:
        raise ValueError('equal nonempty actual/prediction arrays required')
    residuals = [float(a) - float(p) for a, p in zip(actual, predicted)]
    if not all(math.isfinite(r) for r in residuals):
        raise ValueError('nonfinite prediction')
    return {'rmse': math.sqrt(sum(r*r for r in residuals) / len(residuals)),
            'mae': sum(abs(r) for r in residuals) / len(residuals), 'count': len(residuals)}


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lower = int(index)
    return ordered[lower] + (ordered[min(lower+1, len(ordered)-1)] - ordered[lower]) * (index-lower)


class Scaler:
    """Min/max fitted on training context and training targets only."""
    def __init__(self, minimum: list[float], maximum: list[float]):
        self.minimum, self.maximum = minimum, maximum

    @classmethod
    def fit(cls, rows: list[dict]) -> 'Scaler':
        pairs = [[r['groundwater_level'], r['rainfall_mm']] for r in rows]
        return cls([min(p[i] for p in pairs) for i in range(2)],
                   [max(p[i] for p in pairs) for i in range(2)])

    def transform(self, row: dict) -> list[float]:
        return [(row[key]-self.minimum[i]) / (self.maximum[i]-self.minimum[i] or 1.0)
                for i, key in enumerate(('groundwater_level', 'rainfall_mm'))]

    def inverse(self, value: float) -> float:
        return float(value) * (self.maximum[0]-self.minimum[0] or 1.0) + self.minimum[0]

    def dump(self) -> dict:
        return {'minimum': self.minimum, 'maximum': self.maximum, 'fit_scope': 'train_only'}


def _windows(rows: list[dict], scaler: Scaler) -> tuple[list, list, list]:
    x, y, target_rows = [], [], []
    for i in range(20, len(rows)):
        x.append([scaler.transform(r) for r in rows[i-20:i]])
        y.append(scaler.transform(rows[i])[0])
        target_rows.append(rows[i])
    return x, y, target_rows


class TensorFlowBackend:
    """Production backend; MLflow registry versions are the serving identity."""
    def __init__(self, tracking_uri: str, artifacts: Path):
        self.tracking_uri = tracking_uri
        self.artifacts = artifacts

    def _client(self):
        import mlflow
        from mlflow.tracking import MlflowClient
        mlflow.set_tracking_uri(self.tracking_uri)
        return MlflowClient(tracking_uri=self.tracking_uri)

    def train(self, x, y, validation, max_epochs=100, initial=None, learning_rate=0.001, architecture='absolute_lstm'):
        import numpy as np
        import tensorflow as tf
        tf.keras.utils.set_random_seed(42)
        if initial is None:
            if architecture == 'absolute_lstm':
                model = tf.keras.Sequential([
                    tf.keras.layers.Input(shape=(20, 2)),
                    tf.keras.layers.LSTM(32, return_sequences=True),
                    tf.keras.layers.LSTM(32), tf.keras.layers.Dense(16, activation='relu'),
                    tf.keras.layers.Dense(1)])
            elif architecture == 'residual_lstm':
                inputs = tf.keras.layers.Input(shape=(20, 2), name='daily_observations')
                hidden = tf.keras.layers.LSTM(32, return_sequences=True)(inputs)
                hidden = tf.keras.layers.LSTM(32)(hidden)
                hidden = tf.keras.layers.Dense(16, activation='relu')(hidden)
                delta = tf.keras.layers.Dense(1, kernel_initializer='zeros', bias_initializer='zeros',
                                              name='learned_level_change')(hidden)
                last_day = tf.keras.layers.Cropping1D(cropping=(19, 0), name='last_observed_day')(inputs)
                last_pair = tf.keras.layers.Flatten()(last_day)
                persistence = tf.keras.layers.Dense(1, use_bias=False, trainable=False,
                    kernel_initializer=tf.keras.initializers.Constant([[1.0], [0.0]]),
                    name='last_groundwater_level')(last_pair)
                outputs = tf.keras.layers.Add(name='next_level')([persistence, delta])
                model = tf.keras.Model(inputs, outputs, name='groundwater_residual_lstm')
            else:
                raise ValueError('unsupported model_architecture')
        else:
            model = tf.keras.models.clone_model(initial)
            model.set_weights(initial.get_weights())
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate), loss='mse')
        options = tf.data.Options()
        options.threading.private_threadpool_size = 1
        options.threading.max_intra_op_parallelism = 1
        def bounded_dataset(inputs, targets):
            return tf.data.Dataset.from_tensor_slices((np.asarray(inputs, dtype='float32'),
                                                       np.asarray(targets, dtype='float32'))).batch(32).with_options(options)
        kwargs = {}
        if validation is not None:
            kwargs['validation_data'] = bounded_dataset(*validation)
            kwargs['callbacks'] = [tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)]
        model.fit(bounded_dataset(x, y), epochs=max_epochs, shuffle=False, verbose=0, **kwargs)
        return model

    def predict(self, model, inputs):
        import numpy as np
        return [float(v[0]) for v in model(np.asarray(inputs, dtype='float32'), training=False).numpy()]

    def register(self, name: str, model, bundle: dict, directory: Path) -> str:
        import mlflow
        client = self._client()
        directory.mkdir(parents=True, exist_ok=True)
        model.save(directory / 'model.keras')
        _json(directory / 'bundle.json', bundle)
        experiment_name = 'GroundWatch-' + hashlib.sha256(str(self.artifacts.resolve()).encode()).hexdigest()[:12]
        experiment = client.get_experiment_by_name(experiment_name)
        experiment_id = experiment.experiment_id if experiment else client.create_experiment(
            experiment_name, artifact_location=self.artifacts.resolve().as_uri())
        with mlflow.start_run(experiment_id=experiment_id, run_name=f'{name}-{bundle["kind"]}') as run:
            mlflow.log_params({'district': bundle['district_code'], 'kind': bundle['kind'],
                               'dataset_version': bundle.get('dataset_version', 'unknown'),
                               'model_architecture': bundle.get('model_architecture', 'absolute_lstm'),
                               'learning_rate': bundle.get('learning_rate', 0.001),
                               'seed': 42, 'window': 20})
            for section, values in bundle.get('metrics', {}).items():
                for key, value in values.items():
                    if isinstance(value, (float, int)):
                        prefix = 'reference_' if bundle['kind'] == 'fine_tune' else ''
                        mlflow.log_metric(f'{prefix}{section}_{key}', value)
            if bundle.get('metrics_reference_version'):
                mlflow.log_param('metrics_reference_version', bundle['metrics_reference_version'])
            mlflow.log_artifacts(str(directory), artifact_path='bundle')
            try:
                client.get_registered_model(name)
            except mlflow.exceptions.MlflowException:
                client.create_registered_model(name)
            source = f'{run.info.artifact_uri}/bundle'
            version = client.create_model_version(name, source, run.info.run_id)
            return str(version.version)

    def record_evaluation(self, name, version, result):
        client = self._client()
        model_version = client.get_model_version(name, str(version))
        for section, values in result.get('metrics', {}).items():
            for key, value in values.items():
                if isinstance(value, (int,float)):
                    client.log_metric(model_version.run_id, f'{section}_{key}', float(value))
        for key in ('gate_passed','status','shadow_start','shadow_end','reason'):
            if key in result:
                client.set_model_version_tag(name,str(version),key,str(result[key]))
                client.set_tag(model_version.run_id,key,str(result[key]))
        client.log_dict(model_version.run_id, result, 'evaluation/shadow-result.json')

    def load(self, name: str, version: str):
        import mlflow
        from tensorflow import keras
        self._client()
        directory = Path(mlflow.artifacts.download_artifacts(artifact_uri=f'models:/{name}/{version}'))
        return keras.models.load_model(directory / 'model.keras'), json.loads((directory / 'bundle.json').read_text())

    def alias(self, name: str) -> str | None:
        client = self._client()
        try:
            return str(client.get_model_version_by_alias(name, 'champion').version)
        except Exception as error:
            code = getattr(error, 'error_code', '')
            message = str(error)
            if code == 'RESOURCE_DOES_NOT_EXIST' or (
                code == 'INVALID_PARAMETER_VALUE' and
                re.search(r'Registered model alias [\'\"]?champion[\'\"]? not found', message, re.IGNORECASE)
            ):
                return None
            raise

    def set_alias(self, name: str, version: str | None):
        client = self._client()
        if version is None:
            client.delete_registered_model_alias(name, 'champion')
        else:
            client.set_registered_model_alias(name, 'champion', str(version))


class ModelManager:
    def __init__(self, root, tracking_uri=None, namespace='historical', backend=None):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', namespace):
            raise ValueError('invalid model namespace')
        self.namespace = namespace
        self.root = Path(root) / namespace
        self.root.mkdir(parents=True, exist_ok=True)
        self.backend = backend or TensorFlowBackend(
            tracking_uri or f'sqlite:///{self.root / "mlflow.db"}', self.root / 'artifacts')
        self._cache: dict[str, tuple] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.RLock()

    def _lock(self, code):
        with self._guard:
            return self._locks.setdefault(code, threading.RLock())

    def _name(self, code):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', str(code)):
            raise ValueError('invalid district code')
        return f'GroundWatch_{self.namespace}_{code}'

    def _state(self, code):
        path = self.root / f'{code}.json'
        return json.loads(path.read_text()) if path.exists() else {'district_code': code, 'versions': {}, 'champion': None, 'history': []}

    def _save(self, code, state):
        _json(self.root / f'{code}.json', state)

    def _check_namespace(self, namespace):
        if namespace is not None and namespace != self.namespace:
            raise ValueError('namespace mismatch: instantiate an isolated manager')

    def _loaded(self, code, version=None):
        name = self._name(code)
        with self._lock(code):
            if version is None:
                version = self.backend.alias(name)
                if version is None:
                    raise ModelNotReady(f'{code}: model_not_ready')
                cached = self._cache.get(code)
                if cached and cached[0] == str(version):
                    return cached[1], cached[2], str(version)
            model, bundle = self.backend.load(name, str(version))
            if bundle['district_code'] != code or bundle['namespace'] != self.namespace:
                raise ValueError('registered model identity mismatch')
            if self.backend.alias(name) == str(version):
                self._cache[code] = (str(version), model, bundle)
            return model, bundle, str(version)

    def current_version(self, code):
        return self.backend.alias(self._name(code))

    def check_ready(self, code, metadata):
        model, bundle, version = self._loaded(code)
        fields = ('station_id','level_unit','mapping_version','dataset_version')
        if metadata.get('feature_contract_id'):
            fields = ('station_id','level_unit','mapping_version','feature_contract_id',
                      'preprocessing_version','rain_source','weather_station_id')
            if not bundle.get('training_snapshot_id') or not bundle.get('feature_contract_id'):
                raise ValueError('legacy model cannot serve live API contract')
        for field in fields:
            if metadata.get(field) != bundle.get(field):
                raise ValueError(f'{field}: latest dataset/model mismatch')
        self._predict(model,bundle,validate_rows(bundle['smoke_rows'],20))
        return version

    def reconcile(self):
        """Recover a registry-alias commit interrupted before local history write."""
        repaired = []
        for path in self.root.glob('*.json'):
            code = path.stem
            with self._lock(code):
                state = self._state(code)
                actual = self.current_version(code)
                if actual != state.get('champion'):
                    if actual is not None:
                        _, bundle, _ = self._loaded(code,actual)
                        state['versions'].setdefault(actual,bundle)
                        state['history'].append({'from':state.get('champion'),'to':actual,'recovered':True})
                    state['champion'] = actual
                    self._save(code,state)
                    repaired.append(code)
        return repaired

    def _predict(self, model, bundle, rows):
        scaler = Scaler(**{k: bundle['scaler'][k] for k in ('minimum', 'maximum')})
        outputs = self.backend.predict(model, [[scaler.transform(r) for r in rows]])
        value = scaler.inverse(outputs[0])
        if not math.isfinite(value):
            raise ValueError('nonfinite prediction')
        return value

    def _identity(self, code, rows, bundle):
        for row in rows:
            for key, expected in (('district_code', code), ('station_id', bundle.get('station_id')), ('level_unit', bundle.get('level_unit'))):
                if row.get(key) is not None and expected is not None and str(row[key]) != str(expected):
                    raise ValueError(f'{key}: model/input mismatch')

    def predict(self, district_code, records, namespace=None):
        self._check_namespace(namespace)
        rows = validate_rows(records, 20)
        model, bundle, version = self._loaded(district_code)
        self._identity(district_code, rows, bundle)
        return {'district_code': district_code, 'station_id': bundle['station_id'],
                'prediction': self._predict(model, bundle, rows), 'model_version': version,
                'unit': bundle['level_unit'], 'level_unit': bundle['level_unit'],
                'dataset_version': bundle['dataset_version'], 'mapping_version': bundle['mapping_version'],
                'observed_date': rows[-1]['date'],
                'forecast_date': str(date.fromisoformat(rows[-1]['date']) + timedelta(days=1)),
                'namespace': self.namespace, 'threshold': bundle['threshold']}

    def train(self, dataset, district_code=None, metadata=None, max_epochs=100):
        if isinstance(dataset, str):
            code, records = dataset, district_code
        else:
            code, records = district_code, dataset.rows_for_district(district_code)
            metadata = metadata or dataset.metadata_for_district(district_code)
        configuration = (metadata or {}).get('training', {})
        policy = (metadata or {}).get('split_policy', configuration.get('split_policy', configuration.get('policy')))
        if policy == 'gap_aware':
            replay_start = (metadata or {}).get('replay_start', configuration.get('replay_start'))
            if not replay_start:
                raise ValueError('gap_aware training requires explicit common replay_start')
            return self.train_windowed(code, records, replay_start=replay_start, metadata=metadata, max_epochs=max_epochs)
        self._name(code)
        rows = validate_rows(records)
        if len(rows) < 410:
            raise ValueError('at least 410 consecutive calendar days required (180/60/60/90 targets plus20 context)')
        metadata = dict(metadata or {})
        for key in ('station_id', 'level_unit', 'dataset_version', 'mapping_version'):
            metadata.setdefault(key, rows[0].get(key))
            if not metadata[key] or str(metadata[key]).lower() in ('unknown', 'unverified'):
                raise ValueError(f'{key}: verified metadata required')
        if metadata.get('manifest_approved') is not True:
            raise ValueError('representative station manifest approval required')
        self._identity(code, rows, metadata)
        train_count = len(rows) - 20 - 60 - 60 - 90
        train_end = 20 + train_count
        scaler = Scaler.fit(rows[:train_end])
        x, y, targets = _windows(rows, scaler)
        v_end, t_end = train_count+60, train_count+120
        architecture = metadata.get('model_architecture', configuration.get('model_architecture', 'absolute_lstm'))
        if architecture not in ('absolute_lstm', 'residual_lstm'):
            raise ValueError('unsupported model_architecture')
        metadata['model_architecture'] = architecture
        learning_rate = float(metadata.get('learning_rate', configuration.get('learning_rate', .001)))
        if not math.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError('learning_rate must be finite and positive')
        metadata['learning_rate'] = learning_rate
        model = self.backend.train(x[:train_count], y[:train_count], (x[train_count:v_end], y[train_count:v_end]),
                                   max_epochs=max_epochs or 100, architecture=architecture, learning_rate=learning_rate)
        measured = {}
        for label, start, end in (('validation', train_count, v_end), ('test', v_end, t_end)):
            actual = [r['groundwater_level'] for r in targets[start:end]]
            predicted = [scaler.inverse(v) for v in self.backend.predict(model, x[start:end])]
            measured[label] = metrics(actual, predicted)
            persistence = [rows[20+i-1]['groundwater_level'] for i in range(start, end)]
            measured[f'{label}_persistence'] = metrics(actual, persistence)
            if label == 'validation':
                rolling = [metrics(actual[i-20:i+1], predicted[i-20:i+1])['rmse'] for i in range(20, len(actual))]
        threshold = max(1e-6, _percentile(rolling, .95) * 1.5)
        splits = {label: {'start': targets[start]['date'], 'end': targets[end-1]['date'], 'count': end-start}
                  for label, start, end in (('train', 0, train_count), ('validation', train_count, v_end), ('test', v_end, t_end), ('replay', t_end, len(targets)))}
        bundle = {**metadata, 'district_code': code, 'namespace': self.namespace, 'kind': 'initial',
                  'scaler': scaler.dump(), 'metrics': measured, 'splits': splits, 'threshold': threshold,
                  'feature_order': ['groundwater_level', 'rainfall_mm'], 'window': 20,
                  'seed': 42, 'trained_through': targets[train_count-1]['date'],
                  'training_hash': hashlib.sha256(json.dumps(rows[:train_end], sort_keys=True).encode()).hexdigest(),
                  'guard_rows': rows[train_count:20+v_end], 'smoke_rows': rows[train_end-20:train_end]}
        version = self._register(code, model, bundle)
        passed = measured['validation']['rmse'] <= measured['validation_persistence']['rmse'] * 1.10 + 1e-12
        result = {'status': 'rejected', 'version': version, 'model_version': version, 'metrics': measured,
                  'splits': splits, 'threshold': threshold, 'gate_passed': passed}
        if passed:
            self.promote(code, version)
            result['status'] = 'promoted'
        return result

    def train_windowed(self, dataset, district_code=None, replay_start=None, metadata=None, max_epochs=100):
        """Train on independently valid windows; calendar gaps are never joined.

        Historical training dates can have gaps. Validation/test/replay target
        blocks are independently continuous and strictly chronologically ordered.
        Observations after the configured replay interval cannot affect fitting.
        """
        from data.groundwater import Observation, continuous_windows, gap_aware_split
        if isinstance(dataset, str):
            code, records = dataset, district_code
        else:
            code, records = district_code, dataset.rows_for_district(district_code)
            metadata = metadata or dataset.metadata_for_district(district_code)
        self._name(code)
        rows = sorted((_row(r) for r in records), key=lambda r:r['date'])
        if not rows or len({r['date'] for r in rows}) != len(rows):
            raise ValueError('nonempty unique daily observations required')
        metadata = dict(metadata or {})
        for key in ('station_id', 'level_unit', 'dataset_version', 'mapping_version'):
            metadata.setdefault(key, rows[0].get(key))
            if not metadata[key] or str(metadata[key]).lower() in ('unknown', 'unverified'):
                raise ValueError(f'{key}: verified metadata required')
        if metadata.get('manifest_approved') is not True:
            raise ValueError('representative station manifest approval required')
        self._identity(code, rows, metadata)
        observations = [Observation(metadata['station_id'], code, date.fromisoformat(r['date']),
                                    r['groundwater_level'], r['rainfall_mm'], metadata['level_unit'],
                                    metadata['dataset_version']) for r in rows]
        partitions = gap_aware_split(continuous_windows(observations, 20), replay_start)
        configuration = metadata.get('training', {})
        cap = metadata.get('train_max_targets', configuration.get('train_max_targets'))
        if cap is not None:
            if isinstance(cap, bool) or not isinstance(cap, int) or cap < 180:
                raise ValueError('train_max_targets must be an integer at least180')
            partitions['train'] = partitions['train'][-cap:]
            metadata['train_max_targets'] = cap
        by_date = {r['date']: r for r in rows}
        train_dates = {str(w.target_date-timedelta(days=offset))
                       for w in partitions['train'] for offset in range(21)}
        fit_rows = [by_date[day] for day in sorted(train_dates)]
        scaler = Scaler.fit(fit_rows)
        def arrays(windows):
            x = [[scaler.transform({'groundwater_level':level, 'rainfall_mm':rain})
                  for level, rain in w.inputs] for w in windows]
            y = [(w.target-scaler.minimum[0])/(scaler.maximum[0]-scaler.minimum[0] or 1.0) for w in windows]
            return x, y
        train_x, train_y = arrays(partitions['train'])
        validation_x, validation_y = arrays(partitions['validation'])
        architecture = metadata.get('model_architecture', configuration.get('model_architecture', 'absolute_lstm'))
        if architecture not in ('absolute_lstm', 'residual_lstm'):
            raise ValueError('unsupported model_architecture')
        metadata['model_architecture'] = architecture
        learning_rate = float(metadata.get('learning_rate', configuration.get('learning_rate', .001)))
        if not math.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError('learning_rate must be finite and positive')
        metadata['learning_rate'] = learning_rate
        model = self.backend.train(train_x, train_y, (validation_x, validation_y),
                                   max_epochs=max_epochs or 100, architecture=architecture, learning_rate=learning_rate)
        measured = {}
        for label in ('validation', 'test'):
            windows = partitions[label]
            x, _ = arrays(windows)
            actual = [w.target for w in windows]
            predicted = [scaler.inverse(v) for v in self.backend.predict(model, x)]
            measured[label] = metrics(actual, predicted)
            measured[f'{label}_persistence'] = metrics(actual, [w.inputs[-1][0] for w in windows])
            if label == 'validation':
                rolling = [metrics(actual[i-20:i+1], predicted[i-20:i+1])['rmse'] for i in range(20, len(windows))]
        threshold = max(1e-6, _percentile(rolling, .95)*1.5)
        splits = {label: {'start':str(windows[0].target_date), 'end':str(windows[-1].target_date),
                          'count':len(windows), 'target_dates_continuous': all(
                              b.target_date-a.target_date == timedelta(days=1) for a,b in zip(windows, windows[1:]))}
                  for label, windows in partitions.items()}
        validation = partitions['validation']
        guard_start = validation[0].target_date-timedelta(days=20)
        guard_rows = [by_date[str(guard_start+timedelta(days=i))] for i in range(80)]
        latest_train = partitions['train'][-1].target_date
        smoke_rows = [by_date[str(latest_train-timedelta(days=offset))] for offset in range(19,-1,-1)]
        bundle = {**metadata, 'district_code':code, 'namespace':self.namespace, 'kind':'initial',
                  'split_policy':'gap_aware', 'replay_start':str(partitions['replay'][0].target_date),
                  'scaler':scaler.dump(), 'metrics':measured, 'splits':splits, 'threshold':threshold,
                  'feature_order':['groundwater_level','rainfall_mm'], 'window':20, 'seed':42,
                  'trained_through':str(latest_train),
                  'training_hash':hashlib.sha256(json.dumps(fit_rows, sort_keys=True).encode()).hexdigest(),
                  'scaler_fit_start':fit_rows[0]['date'], 'scaler_fit_end':fit_rows[-1]['date'],
                  'scaler_fit_observations':len(fit_rows), 'guard_rows':guard_rows, 'smoke_rows':smoke_rows}
        version = self._register(code, model, bundle)
        passed = measured['validation']['rmse'] <= measured['validation_persistence']['rmse']*1.10 + 1e-12
        result = {'status':'rejected', 'version':version, 'model_version':version, 'metrics':measured,
                  'splits':splits, 'threshold':threshold, 'split_policy':'gap_aware', 'gate_passed':passed}
        if passed:
            self.promote(code, version)
            result['status'] = 'promoted'
        return result

    def _register(self, code, model, bundle):
        with self._lock(code):
            directory = self.root / 'bundles' / code / hashlib.sha256(os.urandom(32)).hexdigest()[:16]
            version = str(self.backend.register(self._name(code), model, bundle, directory))
            state = self._state(code)
            state['versions'][version] = bundle
            self._save(code, state)
            return version

    def promote(self, code, version):
        """Activate only a quality-validated initial model or shadow candidate."""
        with self._lock(code):
            _, bundle, version = self._loaded(code, str(version))
            current = self.current_version(code)
            if bundle.get('kind') == 'initial':
                scores = bundle.get('metrics', {})
                validation = scores.get('validation', {}).get('rmse')
                persistence = scores.get('validation_persistence', {}).get('rmse')
                if not self._valid_rmse(validation) or not self._valid_rmse(persistence) or validation > persistence * 1.10 + 1e-12:
                    raise ModelNotReady('initial quality gate was not passed')
            elif bundle.get('kind') == 'fine_tune':
                evaluation = self._state(code)['versions'][version].get('shadow_result', {})
                self._validate_shadow_gate(bundle, version, evaluation)
                if current == version and evaluation['status'] == 'promoted':
                    return {'status': 'promoted', 'model_version': version,
                            'previous_version': evaluation['previous_version']}
                if current != bundle['parent_version']:
                    raise ModelNotReady('champion_changed')
            else:
                raise ModelNotReady('unknown model quality policy')
            return self._activate(code, version, current)

    @staticmethod
    def _valid_rmse(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0

    def _validate_shadow_gate(self, bundle, version, evaluation):
        """Recheck persisted evidence rather than trusting a caller's pass flag."""
        scores = evaluation.get('metrics', {})
        candidate = scores.get('shadow_candidate', {})
        champion = scores.get('shadow_champion', {})
        guard = scores.get('historical_guard', {})
        reference = bundle.get('metrics', {}).get('validation', {}).get('rmse')
        values = (candidate.get('rmse'), champion.get('rmse'), guard.get('rmse'), reference)
        try:
            start, end = date.fromisoformat(evaluation['shadow_start']), date.fromisoformat(evaluation['shadow_end'])
            dates_valid = start > date.fromisoformat(bundle['shadow_after']) and (end-start).days == 29
        except (KeyError, TypeError, ValueError):
            dates_valid = False
        if not (
            evaluation.get('status') in ('gate_passed', 'promoted')
            and evaluation.get('gate_passed') is True
            and evaluation.get('candidate_version') == version
            and evaluation.get('previous_version') == bundle['parent_version']
            and candidate.get('count') == champion.get('count') == 30
            and isinstance(guard.get('count'), int) and guard['count'] > 0
            and dates_valid and all(self._valid_rmse(value) for value in values)
            and champion['rmse'] > 0 and candidate['rmse'] <= champion['rmse'] * .95
            and guard['rmse'] <= reference * 1.10 + 1e-12
        ):
            raise ModelNotReady('shadow quality gate was not passed')

    def _activate(self, code, version, expected_current):
        """Shared switch for validated promotion and explicit history-based rollback."""
        with self._lock(code):
            model, bundle, version = self._loaded(code, str(version))
            self._predict(model, bundle, validate_rows(bundle['smoke_rows'], 20))
            name, old = self._name(code), self.backend.alias(self._name(code))
            if old != expected_current:
                raise ModelNotReady('champion_changed')
            if old == version:
                return {'status': 'promoted', 'model_version': version, 'previous_version': old}
            old_cache = self._cache.get(code)
            state = self._state(code)
            try:
                self.backend.set_alias(name, version)
                self._cache[code] = (version, model, bundle)
                state['champion'] = version
                state['history'].append({'from': old, 'to': version, 'promoted_at':datetime.now(timezone.utc).isoformat()})
                evaluation = state['versions'][version].get('shadow_result', {})
                if evaluation.get('status') == 'gate_passed':
                    evaluation.update(status='promoted', model_version=version, previous_version=old)
                self._save(code, state)
            except Exception:
                self.backend.set_alias(name, old)
                if old_cache is None:
                    self._cache.pop(code, None)
                else:
                    self._cache[code] = old_cache
                raise
            return {'status': 'promoted', 'model_version': version, 'previous_version': old}

    def fine_tune(self, district_code, records, metadata=None, namespace=None):
        self._check_namespace(namespace)
        rows = validate_rows(records, 41)
        model, bundle, champion = self._loaded(district_code)
        self._identity(district_code, rows, bundle)
        if rows[-1]['date'] <= bundle['trained_through']:
            raise ValueError('fine-tuning requires new observations after champion training cutoff')
        scaler = Scaler(**{k: bundle['scaler'][k] for k in ('minimum', 'maximum')})
        x, y, _ = _windows(rows, scaler)
        candidate = self.backend.train(x, y, None, max_epochs=10, initial=model, learning_rate=.0001)
        for field in ('station_id', 'district_code', 'level_unit', 'mapping_version', 'namespace'):
            if metadata and field in metadata and metadata[field] != bundle.get(field):
                raise ValueError(f'{field}: fine-tuning cannot change model identity')
        new_bundle = {**bundle, **(metadata or {}), 'kind': 'fine_tune', 'parent_version': champion,
                      'trained_through': rows[-1]['date'], 'shadow_after': rows[-1]['date'],
                      'metrics_reference_version': bundle.get('metrics_reference_version', champion),
                      'threshold_policy': 'retain_initial_validation_reference',
                      'fine_tuning_hash': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
                      'fine_tuning_rows_count': 41,
                      'learning_rate': .0001,
                      'smoke_rows': rows[-20:], 'scaler': bundle['scaler']}
        new_bundle.pop('shadow_result', None)
        version = self._register(district_code, candidate, new_bundle)
        return {'status': 'awaiting_shadow', 'candidate_version': version, 'model_version': champion,
                'trained_through': rows[-1]['date'], 'required_shadow_targets': 30}

    def clone_from(self, other_manager, district_code, metadata=None):
        """Register an independently addressable copy of a validated initial model.

        Only the original initial champion is eligible: a replay-adapted model
        could have consumed observations after the destination replay clock.
        """
        if other_manager.namespace == self.namespace:
            raise ValueError('cloning requires a distinct isolated namespace')
        model, source, source_version = other_manager._loaded(district_code)
        if source.get('kind') != 'initial':
            raise ValueError('only an initial champion may seed an isolated replay')
        validation = source.get('metrics', {}).get('validation', {}).get('rmse')
        persistence = source.get('metrics', {}).get('validation_persistence', {}).get('rmse')
        if validation is None or persistence is None or not all(math.isfinite(v) for v in (validation, persistence)):
            raise ValueError('source initial gate evidence is missing')
        if validation > persistence * 1.10 + 1e-12:
            raise ValueError('source initial quality gate was not passed')
        if metadata is not None:
            if metadata.get('manifest_approved') is not True:
                raise ValueError('representative station manifest approval required')
            for field in ('station_id', 'district_code', 'level_unit', 'dataset_version', 'mapping_version'):
                if field in metadata and metadata[field] != source.get(field):
                    raise ValueError(f'{field}: clone source/input mismatch')
        bundle = json.loads(json.dumps(source))
        bundle.update(namespace=self.namespace, cloned_from_namespace=other_manager.namespace,
                      cloned_from_version=source_version)
        version = self._register(district_code, model, bundle)
        result = self.promote(district_code, version)
        return {**result, 'version': version, 'splits': bundle['splits'],
                'threshold': bundle['threshold'], 'metrics': bundle['metrics'],
                'training_hash': bundle['training_hash'], 'gate_passed': True,
                'cloned_from_namespace': other_manager.namespace, 'cloned_from_version': source_version}

    def predict_candidate(self, district_code, version, records):
        rows = validate_rows(records, 20)
        model, bundle, version = self._loaded(district_code, str(version))
        self._identity(district_code, rows, bundle)
        return {'prediction': self._predict(model, bundle, rows), 'model_version': version}

    def evaluate_candidate(self, district_code, candidate_version, records, namespace=None):
        self._check_namespace(namespace)
        rows = validate_rows(records)
        candidate, bundle, version = self._loaded(district_code, str(candidate_version))
        if bundle.get('kind') != 'fine_tune':
            raise ModelNotReady('shadow evaluation requires a fine-tuned candidate')
        with self._lock(district_code):
            previous = self._state(district_code)['versions'][version].get('shadow_result', {})
            if previous.get('status') in ('promoted', 'rejected'):
                return previous
        self._identity(district_code, rows, bundle)
        eligible = [i for i in range(20, len(rows)) if rows[i]['date'] > bundle['shadow_after']]
        if len(eligible) < 30:
            return {'status': 'pending', 'count': len(eligible), 'required': 30}
        champion, old_bundle, current = self._loaded(district_code)
        if current != bundle['parent_version']:
            return self.reject_candidate(district_code, version, 'champion_changed')
        selected = eligible[:30]
        actual = [rows[i]['groundwater_level'] for i in selected]
        candidate_values = [self._predict(candidate, bundle, rows[i-20:i]) for i in selected]
        champion_values = [self._predict(champion, old_bundle, rows[i-20:i]) for i in selected]
        candidate_score, champion_score = metrics(actual, candidate_values), metrics(actual, champion_values)
        guard = bundle['guard_rows']
        guard_actual = [r['groundwater_level'] for r in guard[20:]]
        guard_score = metrics(guard_actual, [self._predict(candidate, bundle, guard[i-20:i]) for i in range(20, len(guard))])
        passed = (champion_score['rmse'] > 0 and candidate_score['rmse'] <= champion_score['rmse'] * .95) and guard_score['rmse'] <= old_bundle['metrics']['validation']['rmse'] * 1.10 + 1e-12
        result = {'status': 'gate_passed' if passed else 'rejected', 'candidate_version': version, 'gate_passed': passed,
                  'gates': {'future_improvement': {
                      'passed': (champion_score['rmse'] > 0 and candidate_score['rmse'] <= champion_score['rmse'] * .95),
                      'rmse': candidate_score['rmse'], 'limit': champion_score['rmse'] * .95},
                      'historical_guard': {
                          'passed': guard_score['rmse'] <= old_bundle['metrics']['validation']['rmse'] * 1.10 + 1e-12,
                          'rmse': guard_score['rmse'],
                          'limit': old_bundle['metrics']['validation']['rmse'] * 1.10 + 1e-12}},
                  'metrics': {'shadow_candidate': candidate_score, 'shadow_champion': champion_score, 'historical_guard': guard_score},
                  'shadow_start': rows[selected[0]]['date'], 'shadow_end': rows[selected[-1]]['date']}
        if passed:
            result['previous_version'] = current
        with self._lock(district_code):
            # Evaluation runs outside the lock; another valid promotion may win.
            state = self._state(district_code)
            previous = state['versions'][version].get('shadow_result', {})
            if previous.get('status') in ('promoted', 'rejected'):
                return previous
            if self.current_version(district_code) != current:
                return self.reject_candidate(district_code, version, 'champion_changed')
            state['versions'][version]['shadow_result'] = result
            self._save(district_code, state)
            if hasattr(self.backend,'record_evaluation'):
                self.backend.record_evaluation(self._name(district_code),version,result)
            if passed:
                try:
                    result.update(self.promote(district_code, version))
                except ModelNotReady:
                    if self.current_version(district_code) != current:
                        return self.reject_candidate(district_code, version, 'champion_changed')
                    raise
                if hasattr(self.backend,'record_evaluation'):
                    try:
                        self.backend.record_evaluation(self._name(district_code),version,result)
                    except Exception as exc:
                        result['tracking_warning'] = f'promotion completed; evaluation tracking failed: {exc}'
            state = self._state(district_code)
            state['versions'][version]['shadow_result'] = result
            self._save(district_code,state)
        return result

    def reject_candidate(self, district_code, version, reason):
        result={'status':'rejected','candidate_version':str(version),'reason':reason,'gate_passed':False}
        with self._lock(district_code):
            state=self._state(district_code)
            state['versions'][str(version)]['shadow_result']=result
            self._save(district_code,state)
        if hasattr(self.backend,'record_evaluation'):
            try:
                self.backend.record_evaluation(self._name(district_code),str(version),result)
            except Exception as exc:
                result['tracking_warning']=str(exc)
        return result

    def rollback(self, district_code, version=None):
        with self._lock(district_code):
            state = self._state(district_code)
            if version is None:
                version = next((h['from'] for h in reversed(state['history']) if h['from'] and h['from'] != state['champion']), None)
            validated = {str(h['to']) for h in state['history']}
            if version is None or str(version) not in validated:
                raise ModelNotReady('no previous registered version to restore')
            result = self._activate(district_code, str(version), self.current_version(district_code))
            result['status'] = 'rolled_back'
            return result

    def list_models(self):
        result = []
        for path in sorted(self.root.glob('*.json')):
            state = json.loads(path.read_text())
            code = state['district_code']
            champion = self.backend.alias(self._name(code))
            bundle = state['versions'].get(str(champion), {})
            public_bundle = {k: v for k, v in bundle.items() if k not in ('guard_rows', 'smoke_rows')}
            result.append({**public_bundle, 'district_code': code, 'champion_version': champion,
                           'model_version': champion, 'namespace': self.namespace,
                           'status': 'ready' if champion else 'not_ready',
                           'versions': {v: {k: item for k, item in b.items() if k not in ('guard_rows', 'smoke_rows')}
                                        for v, b in state['versions'].items()}, 'history': state['history']})
        return result
