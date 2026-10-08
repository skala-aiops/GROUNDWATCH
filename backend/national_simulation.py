"""Deterministic scenario data, never a replacement for official observations."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random

SCENARIO = 'national-rain-response-v1'
NAMESPACE = 'national_synthetic_v1'
SEED = 20261008
START = date(2022, 1, 1)


def generate(catalog, candidates, end, seed=SEED):
    end = date.fromisoformat(end) if isinstance(end, str) else end
    if end < START + timedelta(days=1095):
        raise ValueError('scenario requires at least three years')
    sources = {str(s['source_station_id']): s for s in catalog['accepted']}
    stations = []
    for candidate in candidates['candidates']:
        source_id = str(candidate['source_station_id'])
        source = sources[source_id]
        station_id = 'sim-gims-' + source_id
        derived_seed = int(hashlib.sha256(f'{seed}:{source_id}'.encode()).hexdigest()[:16], 16)
        rng = random.Random(derived_seed)
        base = 10 + rng.random()*15
        response = 0.002 + rng.random()*0.002
        memory = 0.0
        rows = []
        for offset in range((end-START).days+1):
            day = START + timedelta(days=offset)
            monsoon = (day.month == 6 and day.day >= 20) or (day.month == 7 and day.day <= 25)
            wet = rng.random() < (0.68 if monsoon else 0.24)
            rain = round(min(160, rng.gammavariate(1.5, 22 if monsoon else 8)) if wet else 0.0, 2)
            memory = memory*0.88 + rain*response
            seasonal = 0.25*math.sin(2*math.pi*day.timetuple().tm_yday/365.25)
            # Last 90 days have a deliberate response shift to exercise drift workflows.
            drift = 0.45 if day >= date(2026, 7, 10) else 0.0
            level = round(base + seasonal + memory + drift + rng.gauss(0, 0.012), 5)
            row = {'date': day.isoformat(), 'station_id': station_id,
                   'groundwater_level': level, 'rainfall_mm': rain,
                   'level_unit': 'm', 'level_reference': 'simulation_relative_datum',
                   'source_kind': 'synthetic', 'quality_status': 'valid',
                   'scenario_id': SCENARIO, 'seed': seed, 'simulation_clock':True,
                   'available_at': (day+timedelta(days=1)).isoformat()+'T11:30:00+09:00',
                   'collected_at': (day+timedelta(days=1)).isoformat()+'T11:30:00+09:00'}
            digest = hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
            rows.append({**row,'revision_id':digest,'source_sha256':digest})
        stations.append({'station': {
            'station_id': station_id, 'source_station_id': 'sim-'+source_id,
            'provider': 'groundwatch_simulation', 'name': source['name']+' · 시뮬레이션',
            'region_code': source['region_code'], 'latitude':source.get('latitude'),
            'longitude':source.get('longitude'), 'verified':False,
            'source_kind':'synthetic','namespace':NAMESPACE,
            'level_unit':'m','level_reference':'simulation_relative_datum',
            'source_contract_verified':True,'source_contract_scope':'simulation_generator',
            'simulation_contract_verified':True,'simulation_clock':True,'mapping_status':'synthetic',
            'operational_approved':False,'mapping_version':SCENARIO,
            'scenario_id':SCENARIO,'seed':seed,'catalog_source_station_id':source_id,
            'coordinate_status':'catalog_position_for_scenario_only',
            'evidence':['backend/national_simulation.py', 'synthetic scenario; not field observations'],
            'simulation_provenance':{'start_date':START.isoformat(),'end_date':end.isoformat(),
                'seed':seed,'generator':SCENARIO,'monsoon_window':'06-20 through 07-25 (scenario only)',
                'drift_start_date':'2026-07-10','drift_shift_m':0.45,
                'formula':'base + annual sine + AR(0.88) rain recharge + Gaussian noise + shift since2026-07-10'}},
            'observations':rows})
    if len(stations) != 17 or len({s['station']['region_code'] for s in stations}) != 17:
        raise ValueError('exactly 17 scenario regions required')
    return {'source_kind':'synthetic','namespace':NAMESPACE,'scenario_id':SCENARIO,
            'seed':seed,'simulation_clock':True,
            'actual_generated_at':datetime.now(timezone.utc).isoformat(),
            'operational_promotion_allowed':False,'stations':stations}


def bootstrap(service, data_dir, end, max_epochs=5):
    data_dir = Path(data_dir)
    stamp = str(end)
    cached = getattr(service, '_simulation_payload', None)
    payload = cached if cached and cached['end_date'] == stamp else generate(json.loads((data_dir/'national_stations_gims.json').read_text()),
                       json.loads((data_dir/'national_region_coverage_probe.json').read_text()),end)
    first_import = cached is not payload
    payload['end_date'] = stamp
    service._simulation_payload = payload
    if first_import:
        output = service.root/'simulation-generation.json'
        output.write_text(json.dumps({k:v for k,v in payload.items() if k!='stations'},ensure_ascii=False,indent=2))
    results = []
    for item in payload['stations']:
        station = item['station']; sid = station['station_id']
        # End date is data provenance, not immutable station metadata.
        station['simulation_provenance'].pop('end_date', None)
        if first_import:
            service.repo.register_station(station)
            existing = {r['revision_id'] for r in service.repo.observations(sid)}
            added = [r for r in item['observations'] if r['revision_id'] not in existing]
            if added:
                service.repo.add_observations(sid, added)
        manager = service.manager_for(sid)
        jobs = [j for j in service.store.jobs() if j['payload'].get('station_id') == sid]
        models = manager.list_models(sid)
        queued = []
        for variant in ('M0', 'M1'):
            if any(m.get('variant') == variant for m in models) or any(j['kind']=='train' and j['payload'].get('variant','M0')==variant for j in jobs):
                continue
            if any(j['status'] in ('queued','running') for j in jobs):
                break
            job = service.enqueue('train',sid,variant=variant,max_epochs=max_epochs)
            jobs.append(job)
            queued.append(job['id'])
            break
        latest = item['observations'][-1]['date']
        if (any(m.get('active') for m in models) and not any(j['status'] in ('queued','running') for j in jobs)
                and not any(j['kind']=='predict' and j['payload'].get('input_end_date')==latest for j in jobs)):
            queued.append(service.enqueue('predict',sid,input_end_date=latest)['id'])
        results.append({'station_id':sid,'source_kind':'synthetic','rows':len(item['observations']),'queued':queued})
    return results
