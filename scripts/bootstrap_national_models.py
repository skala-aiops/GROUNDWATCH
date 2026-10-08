"""Import evidenced experimental joins and queue real model evaluation once.

No production approval, legacy manifest edit, synthetic substitution or repeated
failed-job retry. Run inside the standard container; worker executes queued jobs.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.national_service import NationalService


def bootstrap(service, path, max_epochs=30):
    payload=json.loads(Path(path).read_text())
    catalog=json.loads((Path(path).parent/'national_stations_gims.json').read_text())
    by_source={s['source_station_id']:s for s in catalog['accepted']}
    result=[]
    for mapping in payload['mappings']:
        if mapping['selection_basis']!='official_station_name':
            continue
        if not (mapping['source_contract_verified'] is True and mapping['mapping_status']=='experimental'
                and mapping['operational_approved'] is False):
            raise ValueError('explicit experimental source contract required')
        source_id=mapping['groundwater_source_station_id']
        station_id='kwater-'+source_id
        contract=mapping['source_contract']
        station={'station_id':station_id,'provider':'kwater','source_station_id':source_id,
            'name':mapping['groundwater_name'],'region_code':by_source[source_id]['region_code'],
            'level_unit':contract['level_unit'],'level_reference':contract['level_reference'],
            'verified':False,'source_kind':'observed','source_contract_verified':True,
            'mapping_status':'experimental','operational_approved':False,
            'mapping_version':mapping['mapping_evidence_version'],
            'weather_station_id':'kma_asos:'+mapping['weather_source_station_id'],
            'weather_source_station_id':mapping['weather_source_station_id'],
            'rainy_region':mapping['rainy_region'],
            'evidence':contract['evidence']+[mapping['mapping_evidence']['gims_source_url']],
            'mapping_id':mapping['mapping_id']}
        service.repo.register_station(station)
        service.repo.add_observations(station_id,mapping['observations'])
        for period in mapping['rainy_periods']:
            service.repo.add_rainy_period({'year':int(period['year']),'region_code':period['region'],
                'start_date':period['start_date'],'end_date':period['end_date'],
                'source_sha256':period['source_sha256'],'source_kind':'observed',
                'evidence':['https://data.kma.go.kr/climate/rainySeason/selectRainySeasonList.do',
                            'official ASOS station ID '+mapping['weather_source_station_id']]})
        existing=service.manager.list_models(station_id)
        jobs=[j for j in service.store.jobs() if j['payload'].get('station_id')==station_id]
        queued=[]
        for variant in ('M0','M1'):
            if any(m['variant']==variant for m in existing) or any(
                    j['kind']=='train' and j['payload'].get('variant','M0')==variant for j in jobs):
                continue
            if any(j['status'] in ('queued','running') for j in jobs):
                break
            job=service.enqueue('train',station_id,variant=variant,max_epochs=max_epochs)
            jobs.append(job);queued.append(job['id'])
            break
        latest=mapping['observations'][-1]['date']
        if (not any(j['status'] in ('queued','running') for j in jobs)
                and any(m.get('active') for m in existing)
                and not any(j['kind']=='predict' and j['payload'].get('input_end_date')==latest for j in jobs)):
            queued.append(service.enqueue('predict',station_id,input_end_date=latest)['id'])
        result.append({'station_id':station_id,'observations':len(mapping['observations']),
            'mapping_status':'experimental','operational_approved':False,'queued':queued})
    return result


def main():
    import os
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',default=os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
    parser.add_argument('--input',default='data/national_experimental_joined.json')
    parser.add_argument('--max-epochs',type=int,default=30)
    args=parser.parse_args()
    print(json.dumps(bootstrap(NationalService(args.state_root),args.input,args.max_epochs),ensure_ascii=False))

if __name__=='__main__':main()
