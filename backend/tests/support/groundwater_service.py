"""Durable service and simulated-clock integration; no claimed model accuracy."""
import csv
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from data.groundwater import DISTRICTS
from backend.groundwater_service import GroundwaterService
from backend.groundwater_store import Store


FIRST = DISTRICTS[0]['district_code']
START = date(2020, 1, 1)


class FakeManager:
    def __init__(self):
        self.models, self.calls = {}, []

    def list_models(self):
        return list(self.models.values())

    def train(self, code, records, metadata, max_epochs):
        if len(records) < 410:
            raise ValueError('410 days required')
        splits = {'replay': {'start': records[-90]['date'], 'end': records[-1]['date']}}
        self.models[code] = {'district_code': code, 'model_version': '1', 'status': 'ready',
                             'threshold': .01, 'splits': splits, 'trained_through': records[199]['date']}
        return {'status': 'promoted', 'model_version': '1', 'splits': splits}

    def predict(self, code, records):
        self.calls.append(('predict', records[-1]['date']))
        return {'prediction': records[-1]['groundwater_level']-(10 if code == FIRST else 0),
                'model_version': self.models[code]['model_version'], 'unit': 'fixture_m'}

    def fine_tune(self, code, records, metadata):
        self.calls.append(('fine_tune', records[-1]['date']))
        return {'candidate_version': '2', 'status': 'awaiting_shadow'}

    def evaluate_candidate(self, code, version, records):
        self.calls.append(('evaluate', records[-1]['date']))
        self.models[code]['model_version'] = version
        return {'status': 'promoted', 'model_version': version}


def upload_fixture(service):
    manifest = {'approved': True, 'mapping_version': 'explicit-test-only',
                'stations': [{'district_code': district['district_code'],
                              'station_id': 'fixture-'+district['district_code'],
                              'level_unit': 'fixture_m'} for district in DISTRICTS]}
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=['station_id','district_code','date','groundwater_level','rainfall_mm','level_unit'])
    writer.writeheader()
    for i in range(410):
        writer.writerow({'station_id': 'fixture-'+FIRST, 'district_code': FIRST,
                         'date': str(START+timedelta(days=i)), 'groundwater_level': float(i),
                         'rainfall_mm': float(i%7), 'level_unit': 'fixture_m'})
    for district in DISTRICTS[1:]:
        for i in range(410):
            writer.writerow({'station_id': 'fixture-'+district['district_code'],
                             'district_code': district['district_code'], 'date': str(START+timedelta(days=i)),
                             'groundwater_level': 1., 'rainfall_mm': 0., 'level_unit': 'fixture_m'})
    queued = service.queue_upload(stream.getvalue().encode('utf-8-sig'), json.dumps(manifest).encode())
    service.execute_one()
    assert service.store.job(queued['job_id'])['status'] == 'completed', service.store.job(queued['job_id'])
    return queued['dataset_id']
