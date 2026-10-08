"""Model lifecycle checks with a deterministic backend, not accuracy evidence."""
import copy
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from backend.groundwater_models import ModelManager, ModelNotReady, TensorFlowBackend, validate_rows


class Backend:
    def __init__(self):
        self.versions, self.aliases, self.calls = {}, {}, []
        self.fail_alias = False
        self.train_offset = 0.0

    def train(self, x, y, validation, **kwargs):
        self.calls.append((copy.deepcopy(x), copy.deepcopy(y), kwargs))
        return {'offset': self.train_offset}

    def predict(self, model, inputs):
        return [row[-1][0] + model['offset'] for row in inputs]

    def register(self, name, model, bundle, directory):
        entries = self.versions.setdefault(name, {})
        version = str(len(entries)+1)
        entries[version] = (copy.deepcopy(model), copy.deepcopy(bundle))
        return version

    def load(self, name, version):
        return copy.deepcopy(self.versions[name][version])

    def alias(self, name):
        return self.aliases.get(name)

    def set_alias(self, name, version):
        if self.fail_alias:
            self.fail_alias = False
            raise RuntimeError('registry unavailable')
        if version is None:
            self.aliases.pop(name, None)
        else:
            self.aliases[name] = version


def rows(count=410, code='11110', start=date(2020, 1, 1)):
    return [{'date': str(start+timedelta(days=i)), 'groundwater_level': i*.1-5,
             'rainfall_mm': float(i % 7), 'station_id': 'official-well-1',
             'district_code': code, 'level_unit': 'm'} for i in range(count)]


META = {'station_id': 'official-well-1', 'level_unit': 'm',
        'dataset_version': 'verified-fixture', 'mapping_version': 'fixed-fixture',
        'manifest_approved': True}
