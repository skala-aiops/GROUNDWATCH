"""Live daily inference is isolated from historical replay and legacy models."""
from datetime import date, timedelta
import math
from pathlib import Path
import json
from data.groundwater import DISTRICTS, CanonicalDataset, Observation
from serving_app.groundwater_store import now
from serving_app.groundwater_service import today
from serving_app.observation_repository import ObservationRepository


class LiveObservations:
    def __init__(self, service):
        self.service=service
        self.repo=ObservationRepository(service.root/'external'/'observations.sqlite3')
        manifest=Path(__file__).resolve().parents[1]/'data'/'representatives.json'
        if manifest.exists():
            self.repo.bootstrap_candidates(json.loads(manifest.read_text()))

    def mapping_for_code(self, code):
        candidates=[m for m in self.repo.mappings() if m['district_code']==code]
        approved=[m for m in self.repo.selected_mappings() if m['district_code']==code]
        # Explicit activation selects version, never latest row order.
        active=self.repo.active()
        for m in approved:
            if m['station_id'] in active and self.repo.snapshot(active[m['station_id']])['mapping_version']==m['version']:
                return m
        if approved:
            return approved[0]
        return candidates[0] if candidates else None

    def freshness(self,target=None):
        target=target or today().isoformat()
        target_day=date.fromisoformat(target);end=target_day-timedelta(days=1)
        start=end-timedelta(days=19);active=self.repo.active();items=[]
        for district in DISTRICTS:
            m=self.mapping_for_code(district['district_code'])
            item={**district,'target_date':target,'required_input_end_date':end.isoformat(),
                'station_id':m['station_id'] if m else None,'station_name':m.get('station_name') if m else None,
                'mapping_version':m['version'] if m else None,'mapping_approved':bool(m and m['approved']),
                'feature_contract_id':m['contract_id'] if m else None,'sources':{},
                'data_status':'MAPPING_REQUIRED','reason':'서울시 식별·단위·ASOS 매핑 검증이 필요합니다.',
                'inference_snapshot_id':None}
            if m:
                for name,station,metric in [('seoul',m['seoul_name'],'groundwater_level'),('kma',m['weather_station'],'rainfall_mm')]:
                    revisions=self.repo.revisions(name,station,metric,'1900-01-01',end.isoformat(),now())
                    good=[v for v in revisions.values() if v['quality']=='valid']
                    latest=max((r['observed_date'] for r in good),default=None)
                    with self.repo.connect() as db:
                        run=db.execute('SELECT * FROM collection_runs WHERE source=? AND station=? ORDER BY collected_at DESC LIMIT 1',
                                       (name,station)).fetchone()
                    item['sources'][name]={'station':station or None,'latest_valid_observed_date':latest,
                        'last_collected_at':run['collected_at'] if run else None,
                        'last_collection_status':run['status'] if run else 'never_collected',
                        'valid_input_days':sum(start.isoformat()<=r['observed_date']<=end.isoformat() for r in good)}
                if m['approved']:
                    sid=active.get(m['station_id'])
                    item.update(data_status='DATA_REQUIRED',reason='검증된 연속20일 snapshot이 필요합니다.')
                    if sid:
                        snapshot=self.repo.snapshot(sid)
                        if snapshot['end_date']==end.isoformat() and len(snapshot['rows'])>=20 and snapshot['mapping_version']==m['version'] and snapshot['feature_contract_id']==m['contract_id']:
                            item.update(data_status='READY',reason=None,inference_snapshot_id=sid)
                        else:
                            item.update(data_status='STALE_DATA',reason='활성 snapshot의 입력 종료일이 전일과 다릅니다.')
            items.append(item)
        return {'target_date':target,'input_end_date':end.isoformat(),'total':25,
                'data_ready_count':sum(x['data_status']=='READY' for x in items),'stations':items,
                'repository':self.repo.summary()}

    def forecasts(self,target=None):
        target=target or today().isoformat()
        state=self.freshness(target);records=self.repo.predictions(target)
        latest={p['station_id']:p for p in records};items=[]
        for row in state['stations']:
            prediction=latest.get(row['station_id'])
            item={**row,'forecast_date':target,'observed_date':row['sources'].get('seoul',{}).get('latest_valid_observed_date'),
                'prediction':None,'model_version':None,'issued_at':None,'mode':'live',
                'quality_status':row['data_status'],'model_evaluation_status':'EVALUATION_PENDING','unit':None}
            if row['data_status']=='READY':
                item.update(quality_status='MODEL_OR_FORECAST_REQUIRED',reason='호환 모델과 일별 예측 발행이 필요합니다.')
            if prediction and prediction['inference_snapshot_id']==row['inference_snapshot_id']:
                item.update(prediction);item.update(quality_status='NORMAL',reason=None)
            try:
                monitor=self.service.store.get('monitor',f"observed_api_v1:{row['district_code']}")
            except KeyError:
                monitor={}
            if (item['prediction'] is not None and str(monitor.get('version')) == str(item['model_version'])
                    and monitor.get('rmse') is not None and monitor.get('threshold') is not None):
                item['model_evaluation_status']='WARN' if monitor['rmse']>monitor['threshold'] else 'EVALUATION_PASSED'
                item['evaluation_as_of']=monitor.get('last_processed_target_date')
            items.append(item)
        return {'mode':'live','target_date':target,'input_end_date':state['input_end_date'],
                'ready_count':sum(x['prediction'] is not None for x in items),'total':25,'forecasts':items}

    def history(self, code):
        mapping=self.mapping_for_code(code)
        active=self.repo.active()
        if not mapping or not mapping['approved'] or mapping['station_id'] not in active:
            return {'history':[], 'unit':None, 'version_history':[],
                    'reason':'검증된 API snapshot이 없습니다. 과거 자료를 대신 표시하지 않습니다.'}
        snapshot=self.repo.snapshot(active[mapping['station_id']])
        if (snapshot['mapping_version']!=mapping['version'] or
                snapshot['feature_contract_id']!=mapping['contract_id']):
            return {'history':[], 'unit':None, 'version_history':[], 'reason':'활성 자료의 관측소 계약이 다릅니다.'}
        end=today().isoformat(); start=(today()-timedelta(days=179)).isoformat()
        cutoff=now()
        levels=self.repo.revisions('seoul',mapping['seoul_name'],'groundwater_level',start,end,cutoff)
        rain=self.repo.revisions('kma',mapping['weather_station'],'rainfall_mm',start,end,cutoff)
        with self.repo.connect() as db:
            complete={r['revision_id'] for r in db.execute('''SELECT DISTINCT cm.revision_id
                FROM collection_members cm JOIN collection_runs cr ON cr.id=cm.run_id
                WHERE cr.status='collected' AND cr.collected_at<=?''',(cutoff,))}
        levels={day:row for day,row in levels.items() if row['quality']=='valid'
                and row['unit']==snapshot['level_unit'] and row['id'] in complete}
        rain={day:row for day,row in rain.items() if row['quality']=='valid'
              and row['unit']=='mm' and row['id'] in complete}
        rows={day:{'date':day,'groundwater_level':row['value'],
                   'rainfall_mm':rain.get(day,{}).get('value'),'predictions':[]}
              for day,row in levels.items()}
        with self.repo.connect() as db:
            predictions=db.execute('''SELECT body FROM live_predictions
                WHERE station_id=? AND target_date BETWEEN ? AND ? ORDER BY issued_at,id''',
                (mapping['station_id'],start,end)).fetchall()
        for record in predictions:
            prediction=json.loads(record['body'])
            if prediction['feature_contract_id']!=mapping['contract_id']:
                continue
            row=rows.setdefault(prediction['forecast_date'],{'date':prediction['forecast_date'],
                'groundwater_level':None,'rainfall_mm':None,'predictions':[]})
            row['predictions'].append(prediction)
            row.update(prediction=prediction['prediction'],prediction_model_version=prediction['model_version'])
        model=next((m for m in self.service.manager('observed_api_v1').list_models()
                    if m['district_code']==code),{})
        return {'history':[rows[day] for day in sorted(rows)],'unit':snapshot['level_unit'],
                'version_history':model.get('history',[]),'inference_snapshot_id':snapshot['id'],
                'weather_station_id':snapshot['weather_station_id'],'mapping_version':snapshot['mapping_version']}

    def pipeline(self,code):
        row=next(x for x in self.forecasts()['forecasts'] if x['district_code']==code)
        ns='observed_api_v1';jobs=self.service.store.jobs(ns)
        events=[e for e in self.service.store.list('event') if e.get('namespace')==ns and e.get('district_code')==code]
        try:monitor=self.service.store.get('monitor',f'{ns}:{code}')
        except KeyError:monitor={}
        scoped=[j for j in jobs if j['payload'].get('snapshot_id') and
                self.repo.snapshot(j['payload']['snapshot_id'])['station_id']==row['station_id']]
        fine=next((j for j in scoped if j['kind']=='fine_tune_live'),None)
        evaluation=next((e['result'] for e in events if e.get('result',{}).get('status') in ('promoted','rejected')),None)
        stages=[{'key':'data','title':'API 수집·검증·결합·발행','status':'completed' if row['data_status']=='READY' else 'pending',
                 'detail':row['reason'] or row['inference_snapshot_id']},
            {'key':'monitor','title':'오차 감시','status':'completed' if monitor.get('rmse') is not None else 'pending','detail':'실제 발행 예측의 정답21일 연속 창'},
            {'key':'drift','title':'품질 경보','status':'completed' if any(e['kind']=='quality' for e in events) else 'pending','detail':'자료 장애와 모델 오차 경보 분리'},
            {'key':'retrain','title':'재학습','status':fine['status'] if fine else 'pending','detail':fine['id'] if fine else '검증41일로 후보 생성'},
            {'key':'evaluate','title':'후보 평가','status':evaluation['status'] if evaluation and not monitor.get('candidate') else 'pending','detail':f"후보 {monitor.get('candidate') or '없음'} · 후속30일 정답 대기"},
            {'key':'promote','title':'모델 교체','status':'completed' if evaluation and evaluation['status']=='promoted' else 'pending','detail':'5% 개선·guard110%·실제 로딩 게이트'},
            {'key':'serve','title':'현재 모델 서빙','status':'completed' if row['prediction'] is not None else 'pending','detail':f"실제 발행 버전 {row['model_version'] or '없음'}"}]
        return {'namespace':ns,'district_code':code,'replay_id':None,'as_of':row['target_date'],
            'source_kind':'observed_api','stages':stages,'defaults':None,'evaluation':evaluation,
            'remaining_days':0,'advance_active':False,'replay_status':None,
            'log':sorted([{'at':j['updated_at'],'kind':j['kind'],'status':j['status'],'message':j['error'] or j['id']} for j in scoped]+
                         [{'at':e['created_at'],'kind':e['kind'],'status':e['status'],'message':e['message']} for e in events],
                         key=lambda x:x['at'],reverse=True)[:50],
            'note':'API 일별 운영입니다. 매핑·단위·연속 입력·호환 모델이 확인되지 않으면 예측을 발행하지 않습니다. 과거 재생 기록과 혼합하지 않습니다.'}

    def dataset(self,sid):
        s=self.repo.snapshot(sid);m=self.repo.mapping(s['station_id'],s['mapping_version'])
        metadata={'station_id':s['station_id'],'district_code':m['district_code'],'level_unit':s['level_unit'],
            'mapping_version':s['mapping_version'],'dataset_version':sid,'training_snapshot_id':sid,
            'feature_contract_id':s['feature_contract_id'],'preprocessing_version':s['preprocessing_version'],
            'rain_source':s['rain_source'],'weather_station_id':s['weather_station_id'],
            'manifest_approved':True,'train_max_targets':730,'model_architecture':'residual_lstm'}
        records=[Observation(r['station_id'],r['district_code'],date.fromisoformat(r['date']),
            r['groundwater_level'],r['rainfall_mm'],r['level_unit'],sid) for r in s['rows']]
        dataset=CanonicalDataset(records,sid,{}, {'approved':True,'mapping_version':s['mapping_version'],
                                                'stations':[metadata]})
        return dataset,metadata

    def execute_job(self,job):
        payload=job['payload'];sid=payload['snapshot_id'];s=self.repo.snapshot(sid)
        m=self.repo.mapping(s['station_id'],s['mapping_version']);code=m['district_code']
        manager=self.service.manager('observed_api_v1')
        dataset,metadata=self.dataset(sid)
        if job['kind']=='train_live':
            return manager.train_windowed(dataset,code,replay_start=payload['replay_start'],metadata=metadata)
        if job['kind']=='fine_tune_live':
            manager.check_ready(code,metadata)
            result=manager.fine_tune(code,s['rows'][-41:],metadata=metadata)
            state_id=f'observed_api_v1:{code}'
            state=self.service.store.get('monitor',state_id)
            state.update(candidate=result['candidate_version'],candidate_as_of=s['end_date'])
            self.service.store.put('monitor',state,state_id)
            self.service.store.event(code,'model','API 자료 재학습 후보 생성; 후속30일 정답 대기',
                                     'observed_api_v1',result=result)
            return result
        if job['kind']!='predict_live':
            raise ValueError('unsupported live job')
        target=today().isoformat()
        if s['end_date']!=(today()-timedelta(days=1)).isoformat():
            raise ValueError('live input snapshot must end yesterday')
        version=manager.check_ready(code,metadata)
        result=manager.predict(code,s['rows'][-20:])
        result.update(training_snapshot_id=result['dataset_version'],inference_snapshot_id=sid,
            feature_contract_id=s['feature_contract_id'],issued_at=now(),mode='live',source_kind='observed_api',
            forecast_date=target,input_end_date=s['end_date'])
        if manager.current_version(code)!=version:
            raise ValueError('model changed during live prediction; retry')
        pid=self.repo.save_prediction(result)
        return {'prediction_id':pid,**result}

    def cycle(self):
        """Publish only verified complete inputs, issue persistent jobs, then evaluate labels."""
        results=[];target=today();end=target-timedelta(days=1)
        for mapping in self.repo.selected_mappings():
            if not mapping['approved']:
                continue
            try:
                s=self.repo.publish_snapshot(mapping['station_id'],mapping['version'],
                    (end-timedelta(days=19)).isoformat(),end.isoformat())
                self.repo.activate(s['id'])
                _,metadata=self.dataset(s['id'])
                self.service.manager('observed_api_v1').check_ready(mapping['district_code'],metadata)
                existing=self.repo.predictions(target.isoformat())
                if not any(p['inference_snapshot_id']==s['id'] for p in existing):
                    self.service.store.enqueue('predict_live',{'snapshot_id':s['id'],'namespace':'observed_api_v1'},
                                               f"live:{mapping['station_id']}:{target}")
                results.append({'station_id':mapping['station_id'],'status':'ready'})
            except (ValueError,KeyError,RuntimeError,FileNotFoundError) as exc:
                results.append({'station_id':mapping['station_id'],'status':'blocked','reason':str(exc)})
        self.repo.evaluate_available()
        self.monitor()
        state={'checked_at':now(),'status':'checked' if results else 'mapping_required','stations':results}
        self.service.store.put('live_cycle',state,'observed_api_v1')
        return state

    def monitor(self):
        """Use the first recorded evaluation for decisions; later corrections remain audit revisions."""
        namespace='observed_api_v1'
        with self.repo.connect() as db:
            rows=db.execute('''SELECT p.*,e.body AS evaluation FROM live_predictions p JOIN live_evaluations e
                ON e.prediction_id=p.id WHERE e.rowid=(SELECT MIN(e2.rowid) FROM live_evaluations e2
                WHERE e2.prediction_id=p.id) ORDER BY p.target_date,p.issued_at''').fetchall()
        for m in self.repo.selected_mappings():
            if not m['approved']:
                continue
            code=m['district_code'];manager=self.service.manager(namespace)
            model=next((x for x in manager.list_models() if x['district_code']==code),None)
            if not model or model.get('status')!='ready' or model.get('feature_contract_id')!=m['contract_id']:
                continue
            version=str(model.get('model_version',model.get('version')))
            labelled={r['target_date']:dict(r) for r in reversed(rows)
                      if r['station_id']==m['station_id'] and str(r['model_version'])==version}
            if not labelled:
                continue
            ordered=[labelled[k] for k in sorted(labelled)];as_of=ordered[-1]['target_date'];sid=f'{namespace}:{code}'
            try:state=self.service.store.get('monitor',sid)
            except KeyError:state={'district_code':code,'version':version,'breaches':0,'candidate':None,'last_trigger':None}
            if state['version']!=version:
                state.update(version=version,breaches=0,candidate=None,last_trigger=None,last_processed_target_date='',rmse=None)
            pending=[r['target_date'] for r in ordered if r['target_date']>state.get('last_processed_target_date','')]
            all_ordered=ordered
            for as_of in pending:
                ordered=[r for r in all_ordered if r['target_date']<=as_of]
                previous=(date.fromisoformat(as_of)-timedelta(days=1)).isoformat()
                if state.get('last_processed_target_date')!=previous:state['breaches']=0
                state.update(last_processed_target_date=as_of,threshold=model.get('threshold'),feature_contract_id=m['contract_id'])
                event=job=None
                promoted=False
                if state.get('candidate'):
                    after=date.fromisoformat(state['candidate_as_of']);shadow_end=after+timedelta(days=30)
                    if date.fromisoformat(as_of)>=shadow_end:
                        try:
                            snap=self.repo.publish_snapshot(m['station_id'],m['version'],
                                (after-timedelta(days=19)).isoformat(),shadow_end.isoformat())
                            result=manager.evaluate_candidate(code,state['candidate'],snap['rows'])
                        except ValueError:
                            result=manager.reject_candidate(code,state['candidate'],'shadow_calendar_gap_or_unverified_data')
                        promoted=result['status']=='promoted'
                        if result['status']!='pending':
                            state.update(candidate=None,last_trigger=as_of,breaches=0)
                            event={'district_code':code,'kind':'model','namespace':namespace,
                                   'message':f"API 후보 평가: {result['status']}",'result':result}
                elif len(ordered)>=21:
                    window=ordered[-21:]
                    if all(date.fromisoformat(b['target_date'])-date.fromisoformat(a['target_date'])==timedelta(days=1)
                           for a,b in zip(window,window[1:])):
                        rmse=math.sqrt(sum(json.loads(r['evaluation'])['residual']**2 for r in window)/21)
                        threshold=model.get('threshold');state.update(rmse=rmse,as_of=as_of)
                        state['breaches']=state['breaches']+1 if threshold is not None and rmse>threshold else 0
                        cooldown=not state.get('last_trigger') or (date.fromisoformat(as_of)-date.fromisoformat(state['last_trigger'])).days>=21
                        if state['breaches']>=2 and cooldown:
                            try:
                                # Train through the latest completed day known now, never fabricate historical issuance.
                                end=today()-timedelta(days=1)
                                snap=self.repo.publish_snapshot(m['station_id'],m['version'],
                                    (end-timedelta(days=40)).isoformat(),end.isoformat())
                                event={'district_code':code,'kind':'quality','namespace':namespace,
                                    'message':f'API 21일 RMSE {rmse:.6g}: 재학습 요청','rmse':rmse,'threshold':threshold}
                                job=('fine_tune_live',{'snapshot_id':snap['id'],'namespace':namespace},f'model:{namespace}:{code}')
                                state['last_trigger']=as_of
                            except ValueError:
                                state['retrain_blocker']='연속41일 검증 자료가 없습니다.'
                self.service.store.commit_monitor(sid,state,event,job)
                if promoted:
                    break  # Reload the new champion before evaluating any remaining dates.
