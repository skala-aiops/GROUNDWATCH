"""Opt-in observed weather collection, separate from groundwater model jobs.

Completed daily rain and minute accumulations have separate artifacts. Provider
failure never replaces the last good file or creates synthetic observations.
"""
from __future__ import annotations

import json
import os
import signal
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.national_sources import (
    collect_aws_daily, collect_aws_snapshot, parse_aws_daily, parse_aws_snapshot,
)

KST = ZoneInfo('Asia/Seoul')


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def snapshot_provider(requested_at, raw_dir, metadata_path):
    fetched = collect_aws_snapshot(requested_at, output_dir=raw_dir)
    parsed = parse_aws_snapshot(fetched['path'], metadata_path, requested_at=requested_at)
    parsed['collected_at'] = fetched['collected_at']
    return parsed


def daily_provider(requested_date, raw_dir, metadata_path=None):
    fetched = collect_aws_daily(requested_date, output_dir=raw_dir)
    return parse_aws_daily(fetched['path'], requested_date=requested_date, collected_at=fetched['collected_at'])


class WeatherCollector:
    """Persistent single-host scheduler. Inject providers/clock for offline tests."""
    def __init__(self, root=None, *, enabled=None, metadata_path=None,
                 clock=None, snapshot_fetch=None, daily_fetch=None):
        state_root = Path(root or os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
        self.root = state_root/'weather'
        self.root.mkdir(parents=True, exist_ok=True)
        self.enabled = (os.getenv('GROUNDWATCH_WEATHER_COLLECTION_ENABLED','false').lower()
                        in ('true','1','yes')) if enabled is None else enabled
        self.metadata_path = Path(metadata_path or os.getenv('GROUNDWATCH_AWS_METADATA_PATH',
            str(Path(__file__).resolve().parents[1]/'data'/'kma_station_metadata.csv')))
        self.clock = clock or (lambda:datetime.now(timezone.utc))
        self.snapshot_fetch = snapshot_fetch or snapshot_provider
        self.daily_fetch = daily_fetch or daily_provider

    def state(self):
        path = self.root/'weather_state.json'
        return json.loads(path.read_text()) if path.exists() else {'schema_version':1,'streams':{}}

    def _validate(self, stream, payload, request):
        expected = ('minute_snapshot_accumulations_not_completed_daily_rainfall'
                    if stream == 'snapshot' else 'completed_calendar_day_KST_rn_day')
        if (payload.get('source_kind') != 'observed' or payload.get('unit') != 'mm' or
                payload.get('temporal_contract') != expected or not payload.get('observations') or
                not payload.get('raw_sha256')):
            raise ValueError('invalid_observed_weather_payload')
        if stream == 'snapshot':
            observed = datetime.fromisoformat(payload['observed_at'])
            if observed.tzinfo is None or observed.astimezone(KST).strftime('%Y%m%d%H%M') != request:
                raise ValueError('snapshot_timestamp_mismatch')
        elif payload.get('available_dates') != [datetime.strptime(request,'%Y%m%d').date().isoformat()]:
            raise ValueError('daily_date_mismatch')

    def tick(self):
        import fcntl
        instant = self.clock()
        if instant.tzinfo is None:
            raise ValueError('timezone-aware collector clock required')
        instant = instant.astimezone(KST)
        with (self.root/'collector.lock').open('a') as lock:
            try:
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                return {'status':'busy'}
            try:
                state = self.state()
                state.update(checked_at=instant.isoformat(),enabled=bool(self.enabled))
                if not self.enabled:
                    state.update(status='disabled',reason='collection_opt_in_required')
                    atomic_json(self.root/'weather_state.json',state)
                    return state
                if not os.getenv('KMA_APIHUB_KEY','').strip():
                    state.update(status='blocked',reason='credentials_required')
                    atomic_json(self.root/'weather_state.json',state)
                    return state
                # Ten-minute lag avoids querying an unfinished minute; the
                # ten-minute bucket also bounds refreshes after restarts.
                moment = instant-timedelta(minutes=10)
                moment = moment.replace(minute=(moment.minute//10)*10,second=0,microsecond=0)
                requests = [('snapshot',moment.strftime('%Y%m%d%H%M'),self.snapshot_fetch)]
                if (instant.hour,instant.minute) >= (11,30):
                    requests.append(('daily',(instant.date()-timedelta(days=1)).strftime('%Y%m%d'),self.daily_fetch))
                outcomes = []
                for stream, request, fetch in requests:
                    checkpoint = state.setdefault('streams',{}).setdefault(stream,{})
                    if checkpoint.get('completed_request') == request:
                        outcomes.append('up_to_date')
                        continue
                    last_attempt = checkpoint.get('attempted_at')
                    if last_attempt and (instant-datetime.fromisoformat(last_attempt)).total_seconds() < 600:
                        outcomes.append('backoff')
                        continue
                    if stream == 'snapshot' and not self.metadata_path.is_file():
                        checkpoint.update(status='blocked',reason='aws_station_metadata_required')
                        outcomes.append('blocked')
                        continue
                    checkpoint.update(attempted_at=instant.isoformat(),attempted_request=request,status='collecting')
                    # Save the attempt before contacting the supplier, so an
                    # interrupted process does not hammer the API on restart.
                    atomic_json(self.root/'weather_state.json',state)
                    try:
                        payload = fetch(request,self.root/'raw',self.metadata_path)
                        self._validate(stream,payload,request)
                        filename = 'national_aws_snapshot.json' if stream == 'snapshot' else 'national_aws_daily.json'
                        archive = self.root/'archive'/stream/(request+'.json')
                        atomic_json(archive,payload)
                        atomic_json(self.root/filename,payload)
                        checkpoint.update(status='collected',completed_request=request,
                            completed_at=instant.isoformat(),raw_sha256=payload['raw_sha256'],
                            artifact=filename,observations=len(payload['observations']))
                        checkpoint.pop('reason',None)
                        outcomes.append('collected')
                    except Exception:
                        checkpoint.update(status='failed',reason='weather_collection_or_validation_failed')
                        outcomes.append('failed')
                    atomic_json(self.root/'weather_state.json',state)
                degraded = any(checkpoint.get('status') in ('failed','blocked','collecting')
                               for checkpoint in state['streams'].values())
                state.update(status='degraded' if degraded else 'ready')
                state.pop('reason',None)
                atomic_json(self.root/'weather_state.json',state)
                return state
            finally:
                fcntl.flock(lock.fileno(),fcntl.LOCK_UN)


def main():
    collector = WeatherCollector()
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    while not stopping:
        collector.tick()
        # Frequent checks are local; provider calls have persistent 10-minute
        # cadence, daily completion checkpoints and failure backoff.
        for _ in range(30):
            if stopping:
                break
            time.sleep(1)


if __name__ == '__main__':
    main()
