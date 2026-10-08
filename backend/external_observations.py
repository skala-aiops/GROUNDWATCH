"""공식 API 원본 수집. 출처/단위 검증 전에는 기존 학습 자료를 교체하지 않습니다."""
from __future__ import annotations
import hashlib
import json
import math
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo
import requests
from backend.groundwater_store import Store, now

SEOUL_URL = 'http://openapi.seoul.go.kr:8088'
KMA_URL = 'https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList'

class SourceError(Exception):
    """Only safe, fixed error messages may cross the API boundary."""

class OfficialClient:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def _json(self, source, url, params=None):
        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=(5, 20), allow_redirects=False)
            except requests.RequestException:
                if attempt < 2:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                raise SourceError(f'{source}: 연결 실패 또는 응답 시간 초과') from None
            if response.status_code in (429, 403, 401):
                raise SourceError(f'{source}: HTTP {response.status_code}; 인증·활용승인·호출한도를 확인하세요.')
            if response.status_code >= 500 and attempt < 2:
                import time
                time.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                raise SourceError(f'{source}: HTTP {response.status_code}')
            try:
                result = response.json()
            except ValueError:
                # 인증 오류는 XML로 반환될 수 있으며 원문/URL에 키가 포함될 수 있습니다.
                raise SourceError(f'{source}: JSON 응답 아님; 인증·서비스 상태를 확인하세요.') from None
            if not isinstance(result, dict):
                raise SourceError(f'{source}: 응답 형식 오류')
            return result
        raise SourceError(f'{source}: 수집 실패')

    def seoul_page(self, start, end, station_name='', observed_date=''):
        key = os.getenv('SEOUL_OPEN_DATA_KEY', '').strip()
        if not key or key == 'sample':
            raise SourceError('seoul: 실제 SEOUL_OPEN_DATA_KEY가 필요합니다.')
        url = f'{SEOUL_URL}/{quote(key, safe="")}/json/VTsSec/{start}/{end}/'
        if station_name or observed_date:
            url += quote(station_name or ' ', safe='') + '/'
        if observed_date:
            url += quote(observed_date, safe='')
        data = self._json('seoul', url)
        body = data.get('VTsSec', data)
        code = body.get('RESULT', {}).get('CODE')
        if code not in ('INFO-000', 'INFO-200'):
            # Do not echo provider messages which may include the requested key.
            raise SourceError('seoul: 공급자 오류; 인증·요청 조건을 확인하세요.')
        rows = body.get('row', [])
        if not isinstance(rows, list):
            raise SourceError('seoul: row 형식 오류')
        return data, rows, int(body.get('list_total_count', 0))

    def kma_page(self, start, end, station_id, page):
        key = os.getenv('KMA_ASOS_SERVICE_KEY', '').strip()
        if not key:
            raise SourceError('kma: KMA_ASOS_SERVICE_KEY가 필요합니다.')
        data = self._json('kma', KMA_URL, {'ServiceKey':unquote(key), 'dataType':'JSON',
            'dataCd':'ASOS', 'dateCd':'DAY', 'startDt':start.replace('-',''),
            'endDt':end.replace('-',''), 'stnIds':station_id, 'pageNo':page, 'numOfRows':100})
        response = data.get('response', {})
        if str(response.get('header', {}).get('resultCode')) != '00':
            raise SourceError('kma: 공급자 오류; 활용승인·인증·요청 조건을 확인하세요.')
        body = response.get('body', {})
        items = body.get('items') or {}
        rows = items.get('item', []) if isinstance(items, dict) else []
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise SourceError('kma: item 형식 오류')
        return data, rows, int(body.get('totalCount', 0))


def valid_rows(rows, source, start, end, station, today=None):
    """Keep provenance separate; ambiguous/conflicting observations are quarantined."""
    today = today or datetime.now(ZoneInfo('Asia/Seoul')).date()
    accepted, quarantined, groups = [], [], {}
    for row in rows:
        try:
            raw_day = row['OBSRVN_YMD'] if source == 'seoul' else row['tm']
            day = datetime.strptime(str(raw_day), '%Y%m%d' if source == 'seoul' else '%Y-%m-%d').date()
            if day >= today:
                raise ValueError('future_or_unfinished_day')
            if not date.fromisoformat(start) <= day <= date.fromisoformat(end):
                raise ValueError('outside_requested_range')
            identity = str(row['OBSVTR_NM'] if source == 'seoul' else row['stnId'])
            if identity != station:
                raise ValueError('station_mismatch')
            raw = row.get('UDGD_WATL' if source == 'seoul' else 'sumRn')
            if raw is None or raw == '':
                raise ValueError('missing_value')
            value = float(raw)
            if not math.isfinite(value) or source == 'kma' and value < 0:
                raise ValueError('invalid_value')
            item = {'source':source, 'source_station':identity, 'date':day.isoformat(), 'value':value}
            groups.setdefault(day.isoformat(), []).append(item)
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            reason = str(exc) if str(exc) in ('future_or_unfinished_day','outside_requested_range','station_mismatch','missing_value','invalid_value') else 'invalid_schema_or_date'
            quarantined.append({'reason':reason,'row':row})
    for items in groups.values():
        if len({x['value'] for x in items}) > 1:
            quarantined.extend({'reason':'conflicting_observation','row':x} for x in items)
        else:
            accepted.append(items[0])
    return sorted(accepted, key=lambda x:x['date']), quarantined


