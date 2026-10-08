"""Offline provider fixtures; verify scheduling, not real KMA collection."""
import json
from datetime import datetime, timedelta

import pytest

from serving_app.weather_worker import WeatherCollector


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


def test_opt_in_and_credentials_gate_do_not_call_provider(tmp_path,monkeypatch):
    fake = FakeWeather()
    monkeypatch.delenv('KMA_APIHUB_KEY',raising=False)
    assert collector(tmp_path,fake,enabled=False).tick()['status'] == 'disabled'
    assert collector(tmp_path,fake).tick()['reason'] == 'credentials_required'
    assert fake.calls == []
    assert not (tmp_path/'weather'/'national_aws_snapshot.json').exists()


def test_ten_minute_cadence_daily_once_and_restart_checkpoint(tmp_path,monkeypatch):
    monkeypatch.setenv('KMA_APIHUB_KEY','TEST-SECRET')
    fake = FakeWeather()
    worker = collector(tmp_path,fake)
    assert worker.tick()['status'] == 'ready'
    assert fake.calls == [('snapshot','202610081120'),('daily','20261007')]
    fake.instant += timedelta(minutes=4)
    collector(tmp_path,fake).tick()  # Restart with persistent checkpoint.
    assert len(fake.calls) == 2
    fake.instant += timedelta(minutes=6)
    worker.tick()
    assert fake.calls[-1] == ('snapshot','202610081130')
    assert sum(stream == 'daily' for stream,_ in fake.calls) == 1
    assert (tmp_path/'weather'/'archive'/'daily'/'20261007.json').exists()
    assert (tmp_path/'weather'/'weather_state.json').exists()


def test_failure_preserves_last_good_sanitizes_and_backs_off_after_restart(tmp_path,monkeypatch):
    monkeypatch.setenv('KMA_APIHUB_KEY','TEST-SECRET')
    fake = FakeWeather()
    worker = collector(tmp_path,fake)
    worker.tick()
    artifact = tmp_path/'weather'/'national_aws_snapshot.json'
    first = artifact.read_bytes()
    fake.fail = True
    fake.instant += timedelta(minutes=10)
    state = worker.tick()
    assert state['status'] == 'degraded'
    assert artifact.read_bytes() == first
    assert 'TEST-SECRET' not in json.dumps(state)
    calls = len(fake.calls)
    fake.instant += timedelta(minutes=2)
    assert collector(tmp_path,fake).tick()['status'] == 'degraded'
    assert len(fake.calls) == calls
    fake.fail = False
    fake.instant += timedelta(minutes=8)
    assert worker.tick()['status'] == 'ready'
    assert artifact.read_bytes() != first


def test_daily_waits_until_1130_and_metadata_blocks_only_snapshot(tmp_path,monkeypatch):
    monkeypatch.setenv('KMA_APIHUB_KEY','TEST-SECRET')
    fake = FakeWeather()
    missing = tmp_path/'not-yet-present.csv'
    worker = collector(tmp_path,fake,metadata=missing)
    assert worker.tick()['status'] == 'degraded'
    assert fake.calls == [('daily','20261007')]
    missing.write_text('Synthetic fixture')
    assert worker.tick()['status'] == 'ready'
    fake.instant = datetime.fromisoformat('2026-10-09T10:00:00+09:00')
    worker.tick()
    assert ('daily','20261008') not in fake.calls
    fake.instant = datetime.fromisoformat('2026-10-09T11:30:00+09:00')
    worker.tick()
    assert fake.calls[-1] == ('daily','20261008')


def test_separate_process_lock_prevents_concurrent_provider_calls(tmp_path,monkeypatch):
    import fcntl
    monkeypatch.setenv('KMA_APIHUB_KEY','TEST-SECRET')
    fake = FakeWeather()
    worker = collector(tmp_path,fake)
    with (tmp_path/'weather'/'collector.lock').open('a') as locked:
        fcntl.flock(locked.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert worker.tick()['status'] == 'busy'
    assert fake.calls == []


def test_invalid_parsed_payload_does_not_publish_artifact(tmp_path,monkeypatch):
    monkeypatch.setenv('KMA_APIHUB_KEY','TEST-SECRET')
    fake = FakeWeather()
    worker = collector(tmp_path,fake)
    worker.snapshot_fetch = lambda *_:{'source_kind':'synthetic','unit':'mm'}
    assert worker.tick()['streams']['snapshot']['status'] == 'failed'
    assert not (tmp_path/'weather'/'national_aws_snapshot.json').exists()
