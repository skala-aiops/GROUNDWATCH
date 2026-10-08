"""Package collected ASOS history with verified result and raw page hashes."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(collection_root, output):
    root = Path(collection_root).resolve()
    report = json.loads((root / 'collection-report.json').read_text())
    if report.get('failed') or not report.get('results'):
        raise ValueError('incomplete_collection')
    observations, sources, identities = [], [], set()
    for entry in report['results']:
        folder = root / entry['station_id'] / f"{entry['start_date']}_{entry['end_date']}"
        path = folder / 'result.json'
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['result_sha256']:
            raise ValueError('result_hash_mismatch')
        result = json.loads(raw)
        for page in result['raw_pages']:
            if Path(page['file']).name != page['file']:
                raise ValueError('invalid_raw_path')
            if hashlib.sha256((folder / page['file']).read_bytes()).hexdigest() != page['raw_sha256']:
                raise ValueError('raw_hash_mismatch')
        for row in result['accepted']:
            identity = (row['source_station_id'], row['date'])
            if identity in identities:
                raise ValueError('duplicate_observation')
            if (row['source_station_id'] != entry['station_id'] or
                not entry['start_date'] <= row['date'] <= entry['end_date'] or
                row['unit'] != 'mm' or row['metric'] != 'rainfall_mm'):
                raise ValueError('invalid_observation_contract')
            identities.add(identity)
            observations.append(row)
        sources.append({**entry, 'result_path': str(path.relative_to(ROOT)), 'raw_pages': result['raw_pages']})
    value = {'schema_version': 1, 'source': 'kma_asos',
             'period_start': min(r['start_date'] for r in report['results']),
             'period_end': max(r['end_date'] for r in report['results']),
             'observations': observations, 'sources': sources,
             'quality': {'accepted': len(observations),
                         'quarantined': sum(r['quarantined'] for r in report['results']),
                         'blank_rainfall_policy': 'exclude; no zero fill'},
             'applied_to_service': False, 'training_ready': False}
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    Path(output).write_bytes(gzip.compress(payload, mtime=0))
    return value['quality']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection-root', default='runtime/official/national-rain-history-2020-2025')
    parser.add_argument('--output', default='data/national_asos_history_2020_2025.json.gz')
    args = parser.parse_args()
    print(json.dumps(build(args.collection_root, args.output)))
