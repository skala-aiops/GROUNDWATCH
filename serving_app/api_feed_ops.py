"""Native API model operations over immutable issued predictions and later labels."""
from datetime import date, timedelta
import json
import math
from pathlib import Path

from serving_app.api_feed_models import ApiModelManager, ApiFeedTraining, NAMESPACE, CONTRACT, input_hash
from serving_app.groundwater_models import _json
from serving_app.groundwater_store import now, encode


class ApiFeedOperations:
    def __init__(self, service, manager=None):
        self.service=service
        self.store=service.store
        self.root=Path(service.root)
        self.manager=manager

    def models(self):
        if self.manager is None:
            self.manager=ApiModelManager(self.root)
        return self.manager

    def insert_once(self,kind,identifier,body):
        body={**body,'id':identifier,'namespace':NAMESPACE}
        with self.store.connect() as db:
            return db.execute('INSERT OR IGNORE INTO objects VALUES(?,?,?)',
                              (kind,identifier,encode(body))).rowcount == 1

    def records(self,kind,code):
        with self.store.connect() as db:
            return [json.loads(r['body']) for r in db.execute(
                "SELECT body FROM objects WHERE kind=? AND json_extract(body,'$.namespace')=? AND json_extract(body,'$.district_code')=? ORDER BY rowid",
                (kind,NAMESPACE,code))]

    def state(self,code):
        try:return self.store.get('monitor',f'{NAMESPACE}:{code}')
        except KeyError:return {'district_code':code,'version':None,'breaches':0,'candidate':None,
                               'last_trigger':None,'last_processed_target_date':'','rmse':None}

    def enqueue_cycle(self):
        with self.store.connect() as db:
            active=db.execute("SELECT id FROM jobs WHERE kind='monitor_api_feed' AND status IN ('queued','running') LIMIT 1").fetchone()
        if active:return self.store.job(active['id'])
        try:return self.store.enqueue('monitor_api_feed',{'namespace':NAMESPACE},'api-feed-operations')
        except ValueError:return None

    def record_forecast(self,code,forecast,rows):
        if any(r['date']==forecast['forecast_date'] for r in rows):
            raise ValueError('forecast target already present in issuance snapshot')
        if forecast['forecast_date']!=(date.fromisoformat(rows[-1]['date'])+timedelta(days=1)).isoformat():
            raise ValueError('forecast target must follow last input')
        snapshot=self.models().save_observations(code,rows)
        if forecast['inference_snapshot_id']!=snapshot:
            raise ValueError('forecast input hash mismatch')
        identifier=input_hash([code,forecast['forecast_date'],forecast['model_version'],snapshot])
        value={k:v for k,v in forecast.items() if k not in ('backtest','splits','metrics')}
        return self.insert_once('api_forecast',identifier,{**value,'district_code':code,
                                'target_label_available_at_issuance':False})

    def evaluate_labels(self,code,rows,collected_at):
        actuals={r['date']:r for r in rows}
        count=0
        for prediction in self.records('api_forecast',code):
            actual=actuals.get(prediction['forecast_date'])
            if actual is None or collected_at <= prediction['issued_at']:
                continue
            # Neither held-out predictions nor labels present at issuance enter this ledger.
            if prediction.get('target_label_available_at_issuance') is not False:
                continue
            count += self.insert_once('api_evaluation',prediction['id'],{
                'district_code':code,'forecast_id':prediction['id'],'target_date':prediction['forecast_date'],
                'model_version':prediction['model_version'],'prediction':prediction['prediction'],
                'actual':actual['groundwater_level'],'residual':prediction['prediction']-actual['groundwater_level'],
                'actual_hash':input_hash(actual),'actual_available_at':collected_at,'evaluated_at':now(),
                'revision_policy':'first_received_label_for_decisions'})
        return count

    def monitor(self,code,station_id,rows):
        manager=self.models();current=manager.current_version(code)
        if current is None:return
        _,bundle,_=manager._loaded(code)
        state=self.state(code)
        if state['version'] != current:
            candidate=state.get('candidate')
            if candidate and candidate==current:
                # Recover a committed alias after interruption before monitor state commit.
                evaluation=manager._state(code)['versions'][current].get('shadow_result',{})
                if evaluation.get('gate_passed'):
                    state['last_evaluation']=manager.evaluate_actual_candidate(code,current,rows)
            state.update(version=current,breaches=0,candidate=None,rmse=None,feature_contract_id=CONTRACT)
        evaluations=self.records('api_evaluation',code)
        state.update(threshold=bundle['threshold'],feature_contract_id=CONTRACT)
        # First issued prediction of each model/date drives decisions. Corrections remain separate.
        labelled={}
        for evaluation in evaluations:
            if str(evaluation['model_version'])==current:
                labelled.setdefault(evaluation['target_date'],evaluation)
        pending=[d for d in sorted(labelled) if d>state.get('last_processed_target_date','')]
        for day in pending:
            previous=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
            if state.get('last_processed_target_date')!=previous:state['breaches']=0
            state.update(last_processed_target_date=day,threshold=bundle['threshold'],feature_contract_id=CONTRACT)
            event=job=None
            dates=[(date.fromisoformat(day)-timedelta(days=i)).isoformat() for i in range(20,-1,-1)]
            if all(d in labelled for d in dates):
                rmse=math.sqrt(sum(labelled[d]['residual']**2 for d in dates)/21)
                state.update(rmse=rmse,labelled_days=len(labelled))
                state['breaches']=state['breaches']+1 if rmse>bundle['threshold'] else 0
                cooldown=not state.get('last_trigger') or (date.fromisoformat(day)-date.fromisoformat(state['last_trigger'])).days>=21
                if state['breaches']>=2 and not state.get('candidate') and cooldown:
                    snapshot=manager.save_observations(code,rows)
                    trigger_id=input_hash([code,current,day])
                    job=('retrain_api_feed',{'namespace':NAMESPACE,'district_code':code,'station_id':station_id,
                          'station_snapshot_id':snapshot,'trigger_id':trigger_id,'parent_version':current},
                         f'model:{NAMESPACE}:{code}')
                    event={'district_code':code,'kind':'quality','namespace':NAMESPACE,
                           'message':f'실제 API 드리프트 감지: 21일 RMSE {rmse:.6g}, 연속2회 초과',
                           'rmse':rmse,'threshold':bundle['threshold']}
                    state['last_trigger']=day
            else:
                state.update(breaches=0,labelled_days=len(labelled),waiting_for='21 consecutive issued labels')
            self.store.commit_monitor(f'{NAMESPACE}:{code}',state,event,job)
        if not pending:
            # Persist a new champion identity without fabricating a processed target date.
            self.store.put('monitor',state,f'{NAMESPACE}:{code}')
        self.evaluate_pending(code,station_id,rows)

    def evaluate_pending(self,code,station_id,rows):
        state=self.state(code)
        if not state.get('candidate'):return
        manager=self.models()
        result=manager.evaluate_actual_candidate(code,state['candidate'],rows)
        if result['status']=='pending':
            state['candidate_evaluation']=result
            self.store.put('monitor',state,f'{NAMESPACE}:{code}')
            return
        candidate=state['candidate']
        event_id=input_hash(['candidate-evaluation',code,candidate])
        self.insert_once('event',event_id,{'district_code':code,'kind':'model','status':'RECORDED','created_at':now(),
                         'message':f"실제 API 후보 평가: {result['status']}",'result':result})
        state.update(candidate=None,last_evaluation=result,candidate_evaluation=None,breaches=0,
                     last_trigger=rows[-1]['date'])
        if result['status']=='promoted':
            state.update(version=str(result['model_version']),rmse=None)
            self.publish_current(code,station_id,rows)
        self.store.put('monitor',state,f'{NAMESPACE}:{code}')

    def cycle(self,feed):
        snapshot=feed.read()
        if not snapshot.get('water'):return {'status':'data_required'}
        results=[]
        cached=ApiFeedTraining(self.root).read().get('stations',{})
        for station in feed.stations:
            code=station['district_code'];rows=feed.history(code,snapshot)['history']
            if not rows:continue
            previous=cached.get(code,{})
            if previous.get('status')=='ready' and previous.get('input_hash')==input_hash(rows):
                self.record_forecast(code,previous,rows)
            self.evaluate_labels(code,rows,snapshot['water_collected_at'])
            try:
                self.monitor(code,station['station_id'],rows)
                current=self.models().current_version(code)
                if current is not None and current != previous.get('model_version'):
                    self.publish_current(code,station['station_id'],rows)
                results.append({'district_code':code,'status':'checked'})
            except (ValueError,RuntimeError,FileNotFoundError,KeyError) as error:
                self.store.put('api_ops_error',{'district_code':code,'checked_at':now(),'reason':str(error)},code)
                results.append({'district_code':code,'status':'blocked','reason':str(error)})
        return {'status':'checked','stations':results}

    def publish_current(self,code,station_id,rows):
        forecast=self.models().forecast_actual(code,station_id,rows)
        self.record_forecast(code,forecast,rows)
        path=self.root/'external'/'feed'/'models.json'
        cached=ApiFeedTraining(self.root).read()
        cached.setdefault('stations',{})[code]={'input_hash':input_hash(rows),'status':'ready',**forecast}
        cached['ready_count']=sum(r.get('status')=='ready' for r in cached['stations'].values())
        _json(path,cached)
        return forecast

    def execute_job(self,job):
        payload=job['payload'];code=payload['district_code'];manager=self.models()
        if job['kind']=='rollback_api_feed':
            result=manager.rollback(code,payload.get('version'))
            state=self.state(code);state.update(candidate=None,candidate_evaluation=None,breaches=0,
                 version=result['model_version'],rmse=None,last_evaluation={**result,'status':'rolled_back'})
            self.store.put('monitor',state,f'{NAMESPACE}:{code}')
            self.store.event(code,'model','실제 API 이전 검증 모델 복귀',NAMESPACE,reason=payload['reason'],result=result)
            from serving_app.api_observation_feed import ApiObservationFeed
            feed=ApiObservationFeed(self.root);station=next(s for s in feed.stations if s['district_code']==code)
            self.publish_current(code,station['station_id'],feed.history(code)['history'])
            return result
        if job['kind']!='retrain_api_feed':raise ValueError('unsupported native operation')
        if manager.current_version(code)!=payload['parent_version']:
            return {'status':'cancelled','reason':'champion_changed'}
        rows=manager.observations(code,payload['station_snapshot_id'])
        state=self.state(code)
        try:
            result=manager.create_candidate(code,rows,payload['trigger_id'])
            state.update(candidate=result['candidate_version'],candidate_as_of=result['candidate_as_of'],
                         candidate_job=job['id'],last_evaluation=None,candidate_evaluation={'status':'pending','count':0,'required':30})
            self.store.put('monitor',state,f'{NAMESPACE}:{code}')
            self.store.event(code,'model','실제 API 재학습 후보 생성; 학습 이후30일 정답 대기',NAMESPACE,result=result)
            return result
        except Exception:
            self.store.event(code,'model','실제 API 재학습 실패; 기존 모델 유지',NAMESPACE,job_id=job['id'])
            raise

    def pipeline(self,code):
        state=self.state(code)
        forecasts=self.records('api_forecast',code);evaluations=self.records('api_evaluation',code)
        with self.store.connect() as db:
            jobs=[self.store._job(r) for r in db.execute("SELECT * FROM jobs WHERE json_extract(payload,'$.namespace')=? AND json_extract(payload,'$.district_code')=? ORDER BY created_at DESC LIMIT 50",(NAMESPACE,code))]
        events=[e for e in self.store.list('event') if e.get('namespace')==NAMESPACE and e.get('district_code')==code]
        cached=ApiFeedTraining(self.root).read().get('stations',{}).get(code,{})
        latest=state.get('last_evaluation') or {}
        retrain=next((j for j in jobs if j['kind']=='retrain_api_feed'),{})
        stages=[{'key':'data','title':'실제 API 수집·입력 준비','status':'completed' if cached.get('status')=='ready' else 'pending',
                 'detail':f"최신 입력 {cached.get('input_end_date','미준비')} · 예측 대상 {cached.get('forecast_date','미준비')}"},
                {'key':'monitor','title':'발행 예측 오차 확인','status':'completed' if state.get('rmse') is not None else 'pending',
                 'detail':f"정답 확보 {len(evaluations)}건 · 연속21일 창 · 경보 기준 {state.get('threshold','모델 준비 중')}"},
                {'key':'drift','title':'드리프트 경보','status':'completed' if any(e['kind']=='quality' for e in events) else 'pending',
                 'detail':f"연속 초과 {state.get('breaches',0)}회 / 2회"},
                {'key':'retrain','title':'자동 재학습','status':retrain.get('status','pending'),
                 'detail':retrain.get('error') or (f"후보 v{state['candidate']}" if state.get('candidate') else '경보 후 자동 접수 · 실제41일 자료')},
                {'key':'evaluate','title':'새 모델 평가','status':latest.get('status','pending'),
                 'detail':f"후보 이후 정답 {(state.get('candidate_evaluation') or {}).get('count',0)}/30일 · 개선5% · 기존 오차110% 이내"},
                {'key':'promote','title':'모델 교체·기존 유지','status':'completed' if latest.get('status') in ('promoted','rolled_back') else 'rejected' if latest.get('status')=='rejected' else 'pending',
                 'detail':f"현재 모델 v{cached.get('model_version','미준비')}"},
                {'key':'serve','title':'실제 예측 발행','status':'completed' if cached.get('prediction') is not None else 'pending',
                 'detail':f"발행 {len(forecasts)}건 · 관측일·예측일·발행 시각 분리"}]
        versions=[]
        can_rollback=False
        path=self.root/'models'/NAMESPACE/f'{code}.json'
        if path.exists():
            model_state=json.loads(path.read_text())
            can_rollback=any(h['to'] and h['to']!=model_state['champion'] for h in model_state['history'])
            versions=[{'version':version,'kind':bundle['kind'],'trained_through':bundle['trained_through'],
                       'evaluation':bundle.get('shadow_result'),'current':version==model_state['champion']}
                      for version,bundle in model_state['versions'].items()]
        try:
            collection=json.loads((self.root/'external'/'feed'/'latest.json').read_text())
        except FileNotFoundError:collection={}
        if collection.get('errors'):
            stages[0].update(status='warning',detail='공급자 수집 실패 · 이전 정상 자료와 모델 유지')
        return {'namespace':NAMESPACE,'district_code':code,'stages':stages,'monitor':state,'evaluation':latest,
                'candidate':state.get('candidate'),'versions':versions,'jobs':jobs,'events':events,
                'can_rollback':can_rollback,'source_errors':collection.get('errors',{}),
                'issued_count':len(forecasts),'evaluated_count':len(evaluations),
                'policy':{'window_days':21,'consecutive_breaches':2,'retrain_days':41,'shadow_days':30,
                          'minimum_improvement':.05,'historical_limit':1.10,
                          'label_policy':'first_received_after_issuance','forecast_timing':'latest_available_next_day'},
                'note':'시험 구간 예측은 감시에서 제외합니다. 발행 당시 미수신 정답이 새 API 수집에 들어와야 진행합니다.'}
