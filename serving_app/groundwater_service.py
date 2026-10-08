"""자료·구별 서빙·재생 시계·자동 대응을 연결합니다."""
import hashlib
import json
import math
import os
from dataclasses import asdict, is_dataclass, replace
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from serving_app.groundwater_store import Store, now


def today():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def iso(value):
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def row_dict(row):
    value = asdict(row) if is_dataclass(row) else dict(row)
    value['date'] = iso(value['date'])
    return value


class GroundwaterService:
    @staticmethod
    def simulation_clock(replay, as_of=None):
        """Map presentation dates without changing source observations or model time."""
        if not replay or not replay.get('presentation_start_date'):
            return {'enabled': False}
        source = date.fromisoformat(as_of or replay['as_of'])
        elapsed = (source - date.fromisoformat(replay['start_date'])).days
        presentation = date.fromisoformat(replay['presentation_start_date']) + timedelta(days=elapsed)
        return {'enabled': True, 'presentation_as_of': presentation.isoformat(),
                'presentation_forecast_date': (presentation + timedelta(days=1)).isoformat(),
                'source_as_of': source.isoformat(),
                'source_forecast_date': (source + timedelta(days=1)).isoformat(),
                'elapsed_days': elapsed}

    def __init__(self, root=None, manager_factory=None):
        self.root = Path(root or os.getenv('GROUNDWATCH_STATE_DIR', 'runtime/groundwatch')).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.root / 'metadata.sqlite3')
        self._manager_factory = manager_factory
        self._managers = {}
        self._datasets = {}
        self._rows = {}

    def manager(self, namespace='historical'):
        if namespace not in self._managers:
            if self._manager_factory:
                self._managers[namespace] = self._manager_factory(namespace)
            else:
                from serving_app.groundwater_models import ModelManager
                self._managers[namespace] = ModelManager(self.root / 'models', namespace=namespace)
        return self._managers[namespace]

    def dataset(self, dataset_id):
        entry = self.store.get('dataset', dataset_id)
        if entry['status'] != 'ready':
            raise ValueError('검증을 통과한 canonical 자료가 필요합니다.')
        if dataset_id not in self._datasets:
            from data.groundwater import load_canonical
            self._datasets[dataset_id] = load_canonical(entry['path'], entry['manifest_path'])
        return self._datasets[dataset_id]

    def latest_dataset(self):
        return next((x for x in self.store.list('dataset') if x['status'] == 'ready'), None)

    def default_namespace(self):
        entry = self.latest_dataset()
        return entry.get('namespace', 'historical') if entry else 'historical'

    def queue_upload(self, csv_bytes, manifest_bytes, filename='dataset.csv', auto_train=False):
        digest = hashlib.sha256(csv_bytes + manifest_bytes).hexdigest()
        folder = self.root / 'datasets' / digest
        folder.mkdir(parents=True, exist_ok=True)
        path, manifest = folder / 'observations.csv', folder / 'manifest.json'
        path.write_bytes(csv_bytes)
        manifest.write_bytes(manifest_bytes)
        provenance = json.loads(manifest_bytes.decode('utf-8-sig')).get('source_kind', 'observed')
        namespace = f'synthetic_{digest[:12]}' if provenance == 'synthetic' else 'historical'
        return self.store.register_dataset({'id':digest, 'status':'validating', 'path':str(path),
            'manifest_path':str(manifest), 'source_kind':provenance, 'namespace':namespace,
            'filename':Path(filename).name, 'created_at':now(), 'report':{}, 'sha256':digest}, auto_train)

    def records(self, dataset_id, code, replay=None):
        cache_key = (dataset_id, code, replay['id'] if replay else None)
        if cache_key in self._rows:
            return self._rows[cache_key]
        from data.groundwater import station_records
        rows = [row_dict(r) for r in station_records(self.dataset(dataset_id), code)]
        if replay and replay['scenario'] == 'level_shift':
            start, amount = replay['shift_start'], replay['shift_amount']
            rows = [{**r, 'groundwater_level': r['groundwater_level'] + (amount if r['date'] >= start else 0)} for r in rows]
        self._rows[cache_key] = rows
        return rows

    def metadata(self, dataset_id, code):
        ds = self.dataset(dataset_id)
        if hasattr(ds, 'metadata_for_district'):
            return ds.metadata_for_district(code)
        rows = self.records(dataset_id, code)
        entry = self.store.get('dataset', dataset_id)
        manifest = json.loads(Path(entry['manifest_path']).read_text(encoding='utf-8-sig'))
        return {'station_id': rows[0]['station_id'], 'unit': rows[0]['level_unit'],
                'level_unit': rows[0]['level_unit'], 'dataset_version': ds.dataset_version,
                'mapping_version': manifest['mapping_version']}

    def districts(self, dataset_id=None):
        from data.groundwater import DISTRICTS
        result = [dict(x) for x in DISTRICTS]
        entry = self.store.get('dataset', dataset_id) if dataset_id else self.latest_dataset()
        mapping_version = None
        if entry:
            manifest = json.loads(Path(entry['manifest_path']).read_text(encoding='utf-8-sig'))
            mapping_version = manifest['mapping_version']
            stations = {x['district_code']: x for x in manifest['stations']}
            result = [{**r, **stations.get(r['district_code'], {})} for r in result]
        return {'districts': result, 'mapping_version': mapping_version}

    def forecasts(self, as_of=None, mode='historical_replay', replay_id=None, dataset_id=None):
        if mode not in ('historical_replay', 'current'):
            raise ValueError('mode는 historical_replay 또는 current입니다.')
        replay = self.store.get('replay', replay_id) if replay_id else None
        entry = self.store.get('dataset', dataset_id) if dataset_id else self.latest_dataset()
        if replay:
            entry = self.store.get('dataset', replay['dataset_id'])
            if replay['status'] != 'ready':
                raise ValueError('재생 모델 초기화가 완료되지 않았습니다.')
            # 조회로 미래 재생 정답에 접근하지 않습니다.
            if as_of and as_of > replay['as_of']:
                raise ValueError('재생 시계 이후 날짜는 조회할 수 없습니다.')
            as_of = as_of or replay['as_of']
        if mode == 'current':
            if replay:
                raise ValueError('현재 모드에서는 재생 세션을 선택할 수 없습니다.')
            if as_of and as_of != today().isoformat():
                raise ValueError('현재 모드 기준일은 서울 오늘 날짜여야 합니다.')
            as_of = today().isoformat()
        if not as_of and entry:
            ds = self.dataset(entry['id'])
            as_of = max(iso(r.date) for r in ds.records) if ds.records else today().isoformat()
        as_of = as_of or today().isoformat()
        anchor = date.fromisoformat(as_of)
        namespace = replay['id'] if replay else (entry.get('namespace', 'historical') if entry else 'historical')
        models = {str(x['district_code']): x for x in self.manager(namespace).list_models()}
        district_data = self.districts(entry['id'] if entry else None)
        events = self.store.list('event')
        items = []
        for district in district_data['districts']:
            code = district['district_code']
            value = {**district, 'observed_date': None, 'forecast_date': (anchor + timedelta(days=1)).isoformat(),
                     'prediction': None, 'unit': district.get('level_unit'), 'model_version': None,
                     'dataset_version': entry['id'] if entry else None,
                     'mapping_version': district_data['mapping_version'], 'quality_status': 'DATA_REQUIRED',
                     'inspection_status': 'NONE', 'mode': mode, 'replay_id': replay_id,
                     'generated_at': now(), 'freshness_days': None, 'reason': '검증한 자료와 대표 관측소 매핑이 필요합니다.'}
            value['source_kind'] = ('synthetic' if replay and replay.get('synthetic') else entry.get('source_kind', 'observed')) if entry else None
            if entry:
                rows = [r for r in self.records(entry['id'], code, replay) if r['date'] <= as_of]
                provenance = self.dataset(entry['id']).manifest.get('provenance', {})
                interval = provenance.get('intervals', {}).get(code, {})
                def modified(r):
                    return bool(replay and replay['scenario']=='level_shift' and r['date']>=replay['shift_start'])
                observed = [r['date'] for r in rows if r.get('origin', entry.get('source_kind')) == 'observed' and not modified(r)]
                synthetic = [r['date'] for r in rows if r.get('origin', entry.get('source_kind')) == 'synthetic' or modified(r)]
                value['data_source'] = {
                    'kind': value['source_kind'], 'observed_through': max(observed, default=None),
                    'input_through': rows[-1]['date'] if rows else None,
                    'contains_synthetic': bool(synthetic) or bool(replay and replay.get('synthetic')),
                    'synthetic_from': min(synthetic, default=None),
                    'synthetic_through': max(synthetic, default=None),
                    'original_observed_through': interval.get('observed_through') or max(
                        (r['date'] for r in rows if r.get('origin', entry.get('source_kind'))=='observed'), default=None),
                    'generated_at': provenance.get('generated_at') or entry.get('generated_at'), 'registered_at': entry.get('created_at'),
                    'external_api_applied': False}
                if rows:
                    value.update(observed_date=rows[-1]['date'], unit=rows[-1]['level_unit'],
                                 freshness_days=(anchor-date.fromisoformat(rows[-1]['date'])).days,
                                 input_origin='synthetic' if modified(rows[-1]) else rows[-1].get('origin', entry.get('source_kind', 'observed')))
                value['latest_comparison'] = None
                if rows:
                    observed = rows[-1]
                    saved = [p for p in self.store.forecasts(namespace, code, source_dataset_id=entry['id'])
                             if p['forecast_date'] == observed['date']]
                    chosen = max(saved, key=lambda p: p.get('generated_at') or '') if saved else {}
                    value['latest_comparison'] = {
                        'date': observed['date'], 'actual': observed['groundwater_level'],
                        'prediction': chosen.get('prediction'), 'model_version': chosen.get('model_version')}
                model = models.get(code)
                if mode == 'current' and value['freshness_days'] is not None and value['freshness_days'] > 0:
                    value.update(quality_status='STALE_DATA', reason=f"오늘까지 관측 자료가 없습니다. 마지막 관측 후 {value['freshness_days']}일 경과했습니다.")
                elif not model or model.get('status') in ('rejected', 'not_ready'):
                    value.update(quality_status='MODEL_NOT_READY', reason='게이트를 통과한 모델이 없습니다.')
                elif len(rows) < 20 or rows[-1]['date'] != as_of or any(
                    date.fromisoformat(rows[-20+i]['date']) != anchor - timedelta(days=19-i) for i in range(20)):
                    value.update(quality_status='DATA_GAP', reason='기준일까지 연속 20일 입력이 없습니다.')
                elif model.get('trained_through') and as_of < model['trained_through']:
                    value.update(quality_status='BEFORE_MODEL_TRAINING_CUTOFF', reason='현재 모델 학습일 이전 예측을 새로 계산하지 않습니다.')
                elif (model.get('splits', {}).get('replay', {}).get('start') and
                      as_of < (date.fromisoformat(model['splits']['replay']['start']) - timedelta(days=1)).isoformat()):
                    value.update(quality_status='BEFORE_EVALUATION_CUTOFF', reason='학습·검증·테스트 이후 기간을 조회하세요.')
                else:
                    try:
                        current_version = model.get('model_version', model.get('version'))
                        cached = self.store.cached_forecast(namespace, code, current_version, value['forecast_date'], entry['id'])
                        manager = self.manager(namespace)
                        version_now = manager.current_version(code) if hasattr(manager, 'current_version') else current_version
                        if cached and cached.get('source_dataset_id') == entry['id'] and str(version_now) == str(current_version):
                            prediction = {k: cached[k] for k in ('prediction', 'model_version', 'unit', 'dataset_version', 'mapping_version')}
                        else:
                            prediction = self.manager(namespace).predict(code, rows[-20:])
                        value.update(prediction)
                        value.update(quality_status='NORMAL', reason=None, source_dataset_id=entry['id'])
                        self.store.forecast(namespace, value)
                    except (ValueError, FileNotFoundError, KeyError, RuntimeError) as exc:
                        value.update(quality_status='MODEL_NOT_READY', reason=str(exc))
                open_events = [e for e in events if e['district_code'] == code
                               and e.get('namespace') == namespace and e['status'] != 'RESOLVED']
                if open_events:
                    value['inspection_status'] = 'OPEN' if any(e['kind'] == 'inspection' for e in open_events) else 'NONE'
                    if value['prediction'] is not None and any(e['kind'] == 'quality' for e in open_events):
                        value['quality_status'] = 'WARN'
            items.append(value)
        clock = self.simulation_clock(replay, as_of)
        if clock['enabled']:
            for value in items:
                observed = value['observed_date']
                value['presentation_observed_date'] = self.simulation_clock(replay, observed)['presentation_as_of'] if observed else None
                value['presentation_forecast_date'] = clock['presentation_forecast_date']
        return {'forecasts': items, 'as_of': as_of, 'ready_count': sum(x['prediction'] is not None for x in items),
                'total': 25, 'mode': mode, 'replay_id': replay_id, 'simulation': clock,
                'provenance': self.dataset(entry['id']).manifest.get('provenance', {}) if entry else {}}

    def history(self, code, dataset_id=None, replay_id=None):
        replay = self.store.get('replay', replay_id) if replay_id else None
        entry = self.store.get('dataset', replay['dataset_id'] if replay else dataset_id) if (replay or dataset_id) else self.latest_dataset()
        if not entry:
            return {'history': [], 'unit': None}
        rows = self.records(entry['id'], code, replay)
        if replay:
            rows = [r for r in rows if r['date'] <= replay['as_of']]
        namespace = replay['id'] if replay else entry.get('namespace', 'historical')
        predictions = self.store.forecasts(namespace, code, source_dataset_id=entry['id'])
        by_date = {}
        for prediction in predictions:
            by_date.setdefault(prediction['forecast_date'], []).append({k:prediction.get(k) for k in
                ('prediction','model_version','source_dataset_id','dataset_version','generated_at')})
        history = []
        for row in rows[-180:]:
            choices = sorted(by_date.get(row['date'], []), key=lambda p:p.get('generated_at') or '')
            chosen = choices[-1] if choices else {}
            history.append({**row, 'prediction':chosen.get('prediction'),
                            'prediction_model_version':chosen.get('model_version'), 'predictions':choices})
        # Display the actually stored next-day prediction without manufacturing
        # its observation or rainfall. Historical replay still reveals one day.
        if rows:
            next_date = (date.fromisoformat(rows[-1]['date'])+timedelta(days=1)).isoformat()
            choices = sorted(by_date.get(next_date, []), key=lambda p:p.get('generated_at') or '')
            if choices:
                chosen = choices[-1]
                history.append({'date':next_date,'groundwater_level':None,'rainfall_mm':None,
                                'origin':'prediction','prediction':chosen['prediction'],
                                'prediction_model_version':chosen['model_version'],'predictions':choices})
        clock = self.simulation_clock(replay)
        if clock['enabled']:
            next_date = clock['source_forecast_date']
            choices = sorted(by_date.get(next_date, []), key=lambda p:p.get('generated_at') or '')
            if choices and not any(r['date'] == next_date for r in history):
                chosen = choices[-1]
                history.append({'date': next_date, 'groundwater_level': None, 'rainfall_mm': None,
                                'prediction': chosen['prediction'], 'prediction_model_version': chosen['model_version'],
                                'predictions': choices})
            for row in history:
                row['presentation_date'] = self.simulation_clock(replay, row['date'])['presentation_as_of']
        return {'history':history, 'unit':rows[-1]['level_unit'] if rows else None,
                'source_kind':'synthetic' if replay and replay.get('synthetic') else entry.get('source_kind'),
                'source_dataset_id':entry['id'], 'prediction_selection':'latest_recorded_per_target',
                'version_history':next((m.get('history',[]) for m in self.manager(namespace).list_models() if m['district_code']==code),[]),
                'simulation': clock}

    def readiness(self):
        entry = self.latest_dataset()
        if not entry:
            return {'status':'data_or_model_required','ready_count':0,'forecast_ready_count':0,'total':25,'dataset_ready':False}
        manager = self.manager(entry.get('namespace','historical'))
        models = {m['district_code']:m for m in manager.list_models()}
        details, count, forecast_count = [], 0, 0
        latest = max(iso(r.date) for r in self.dataset(entry['id']).records)
        for district in self.districts(entry['id'])['districts']:
            code = district['district_code']
            try:
                metadata = self.metadata(entry['id'], code)
                if hasattr(manager, 'check_ready'):
                    manager.check_ready(code, metadata)
                else:
                    model = models.get(code,{})
                    if not model.get('model_version'):
                        raise ValueError('model_not_ready')
                count += 1
                rows = self.records(entry['id'],code)[-20:]
                continuous = len(rows)==20 and rows[-1]['date']==latest and all(
                    date.fromisoformat(rows[i+1]['date'])-date.fromisoformat(rows[i]['date'])==timedelta(days=1) for i in range(19))
                forecast_count += int(continuous)
                reason = None if continuous else ('input_insufficient' if len(rows)<20 else
                         'input_end_mismatch' if rows[-1]['date']!=latest else 'input_date_gap')
                details.append({'district_code':code,'model_ready':True,'input_ready':continuous,
                                'reason':reason,'input_end_date':rows[-1]['date'] if rows else None})
            except Exception as error:
                details.append({'district_code':code,'model_ready':False,'input_ready':False,'reason':str(error)})
        return {'status':'ready' if count==25 and forecast_count==25 else 'data_or_model_required','ready_count':count,
                'forecast_ready_count':forecast_count,'total':25,'dataset_ready':True,'as_of':latest,'districts':details}

    def monitoring(self, replay_id=None):
        namespace = replay_id or self.default_namespace()
        if replay_id:
            self.store.get('replay',replay_id)
        states = {s['district_code']:s for s in self.store.list('monitor') if s['id'].startswith(namespace+':')}
        return {'namespace':namespace,'monitors':[{k:v for k,v in {**m,**states.get(m['district_code'],{})}.items()
                if k in ('district_code','model_version','threshold','rmse','as_of','last_processed_target_date','breaches','candidate','candidate_as_of','last_trigger')}
                for m in self.manager(namespace).list_models()]}

    def pipeline(self, district_code='11110', replay_id=None):
        replay=self.store.get('replay',replay_id) if replay_id else None
        entry=self.store.get('dataset',replay['dataset_id']) if replay else self.latest_dataset()
        namespace=replay_id or self.default_namespace()
        model=next((m for m in self.manager(namespace).list_models() if m['district_code']==district_code),{})
        jobs=[j for j in self.store.jobs(namespace) if j['payload'].get('district_code') in (None,district_code)]
        events=[e for e in self.store.list('event') if e.get('namespace')==namespace and e.get('district_code')==district_code]
        try: monitor=self.store.get('monitor',f'{namespace}:{district_code}')
        except KeyError: monitor={}
        labelled=self.store.forecasts(namespace,district_code,labelled=True,source_dataset_id=entry['id'] if entry else None)
        fine=next((j for j in jobs if j['kind']=='fine_tune'),None)
        evaluation=next((e for e in events if e.get('result',{}).get('candidate_version') and e.get('result',{}).get('status') in ('promoted','rejected')),None)
        quality=next((e for e in events if e['kind']=='quality'),None)
        version=model.get('model_version')
        served=[f for f in self.store.forecasts(namespace,district_code,source_dataset_id=entry['id'] if entry else None) if str(f.get('model_version'))==str(version)]
        history=[h for h in model.get('history',[]) if h.get('from') and h.get('from')!=h.get('to')]
        pending=monitor.get('candidate')
        current_evaluation=evaluation if evaluation and (not fine or evaluation['created_at']>=fine['created_at']) else None
        cycle_version=pending or (current_evaluation['result'].get('candidate_version') if current_evaluation else None)
        cycle_promoted=bool(current_evaluation and current_evaluation['result']['status']=='promoted' and any(str(h['to'])==str(cycle_version) for h in history))
        pending_days=0
        if pending and replay and monitor.get('candidate_as_of'):
            pending_days=sum(r['date']>monitor['candidate_as_of'] and r['date']<=replay['as_of'] for r in self.records(replay['dataset_id'],district_code,replay))
        evaluation_detail = current_evaluation['message'] if current_evaluation else '새 정답30일 · 개선5% · guard110%'
        if current_evaluation:
            scores = current_evaluation['result'].get('metrics', {})
            candidate_rmse = scores.get('shadow_candidate', {}).get('rmse')
            champion_rmse = scores.get('shadow_champion', {}).get('rmse')
            if candidate_rmse is not None and champion_rmse is not None:
                outcome = '기준 통과' if cycle_promoted else '기준 미충족 · 기존 모델 유지'
                evaluation_detail = f'새 모델 RMSE {candidate_rmse:.4g} · 기존 {champion_rmse:.4g} · {outcome}'
                failed_gates = [label for key,label in (
                    ('future_improvement','향후 구간 5% 개선 미충족'),
                    ('historical_guard','기존 구간 오차 110% 조건 미충족'))
                    if current_evaluation['result'].get('gates',{}).get(key,{}).get('passed') is False]
                if failed_gates:
                    evaluation_detail += ' · ' + ' · '.join(failed_gates)
        retrain_detail = '드리프트 감지 후 자동 접수'
        if fine:
            retrain_detail = fine['error'] or ('후보 학습 완료 · 이후 정답으로 평가' if fine['status']=='completed' else fine['id'])
        stages=[
            {'key':'data','title':'자료 검증','status':'completed' if entry and entry['status']=='ready' else 'pending','detail':entry['id'][:12] if entry else '자료 등록 필요'},
            {'key':'monitor','title':'오차 감시','status':'completed' if monitor.get('rmse') is not None else 'pending','detail':f"정답 {len({f['forecast_date'] for f in labelled})}일 · 21일 창 · RMSE {monitor.get('rmse','평가 대기')} · 임계값 {model.get('threshold','미정')}"},
            {'key':'drift','title':'드리프트 감지','status':'completed' if quality else 'pending','detail':quality['message'] if quality else f"21일 오차 기준 연속 {monitor.get('breaches',0)}/2회 초과 · 정답 21일 확보 후 판정"},
            {'key':'retrain','title':'자동 재학습','status':fine['status'] if fine else 'pending','detail':retrain_detail},
            {'key':'evaluate','title':'후보 평가','status':'pending' if pending else current_evaluation['result']['status'] if current_evaluation else 'pending','detail':f"후보 v{pending} · 후속 정답 {pending_days}/30일 대기" if pending else evaluation_detail},
            {'key':'promote','title':'모델 교체','status':'completed' if cycle_promoted else 'rejected' if current_evaluation and current_evaluation['result']['status']=='rejected' else 'pending','detail':f"후보 v{cycle_version} 게이트 통과·교체" if cycle_promoted else f"현재 후보 미교체 · 현재 서빙 v{version or '없음'}"},
            {'key':'serve','title':'현재 모델 서빙','status':'completed' if served else 'pending','detail':f"실제 예측 v{version} · {served[-1]['forecast_date']}" if served else '조회 후 실제 응답 버전 확인'}]
        defaults=None
        if entry:
            rows=self.records(entry['id'],district_code)
            metadata=self.metadata(entry['id'],district_code)
            start=metadata.get('replay_start') or (rows[-90]['date'] if len(rows)>=410 else None)
            if start:
                defaults={'dataset_id':entry['id'],'start_date':str(date.fromisoformat(start)-timedelta(days=1)),
                          'end_date':rows[-1]['date'],'shift_start':str(date.fromisoformat(start)+timedelta(days=21)),
                          'shift_amount':.2}
        return {'namespace':namespace,'district_code':district_code,'replay_id':replay_id,
                'simulation': self.simulation_clock(replay),
                'as_of':replay['as_of'] if replay else (max((r['date'] for r in self.records(entry['id'],district_code)),default=None) if entry else None),'replay_status':replay['status'] if replay else None,
                'remaining_days':(date.fromisoformat(replay.get('end_date') or defaults['end_date'])-date.fromisoformat(replay['as_of'])).days if replay and defaults else 0,
                'latest_advance_job':next(({k:j[k] for k in ('id','kind','status','result','error')} for j in jobs if j['kind']=='advance'),None),
                'active_jobs':[{k:j[k] for k in ('id','kind','status','result','error')} for j in jobs if j['status'] in ('queued','running')],
                'advance_active':any(j['kind']=='advance' and j['status'] in ('queued','running') for j in jobs),'stages':stages,'defaults':defaults,
                'log':sorted([{'at':e['created_at'],'kind':e['kind'],'message':e['message'],'status':e['status']} for e in events]+[{'at':j['updated_at'],'kind':j['kind'],'message':j['error'] or j['id'],'status':j['status']} for j in jobs],key=lambda x:x['at'],reverse=True)[:50],
                'candidate_version':pending,'evaluation':evaluation.get('result') if evaluation else None,
                'drift_demo':{'shift_start':replay['shift_start'],'shift_amount':replay['shift_amount'],'applied':replay['as_of']>=replay['shift_start'],
                    'monitoring_note':'정답 21일 → 기준 연속 2회 초과 → 자동 재학습 → 후속 정답 30일 평가'} if replay and replay['scenario']=='level_shift' else None,
                'source_kind':('synthetic' if replay and replay.get('synthetic') else entry.get('source_kind')) if entry else None,
                'note':'현재 후보의 평가·교체와 현재 모델 서빙을 구분합니다. 초기 모델도 서빙할 수 있으며, 과거 교체가 현재 후보의 성공을 뜻하지 않습니다. 단계 완료는 현장 안전 확인이 아닙니다.'}

    def evaluate_service_health(self):
        summary = self.store.metric_summary(300)
        bucket = datetime.now(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M')
        key = 'service-metrics:'+bucket
        try:
            self.store.get('service_sample',key)
            return summary
        except KeyError:
            pass
        warnings = []
        if summary['count'] >= 20:
            if summary['p95_seconds'] > 1:
                warnings.append('p95 > 1s')
            if summary['error_rate'] >= .01:
                warnings.append('5xx >= 1%')
        sample = {'at':now(), 'summary':summary,'warnings':warnings}
        self.store.put('service_sample',sample,key)
        if warnings:
            self.store.event(None,'service','서비스 지표 경보: '+', '.join(warnings),'service',summary=summary)
        return sample

    def train_job(self, dataset_id, district_code=None, namespace=None, reuse_existing=False):
        self.dataset(dataset_id)
        namespace = namespace or self.store.get('dataset', dataset_id).get('namespace', 'historical')
        return self.store.enqueue('train', {'dataset_id': dataset_id, 'district_code': district_code,
                                          'namespace': namespace, 'reuse_existing': reuse_existing}, f'model:{namespace}:{district_code or "all"}')

    def create_replay(self, dataset_id, start_date, end_date=None, scenario='historical', shift_start=None, shift_amount=0, presentation_start_date=None):
        self.dataset(dataset_id)
        start = date.fromisoformat(start_date)
        all_records = self.dataset(dataset_id).records
        latest = max(iso(r.date) for r in all_records)
        if start_date > latest or (end_date and end_date > latest):
            raise ValueError('재생 날짜가 관측 자료의 마지막 날짜를 넘었습니다.')
        if end_date and date.fromisoformat(end_date) < start:
            raise ValueError('종료일은 시작일 이후여야 합니다.')
        if scenario not in ('historical', 'level_shift'):
            raise ValueError('지원하지 않는 시나리오입니다.')
        if presentation_start_date:
            date.fromisoformat(presentation_start_date)
            if scenario != 'historical':
                raise ValueError('공급 시뮬레이션은 원관측값을 사용하는 historical 시나리오만 허용합니다.')
        if scenario == 'level_shift' and (not shift_start or date.fromisoformat(shift_start) <= start or not math.isfinite(shift_amount)):
            raise ValueError('변화 시작일은 재생 시작일 이후이며 변화량은 유한값이어야 합니다.')
        replay = self.store.put('replay', {'dataset_id': dataset_id, 'as_of': start_date,
            'start_date': start_date, 'end_date': end_date, 'scenario': scenario,
            'presentation_start_date': presentation_start_date,
            'shift_start': shift_start, 'shift_amount': shift_amount,
            'status': 'initializing', 'created_at': now(), 'synthetic': scenario != 'historical'})
        job = self.train_job(dataset_id, namespace=replay['id'])
        return {**replay, 'job_id': job['id']}

    def advance_job(self, replay_id, days=1):
        replay = self.store.get('replay', replay_id)
        if replay.get('presentation_start_date') and days != 1:
            raise ValueError('공급 시뮬레이션은 하루씩만 진행할 수 있습니다.')
        if replay['status'] != 'ready':
            raise ValueError('재생 모델 초기화가 완료되지 않았습니다.')
        target = (date.fromisoformat(replay['as_of']) + timedelta(days=days)).isoformat()
        end = replay.get('end_date') or max(iso(r.date) for r in self.dataset(replay['dataset_id']).records)
        if target > end:
            raise ValueError('요청한 진행일이 재생 종료일 또는 자료 마지막 날짜를 넘었습니다.')
        return self.store.enqueue('advance', {'replay_id': replay_id, 'days': days, 'target_date': target}, f'replay:{replay_id}')

    def run_job(self, job):
        kind, payload = job['kind'], job['payload']
        if kind in ('monitor_api_feed','retrain_api_feed','rollback_api_feed'):
            from serving_app.api_feed_ops import ApiFeedOperations
            operations=ApiFeedOperations(self)
            if kind == 'monitor_api_feed':
                from serving_app.api_observation_feed import ApiObservationFeed
                return operations.cycle(ApiObservationFeed(self.root))
            return operations.execute_job(job)
        if kind == 'train_api_feed':
            from serving_app.api_feed_models import ApiFeedTraining
            from serving_app.api_observation_feed import ApiObservationFeed
            return ApiFeedTraining(self.root).execute(payload['feed_hash'], ApiObservationFeed(self.root).stations)
        if kind in ('train_live','predict_live','fine_tune_live'):
            from serving_app.live_observations import LiveObservations
            return LiveObservations(self).execute_job(job)
        if kind == 'validate':
            entry = self.store.get('dataset', payload['dataset_id'])
            try:
                from data.groundwater import load_canonical, validate_manifest
                dataset = load_canonical(entry['path'], entry['manifest_path'])
                manifest = json.loads(Path(entry['manifest_path']).read_text(encoding='utf-8-sig'))
                validate_manifest(manifest)
                if not dataset.records or dataset.report['districts_with_data'] != 25:
                    raise ValueError('대표 25개 구 모두 유효한 관측 자료가 필요합니다.')
                entry.update(status='ready', report=dataset.report, dataset_version=dataset.dataset_version)
                self.store.put('dataset', entry)
                if payload.get('auto_train'):
                    self.train_job(entry['id'], reuse_existing=True)
                return {'dataset_id': entry['id'], 'report': dataset.report}
            except Exception as exc:
                entry.update(status='invalid', report={'error': str(exc)})
                self.store.put('dataset', entry)
                raise
        if kind == 'train':
            entry_id = payload['dataset_id']
            namespace = payload.get('namespace', 'historical')
            manager = self.manager(namespace)
            codes = [payload['district_code']] if payload.get('district_code') else [x['district_code'] for x in self.districts(entry_id)['districts']]
            replay = next((r for r in self.store.list('replay') if r['id'] == namespace), None)
            existing = {m['district_code']: m for m in manager.list_models()} if payload.get('reuse_existing') else {}
            source_manager = self.manager(self.store.get('dataset', entry_id).get('namespace', 'historical'))
            source_models = {m['district_code']: m for m in source_manager.list_models()} if replay else {}
            results = []
            for code in codes:
                try:
                    rows = self.records(entry_id, code)
                    metadata = self.metadata(entry_id, code)
                    old = existing.get(code, {})
                    same = old.get('status') == 'ready' and old.get('kind') == 'initial' and all(
                        old.get(k) == metadata.get(k) for k in ('station_id','level_unit','dataset_version','mapping_version',
                        'split_policy','replay_start','train_max_targets','model_architecture','learning_rate'))
                    if replay:
                        if len(rows) < 410 or replay['start_date'] < (date.fromisoformat(rows[-90]['date']) - timedelta(days=1)).isoformat():
                            raise ValueError('재생 시작일은 최소 410일 자료의 마지막 90일 구간 안이어야 합니다.')
                    initial = source_models.get(code) if replay else None
                    if initial and (initial.get('status') != 'ready' or initial.get('kind') != 'initial'):
                        initial = None
                    if same and not replay:
                        result = {'status': 'retained', 'model_version': old['model_version'], 'metrics': old['metrics'],
                                  'splits': old['splits'], 'reason': '동일 자료·관측소·학습 설정의 검증된 초기 모델 재사용'}
                    elif initial and initial.get('dataset_version') == metadata.get('dataset_version'):
                        result = manager.clone_from(source_manager, code, metadata=metadata)
                    else:
                        result = manager.train(code, rows, metadata=metadata,
                            max_epochs=int(os.getenv('GROUNDWATCH_TRAIN_EPOCHS', '100')))
                    if replay and result.get('status') == 'promoted':
                        models = [x for x in manager.list_models() if x['district_code'] == code]
                        # No inference on data used by initial training or validation/test.
                        split = result.get('splits', models[0].get('splits', {}) if models else {})
                        replay_cutoff = split.get('replay', {}).get('start') or result.get('replay_start')
                        if replay_cutoff and replay['start_date'] < (date.fromisoformat(str(replay_cutoff)) - timedelta(days=1)).isoformat():
                            raise ValueError(f'재생 시작일은 잠금 테스트 이후 {replay_cutoff}부터 가능합니다.')
                    results.append({'district_code': code, **result})
                except Exception as exc:
                    results.append({'district_code': code, 'status': 'failed', 'error': str(exc)})
                self.store.event(code, 'model', f'초기 학습: {results[-1]["status"]}', namespace, result=results[-1])
                self.store.progress(job['id'], {'models': results, 'processed': len(results), 'total': len(codes)})
            if replay:
                replay['ready_count'] = sum(x['status'] == 'promoted' for x in results)
                replay['status'] = 'ready' if replay['ready_count'] == len(codes) else ('partial' if replay['ready_count'] else 'failed')
                self.store.put('replay', replay)
            return {'models': results, 'promoted_count': sum(x['status'] == 'promoted' for x in results),
                    'retained_count': sum(x['status'] == 'retained' for x in results),
                    'failed_districts':[x['district_code'] for x in results if x['status'] not in ('promoted','retained')],
                    'requested_count':len(codes), 'all_ready':all(x['status'] in ('promoted','retained') for x in results)}
        if kind == 'advance':
            replay = self.store.get('replay', payload['replay_id'])
            target = payload.get('target_date') or (date.fromisoformat(replay['as_of']) + timedelta(days=payload['days'])).isoformat()
            start = date.fromisoformat(replay['as_of'])
            total = (date.fromisoformat(target)-start).days
            while replay['as_of'] < target:
                self.advance_day(replay)
                self.store.progress(job['id'], {'processed':(date.fromisoformat(replay['as_of'])-start).days, 'total':total, 'as_of':replay['as_of']})
                # Process training at the triggering replay date, before revealing
                # further labels. One worker retains serial TensorFlow execution.
                while followup := self.store.claim('fine_tune'):
                    self._execute(followup)
            return {'replay_id': replay['id'], 'as_of': replay['as_of']}
        if kind == 'rollback':
            result = self.manager(payload['namespace']).rollback(payload['district_code'], payload.get('version'))
            self.store.event(payload['district_code'], 'model', '검증된 이전 모델로 롤백',
                             payload['namespace'], reason=payload['reason'], result=result)
            return result
        if kind == 'fine_tune':
            replay = self.store.get('replay', payload['replay_id'])
            code, namespace = payload['district_code'], replay['id']
            rows = [r for r in self.records(replay['dataset_id'], code, replay) if r['date'] <= payload['as_of']]
            result = self.manager(namespace).fine_tune(code, rows[-41:], metadata=self.metadata(replay['dataset_id'], code))
            state_id = f'{namespace}:{code}'
            state = self.store.get('monitor', state_id)
            state.update(candidate=result.get('candidate_version', result.get('version')), candidate_as_of=payload['as_of'])
            self.store.put('monitor', state, state_id)
            self.store.event(code, 'model', '재학습 후보 생성, 후속 정답 30일 평가 대기', namespace, result=result)
            return result
        raise ValueError(f'지원하지 않는 작업: {kind}')

    def advance_day(self, replay):
        namespace = replay['id']
        anchor = date.fromisoformat(replay['as_of'])
        next_day = (anchor + timedelta(days=1)).isoformat()
        if replay.get('end_date') and next_day > replay['end_date']:
            raise ValueError('재생 종료일을 넘었습니다.')
        all_rows = [r for r in self.dataset(replay['dataset_id']).records]
        if next_day > max(iso(r.date) for r in all_rows):
            raise ValueError('관측 자료의 마지막 날짜를 넘었습니다.')
        # Predict at t, then reveal t+1 label. The clock never reveals future labels.
        self.forecasts(as_of=replay['as_of'], replay_id=namespace)
        for district in self.districts(replay['dataset_id'])['districts']:
            code = district['district_code']
            rows = [r for r in self.records(replay['dataset_id'], code, replay) if r['date'] <= next_day]
            if not rows or rows[-1]['date'] != next_day:
                continue
            self.store.label(namespace, code, next_day, rows[-1]['groundwater_level'])
            self.monitor(replay, code, rows, next_day)
        replay['as_of'] = next_day
        self.store.put('replay', replay)

    def monitor(self, replay, code, rows, as_of):
        namespace, manager = replay['id'], self.manager(replay['id'])
        models = [x for x in manager.list_models() if x['district_code'] == code]
        if not models:
            return
        model = models[0]
        version = str(model.get('model_version', model.get('version')))
        threshold = model.get('threshold', model.get('drift_threshold'))
        state_id = f'{namespace}:{code}'
        try:
            state = self.store.get('monitor', state_id)
        except KeyError:
            state = {'district_code':code,'version':version,'breaches':0,'last_trigger':None,'candidate':None}
        if state.get('last_processed_target_date','') >= as_of:
            return
        if state['version'] != version:
            state.update(version=version,breaches=0,last_trigger=as_of,candidate=None)
        previous_day = (date.fromisoformat(as_of)-timedelta(days=1)).isoformat()
        if state.get('last_processed_target_date') != previous_day:
            state['breaches'] = 0
        state.update(last_processed_target_date=as_of,threshold=threshold)
        event, job = None, None
        if state.get('candidate'):
            future = [r for r in rows if r['date'] > state['candidate_as_of']]
            if len(future) >= 30:
                cutoff = future[29]['date']
                shadow = [r for r in rows if r['date'] <= cutoff][-50:]
                continuous = len(shadow)==50 and all(date.fromisoformat(shadow[i]['date'])+timedelta(days=1)==date.fromisoformat(shadow[i+1]['date']) for i in range(49))
                result = manager.evaluate_candidate(code,state['candidate'],shadow) if continuous else (manager.reject_candidate(code,state['candidate'],'shadow_calendar_gap') if hasattr(manager,'reject_candidate') else {'status':'rejected','reason':'shadow_calendar_gap','candidate_version':state['candidate']})
                if result.get('status') != 'pending':
                    event = {'district_code':code,'kind':'model','namespace':namespace,
                             'message':f'후보 평가: {result.get("status")}', 'result':result}
                    state.update(candidate=None,last_trigger=as_of,breaches=0)
        else:
            labelled = self.store.forecasts(namespace,code,version,labelled=True,source_dataset_id=replay['dataset_id'])[-21:]
            if len(labelled)==21 and labelled[-1]['forecast_date']==as_of and all(
                date.fromisoformat(labelled[i]['forecast_date'])+timedelta(days=1)==date.fromisoformat(labelled[i+1]['forecast_date']) for i in range(20)):
                rmse = math.sqrt(sum((r['prediction']-r['actual'])**2 for r in labelled)/21)
                state.update(rmse=rmse,as_of=as_of)
                state['breaches'] = state['breaches']+1 if threshold is not None and rmse>threshold else 0
                cooldown = not state.get('last_trigger') or (date.fromisoformat(as_of)-date.fromisoformat(state['last_trigger'])).days>=21
                if state['breaches']>=2 and cooldown and len(rows)>=41:
                    event = {'district_code':code,'kind':'quality','namespace':namespace,
                             'message':f'21일 RMSE {rmse:.6g} > 임계값 {threshold:.6g}: 재학습 요청',
                             'rmse':rmse,'threshold':threshold,'model_version':version}
                    job = ('fine_tune',{'replay_id':namespace,'district_code':code,'as_of':as_of},f'model:{namespace}:{code}')
                    state['last_trigger'] = as_of
        self.store.commit_monitor(state_id,state,event,job)

    def execute_one(self):
        job = self.store.claim()
        if not job:
            return False
        self._execute(job)
        return True

    def _execute(self, job):
        try:
            result = self.run_job(job)
            error = '요청한 구 중 학습·게이트를 통과하지 못한 구가 있습니다. 구별 결과를 확인하세요.' if job['kind'] == 'train' and not result.get('all_ready', result.get('promoted_count',0) + result.get('retained_count',0) > 0) else None
            if job['kind']=='train_live' and result.get('status')=='rejected':
                error='API 자료 초기 모델이 품질 게이트를 통과하지 못했습니다. 기존 모델을 유지합니다.'
            self.store.finish(job['id'], result=result, error=error)
        except Exception as exc:
            self.store.finish(job['id'], error=f'{type(exc).__name__}: {exc}')
            self.store.event(None, 'job', f'{job["kind"]} 실패: {exc}', job.get('payload', {}).get('namespace', 'historical'), job_id=job['id'])
