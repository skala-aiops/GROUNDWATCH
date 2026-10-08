"""Synthetic source records verify integrity and display-only sample behavior."""
import hashlib
import json

import pytest

from scripts.build_groundwater_samples import build


def report(tmp_path,rows,result_code='Success'):
    raw = json.dumps({'response':{'resultCode':result_code,'resultData':rows}}).encode()
    (tmp_path/'raw.json').write_bytes(raw)
    return {'period_start':'2026-01-01','period_end':'2026-01-03',
        'stations':[{'source_station_id':'1','name':'SYNTHETIC TEST ONLY',
                     'raw_sources':[{'file':'raw.json','sha256':hashlib.sha256(raw).hexdigest()}]}]}


def row(day,elev='0',lev='-2'):
    return {'gennum':'1','ymd':day,'elev':elev,'lev':lev}


def test_hash_mismatch_blocks_sample_generation(tmp_path):
    source = report(tmp_path,[row('20260101')])
    (tmp_path/'raw.json').write_text('{}')
    with pytest.raises(ValueError,match='hash mismatch'):
        build(source,tmp_path)


def test_source_zero_negative_depth_and_missing_duplicates_remain_distinct(tmp_path):
    source = report(tmp_path,[row('20260101'),row('20260103','2'),row('20260103','3')])
    output = build(source,tmp_path)
    station = output['stations'][0]
    assert station['quality']['valid_days'] == 1
    assert station['quality']['missing_dates'] == ['2026-01-02']
    assert station['quality']['duplicate_dates'] == ['2026-01-03']
    assert station['observations'][0]['elev'] == 0
    assert station['observations'][0]['lev'] == -2
    assert station['observations'][0]['raw_elev'] == '0'
    assert station['observations'][1]['groundwater_level'] is None
    assert station['observations'][2]['groundwater_level'] is None
    assert station['verified'] is False and station['model_ready'] is False
    assert station['training_approved'] is False and station['mapping_approved'] is False


def test_failed_source_envelope_is_not_a_valid_empty_series(tmp_path):
    source = report(tmp_path,[],result_code='Error')
    with pytest.raises(ValueError,match='envelope'):
        build(source,tmp_path)
