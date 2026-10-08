"""Train on real provider water labels; missing rainfall is an explicit input feature.

Provider-native values are never merged with gl.-m or demonstration models.
Forecast dates follow the available observation, not the collection clock.
"""
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import statistics

from backend.groundwater_models import ModelManager, ModelNotReady, Scaler, metrics, _json
from backend.groundwater_store import now

NAMESPACE = 'api_native_masked_v1'
CONTRACT = 'VTsSec-native-ASOS108-train-median-missing-mask-v1'


def input_hash(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, allow_nan=False).encode()).hexdigest()


def water_windows(rows):
    """Only real, consecutive 21-day water observations can supply a training label."""
    rows = sorted(rows, key=lambda row: row['date'])
    if len({row['date'] for row in rows}) != len(rows):
        raise ValueError('duplicate water date')
    for row in rows:
        if not math.isfinite(row['groundwater_level']):
            raise ValueError('invalid water label')
        rain = row['rainfall_mm']
        if rain is not None and (not math.isfinite(rain) or rain < 0):
            raise ValueError('invalid rain input')
    return [rows[i-20:i+1] for i in range(20, len(rows))
            if all(date.fromisoformat(b['date'])-date.fromisoformat(a['date']) == timedelta(days=1)
                   for a,b in zip(rows[i-20:i], rows[i-19:i+1]))]


def prepare(rows, median):
    return [{**row, 'rainfall_mm':median if row['rainfall_mm'] is None else row['rainfall_mm'],
             'rain_missing':int(row['rainfall_mm'] is None)} for row in rows]


def features(rows, scaler):
    return [scaler.transform(row) + [row['rain_missing']] for row in rows]


