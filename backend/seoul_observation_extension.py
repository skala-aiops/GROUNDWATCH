"""Read-only observed display snapshot; never a model training/inference dataset."""
import csv
import hashlib
import io
import json
import math
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'


def load_extension(data_dir=DATA):
    data_dir = Path(data_dir)
    try:
        payload = (data_dir / 'seoul_observation_extension.csv').read_bytes()
        manifest = json.loads((data_dir / 'seoul_observation_extension_manifest.json').read_text())
        base = (data_dir / 'groundwater_observations.csv').read_bytes()
        representatives = json.loads((data_dir / 'representatives.json').read_text())
        if (hashlib.sha256(payload).hexdigest() != manifest['canonical_sha256'] or
                hashlib.sha256(base).hexdigest() != manifest['frozen_base_sha256'] or
                manifest['source_kind'] != 'observed' or manifest['unit'] != 'gl.-m'):
            return None
        approved = {str(s['district_code']): s for s in representatives['stations']}
        reported = {str(s['district_code']): s for s in manifest['stations']}
        if len(reported) != 25 or len(manifest['stations']) != 25 or set(reported) != set(approved):
            return None
        if any(reported[c]['station_id'] != approved[c]['station_id'] for c in approved):
            return None
        rows, seen = {}, set()
        for raw in csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))):
            code = raw['district_code']
            day = date.fromisoformat(raw['date'])
            key = (code, raw['date'])
            level, rain = float(raw['groundwater_level']), float(raw['rainfall_mm'])
            if (code not in approved or raw['station_id'] != approved[code]['station_id'] or
                    raw['level_unit'] != approved[code]['level_unit'] or raw['level_unit'] != manifest['unit'] or
                    not math.isfinite(level) or not math.isfinite(rain) or rain < 0 or key in seen or
                    not date(2024, 3, 18) < day <= date.fromisoformat(manifest['requested_end'])):
                return None
            seen.add(key)
            rows.setdefault(code, []).append({**raw, 'groundwater_level': level,
                'rainfall_mm': rain, 'origin': 'observed', 'prediction': None, 'predictions': [],
                'observation_snapshot_id': manifest['canonical_sha256']})
        if len(seen) != manifest['rows'] or set(rows) != set(approved):
            return None
        return {'rows': {c: sorted(v, key=lambda r:r['date']) for c,v in rows.items()},
                'id': manifest['canonical_sha256'], 'collected_at': manifest['collected_at'],
                'source_url': manifest['source_url']}
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return None
