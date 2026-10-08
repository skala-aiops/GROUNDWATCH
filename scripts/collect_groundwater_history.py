"""Bounded multi-year GIMS raw collection for explicit station IDs; no model mutation."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serving_app.national_sources import collect_kwater

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--station',action='append',required=True)
    p.add_argument('--start',required=True);p.add_argument('--end',required=True)
    p.add_argument('--output',required=True);args=p.parse_args()
    for line in (ROOT/'.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);os.environ.setdefault(key,value.strip().strip('\"\''))
    root=(ROOT/args.output).resolve()
    if not root.is_relative_to(ROOT/'runtime'):raise ValueError('raw_path_must_be_runtime')
    root.mkdir(parents=True,exist_ok=True)
    report={'period_start':args.start,'period_end':args.end,'stations':[], 'applied_to_service':False}
    catalog={str(s['source_station_id']):s for s in json.loads((ROOT/'data/national_stations_gims.json').read_text())['accepted']}
    for station in args.station:
        metadata=catalog.get(station)
        if not metadata:raise ValueError('unknown_catalog_station')
        folder=root/station
        result=collect_kwater(args.start,args.end,station,output_dir=folder)
        item={'source_station_id':station,'name':metadata['name'],
            'latitude':metadata['latitude'],'longitude':metadata['longitude'],
            'raw_sources':[{'file':str((folder/r['file']).relative_to(ROOT)),
                'sha256':r['raw_sha256']} for r in result['raw_pages']]}
        report['stations'].append(item)
        (root/'readiness.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'source_station_id':station,'raw_pages':len(item['raw_sources']),
            'status':'raw_collected_not_training_approved'}),flush=True)
    print('report:',str((root/'readiness.json').relative_to(ROOT)))
if __name__=='__main__':main()
