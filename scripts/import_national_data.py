"""Normalize explicit local CSV or collect ASOS; does not modify running service."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.national_sources import import_csv, collect_asos, collect_kwater, import_kma_rainy_csv
from backend.external_observations import SourceError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    local=sub.add_parser('csv');local.add_argument('path');local.add_argument('--source',required=True)
    local.add_argument('--kind',choices=['observations','rainy_seasons'],default='observations')
    asos=sub.add_parser('asos');asos.add_argument('--start',required=True);asos.add_argument('--end',required=True)
    asos.add_argument('--station',required=True);asos.add_argument('--raw-dir',required=True)
    kwater=sub.add_parser('kwater');kwater.add_argument('--start',required=True);kwater.add_argument('--end',required=True)
    kwater.add_argument('--station',required=True);kwater.add_argument('--raw-dir',required=True)
    rainy=sub.add_parser('kma-rainy');rainy.add_argument('path');rainy.add_argument('--output-dir',required=True)
    rainy.add_argument('--repository',help='Explicit national SQLite import; never approves station mappings')
    args=parser.parse_args()
    try:
        if args.command=='csv':result=import_csv(args.path,source=args.source,kind=args.kind)
        elif args.command=='kma-rainy':
            result=import_kma_rainy_csv(args.path,output_dir=args.output_dir)
            if args.repository:
                from backend.national_repository import NationalRepository
                repo=NationalRepository(args.repository)
                for item in result['accepted']:repo.add_rainy_period(item)
                result['imported_rows']=len(result['accepted'])
        elif args.command=='asos':result=collect_asos(args.start,args.end,args.station,output_dir=args.raw_dir)
        else:result=collect_kwater(args.start,args.end,args.station,output_dir=args.raw_dir)
    except (SourceError,ValueError,OSError,UnicodeError):
        # No exception or request URL can leak keys or arbitrary provider responses.
        reason=('kwater_auth_required' if not os.getenv('GIMS_API_KEY','').strip() else 'kwater_collection_failed') if args.command=='kwater' else 'collection_or_import_failed'
        print(json.dumps({'status':'blocked','reason':reason}),file=sys.stderr)
        return 2
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
