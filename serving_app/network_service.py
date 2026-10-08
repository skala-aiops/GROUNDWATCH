"""Single station read facade; original services remain the owners of state."""
import json
import csv
import math
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'


def _read(name, default):
    path = DATA / name
    return json.loads(path.read_text()) if path.exists() else default


class NetworkService:
    def __init__(self, legacy, national):
        self.legacy, self.national = legacy, national

    @staticmethod
    def _persistence(rows, source):
        if not source.get('source_contract_verified') or len(rows) < 20:
            return None
        window = rows[-20:]
        for i, row in enumerate(window):
            value = row.get('groundwater_level')
            if (row.get('quality_status', 'valid') != 'valid' or
                row.get('source_kind', 'observed') not in ('observed', 'observed_api') or
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or
                row.get('level_unit') != source.get('level_unit') or
                row.get('level_reference') != source.get('level_reference')):
                return None
            if i and date.fromisoformat(row['date']) - date.fromisoformat(window[i-1]['date']) != timedelta(days=1):
                return None
        return {'prediction': window[-1]['groundwater_level'],
                'target_date': (date.fromisoformat(window[-1]['date']) + timedelta(days=1)).isoformat(),
                'input_end_date': window[-1]['date'], 'prediction_scope': 'experimental',
                'horizon_days':1,'forecast_timing':None}

    def _national_index(self, as_of=None):
        catalog = _read('national_stations_gims.json', {}).get('accepted', [])
        samples = _read('national_groundwater_samples.json', {}).get('stations', [])
        sample_map = {str(s['source_station_id']): s for s in samples}
        registered, cursor = [], None
        while True:
            page = self.national.repo.list_stations(cursor=cursor, limit=200)
            registered.extend(page['items'])
            cursor = page.get('next_cursor')
            if not cursor:
                break
        registry = {str(s.get('source_station_id', s['station_id'])): s for s in registered}
        sources = {str(s['source_station_id']): s for s in catalog}
        for sid, sample in sample_map.items():
            sources[sid] = {**sources.get(sid, {}), **sample}
        for sid, station in registry.items():
            sources[sid] = {**sources.get(sid, {}), **station}
        result = []
        for sid, source in sources.items():
            sample, operational = sample_map.get(sid), registry.get(sid)
            rows = self.national.repo.observations(operational['station_id'], end=as_of) if operational else (sample or {}).get('observations', [])
            rows = [r for r in rows if not as_of or r['date'] <= as_of]
            models = self.national.manager.list_models(operational['station_id']) if operational else []
            active = next((m for m in models if m.get('active')), None)
            issued = self.national.forecasts(operational['station_id']) if operational else []
            issued = [p for p in issued if not as_of or p.get('input_end_date', p.get('target_date', '')) <= as_of]
            active_issued = [p for p in issued if active and p.get('model_version') == active.get('version')]
            prediction = max(active_issued, key=lambda p: (p.get('target_date', ''), p.get('issued_at', '')), default={})
            fallback = self._persistence(rows, source) if not active else None
            if fallback:
                prediction = fallback
            verified = bool(source.get('verified'))
            experimental = bool(operational and source.get('source_contract_verified') and source.get('mapping_status') == 'experimental')
            ready = bool(operational and self.national.repo.readiness(operational['station_id']).get('data_ready'))
            name = source.get('name', sid)
            public_source = {k: v for k, v in source.items() if k not in ('observations', 'raw_sources', 'quality')}
            result.append({**public_source, 'station_id': f'kwater:{sid}', 'provider': 'kwater',
                'source_station_id': sid, 'operation_station_id': operational['station_id'] if operational else None,
                'name': name, 'district_name': name, 'district_code': f'kwater:{sid}',
                'region_code': source.get('region_code') or '미분류', 'region_name': source.get('region_code') or '미분류',
                'unit': source.get('level_unit', source.get('unit')),
                'reference_status': 'source_contract_verified' if source.get('source_contract_verified') else source.get('level_reference_status', 'verified' if verified else 'unverified'),
                'level_reference': source.get('level_reference', 'unverified'),
                'observed_date': rows[-1]['date'] if rows else None,
                'forecast_date': prediction.get('target_date'),
                'prediction_input_end_date':prediction.get('input_end_date'),
                'forecast_timing':prediction.get('forecast_timing'),
                'horizon_days':prediction.get('horizon_days'),
                'prediction_issued_at':None if fallback else prediction.get('issued_at'), 'prediction': prediction.get('predicted_level', prediction.get('prediction')),
                'model_version': prediction.get('model_version') or (active or {}).get('version'),
                'model_ready': bool(active and ready),
                'prediction_method': 'persistence' if fallback else 'lstm' if prediction else None,
                'prediction_evidence': 'read_time_baseline_not_issued' if fallback else 'archived_issued_prediction' if prediction else None, 'source_kind': source.get('source_kind', 'observed'),
                'prediction_scope': prediction.get('prediction_scope', 'experimental' if experimental else 'operational' if verified else None),
                'latest_actual_level': rows[-1].get('groundwater_level') if rows else None,
                'latest_comparison': {'date': rows[-1]['date'], 'actual': rows[-1].get('groundwater_level'), 'prediction': next((p.get('prediction', p.get('predicted_level')) for p in reversed(issued) if p.get('target_date') == rows[-1]['date']), None)} if rows else None,
                'data_status': 'observations_available' if rows else 'catalog_only',
                'model_status': 'active' if active else 'not_ready',
                'verified': verified, 'training_approved': bool(source.get('operational_approved', verified)),
                'capabilities': {'history': bool(rows), 'train': bool(verified and ready),
                    'train_experimental': bool(experimental and rows), 'predict': bool(active and ready),
                    'replay': False, 'rollback': bool(operational and sum(bool(m.get('activated_at')) for m in models) > 1)}})
        return result

    def stations(self, mode='current', replay_id=None, as_of=None, region_code=None):
        legacy = self.legacy.forecasts(mode=mode, replay_id=replay_id, as_of=as_of)
        items = []
        for row in legacy['forecasts']:
            code = str(row['district_code'])
            items.append({**row, 'station_id': 'seoul:' + str(row.get('station_id') or code),
                'provider': 'seoul', 'legacy_district_code': code, 'name': row['district_name'],
                'region_code': '서울특별시', 'region_name': '서울특별시',
                'reference_status': row.get('level_reference', 'legacy_manifest'),
                'data_status': row.get('quality_status'),
                'model_status': 'active' if row.get('prediction') is not None else 'not_ready',
                'model_ready': row.get('prediction') is not None,
                'prediction_method': 'lstm' if row.get('prediction') is not None else None,
                'prediction_input_end_date':row.get('input_end_date'),
                'forecast_timing':row.get('forecast_timing'),
                'horizon_days':row.get('horizon_days'),
                'prediction_issued_at':row.get('issued_at'),
                'capabilities': {'history': bool(row.get('observed_date')), 'train': True,
                    'train_experimental': False, 'predict': row.get('prediction') is not None,
                    'replay': True, 'rollback': bool(row.get('model_version'))}})
        items.extend(self._national_index(legacy['as_of']))
        regions = sorted({r['region_code'] for r in items})
        if region_code:
            items = [r for r in items if r['region_code'] == region_code]
        return {'stations': items, 'regions': regions, 'ready_count': sum(bool(r.get('model_ready')) for r in items),
                'prediction_available_count': sum(r['prediction'] is not None for r in items),
                'fallback_count': sum(r.get('prediction_method') == 'persistence' for r in items),
                'total_count': len(items), 'as_of': legacy['as_of'], 'mode': mode, 'replay_id': replay_id,
                'simulation': legacy.get('simulation')}

    def _station(self, station_id, **scope):
        return next((s for s in self.stations(**scope)['stations'] if s['station_id'] == station_id), None)

    def history(self, station_id, **scope):
        station = self._station(station_id, **scope)
        if station is None:
            raise KeyError('관측소를 찾을 수 없습니다.')
        if station['provider'] == 'seoul':
            value = self.legacy.history(station['legacy_district_code'], replay_id=scope.get('replay_id'))
            rows = value['history']
        elif station.get('operation_station_id'):
            rows = self.national.repo.observations(station['operation_station_id'], end=scope.get('as_of'))
        else:
            sample = next((s for s in _read('national_groundwater_samples.json', {}).get('stations', [])
                           if str(s['source_station_id']) == station['source_station_id']), {})
            rows = sample.get('observations', [])
        if scope.get('as_of'):
            rows = [r for r in rows if r['date'] <= scope['as_of']]
        rows = [{**r, 'prediction': r.get('prediction'), 'rainfall_mm': r.get('rainfall_mm'),
                 'origin': r.get('origin', 'observed')} for r in rows]
        candidates = next((s.get('nearest_weather_candidates', []) for s in
            _read('national_training_readiness.json', {}).get('stations', [])
            if str(s['source_station_id']) == station.get('source_station_id')), [])
        rainy_region = station.get('rainy_region')
        periods = self.national.repo.rainy_periods(region_code=rainy_region) if rainy_region and station.get('source_contract_verified') else []
        weather = {'mapping_status': station.get('mapping_status', 'unapproved'),
                   'source_station_id': station.get('weather_source_station_id'),
                   'mapping_version': station.get('mapping_version'),
                   'source_contract_verified': bool(station.get('source_contract_verified')),
                   'operational_approved': bool(station.get('operational_approved')),
                   'candidates': candidates, 'rainy_region': rainy_region,
                   'rainy_period': periods or None, 'rainy_period_usage': 'evaluation_only',
                   'note': '실험 매핑과 운영 승인은 구분합니다. 장마 통계는 평가용이며 미래 예보가 아닙니다.'}
        if station['provider'] == 'seoul':
            # Seoul rain remains the original source join; 108 is only a post-hoc
            # rainy-season context, not a replacement weather-input mapping.
            periods = self.national.repo.rainy_periods(region_code='kma_asos:108')
            if not periods and (DATA / 'rainy_seasons_kma.csv').exists():
                with (DATA / 'rainy_seasons_kma.csv').open(encoding='utf-8-sig', newline='') as source:
                    periods = [{**r, 'year':int(r['year']), 'region_code':r['region']}
                               for r in csv.DictReader(source) if r['region'] == 'kma_asos:108']
            weather.update(mapping_status='seoul_source_date_join',
                rainy_region='kma_asos:108',
                rainy_period=periods or None,
                note='서울 원천 강수 입력을 유지합니다. 서울(108) 장마 통계는 사후 평가용이며 실시간 장마 판정이 아닙니다.')
        if rows:
            station = {**station, 'latest_actual_level': rows[-1].get('groundwater_level'),
                       'latest_comparison': {'date': rows[-1]['date'], 'actual': rows[-1].get('groundwater_level'), 'prediction': rows[-1].get('prediction')}}
        return {'station': station, 'history': rows, 'weather_context': weather}

    def pipeline(self, station_id, **scope):
        station = self._station(station_id, **scope)
        if station is None:
            raise KeyError('관측소를 찾을 수 없습니다.')
        if station['provider'] == 'seoul':
            result = self.legacy.pipeline(station['legacy_district_code'], replay_id=scope.get('replay_id'))
        elif station.get('operation_station_id'):
            result = self.national.pipeline(station['operation_station_id'])
            result = {**result, 'stages': [], 'active_jobs': [j for j in result.get('jobs', []) if j.get('status') in ('queued', 'running')], 'log': [], 'defaults': {}}
        else:
            result = {'stages': [], 'active_jobs': [], 'log': [], 'defaults': {},
                      'note': '원천 관측 조회 단계입니다. 승인된 모델과 작업 이력은 없습니다.'}
        seasonal_path = self.national.root.parent / 'seasonal_evaluation.json' if hasattr(self.national, 'root') else None
        seasonal = json.loads(seasonal_path.read_text()) if seasonal_path and seasonal_path.exists() else {}
        evaluation = next((item for item in seasonal.get('stations', []) if item['station_id'] == station.get('operation_station_id')), None)
        collection_path = self.national.root / 'observation_collection' / 'state.json' if hasattr(self.national, 'root') else None
        collection = json.loads(collection_path.read_text()) if collection_path and collection_path.exists() else None
        return {**result, 'station': station, 'capabilities': station['capabilities'],
                'observation_collection': collection,
                'seasonal_evaluation': {**evaluation, 'evaluation_mode': 'retrospective', 'operational_promotion_evidence': False} if evaluation else None}
