"""Register an evidence-backed immutable API mapping; does not modify historical representatives."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.observation_repository import ObservationRepository

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('file',help='JSON array of mappings including official identity/unit/rain evidence')
    parser.add_argument('--select',action='store_true',help='Explicitly select verified operational mapping versions')
    args=parser.parse_args()
    mappings=json.loads(Path(args.file).read_text())
    if not isinstance(mappings,list):raise ValueError('JSON mapping array required')
    root=Path(os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
    repo=ObservationRepository(root/'external'/'observations.sqlite3')
    for mapping in mappings:
        repo.register_mapping(mapping)
        if args.select:repo.select_mapping(mapping['station_id'],mapping['version'])
    print(json.dumps({'registered':len(mappings),'historical_representatives_changed':False}))
