"""Isolated nationwide jobs; never substitute synthetic Seoul data for observations."""
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import os

from serving_app.groundwater_store import Store, now
from serving_app.national_repository import NationalRepository
from serving_app.national_models import NationalModelManager
from serving_app.national_monitor import evaluate_monitor, reference_threshold


def kst_today():
    return datetime.now(ZoneInfo('Asia/Seoul')).date()


class NationalService:
    def __init__(self, root, manager=None):
        self.root = Path(root) / 'national'
        self.repo = NationalRepository(self.root / 'observations.sqlite3')
        self.store = Store(self.root / 'jobs.sqlite3')
        self.manager = manager or NationalModelManager(self.root / 'models')
        self.synthetic_manager = None

    def manager_for(self, station_id):
        if self.station(station_id).get('source_kind') != 'synthetic':
            return self.manager
        if self.synthetic_manager is None:
            self.synthetic_manager = NationalModelManager(self.root / 'models',
                namespace='national_synthetic_v1', source_kind='synthetic')
        return self.synthetic_manager

    def station(self, station_id):
        item = self.repo.station(station_id)
        if item is None:
            raise KeyError('관측소를 찾을 수 없습니다.')
        return item

    @staticmethod
    def contiguous_segment(rows, station, end=None):
        """Latest valid block, with gaps/invalid rows never joined or filled."""
        segment = []
        for row in rows:
            if end is not None and row['date'] > end:
                continue
            valid = (row.get('quality_status', 'valid') == 'valid' and
                     row.get('source_kind', 'observed') in (('synthetic',) if station.get('source_kind') == 'synthetic' else ('observed', 'observed_api')) and
                     all(row.get(k) == station[k] for k in ('level_unit', 'level_reference')))
            if not valid:
                segment = []
                continue
            if segment and date.fromisoformat(row['date'])-date.fromisoformat(segment[-1]['date']) != timedelta(days=1):
                segment = []
            segment.append(row)
        return segment

    def _require_observed(self, station):
        if (station.get('source_kind') == 'synthetic' and station.get('mapping_status') == 'synthetic'
                and station.get('source_contract_verified') is True and station.get('operational_approved') is False
                and station.get('mapping_version') and station.get('evidence')
                and station.get('level_unit') and station.get('level_reference')):
            return
        experimental = (station.get('source_contract_verified') is True and
                        station.get('mapping_status') == 'experimental' and
                        station.get('operational_approved') is False and
                        bool(station.get('mapping_version')) and bool(station.get('evidence')))
        if (not station.get('verified') and not experimental) or station.get('source_kind') != 'observed':
            raise ValueError('verified observed station required')
        if not station.get('level_unit') or not station.get('level_reference'):
            raise ValueError('verified unit and reference required')

    def enqueue(self, kind, station_id, **payload):
        self.station(station_id)
        if kind not in ('train', 'predict', 'fine_tune', 'evaluate', 'promote', 'rollback'):
            raise ValueError('지원하지 않는 전국 작업입니다.')
        return self.store.enqueue(kind, {'station_id': station_id, **payload}, f'national:{station_id}')

    def forecasts(self, station_id):
        self.station(station_id)
        return [p for p in self.store.list('prediction') if p['station_id'] == station_id]

    def seasonal_labels(self, station_id, rows):
        region = self.station(station_id).get('rainy_region')
        if not region:
            return {}
        periods = self.repo.rainy_periods(region_code=region)
        years = {}
        for period in periods:
            years.setdefault(period['year'], []).append(period)
        labels = {}
        for row in rows:
            matches = years.get(date.fromisoformat(row['date']).year, [])
            if len(matches) == 1:
                p = matches[0]
                labels[row['date']] = ['rainy' if p['start_date'] <= row['date'] <= p['end_date'] else 'non_rainy']
        return labels

    @staticmethod
    def _prediction_scope(station):
        return 'synthetic' if station.get('source_kind') == 'synthetic' else 'experimental' if station.get('operational_approved') is False else 'operational'

    @staticmethod
    def _experimental_monitoring_enabled():
        return os.getenv('GROUNDWATCH_EXPERIMENTAL_MONITORING_ENABLED','false').lower() in ('true','1','yes')

    def issuance_proofs(self, station_id, version, rows):
        scope = self._prediction_scope(self.station(station_id))
        actual = {r['date']: r for r in rows}
        proofs = []
        for p in self.store.list('paired_prediction'):
            if (p['station_id'] == station_id and p['candidate_version'] == version and p['target_date'] in actual
                    and p.get('prediction_scope', 'operational') == scope):
                label = actual[p['target_date']]
                proofs.append({**p, 'actual_available_at': self.repo.first_observation_availability(station_id,p['target_date']) or label['available_at'],
                               'actual_revision_id': label['revision_id']})
        by_date = {}
        for proof in sorted(proofs, key=lambda x: (x['target_date'], x['issued_at'])):
            by_date.setdefault(proof['target_date'], proof)
        return [by_date[d] for d in sorted(by_date)][:30]

    def pending_candidates(self, station_id):
        models = self.manager_for(station_id).list_models(station_id)
        active = next((m for m in models if m.get('active')), None)
        return [m for m in models if m.get('status') == 'awaiting_shadow' and m.get('evaluation_status') not in ('experimental_gate_passed','synthetic_gate_passed','gate_passed','rejected','expired_insufficient_seasonal_evidence','expired_shadow_timeout') and not m.get('active') and
                active and m.get('comparison_version') == active['version']]

    def _reference(self, station_id, version):
        bundle = self.manager_for(station_id)._bundle(station_id, version)
        version = bundle.get('initial_reference_version', version)
        key = hashlib.sha256(json.dumps([station_id, version]).encode()).hexdigest()
        try:
            return self.store.get('national_reference', key)['threshold']
        except KeyError:
            bundle = self.manager_for(station_id)._bundle(station_id, version)
            guard = bundle['guard_rows']
            predicted = self.manager_for(station_id)._predictions(station_id, version, guard, list(range(20, len(guard))))
            threshold = reference_threshold([r['groundwater_level'] for r in guard[20:]], predicted)
            self.store.put('national_reference', {'station_id': station_id, 'model_version': version,
                'threshold': threshold, 'policy': 'frozen_holdout_rolling21_p95_times1.5',
                'reference_hash': hashlib.sha256(json.dumps(guard,sort_keys=True).encode()).hexdigest()}, key)
            return threshold

    def monitor_station(self, station_id, cutoff=None):
        station = self.station(station_id)
        self._require_observed(station)
        scope = self._prediction_scope(station)
        if scope == 'experimental' and not self._experimental_monitoring_enabled():
            return {'status':'experimental_monitoring_disabled','prediction_scope':scope}
        cutoff = cutoff or now()
        models = self.manager_for(station_id).list_models(station_id)
        active = next((m for m in models if m.get('active')), None)
        if active is None:
            return {'status': 'model_not_ready'}
        version = active['version']
        completed_day = datetime.fromisoformat(cutoff).astimezone(ZoneInfo('Asia/Seoul')).date()-timedelta(days=1)
        rows = self.repo.observations(station_id, end=completed_day.isoformat(), cutoff=cutoff)
        actuals = {r['date']:r for r in rows}
        predictions = [p for p in self.forecasts(station_id) if (p.get('mode') == 'live' or (scope == 'experimental' and p.get('mode') == 'experimental' and p.get('forecast_timing') == 'same_day_estimate'))
            and p.get('prediction_scope','operational') == scope and p.get('model_version') == version]
        by_date = {}
        for prediction in sorted(predictions, key=lambda p:p['issued_at']):
            target = prediction['target_date']
            label = actuals.get(target)
            if not label or label.get('quality_status') != 'valid':
                continue
            if datetime.fromisoformat(prediction['issued_at']) >= datetime.fromisoformat(self.repo.first_observation_availability(station_id,target,cutoff) or label['available_at']):
                continue
            if any(label[k] != station[k] for k in ('level_unit','level_reference')):
                continue
            # Freeze the first verified label revision used for monitoring.
            label_key = hashlib.sha256(json.dumps([station_id,version,target]).encode()).hexdigest()
            try:
                archived = self.store.get('national_label', label_key)
            except KeyError:
                archived = self.store.put('national_label', {'station_id':station_id, 'model_version':version,
                    'target_date':target, 'prediction':prediction['prediction'],
                    'actual':label['groundwater_level'], 'actual_revision_id':label['revision_id'],
                    'actual_available_at':label['available_at'], 'prediction_id':prediction['id'],
                    'namespace':self.manager_for(station_id).namespace, 'source_kind':station['source_kind'],'prediction_scope':scope}, label_key)
            by_date.setdefault(target, archived)
        pairs = [by_date[d] for d in sorted(by_date)]
        if not pairs:
            return {'status':'no_labelled_prediction'}
        threshold = self._reference(station_id, version)
        state_id = f'national:{station_id}'
        try:
            state = self.store.get('monitor', state_id)
        except KeyError:
            state = {}
        latest = None
        for pair in pairs:
            if state.get('version') == version and pair['target_date'] <= state.get('last_processed_target_date',''):
                continue
            training = self.contiguous_segment(rows, station, pair['target_date'])
            latest = evaluate_monitor(pairs, threshold, state, bool(self.pending_candidates(station_id)),
                                      training, pair['target_date'], namespace=self.manager_for(station_id).namespace,
                                      source_kind=station.get('source_kind','observed'))
            state = latest['state']
            state['feature_contract_id'] = active['feature_contract_id']
            state['last_reason'] = latest['reason']
            job = ('fine_tune', {'station_id':station_id, 'input_end_date':pair['target_date']}, f'national:{station_id}') if latest['trigger'] else None
            self.store.commit_monitor(state_id, state, job=job)
            # Read the actually committed cooldown after a scope collision.
            state = self.store.get('monitor', state_id)
            if latest['trigger'] and state.get('last_trigger') != pair['target_date']:
                latest.update(trigger=False, reason='job_scope_busy')
            latest['state'] = state
        return latest or {'status':'already_processed', 'state':state}

    def schedule_once(self, timestamp=None):
        """Opt-in worker calls this; never collect guessed sources or auto-train."""
        instant = datetime.fromisoformat(timestamp or now()).astimezone(ZoneInfo('Asia/Seoul'))
        if (instant.hour, instant.minute) < (11, 30):
            return []
        scheduled = []
        cursor = None
        while True:
            page = self.repo.list_stations(verified=None if self._experimental_monitoring_enabled() else True,cursor=cursor,limit=200)
            for station in page['items']:
                experimental = (station.get('source_contract_verified') is True and station.get('mapping_status') == 'experimental' and station.get('operational_approved') is False)
                if station.get('source_kind') != 'observed' or not (station.get('verified') or experimental and self._experimental_monitoring_enabled()):
                    continue
                station_id = station['station_id']
                try:
                    self.monitor_station(station_id, instant.isoformat())
                    active = next((m for m in self.manager_for(station_id).list_models(station_id) if m.get('active')), None)
                    if active is None:
                        continue
                    manager = self.manager_for(station_id)
                    for candidate in self.pending_candidates(station_id):
                        guard = manager._bundle(station_id, candidate['version'])['guard_rows']
                        manager.expire_candidate(station_id, candidate['version'],instant.date().isoformat(),
                            max_wait_days=90, seasonal_labels=self.seasonal_labels(station_id, guard))
                    candidates = self.pending_candidates(station_id)
                    actions = []
                    for candidate in candidates:
                        elapsed = (instant.date()-date.fromisoformat(candidate['shadow_after'])).days
                        if elapsed >= 31:
                            actions.append(('evaluate', {'version':candidate['version'], 'automatic':True}))
                    if self.repo.readiness(station_id, cutoff=instant.isoformat())['data_ready']:
                        actions.append(('predict', {}))
                    for kind, payload in actions:
                        identity = hashlib.sha256(json.dumps([station_id,kind,payload,instant.date().isoformat()],sort_keys=True).encode()).hexdigest()
                        try:
                            self.store.get('national_schedule', identity)
                            continue
                        except KeyError:
                            pass
                        job = self.enqueue(kind, station_id, **payload)
                        self.store.put('national_schedule', {'station_id':station_id,'job_id':job['id'],
                                       'date':instant.date().isoformat(),'kind':kind}, identity)
                        scheduled.append(job)
                        break  # Station scope serializes work; retry remaining action next tick.
                except Exception as exc:
                    # Readiness/model evidence is a block, never a guessed forecast.
                    self.store.put('national_scheduler', {'station_id':station_id,'at':instant.isoformat(),
                        'status':'blocked','error_type':type(exc).__name__,
                        'detail':'자료·단위·모델 준비 또는 실행 중인 작업을 확인하세요.'}, station_id)
                    continue
            cursor = page['next_cursor']
            if cursor is None:
                break
        return scheduled

    def execute_one(self):
        job = self.store.claim()
        if job is None:
            return False
        try:
            p = job['payload']
            station = self.station(p['station_id'])
            self._require_observed(station)
            cutoff = now()
            if job['kind'] == 'train':
                rows = self.repo.observations(p['station_id'], end=(kst_today()-timedelta(days=1)).isoformat(), cutoff=cutoff)
                rows = self.contiguous_segment(rows, station)
                options = {k: p[k] for k in ('validation_targets', 'holdout_targets', 'max_epochs') if k in p}
                result = self.manager_for(p['station_id']).train(p['station_id'], rows, metadata=station,
                                            variant=p.get('variant', 'M0'), **options)
            elif job['kind'] == 'predict':
                end = p.get('input_end_date') or (kst_today()-timedelta(days=1)).isoformat()
                snapshot = self.repo.snapshot(p['station_id'], end, cutoff)
                result = self.manager_for(p['station_id']).predict(p['station_id'], snapshot['rows'], metadata=station)
                result['prediction'] = result.get('predicted_level', result.get('prediction'))
                target = (date.fromisoformat(end)+timedelta(days=1)).isoformat()
                result = {**result, 'station_id': p['station_id'], 'target_date': target,
                          'input_end_date': end, 'issued_at': cutoff, 'horizon_days': 1,
                          'snapshot_id': snapshot.get('sha256', snapshot.get('id')),
                          'unit': station['level_unit'], 'level_reference': station['level_reference'],
                          'source_kind': station.get('source_kind', 'observed'),
                          'mode': 'simulation' if station.get('source_kind') == 'synthetic' else 'historical_replay' if target < kst_today().isoformat() else 'live',
                          'prediction_scope':self._prediction_scope(station),
                          'forecast_timing': 'historical_reconstruction' if target < kst_today().isoformat() else 'same_day_estimate'}
                key = hashlib.sha256(json.dumps([p['station_id'], target, result.get('model_version'),
                                                result['snapshot_id']], sort_keys=True).encode()).hexdigest()
                try:
                    result = self.store.get('prediction', key)
                    newly_issued = False
                except KeyError:
                    result = self.store.put('prediction', result, key)
                    newly_issued = True
                target_already_available = bool(self.repo.observations(p['station_id'],start=target,end=target,cutoff=cutoff))
                pairing_enabled = result.get('prediction_scope','operational') == 'operational' or self._experimental_monitoring_enabled()
                if result['mode'] == 'live' and newly_issued and pairing_enabled and not target_already_available:
                    for candidate in self.pending_candidates(p['station_id']):
                        if target <= candidate['shadow_after']:
                            continue
                        candidate_result = self.manager_for(p['station_id']).predict(p['station_id'], snapshot['rows'],
                                                                metadata=station, version=candidate['version'])
                        pair = {'station_id': p['station_id'], 'target_date': target,
                                'candidate_version': candidate['version'], 'champion_version': result['model_version'],
                                'candidate_prediction': candidate_result['predicted_level'],
                                'champion_prediction': result['prediction'], 'issued_at': cutoff,
                                'snapshot_id': result['snapshot_id'], 'input_end_date': end,
                                'forecast_timing': result['forecast_timing'],'prediction_scope':result['prediction_scope'],
                                'operational_promotion_evidence':result['prediction_scope']=='operational',
                                'namespace':self.manager_for(p['station_id']).namespace,'horizon_days':1,
                                'feature_contract_id':candidate_result['feature_contract_id'],
                                'mapping_version':station.get('mapping_version')}
                        pair_id = hashlib.sha256(json.dumps([p['station_id'], target, candidate['version'],
                                                            result['model_version']], sort_keys=True).encode()).hexdigest()
                        try:
                            self.store.get('paired_prediction', pair_id)
                        except KeyError:
                            self.store.put('paired_prediction', pair, pair_id)
            elif job['kind'] == 'fine_tune':
                if self.pending_candidates(p['station_id']):
                    raise ValueError('candidate_pending')
                end = p.get('input_end_date') or (kst_today()-timedelta(days=1)).isoformat()
                if date.fromisoformat(end) >= kst_today():
                    raise ValueError('fine_tuning_requires_completed_day')
                rows = self.repo.observations(p['station_id'], end=end, cutoff=cutoff)
                rows = self.contiguous_segment(rows, station, end)
                if not rows or rows[-1]['date'] != end:
                    raise ValueError('fine_tuning_data_stale')
                result = self.manager_for(p['station_id']).fine_tune(p['station_id'], rows[-41:], metadata=station)
            elif job['kind'] == 'evaluate':
                bundle = self.manager_for(p['station_id'])._bundle(p['station_id'], p['version'])
                after = date.fromisoformat(bundle['shadow_after'])
                rows = self.repo.observations(p['station_id'], start=(after-timedelta(days=19)).isoformat(),
                    end=min(after+timedelta(days=30),kst_today()-timedelta(days=1)).isoformat(), cutoff=cutoff)
                rows = self.contiguous_segment(rows, station)
                if rows and rows[0]['date'] != (after-timedelta(days=19)).isoformat():
                    raise ValueError('shadow_calendar_gap')
                guard = bundle['guard_rows']
                result = self.manager_for(p['station_id']).evaluate_candidate(p['station_id'], p['version'], rows,
                    seasonal_labels=self.seasonal_labels(p['station_id'], guard),
                    issued_predictions=self.issuance_proofs(p['station_id'], p['version'], rows))
                if p.get('automatic') and result['status'] == 'gate_passed' and station.get('operational_approved') is not False:
                    result['promotion'] = self.manager_for(p['station_id']).promote(p['station_id'],p['version'])
                if result['status'] in ('rejected', 'gate_passed', 'experimental_gate_passed', 'synthetic_gate_passed'):
                    try:
                        monitor = self.store.get('monitor', f'national:{p["station_id"]}')
                        monitor.update(last_trigger=(kst_today()-timedelta(days=1)).isoformat(),breaches=0)
                        self.store.put('monitor',monitor,f'national:{p["station_id"]}')
                    except KeyError:
                        pass
            elif job['kind'] == 'promote':
                result = self.manager_for(p['station_id']).promote(p['station_id'], p['version'])
            elif job['kind'] == 'rollback':
                result = self.manager_for(p['station_id']).rollback(p['station_id'], p['version'], p['reason'])
            else:
                raise ValueError('지원하지 않는 전국 작업입니다.')
            self.store.finish(job['id'], result=result)
        except Exception as exc:
            # Provider URLs, credentials and arbitrary backend error text stay private.
            self.store.finish(job['id'], error=f'{type(exc).__name__}: 전국 작업 실패. 자료·단위·모델 준비를 확인하세요.')
        return True

    def pipeline(self, station_id):
        station = self.station(station_id)
        try:
            monitor = self.store.get('monitor', f'national:{station_id}')
        except KeyError:
            monitor = {'status':'no_labelled_prediction'}
        return {'station': station, 'readiness': self.repo.readiness(station_id),
                'models': self.manager_for(station_id).list_models(station_id),
                'jobs': [j for j in self.store.jobs() if j['payload']['station_id'] == station_id],
                'predictions': self.forecasts(station_id),
                'monitor':monitor,
                'monitoring_policy':{'prediction_scope':self._prediction_scope(station),
                    'experimental_enabled':self._experimental_monitoring_enabled(),
                    'window_days':21,'consecutive_breaches':2,'cooldown_days':21,
                    'fine_tuning_days':41,'candidate_shadow_days':30,
                    'operational_promotion_allowed':station.get('operational_approved') is not False,
                    'candidate_timeout_days':90},
                'limitations': ['M2 예보 입력과 호우특보 자동 수집은 아직 활성화되지 않았습니다.',
                                '과거 자료 재현과 실제 발행 예측은 구분합니다.']}