class ExternalObservations:
    def __init__(self, root, client=None):
        self.root = Path(root) / 'external'
        self.root.mkdir(parents=True, exist_ok=True)
        # Separate queue: training worker must never claim network collection jobs.
        self.store = Store(self.root / 'ingestions.sqlite3')
        from backend.observation_repository import ObservationRepository
        self.observations = ObservationRepository(self.root / 'observations.sqlite3')
        self.client = client or OfficialClient()
        self.import_saved_collections()

    def import_saved_collections(self):
        for job in self.store.jobs():
            for source,result in (job.get('result') or {}).get('sources',{}).items():
                path=self.root/job['id']/f'{source}-validated.json'
                if source not in ('seoul','kma') or not path.exists():
                    continue
                saved=json.loads(path.read_text());p=job['payload']
                station=p['seoul_station'] if source=='seoul' else p['weather_station']
                self.observations.record_collection(job['id'],source,station,p['start_date'],p['end_date'],
                    result,saved['accepted'],saved['quarantined'],result['raw_sha256'])

    def status(self, live_service=None):
        jobs = self.store.jobs()
        try:
            worker = self.store.get('worker', 'external')
        except KeyError:
            worker = None
        with self.observations.connect() as db:
            timing = {source:{
                'last_success_at':db.execute("SELECT MAX(collected_at) FROM collection_runs WHERE source=? AND status='collected'",(source,)).fetchone()[0],
                'last_failure_at':db.execute("SELECT MAX(collected_at) FROM collection_runs WHERE source=? AND status='failed'",(source,)).fetchone()[0]
            } for source in ('seoul','kma')}
        publication = live_service.publication_status() if live_service else None
        return {'sources':{
            'seoul':{'configured':bool(os.getenv('SEOUL_OPEN_DATA_KEY')),'service':'VTsSec',
                     'transport':'HTTP (official endpoint; TLS not verified)'},
            'kma':{'configured':bool(os.getenv('KMA_ASOS_SERVICE_KEY')),'service':'ASOS DAY','available_until':'D-1'}},
            'jobs':jobs[:20], 'observation_store':self.observations.summary(),
            'forecast_integration':publication,
            'collection':{'enabled':os.getenv('GROUNDWATCH_COLLECTION_ENABLED','false').lower()=='true',
                          'timezone':'Asia/Seoul','schedule_hour':10,'lookback_days':7,
                          'input_until':'D-1','worker':worker,'timing':timing},
            'note':'수집 성공과 예측 자료 적용은 다릅니다. 기존 CSV·모델은 유지합니다.'}

    def enqueue(self, start, end, seoul_station, weather_station, shared_weather_day=None):
        a,b = date.fromisoformat(start),date.fromisoformat(end)
        today = datetime.now(ZoneInfo('Asia/Seoul')).date()
        if b < a or b >= today or (b-a).days > 30:
            raise ValueError('전일까지의 최대 31일 기간만 수집할 수 있습니다.')
        if not seoul_station.strip() or len(seoul_station) > 100 or not weather_station.isdigit():
            raise ValueError('서울시 관측소 이름과 기상청 지점 번호를 확인하세요.')
        payload={'start_date':start,'end_date':end,'seoul_station':seoul_station.strip(),
                 'weather_station':weather_station}
        if shared_weather_day:
            payload['shared_weather_day']=shared_weather_day
        scope='ingest:'+hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        try:
            return self.store.enqueue('collect',payload,scope)
        except (sqlite3.IntegrityError, ValueError):
            raise ValueError('동일 범위 수집 작업이 이미 대기·실행 중입니다.') from None

    def _save_raw(self, folder, source, page, data):
        content = json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        # Defensive redaction: error payloads never reach here; still remove echoed keys.
        for name in ('SEOUL_OPEN_DATA_KEY','KMA_ASOS_SERVICE_KEY'):
            key=os.getenv(name,'')
            if key:
                content=content.replace(key.encode(),b'[REDACTED]').replace(unquote(key).encode(),b'[REDACTED]')
        target=folder/f'{source}-{page}.json'
        target.write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    def execute_one(self):
        job=self.store.claim('collect')
        if not job:
            return False
        payload=job['payload'];folder=self.root/job['id'];folder.mkdir(exist_ok=True)
        result={'sources':{},'applied_to_forecasts':False,'collected_at':now(),
                'integration_blockers':['서울시 API 관측소 ID·수위 단위 대조','강수 관측소 매핑 승인','API 강수로 모델 학습·평가']}
        for source in ('seoul','kma'):
            rows,hashes,error,total=[],[],None,0
            shared_key=None
            if source=='kma' and payload.get('shared_weather_day'):
                shared_key='kma:'+fingerprint_request(payload)
                try:
                    shared=self.store.get('weather_collection',shared_key)
                    result['sources'][source]={**shared['result'],'shared_collection_job_id':shared['job_id']}
                    self.store.progress(job['id'],result)
                    continue
                except KeyError:
                    pass
            try:
                # Bounds protect quota and prevent endless changing pagination.
                for page in range(1,11):
                    if source == 'seoul':
                        data,items,count=self.client.seoul_page((page-1)*1000+1,page*1000,
                            payload['seoul_station'])
                    else:
                        data,items,count=self.client.kma_page(payload['start_date'],payload['end_date'],
                            payload['weather_station'],page)
                    if page > 1 and count != total:
                        raise SourceError(f'{source}: 수집 중 총 건수 변경; 다시 수집해야 합니다.')
                    total=count;hashes.append(self._save_raw(folder,source,page,data));rows.extend(items)
                    size=1000 if source=='seoul' else 100
                    expected=max(0,min(size,total-(page-1)*size))
                    if len(items)!=expected:
                        raise SourceError(f'{source}: 페이지 건수 불일치')
                    if len(rows)>=total:
                        break
                    if not items:
                        raise SourceError(f'{source}: 페이지 누락')
                else:
                    raise SourceError(f'{source}: 안전한 페이지 수 제한 초과; 조회 범위를 줄이세요.')
            except SourceError as exc:
                error=str(exc)
            except Exception:
                error=f'{source}: 수집 처리 실패 (민감정보 보호를 위해 원문 생략)'
            station=payload['seoul_station'] if source=='seoul' else payload['weather_station']
            accepted,rejected=valid_rows(rows,source,payload['start_date'],payload['end_date'],station)
            (folder/f'{source}-validated.json').write_text(json.dumps({'accepted':accepted,'quarantined':rejected},ensure_ascii=False))
            result['sources'][source]={'status':'failed' if error else 'empty' if not accepted else 'collected',
                'error':error,'received_rows':len(rows),'accepted_rows':len(accepted),'quarantined_rows':len(rejected),
                'latest_observed_date':accepted[-1]['date'] if accepted else None,
                'pages':len(hashes),'raw_sha256':hashes,'complete':error is None}
            self.observations.record_collection(job['id'],source,station,payload['start_date'],payload['end_date'],
                result['sources'][source],accepted,rejected,hashes)
            if shared_key and error is None:
                self.store.put('weather_collection',{'job_id':job['id'],'result':result['sources'][source]},shared_key)
            self.store.progress(job['id'],result)
        failed=[x for x in result['sources'].values() if x['status']=='failed']
        result['collection_status']='failed' if len(failed)==2 else 'partial' if failed else 'completed'
        self.store.finish(job['id'],result,error='공급자 수집 실패; 소스별 결과를 확인하세요.' if failed else None)
        return True

    def retry(self, job_id):
        job=self.store.job(job_id)
        if job['status'] not in ('failed','interrupted'):
            raise ValueError('실패·중단한 수집만 재시도할 수 있습니다.')
        p=job['payload']
        return self.enqueue(p['start_date'],p['end_date'],p['seoul_station'],p['weather_station'])

    def schedule_due(self):
        """Only verified mappings are eligible; persist day checkpoint across restarts."""
        moment=datetime.now(ZoneInfo('Asia/Seoul'))
        if os.getenv('GROUNDWATCH_COLLECTION_ENABLED','false').lower()!='true' or moment.hour<10:
            return {'status':'disabled_or_before_schedule'}
        day=moment.date().isoformat()
        mappings=self.observations.selected_mappings()
        if not mappings:
            return {'status':'blocked_mapping_required'}
        result=[]
        for m in mappings:
            checkpoint=f"schedule:{day}:{m['version']}:{m['station_id']}"
            try:
                self.store.get('schedule',checkpoint)
                continue
            except KeyError:
                pass
            end=(moment.date()-timedelta(days=1)).isoformat()
            start=(moment.date()-timedelta(days=7)).isoformat()
            job=self.enqueue(start,end,m['seoul_name'],m['weather_station'],day)
            self.store.put('schedule',{'job_id':job['id'],'date':day},checkpoint)
            result.append(job['id'])
        return {'status':'scheduled','jobs':result}


def fingerprint_request(payload):
    return hashlib.sha256(json.dumps({k:payload[k] for k in
        ('shared_weather_day','weather_station','start_date','end_date')},sort_keys=True).encode()).hexdigest()