class ApiModelManager(ModelManager):
    def __init__(self, root, backend=None):
        super().__init__(Path(root)/'models', namespace=NAMESPACE, backend=backend)

    def _predict(self, model, bundle, rows):
        scaler = Scaler(bundle['scaler']['minimum'], bundle['scaler']['maximum'])
        result = scaler.inverse(self.backend.predict(model, [features(rows, scaler)])[0])
        if not math.isfinite(result):
            raise ValueError('nonfinite prediction')
        return result

    def train_actual(self, code, station_id, rows, max_epochs=100):
        windows = water_windows(rows)
        if len(windows) < 50:
            raise ValueError('at least 50 real target windows (70 water days) required')
        test_count = max(10, len(windows)//5)
        validation_count = test_count
        partitions = {'train':windows[:-2*test_count],
                      'validation':windows[-2*test_count:-test_count], 'test':windows[-test_count:]}
        train_end = partitions['train'][-1][-1]['date']
        fit_rows = {r['date']:r for window in partitions['train'] for r in window}
        numeric_rain = [r['rainfall_mm'] for r in fit_rows.values() if r['rainfall_mm'] is not None]
        if len(numeric_rain) < 5:
            raise ValueError('at least 5 observed rainfall values in training context required')
        median = float(statistics.median(numeric_rain))
        scaler = Scaler.fit(prepare(list(fit_rows.values()), median))
        def arrays(partition):
            return ([features(prepare(window[:-1], median), scaler) for window in partition],
                    [scaler.transform(prepare([window[-1]], median)[0])[0] for window in partition])
        model = self.backend.train(*arrays(partitions['train']), arrays(partitions['validation']),
                                   max_epochs=max_epochs, learning_rate=0.0001, architecture='residual_lstm_masked')
        measured, backtest = {}, []
        for name in ('validation', 'test'):
            partition = partitions[name]
            x, _ = arrays(partition)
            predicted = [scaler.inverse(value) for value in self.backend.predict(model, x)]
            actual = [window[-1]['groundwater_level'] for window in partition]
            measured[name] = metrics(actual, predicted)
            measured[name+'_persistence'] = metrics(actual, [window[-2]['groundwater_level'] for window in partition])
            if name == 'test':
                backtest = [{'date':window[-1]['date'], 'prediction':prediction,
                             'kind':'held_out_test', 'trained_through':train_end}
                            for window,prediction in zip(partition,predicted)]
        splits = {name:{'start':part[0][-1]['date'], 'end':part[-1][-1]['date'], 'count':len(part)}
                  for name,part in partitions.items()}
        digest = input_hash(rows)
        self.save_observations(code, rows)
        bundle = {'district_code':code, 'station_id':station_id, 'namespace':NAMESPACE,
                  'kind':'initial', 'level_unit':'API 원값', 'mapping_version':CONTRACT,
                  'dataset_version':digest, 'feature_contract_id':CONTRACT,
                  'training_snapshot_id':digest, 'model_architecture':'residual_lstm_masked',
                  'preprocessing_version':CONTRACT, 'rain_source':'kma_asos_sumRn', 'weather_station_id':'108',
                  'feature_order':['groundwater_level','rainfall_train_median','rain_missing'],
                  'rain_fill_value':median, 'rain_fill_fit_end':train_end,
                  'scaler':scaler.dump(), 'metrics':measured, 'splits':splits,
                  'trained_through':train_end, 'threshold':max(1e-6, measured['validation']['rmse']*1.5),
                  'window':20, 'seed':42, 'smoke_rows':prepare(partitions['train'][-1][:-1], median)}
        version = self._register(code, model, bundle)
        passed = measured['validation']['rmse'] <= measured['validation_persistence']['rmse']*1.10 + 1e-12
        if passed:
            self.promote(code, version)
        return {'status':'promoted' if passed else 'rejected', 'model_version':version,
                'gate_passed':passed, 'metrics':measured, 'splits':splits, 'backtest':backtest,
                'trained_through':train_end, 'rain_fill_value':median}

    def save_observations(self, code, rows):
        digest = input_hash(rows)
        path = self.root.parents[1]/'external'/'feed'/'station-snapshots'/f'{code}-{digest}.json'
        if path.exists():
            if input_hash(json.loads(path.read_text())['rows']) != digest:
                raise ValueError('immutable station snapshot changed')
        else:
            _json(path, {'district_code':code,'rows':rows})
        return digest

    def observations(self, code, digest):
        if not str(code).isdigit() or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid station snapshot identity')
        folder = self.root.parents[1]/'external'/'feed'
        path = folder/'station-snapshots'/f'{code}-{digest}.json'
        if path.exists():
            rows = json.loads(path.read_text())['rows']
            if input_hash(rows) != digest:
                raise ValueError('station snapshot hash mismatch')
            return rows
        # Recover initial models created before the per-station snapshot catalog.
        for path in (folder/'snapshots').glob('*.json'):
            rows = json.loads(path.read_text()).get('stations',{}).get(code,[])
            if rows and input_hash(rows)==digest:
                self.save_observations(code,rows)
                return rows
        raise ValueError('original training observations unavailable')

    def predict_windows(self, code, version, windows):
        model,bundle,_ = self._loaded(code,str(version))
        if bundle.get('feature_contract_id') != CONTRACT:
            raise ValueError('native model contract mismatch')
        scaler=Scaler(bundle['scaler']['minimum'],bundle['scaler']['maximum'])
        x=[features(prepare(w[:-1],bundle['rain_fill_value']),scaler) for w in windows]
        values=[scaler.inverse(v) for v in self.backend.predict(model,x)]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('nonfinite candidate prediction')
        return values

    def create_candidate(self, code, rows, trigger_id, max_epochs=30):
        state=self._state(code)
        for version,bundle in state['versions'].items():
            if bundle.get('trigger_id')==trigger_id:
                return {'candidate_version':version,'candidate_as_of':bundle['trained_through']}
        initial,parent,parent_version=self._loaded(code)
        recent=rows[-41:];windows=water_windows(recent)
        if len(recent)!=41 or len(windows)!=21:
            raise ValueError('41 consecutive real water days required for retraining')
        original=self.observations(code,parent['training_snapshot_id'])
        guard=parent.get('guard_windows') or [w for w in water_windows(original)
            if parent['splits']['validation']['start'] <= w[-1]['date'] <= parent['splits']['validation']['end']]
        guard=[w for w in guard if w[-1]['date'] < windows[0][-1]['date']]
        if len(guard)<10:
            raise ValueError('at least10 untouched historical guard targets required')
        scaler=Scaler(parent['scaler']['minimum'],parent['scaler']['maximum'])
        x=[features(prepare(w[:-1],parent['rain_fill_value']),scaler) for w in windows]
        y=[scaler.transform(prepare([w[-1]],parent['rain_fill_value'])[0])[0] for w in windows]
        model=self.backend.train(x,y,None,initial=initial,max_epochs=max_epochs,
                                 learning_rate=0.0001,architecture='residual_lstm_masked')
        digest=self.save_observations(code,rows)
        bundle={**parent,'kind':'fine_tune','parent_version':parent_version,'trigger_id':trigger_id,
                'training_snapshot_id':digest,'dataset_version':digest,'trained_through':recent[-1]['date'],
                'candidate_training_start':windows[0][-1]['date'],'guard_windows':guard,
                'shadow_after':recent[-1]['date'],
                'metrics':{},'smoke_rows':prepare(recent[-20:],parent['rain_fill_value'])}
        version=self._register(code,model,bundle)
        return {'candidate_version':version,'candidate_as_of':recent[-1]['date']}

    def evaluate_actual_candidate(self, code, version, rows):
        _,bundle,_=self._loaded(code,str(version))
        prior=self._state(code)['versions'][str(version)].get('shadow_result')
        if prior and prior.get('status') in ('promoted','rejected'):
            return prior
        if self.current_version(code)==str(version) and prior and prior.get('gate_passed'):
            result={**prior,'status':'promoted','model_version':str(version),'recovered':True}
            state=self._state(code);state['versions'][str(version)]['shadow_result']=result;self._save(code,state)
            return result
        if self.current_version(code)!=bundle['parent_version']:
            return self.reject_candidate(code,version,'champion_changed')
        cutoff=date.fromisoformat(bundle['trained_through'])
        windows={w[-1]['date']:w for w in water_windows(rows) if w[-1]['date']>cutoff.isoformat()}
        required=[(cutoff+timedelta(days=i)).isoformat() for i in range(1,31)]
        selected=[windows[d] for d in required if d in windows]
        if len(selected)<30:
            return {'status':'pending','count':len(selected),'required':30,
                    'reason':'candidate 학습 이후 연속30일 실제 정답 필요'}
        actual=[w[-1]['groundwater_level'] for w in selected]
        candidate_score=metrics(actual,self.predict_windows(code,version,selected))
        champion_score=metrics(actual,self.predict_windows(code,bundle['parent_version'],selected))
        guard=bundle['guard_windows'];guard_actual=[w[-1]['groundwater_level'] for w in guard]
        guard_score=metrics(guard_actual,self.predict_windows(code,version,guard))
        guard_champion=metrics(guard_actual,self.predict_windows(code,bundle['parent_version'],guard))
        improvement=candidate_score['rmse'] <= champion_score['rmse']*.95
        retention=guard_score['rmse'] <= guard_champion['rmse']*1.10+1e-12
        result={'status':'rejected','candidate_version':str(version),'gate_passed':improvement and retention,
                'gates':{'future_improvement':{'passed':improvement,'rmse':candidate_score['rmse'],'limit':champion_score['rmse']*.95},
                         'historical_guard':{'passed':retention,'rmse':guard_score['rmse'],'limit':guard_champion['rmse']*1.10}},
                'metrics':{'shadow_candidate':candidate_score,'shadow_champion':champion_score,
                           'historical_guard':guard_score,'guard_champion':guard_champion},
                'shadow_start':required[0],'shadow_end':required[-1],
                'previous_version':bundle['parent_version'],
                'evaluation_snapshot_id':self.save_observations(code,rows)}
        # Persist the gate result before alias mutation so a recovered promotion is identifiable.
        state=self._state(code);state['versions'][str(version)]['shadow_result']=dict(result,status='gate_passed' if result['gate_passed'] else 'rejected');self._save(code,state)
        if result['gate_passed']:
            result.update(self.promote(code,version))
        state=self._state(code);state['versions'][str(version)]['shadow_result']=result;self._save(code,state)
        return result

    def _validate_shadow_gate(self, bundle, version, evaluation):
        """Recompute native-contract gates from immutable observations before activation."""
        try:
            if (bundle.get('namespace') != NAMESPACE or bundle.get('feature_contract_id') != CONTRACT
                    or evaluation.get('status') not in ('gate_passed','promoted')
                    or evaluation.get('gate_passed') is not True
                    or evaluation.get('candidate_version') != str(version)
                    or evaluation.get('previous_version') != bundle['parent_version']):
                raise ValueError('candidate identity mismatch')
            code=bundle['district_code']
            rows=self.observations(code,evaluation['evaluation_snapshot_id'])
            cutoff=date.fromisoformat(bundle['trained_through'])
            required=[(cutoff+timedelta(days=i)).isoformat() for i in range(1,31)]
            if evaluation['shadow_start']!=required[0] or evaluation['shadow_end']!=required[-1]:
                raise ValueError('shadow calendar mismatch')
            windows={w[-1]['date']:w for w in water_windows(rows)}
            selected=[windows[d] for d in required]
            guard=bundle['guard_windows']
            if len(guard)<10 or any(w[-1]['date']>=bundle['candidate_training_start'] for w in guard):
                raise ValueError('guard overlaps candidate training')
            actual=[w[-1]['groundwater_level'] for w in selected]
            guard_actual=[w[-1]['groundwater_level'] for w in guard]
            measured={
                'shadow_candidate':metrics(actual,self.predict_windows(code,version,selected)),
                'shadow_champion':metrics(actual,self.predict_windows(code,bundle['parent_version'],selected)),
                'historical_guard':metrics(guard_actual,self.predict_windows(code,version,guard)),
                'guard_champion':metrics(guard_actual,self.predict_windows(code,bundle['parent_version'],guard))}
            for name,score in measured.items():
                saved=evaluation['metrics'][name]
                if (saved.get('count')!=score['count'] or not self._valid_rmse(saved.get('rmse'))
                        or not math.isclose(saved['rmse'],score['rmse'],rel_tol=1e-9,abs_tol=1e-12)):
                    raise ValueError('stored metric mismatch')
            if (measured['shadow_candidate']['rmse']>measured['shadow_champion']['rmse']*.95
                    or measured['historical_guard']['rmse']>measured['guard_champion']['rmse']*1.10+1e-12):
                raise ValueError('native quality gate failed')
        except (KeyError,TypeError,ValueError,IndexError) as exc:
            raise ModelNotReady('native shadow quality gate was not passed') from exc

    def forecast_actual(self, code, station_id, rows):
        model,bundle,version = self._loaded(code)
        if bundle['feature_contract_id'] != CONTRACT or bundle['station_id'] != station_id:
            raise ValueError('API model contract mismatch')
        tail = rows[-20:]
        if len(tail) != 20 or any(date.fromisoformat(b['date'])-date.fromisoformat(a['date']) != timedelta(days=1)
                                 for a,b in zip(tail,tail[1:])):
            raise ValueError('20 consecutive real water observations required')
        value = self._predict(model,bundle,prepare(tail,bundle['rain_fill_value']))
        saved=self._state(code)['versions'][version]
        return {'prediction':value, 'model_version':version,
                'forecast_date':(date.fromisoformat(tail[-1]['date'])+timedelta(days=1)).isoformat(),
                'input_end_date':tail[-1]['date'], 'issued_at':now(), 'unit':'API 원값',
                'trained_through':bundle['trained_through'], 'splits':bundle['splits'],
                'metrics':saved.get('shadow_result',{}).get('metrics',bundle['metrics']), 'rain_fill_value':bundle['rain_fill_value'],
                'imputed_rain_days':sum(row['rainfall_mm'] is None for row in tail),
                'training_snapshot_id':bundle['training_snapshot_id'], 'inference_snapshot_id':input_hash(rows),
                'feature_contract_id':CONTRACT, 'namespace':NAMESPACE,
                'backtest':saved.get('backtest', []), 'threshold':bundle['threshold'],
                'forecast_timing':'latest_available_next_day'}


class ApiFeedTraining:
    def __init__(self, root, manager=None):
        self.root = Path(root)
        self.folder = self.root/'external'/'feed'
        self.manager = manager

    def read(self):
        path = self.folder/'models.json'
        return json.loads(path.read_text()) if path.exists() else {'stations':{}}

    def enqueue_if_due(self, service, feed, retry_failed=False):
        state = feed.read()
        if not state.get('water'):
            return None
        rows = {s['district_code']:feed.history(s['district_code'],state)['history'] for s in feed.stations}
        digest = input_hash(rows)
        old = self.read()
        if old.get('feed_hash') == digest and old.get('status') == 'completed' and not retry_failed:
            return None
        if any(j['kind']=='train_api_feed' and j['status'] in ('queued','running')
               for j in service.store.jobs(NAMESPACE)):
            return None
        path = self.folder/'snapshots'/f'{digest}.json'
        if not path.exists():
            _json(path, {'feed_hash':digest,'stations':rows,'collected_at':state.get('water_collected_at')})
        return service.store.enqueue('train_api_feed',{'namespace':NAMESPACE, 'feed_hash':digest}, 'api-feed-models')

    def execute(self, digest, stations):
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid snapshot hash')
        snapshot = json.loads((self.folder/'snapshots'/f'{digest}.json').read_text())
        if input_hash(snapshot['stations']) != digest:
            raise ValueError('API snapshot changed')
        manager = self.manager or ApiModelManager(self.root)
        from backend.groundwater_service import GroundwaterService
        from backend.api_feed_ops import ApiFeedOperations
        operations=ApiFeedOperations(GroundwaterService(self.root),manager)
        result = {'feed_hash':digest,'started_at':now(), 'status':'running', 'stations':{}}
        _json(self.folder/'models.json',result)
        for station in stations:
            code = station['district_code']; rows = snapshot['stations'][code]
            item = {'input_hash':input_hash(rows),'status':'running'}
            result['stations'][code] = item
            _json(self.folder/'models.json',result)
            try:
                training = None
                if manager.current_version(code) is None:
                    training = manager.train_actual(code,station['station_id'],rows)
                    item.update(training)
                if manager.current_version(code) is not None:
                    item.update(manager.forecast_actual(code,station['station_id'],rows),status='ready')
                    operations.record_forecast(code,item,rows)
                    if training:
                        item['backtest'] = training['backtest']
                        # Persist evaluation predictions alongside the same registered model metadata.
                        saved = manager._state(code)
                        saved['versions'][item['model_version']]['backtest'] = training['backtest']
                        manager._save(code,saved)
                else:
                    item['reason'] = '검증 구간 품질 게이트 미통과; 예측 미발행'
            except (ValueError,RuntimeError,FileNotFoundError,KeyError) as error:
                item.update(status='blocked',reason=str(error))
            _json(self.folder/'models.json',result)
        result.update(status='completed',completed_at=now(),
                      ready_count=sum(s['status']=='ready' for s in result['stations'].values()))
        _json(self.folder/'models.json',result)
        return result
