"""Synthetic, deterministic checks; these are not national performance evidence."""
import json
import math
from datetime import date, timedelta

import pytest

from backend.national_models import NationalModelManager, build_features


class LearnedDeltaBackend:
    """Small genuinely fitted backend to exercise contracts without TensorFlow."""
    def train(self, sequence, summary, targets, validation, variant, max_epochs, **kwargs):
        return {'delta': sum(y-x[-1][0] for x, y in zip(sequence, targets))/len(targets)}

    def predict(self, model, sequence, summary, variant):
        return [x[-1][0]+model['delta'] for x in sequence]

    def save(self, model, path):
        path.write_text(json.dumps(model))

    def load(self, path):
        return json.loads(path.read_text())


def rows(count=160, offset=0):
    return [{'date': (date(2020, 1, 1)+timedelta(days=i+offset)).isoformat(),
             'station_id': 'kwater:one', 'groundwater_level': -5+.01*(i+offset),
             'rainfall_mm': float((i+offset)%4)} for i in range(count)]


def metadata(**changes):
    return {'station_id': 'kwater:one', 'source_kind': 'observed', 'verified': True,
            'level_unit': 'm', 'level_reference': 'ground_level', **changes}


def manager(tmp_path):
    return NationalModelManager(tmp_path, LearnedDeltaBackend())
