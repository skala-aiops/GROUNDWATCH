"""Build observed daily weather history from hash-verified, complete cached responses.

No network requests, station approvals or missing-value imputation are performed.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
import hashlib
import gzip
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from serving_app.national_sources import parse_aws_daily


def build(cache_root, *, root=ROOT, start=None, end=None):
    cache_root, root = Path(cache_root), Path(root)
    first = date.fromisoformat(start) if start else None
    last = date.fromisoformat(end) if end else None
    if first and last and first > last:
        raise ValueError('invalid_period')
    days, metadata, observations, union, provenance, quarantined = [], {}, [], {}, [], []
    previous = None
    for path in sorted((cache_root / 'parsed').glob('*.json')):
        day = date.fromisoformat(path.stem)
        if (first and day < first) or (last and day > last):
            continue
        payload = json.loads(path.read_text())
        raw_path = Path(payload['raw_path'])
        raw_path = raw_path if raw_path.is_absolute() else root / raw_path
        if not raw_path.resolve().is_relative_to(cache_root.resolve()):
            raise ValueError('raw_outside_cache')
        digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if digest != payload.get('raw_sha256'):
            raise ValueError('raw_hash_mismatch')
        verified = parse_aws_daily(raw_path, requested_date=day.strftime('%Y%m%d'),
                                   collected_at=payload['collected_at'])
        for key, expected in verified.items():
            if payload.get(key) != expected:
                raise ValueError('cached_parse_mismatch:' + key)
        if previous and previous['source_url'] != verified['source_url']:
            raise ValueError('mixed_provider')
        previous = verified
        name = day.isoformat()
        days.append(name)
        metadata[name] = verified['stations']
        observations.extend(verified['observations'])
        for station in verified['stations']:
            # This catalogue carries identities only; coordinates are valid on their own day.
            union.setdefault(station['station_id'], dict(station_id=station['station_id'],
                source_station_id=station['source_station_id'], name=station['name'],
                coordinate_source='date_specific_metadata_required'))
        provenance.append(dict(date=name, raw_sha256=digest,
            parsed_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            collected_at=verified['collected_at'], observations=len(verified['observations']),
            quarantined=len(verified['quarantined'])))
        quarantined.extend(dict(date=name, **entry) for entry in verified['quarantined'])
    if not days:
        raise ValueError('no_complete_days')
    variant_ids = []
    for identifier in union:
        variants = {(s['latitude'], s['longitude'], s['name']) for rows in metadata.values()
                    for s in rows if s['station_id'] == identifier}
        if len(variants) > 1:
            variant_ids.append(identifier)
    return dict(schema_version=1, source='기상청 지상·AWS 일강수 이력',
        provider=previous['provider'], source_url=previous['source_url'], source_kind='observed', unit='mm',
        collected_at=max(p['collected_at'] for p in provenance),
        build_contract='raw_sha256_and_full_reparse_verified_v1',
        available_dates=days, stations=sorted(union.values(), key=lambda s:s['station_id']),
        observations=observations, station_metadata_by_date=metadata, provenance=provenance,
        quarantined=quarantined, unit_evidence=previous['unit_evidence'],
        temporal_contract=previous['temporal_contract'], collection_status='verified_cached_complete_responses',
        quality=dict(complete_response_days=len(days), observations=len(observations),
            quarantined_rows=len(quarantined), station_identity_count=len(union),
            coordinate_or_name_variant_station_ids=variant_ids),
        scope_note='일별 공식 응답에 실린 관측지점 강수입니다. 좌표·이름은 선택한 날짜 자료를 사용하며 빈값을 0으로 채우지 않습니다. 지하수 매핑이나 학습 승인을 뜻하지 않습니다.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root', default='runtime/official/aws-history')
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--output', default='data/national_aws_history.json.gz')
    args = parser.parse_args()
    try:
        result = build(ROOT / args.cache_root, start=args.start, end=args.end)
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + '.tmp')
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        temporary.write_bytes(gzip.compress(encoded, mtime=0) if output.suffix == '.gz' else encoded)
        temporary.replace(output)
        print(json.dumps(dict(status='built', days=len(result['available_dates']),
            observations=len(result['observations']), bytes=output.stat().st_size)))
    except (ValueError, KeyError, OSError, TypeError):
        print(json.dumps(dict(status='blocked', reason='cache_or_raw_validation_failed')))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
