"""Opt-in daily observed groundwater/rainfall ingestion for explicit registered mappings.

Never registers stations, approves mappings, trains models or fabricates rain.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time
from zoneinfo import ZoneInfo
from serving_app.national_repository import NationalRepository
from serving_app.national_sources import collect_kwater, join_daily
from serving_app.weather_worker import atomic_json
KST=ZoneInfo('Asia/Seoul')


def groundwater_provider(station_id, day, raw_dir):
    """Validate the exact authenticated APIR10 single-day response, preserving raw evidence."""
    result=collect_kwater(start=day,end=day,station_id=station_id,output_dir=raw_dir)
    pages=result['raw_pages']
    if len(pages)!=1:raise ValueError('unexpected_groundwater_pages')
    page=pages[0];raw=(Path(raw_dir)/page['file']).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=page['raw_sha256']:raise ValueError('groundwater_hash_mismatch')
    response=json.loads(raw)['response']
    if response['resultCode']!='Success' or len(response['resultData'])!=1:raise ValueError('groundwater_no_valid_day')
    item=response['resultData'][0]
    if item['gennum']!=station_id or item['ymd']!=day.replace('-',''):raise ValueError('groundwater_identity_mismatch')
    value=float(item['elev']);depth=float(item['lev'])
    if not math.isfinite(value) or not math.isfinite(depth):raise ValueError('groundwater_invalid_number')
    return dict(date=day,value=value,depth=depth,source_station_id=station_id,metric='groundwater_level',
        unit='m',datum='elevation',quality='valid',raw_sha256=digest,
        available_at=page['collected_at'],collected_at=page['collected_at'])


class NationalObservationCollector:
    def __init__(self, root=None, *, enabled=None, clock=None, fetch=None, repository=None):
        self.state_root=Path(root or os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
        self.root=self.state_root/'national'/'observation_collection'
        self.root.mkdir(parents=True,exist_ok=True)
        self.repo=repository or NationalRepository(self.state_root/'national'/'observations.sqlite3')
        self.enabled=(os.getenv('GROUNDWATCH_NATIONAL_OBSERVATION_COLLECTION_ENABLED','false').lower() in ('true','1','yes')) if enabled is None else enabled
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.fetch=fetch or groundwater_provider

    def state(self):
        path=self.root/'state.json'
        return json.loads(path.read_text()) if path.exists() else dict(schema_version=1,stations={})

    def _stations(self):
        cursor=None;selected=[]
        while True:
            page=self.repo.list_stations(cursor=cursor,limit=200)
            for s in page['items']:
                if (s.get('provider')=='kwater' and s.get('source_kind')=='observed'
                    and s.get('source_contract_verified') is True
                    and s.get('mapping_status') in ('experimental','approved')
                    and s.get('level_unit')=='m' and s.get('level_reference')=='elevation'
                    and str(s.get('source_station_id','')).isdigit()
                    and str(s.get('weather_source_station_id','')).isdigit()
                    and s.get('mapping_version')):
                    selected.append(s)
            cursor=page['next_cursor']
            if not cursor:return selected

    def _rain(self, station, day):
        path=self.state_root/'weather'/'archive'/'daily'/(day.replace('-','')+'.json')
        if not path.exists():path=self.state_root/'weather'/'national_aws_daily.json'
        if not path.exists():raise ValueError('completed_rainfall_missing')
        payload=json.loads(path.read_text())
        if (payload.get('unit')!='mm' or payload.get('provider')!='kma_ground_aws_daily'
            or payload.get('source_kind')!='observed' or payload.get('available_dates')!=[day]
            or payload.get('temporal_contract')!='completed_calendar_day_KST_rn_day'
            or payload.get('collection_status')!='collected' or not payload.get('raw_sha256')):
            raise ValueError('completed_rainfall_unverified')
        identifier='kma_ground_aws_daily:'+station['weather_source_station_id']
        rows=[r for r in payload['observations'] if r['station_id']==identifier and r['date']==day]
        if len(rows)!=1:raise ValueError('mapped_rainfall_missing_or_ambiguous')
        item=rows[0];value=item['rainfall_mm']
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value<0 or item['source_sha256']!=payload['raw_sha256']:
            raise ValueError('mapped_rainfall_invalid')
        return dict(date=day,value=value,metric='rainfall_mm',unit='mm',datum='precipitation',quality='valid',
            raw_sha256=item['source_sha256'],available_at=item['available_at'],collected_at=payload['collected_at'])

    def _level(self, station, day):
        # A successful supplier response is persisted before DB insertion, so
        # retries/restarts never re-fetch an already acquired station/day.
        cache=self.root/'validated'/station['source_station_id']/(day+'.json')
        cached=cache.exists()
        if cached:value=json.loads(cache.read_text())
        else:value=self.fetch(station['source_station_id'],day,self.root/'raw'/station['source_station_id'])
        if (value.get('source_station_id')!=station['source_station_id'] or value.get('date')!=day
            or value.get('metric')!='groundwater_level' or value.get('unit')!='m' or value.get('datum')!='elevation'
            or value.get('quality')!='valid' or not value.get('raw_sha256')
            or isinstance(value.get('value'),bool) or not isinstance(value.get('value'),(float,int))
            or not math.isfinite(value['value'])):raise ValueError('groundwater_contract_mismatch')
        if not cached:atomic_json(cache,value)
        return value

    def tick(self):
        import fcntl
        instant=self.clock()
        if instant.tzinfo is None:raise ValueError('timezone_aware_clock_required')
        instant=instant.astimezone(KST)
        with (self.root/'collector.lock').open('a') as lock:
            try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return dict(status='busy')
            state=self.state();state.update(checked_at=instant.isoformat(),enabled=bool(self.enabled))
            if not self.enabled:state.update(status='disabled',reason='collection_opt_in_required')
            elif (instant.hour,instant.minute)<(11,30):state.update(status='waiting',reason='daily_collection_after_1130_KST')
            elif not os.getenv('GIMS_API_KEY','').strip():state.update(status='blocked',reason='credentials_required')
            else:
                stations=self._stations();outcomes=[];day=(instant.date()-timedelta(days=1)).isoformat()
                for station in stations:
                    checkpoint=state.setdefault('stations',{}).setdefault(station['station_id'],{})
                    if checkpoint.get('completed_day')==day:outcomes.append('up_to_date');continue
                    last=checkpoint.get('attempted_at')
                    if last and (instant-datetime.fromisoformat(last)).total_seconds()<600:outcomes.append('backoff');continue
                    checkpoint.update(attempted_at=instant.isoformat(),attempted_day=day,status='collecting')
                    atomic_json(self.root/'state.json',state)
                    try:
                        rain=self._rain(station,day)
                        level=self._level(station,day)
                        joined=join_daily([level],[rain],station_id=station['station_id'])
                        if len(joined['accepted'])!=1:raise ValueError('invalid_daily_pair')
                        row=joined['accepted'][0]
                        row.update(mapping_id=station.get('mapping_id'),mapping_version=station['mapping_version'],source_kind='observed')
                        self.repo.add_observations(station['station_id'],[row])
                        checkpoint.update(status='ready',completed_day=day,last_good_day=day,
                            last_good_collected_at=row['collected_at'],last_good_revision_id=row['revision_id'])
                        checkpoint.pop('reason',None);outcomes.append('ready')
                    except Exception:
                        # Supplier exceptions may contain a credential-bearing URL.
                        # Persist only a fixed code; never stringify the exception.
                        checkpoint.update(status='blocked',reason='source_or_join_unavailable')
                        outcomes.append('blocked')
                    atomic_json(self.root/'state.json',state)
                state.update(status='blocked' if not stations else ('degraded' if 'blocked' in outcomes else 'ready'),
                    reason='no_explicit_registered_mapping' if not stations else None,target_day=day)
            atomic_json(self.root/'state.json',state)
            return state


def main():
    collector=NationalObservationCollector();stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopping:
        try:collector.tick()
        except Exception:
            # Keep the process alive on local transient errors, without secret-bearing diagnostics.
            pass
        for _ in range(30):
            if stopping:break
            time.sleep(1)

if __name__=='__main__':main()
