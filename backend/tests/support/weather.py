"""Offline provider fixtures; verify scheduling, not real KMA collection."""
import json
from datetime import datetime, timedelta

import pytest

from backend.weather_worker import WeatherCollector


class FakeWeather:
    def __init__(self):
        self.instant = datetime.fromisoformat('2026-10-08T11:35:00+09:00')
        self.calls = []
        self.fail = False

    def snapshot(self, request, raw_dir, metadata_path):
        self.calls.append(('snapshot',request))
        if self.fail:
            raise RuntimeError('provider-url?authKey=TEST-SECRET should never reach state')
        return {'source_kind':'observed','unit':'mm','raw_sha256':'test-snapshot-hash',
            'temporal_contract':'minute_snapshot_accumulations_not_completed_daily_rainfall',
            'observed_at':datetime.strptime(request,'%Y%m%d%H%M').isoformat()+'+09:00',
            'observations':[{'rainfall_mm':{'RN-DAY':0.}}]}

    def daily(self, request, raw_dir, metadata_path):
        self.calls.append(('daily',request))
        return {'source_kind':'observed','unit':'mm','raw_sha256':'test-daily-hash',
            'temporal_contract':'completed_calendar_day_KST_rn_day',
            'available_dates':[datetime.strptime(request,'%Y%m%d').date().isoformat()],
            'observations':[{'rainfall_mm':0.}]}


def collector(tmp_path, fake, metadata=None, **options):
    if metadata is None:
        metadata = tmp_path/'official-metadata-test.csv'
        metadata.write_text('Synthetic metadata fixture, not real source')
    return WeatherCollector(tmp_path,enabled=options.pop('enabled',True),metadata_path=metadata,
        clock=lambda:fake.instant,snapshot_fetch=fake.snapshot,daily_fetch=fake.daily,**options)
