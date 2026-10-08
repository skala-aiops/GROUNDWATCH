"""Collect the provider's actual available observations independently of model mappings.

VTsSec's positional station filter currently returns no rows for names present in
the unfiltered feed. Scan a bounded, date-ordered prefix once for all stations.
Raw API water values are never converted to the historical model's gl.-m input.
"""
import json
import math
import os
from urllib.parse import unquote
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from serving_app.external_observations import OfficialClient, SourceError, valid_rows
from serving_app.groundwater_store import now


class ApiObservationFeed:
    def __init__(self, root, client=None):
        self.folder = Path(root) / 'external' / 'feed'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.client = client or OfficialClient()
        self.stations = json.loads((Path(__file__).parents[1] / 'data/representatives.json').read_text())['stations']

    def read(self):
        path = self.folder / 'latest.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def save_raw(self, path, data):
        content = json.dumps(data, ensure_ascii=False)
        for name in ('SEOUL_OPEN_DATA_KEY', 'KMA_ASOS_SERVICE_KEY'):
            key = os.getenv(name, '')
            if key:
                content = content.replace(key, '[REDACTED]').replace(unquote(key), '[REDACTED]')
        path.write_text(content)

    def refresh(self, max_pages=40, lookback_days=90):
        if not 20 <= lookback_days <= 730:
            raise ValueError('lookback_days must be between20 and730')
        today = datetime.now(ZoneInfo('Asia/Seoul')).date()
        checked = now()
        prior = self.read()
        state = {**prior, 'checked_at': checked, 'check_date': today.isoformat(), 'errors': {}}
        raw_folder = self.folder / today.isoformat()
        raw_folder.mkdir(exist_ok=True)
        try:
            rows, previous, latest, total = [], None, None, None
            future = invalid = 0
            for page in range(1, max_pages + 1):
                data, items, count = self.client.seoul_page((page-1)*1000+1, page*1000)
                if total is not None and count != total:
                    raise SourceError('seoul: 수집 중 총 건수가 변경되었습니다.')
                total = count
                if len(items) != min(1000, max(0, total-(page-1)*1000)):
                    raise SourceError('seoul: 페이지 건수 불일치')
                self.save_raw(raw_folder / f'seoul-{page}.json', data)
                reached = False
                for row in items:
                    try:
                        day = datetime.strptime(str(row['OBSRVN_YMD']), '%Y%m%d').date()
                        value = float(row['UDGD_WATL'])
                        if not math.isfinite(value) or not row.get('OBSVTR_NM'):
                            raise ValueError()
                    except (ValueError, TypeError, KeyError):
                        invalid += 1
                        continue
                    if day >= today:
                        future += 1
                        continue
                    if previous is not None and day > previous:
                        raise SourceError('seoul: 날짜 정렬이 달라져 수집 범위를 보장할 수 없습니다.')
                    previous = day
                    latest = latest or day
                    if day < latest - timedelta(days=lookback_days-1):
                        reached = True
                        continue
                    rows.append(row)
                if reached or page*1000 >= total:
                    break
            else:
                raise SourceError('seoul: 페이지 제한 안에 요청 기간을 확보하지 못했습니다.')
            if not latest:
                raise SourceError('seoul: 유효한 과거 관측이 없습니다.')
            start = (latest - timedelta(days=lookback_days-1)).isoformat()
            grouped = {}
            for station in self.stations:
                name = station.get('source_station_name', station['station_name'])
                matched = [r for r in rows if r['OBSVTR_NM'] == name]
                accepted, rejected = valid_rows(matched, 'seoul', start, latest.isoformat(), name, today)
                grouped[station['district_code']] = {'rows': accepted, 'quarantined': len(rejected)}
            state.update(water=grouped, water_latest=latest.isoformat(), water_collected_at=checked,
                         water_pages=page, water_received_rows=len(rows), future_rows=future,
                         invalid_rows=invalid, provider_total=total, water_lookback_days=lookback_days)
        except SourceError as exc:
            state['errors']['seoul'] = str(exc)
        start = state.get('water_latest')
        if start:
            from datetime import date
            start = (date.fromisoformat(start)-timedelta(days=state.get('water_lookback_days',90)-1)).isoformat()
            end = (today-timedelta(days=1)).isoformat()
            try:
                rows, total = [], None
                for page in range(1, 11):
                    data, items, count = self.client.kma_page(start, end, '108', page)
                    if total is not None and total != count:
                        raise SourceError('kma: 수집 중 총 건수가 변경되었습니다.')
                    total = count
                    if len(items) != min(100, max(0, total-(page-1)*100)):
                        raise SourceError('kma: 페이지 건수 불일치')
                    self.save_raw(raw_folder / f'kma-{page}.json', data)
                    rows.extend(items)
                    if page*100 >= total:
                        break
                else:
                    raise SourceError('kma: 페이지 제한 초과')
                rain, rejected = valid_rows(rows, 'kma', start, end, '108', today)
                state.update(rain=rain, rain_collected_at=checked, rain_received_rows=len(rows),
                             rain_quarantined=len(rejected), rain_latest=rain[-1]['date'] if rain else None)
            except SourceError as exc:
                state['errors']['kma'] = str(exc)
        temp = self.folder / 'latest.tmp'
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n')
        temp.replace(self.folder / 'latest.json')
        return state

    def refresh_if_due(self):
        moment = datetime.now(ZoneInfo('Asia/Seoul'))
        prior = self.read()
        retry = bool(prior.get('errors')) and (moment-datetime.fromisoformat(prior['checked_at'])).total_seconds() >= 3600
        backfill = prior.get('water_lookback_days',90) < 365 and not prior.get('errors')
        if moment.hour >= 10 and (prior.get('check_date') != moment.date().isoformat() or retry or backfill):
            return self.refresh(max_pages=120, lookback_days=365)
        return prior

    def history(self, code, state=None):
        state = self.read() if state is None else state
        rain = {r['date']:r['value'] for r in state.get('rain', [])}
        water = state.get('water', {}).get(code, {}).get('rows', [])
        result = {'unit':'API 원값', 'source_kind':'observed_api', 'history':[
            {'date':r['date'], 'groundwater_level':r['value'], 'rainfall_mm':rain.get(r['date']),
             'source_kind':'observed_api', 'prediction':None, 'predictions':[]} for r in water],
            'note':'서울시 API 원값. 기존 gl.-m와 기준 대조 전이며 ASOS 108 강수는 서울 공통 참고 지점입니다.'}
        return result

    def prediction_history(self, code):
        from serving_app.api_feed_models import ApiFeedTraining, input_hash
        result = self.history(code)
        model = ApiFeedTraining(self.folder.parents[1]).read().get('stations', {}).get(code, {})
        if model.get('status') == 'ready' and model.get('input_hash') == input_hash(result['history']):
            backtest = {row['date']:row for row in model.get('backtest', [])}
            for row in result['history']:
                if row['date'] in backtest:
                    row.update(prediction=backtest[row['date']]['prediction'],
                               prediction_kind='held_out_test',prediction_model_version=model['model_version'])
            result['history'].append({'date':model['forecast_date'], 'groundwater_level':None,
                                      'rainfall_mm':None, 'prediction':model['prediction'],
                                      'prediction_kind':'next_available_day',
                                      'prediction_model_version':model['model_version'], 'predictions':[]})
            result.update(model_version=model['model_version'],metrics=model['metrics'],splits=model['splits'],
                          note='API 원값 모델. 시험 구간 예측과 최신 가용 관측 다음 날 예측을 표시합니다. 강수 원본 결측은 보존합니다.')
        return result

    @staticmethod
    def input_readiness(history):
        """Count complete calendar windows without filling or skipping missing days."""
        longest = current = complete = 0
        previous = None
        for row in sorted(history, key=lambda item: item['date']):
            day = date.fromisoformat(row['date'])
            values = (row.get('groundwater_level'), row.get('rainfall_mm'))
            valid = all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)
            if valid:
                complete += 1
                current = current + 1 if previous is not None and day == previous + timedelta(days=1) else 1
                longest = max(longest, current)
            else:
                current = 0
            previous = day
        return {'required_days':20, 'complete_days':complete,
                'longest_consecutive_days':longest, 'latest_consecutive_days':current,
                'missing_rain_days':sum(row.get('rainfall_mm') is None for row in history),
                'latest_window_complete':current >= 20,
                'model_contract_verified':False}

    def overview(self):
        state = self.read()
        from serving_app.api_feed_models import ApiFeedTraining, input_hash
        models = ApiFeedTraining(self.folder.parents[1]).read()
        rows = []
        for station in self.stations:
            history = self.history(station['district_code'], state)['history']
            last = history[-1] if history else {}
            item = {**{k:station[k] for k in ('district_code','district_name','station_id','station_name')},
                'source_kind':'observed_api', 'unit':'API 원값', 'level_unit':None,
                'observed_date':last.get('date'), 'forecast_date':None, 'prediction':None,
                'model_version':None, 'quality_status':'unit_verification_required' if history else 'data_required',
                'latest_comparison':{'actual':last.get('groundwater_level'), 'prediction':None},
                'model_evaluation_status':'evaluation_pending', 'rainfall_mm':last.get('rainfall_mm'),
                'available_days':len(history), 'reason':'수위 기준·ASOS 입력 계약을 검증한 별도 모델 필요',
                'input_readiness':self.input_readiness(history),
                'data_source':{'kind':'observed_api','observed_through':last.get('date'),
                               'input_through':last.get('date'), 'collected_at':state.get('water_collected_at')}}
            model = models.get('stations', {}).get(station['district_code'], {})
            if model.get('input_hash') == input_hash(history):
                item['api_model'] = model
                if model.get('status') == 'ready':
                    item['input_readiness']['model_contract_verified'] = True
                    item.update({key:model[key] for key in ('prediction','model_version','forecast_date','issued_at')})
                    observed_prediction = next((p['prediction'] for p in model.get('backtest', []) if p['date']==last.get('date')), None)
                    item['latest_comparison']['prediction'] = observed_prediction
                    stale = model['forecast_date'] < datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
                    item.update(quality_status='stale_data' if stale else 'normal',
                                model_evaluation_status='evaluation_passed',
                                reason='최신 가용 관측 다음 날 예측입니다. 오늘 예측이 아닙니다.' if stale else '실제 API 관측으로 학습·예측했습니다.')
                else:
                    item.update(reason=model.get('reason','실제 API 모델 학습 중'),
                                quality_status='quality_rejected' if model.get('status')=='rejected' else model.get('status','pending'))
            rows.append(item)
        return {'mode':'api', 'source_kind':'observed_api', 'as_of':state.get('water_latest'),
                'ready_count':sum(r['prediction'] is not None for r in rows), 'observation_count':sum(r['observed_date'] is not None for r in rows),
                'total':25, 'forecasts':rows,
                'collection':{k:v for k,v in state.items() if k not in ('water','rain')},
                'training':{k:v for k,v in models.items() if k != 'stations'},
                'note':'API 원값으로 학습한 별도 모델입니다. 강수 결측은 원본에 보존하고 모델에는 학습 구간 중앙값과 결측 표시를 입력합니다. 예측 대상일을 확인하세요.'}
