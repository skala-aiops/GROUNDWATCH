"""Deterministic coursework extension; generated rows are never observations."""
import csv
import hashlib
import io
import json
import random
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from data.groundwater import REQUIRED_COLUMNS, load_canonical

SEED = 20261008


def build_extension(source, manifest_path, output_dir, end_date=None, observed_extension_dir=None):
    end = end_date or datetime.now(ZoneInfo('Asia/Seoul')).date()
    if end > datetime.now(ZoneInfo('Asia/Seoul')).date():
        raise ValueError('합성 입력도 오늘 이후 날짜에는 생성하지 않습니다.')
    ds = load_canonical(source, manifest_path, require_all=True)
    manifest = json.loads(Path(manifest_path).read_text())
    rows, intervals = [], {}
    additional = None
    if observed_extension_dir is not None:
        from backend.seoul_observation_extension import load_extension
        additional = load_extension(observed_extension_dir)
        if additional is None:
            raise ValueError('추가 실측의 관측소·단위·해시 검증에 실패했습니다.')
    for station in manifest['stations']:
        code = station['district_code']
        records = ds.rows_for_district(code)
        if additional:
            records.extend({k:r[k] for k in [*REQUIRED_COLUMNS, 'origin']}
                           for r in additional['rows'].get(code, [])
                           if r['station_id'] == station['station_id'] and date.fromisoformat(r['date']) <= end)
        records.sort(key=lambda r: r['date'])
        if not records:
            raise ValueError('원관측이 없는 관측소입니다: ' + code)
        rows.extend({**r, 'origin': 'observed'} for r in records)
        last = date.fromisoformat(records[-1]['date'])
        if last > end:
            raise ValueError('종료일은 마지막 원관측일 이후여야 합니다.')
        rng = random.Random(f'{SEED}:{code}')
        months = {m: [r for r in records if date.fromisoformat(r['date']).month == m] for m in range(1,13)}
        centers = {m: statistics.median(r['groundwater_level'] for r in (months[m] or records)) for m in range(1,13)}
        level = records[-1]['groundwater_level']
        intervals[code] = {'observed_through': last.isoformat(),
                           'synthetic_from': (last+timedelta(days=1)).isoformat(),
                           'synthetic_through': end.isoformat()}
        day = last + timedelta(days=1)
        while day <= end:
            pool = months[day.month] or records
            donor = rng.choice(pool)
            center = centers[day.month]
            # Mean-reverting, bounded seasonal scenario; no hydrological claim.
            level += .03*(center-level) + .015*(donor['groundwater_level']-center)
            rows.append({'station_id':station['station_id'], 'district_code':code,
                         'date':day.isoformat(), 'groundwater_level':round(level,8),
                         'rainfall_mm':donor['rainfall_mm'], 'level_unit':station['level_unit'],
                         'origin':'synthetic'})
            day += timedelta(days=1)
        station.pop('partitions', None)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=[*REQUIRED_COLUMNS,'origin'], extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    content = stream.getvalue().encode('utf-8-sig')
    manifest.update(source_kind='synthetic', canonical_sha256=hashlib.sha256(content).hexdigest(),
                    dataset_version='coursework-extension-'+end.isoformat(),
                    provenance={'kind':'observed_plus_synthetic_extension','seed':SEED,
                                'original_sha256':ds.dataset_version,'generated_through':end.isoformat(),
                                'additional_observation_snapshot_id':additional['id'] if additional else None,
                                'intervals':intervals,
                                'method':'Monthly empirical rain resampling; level += .03*(monthly median-level) + .015*(donor level-monthly median). Fixed per-station seed.',
                                'limitation':'Coursework scenario only; not latest Seoul observations or validated hydrological forecasts.'})
    manifest['training'].update(replay_start=(end-timedelta(days=89)).isoformat(),replay_end=end.isoformat())
    folder = Path(output_dir)/end.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    path, mapping = folder/'observations.csv', folder/'manifest.json'
    path.write_bytes(content)
    mapping.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    # Keep timestamps outside the deterministic CSV/manifest identity. Reusing
    # identical generated content must not enqueue another training job.
    stamp_path = folder/'generation.json'
    identity = hashlib.sha256(content+mapping.read_bytes()).hexdigest()
    stamp = json.loads(stamp_path.read_text()) if stamp_path.exists() else {}
    if stamp.get('identity') != identity:
        stamp_path.write_text(json.dumps({'identity':identity,
            'generated_at':datetime.now(ZoneInfo('UTC')).isoformat()},indent=2)+'\n')
    return path, mapping
