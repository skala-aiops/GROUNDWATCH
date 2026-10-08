"""Read-only observed weather catalogue, separate from groundwater model readiness."""
from datetime import date as Date
from pathlib import Path
import csv
import json
import math
import gzip
from copy import deepcopy
from functools import lru_cache

DATA = Path(__file__).resolve().parents[1] / 'data'

@lru_cache(maxsize=2)
def _read_artifact(path, modified_ns, size):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)

class RainfallNetwork:
    def __init__(self, path=None, additional_path=None):
        self.path = Path(path or DATA / 'national_rainfall.json')
        self.additional_path = Path(additional_path) if additional_path else None

    def load(self):
        if not self.path.exists():
            raise ValueError('전국 강수 자료가 아직 확보되지 않았습니다.')
        stat = self.path.stat()
        data = deepcopy(_read_artifact(str(self.path), stat.st_mtime_ns, stat.st_size))
        if self.additional_path and self.additional_path.exists() and self.additional_path != self.path:
            extra = RainfallNetwork(self.additional_path).load()
            days = set(extra['available_dates'])
            metadata = dict(data.get('station_metadata_by_date', {}))
            metadata.update(extra.get('station_metadata_by_date', {day:extra['stations'] for day in days}))
            union = {s['station_id']:s for s in data['stations']}
            union.update({s['station_id']:s for s in extra['stations']})
            data = {**data, 'stations':list(union.values()), 'station_metadata_by_date':metadata,
                'observations':[r for r in data['observations'] if r['date'] not in days]+extra['observations'],
                'available_dates':sorted(set(data['available_dates'])|days),
                'collected_at':max(data['collected_at'],extra['collected_at'])}
        if data.get('unit') != 'mm' or data.get('source_kind') != 'observed':
            raise ValueError('강수 자료의 단위·출처 확인이 필요합니다.')
        return data

    def network(self, day=None):
        data = self.load()
        dates = data['available_dates']
        if not dates:
            raise ValueError('조회 가능한 관측 날짜가 없습니다.')
        day = day or dates[-1]
        if day not in dates:
            raise LookupError('확보하지 않은 관측 날짜입니다.')
        by_id = {r['station_id']: r for r in data['observations'] if r['date'] == day}
        stations = []
        for meta in data.get('station_metadata_by_date', {}).get(day, data['stations']):
            record = by_id.get(meta['station_id'], {})
            value = record.get('rainfall_mm')
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError('유효하지 않은 강수 자료입니다.')
            stations.append({**meta, 'rainfall_mm': value,
                'quality_status': 'observed' if value is not None else 'missing',
                'groundwater_station_id': None, 'model_ready': False})
        periods = []
        source = DATA / 'rainy_seasons_kma.csv'
        if source.exists():
            with source.open() as stream:
                for row in csv.DictReader(stream):
                    if int(row['year']) == Date.fromisoformat(day).year:
                        periods.append({'year':int(row['year']), 'region':row['region'],
                            'start_date':row['start_date'], 'end_date':row['end_date'],
                            'source_url':'https://data.kma.go.kr/climate/rainySeason/selectRainySeasonList.do'})
        observed = sum(s['rainfall_mm'] is not None for s in stations)
        return {'date':day, 'available_dates':dates, 'source':data['source'],
            'source_url':data['source_url'], 'collected_at':data['collected_at'],
            'latest_observed_date':max((r['date'] for r in data['observations']), default=None), 'latest_available_date':dates[-1], 'unit':'mm', 'source_kind':'observed',
            'scope_note':data.get('scope_note', '확보된 기상 관측지점의 일강수량입니다. 지점 사이의 강수나 전국 면적 평균이 아닙니다. 빈 원천값은 0으로 채우지 않았습니다.'),
            'counts':{'stations':len(stations),'observed':observed,'missing':len(stations)-observed,
                'zero':sum(s['rainfall_mm'] == 0 for s in stations)},
            'stations':stations, 'rainy_periods':periods,
            'boundaries_url':'/api/v2/rainfall/boundary',
            'boundary_source':'Natural Earth 1:50m · 위치 참고용, 공식 행정경계 아님',
            'collection_status':data.get('collection_status','snapshot')}

    def history(self, station_id):
        data=self.load()
        station=next((s for s in data['stations'] if s['station_id']==station_id),None)
        if not station:
            raise KeyError(station_id)
        records={r['date']:r for r in data['observations'] if r['station_id']==station_id}
        history=[]
        for day in data['available_dates']:
            value=records.get(day,{}).get('rainfall_mm')
            history.append({'date':day,'rainfall_mm':value,
                'quality_status':'observed' if value is not None else 'missing'})
        return {'station_id':station_id,'station':station,'history':history,
            'source_url':data['source_url'],'collected_at':data['collected_at'],'unit':'mm'}
