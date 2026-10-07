"""Consistent SQLite online backups plus immutable model/CSV inventory; no secret values."""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def backup(root, destination):
    root=Path(root).resolve();destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=False)
    databases=[]
    for path in sorted(root.rglob('*.sqlite3')):
        if 'backups' in path.relative_to(root).parts:
            continue
        target=destination/path.relative_to(root)
        target.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as source,sqlite3.connect(target) as output:
            source.backup(output)
            tables=[r[0] for r in output.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            counts={table:output.execute('SELECT COUNT(*) FROM "'+table.replace('"','""')+'"').fetchone()[0] for table in tables}
            integrity=output.execute('PRAGMA integrity_check').fetchone()[0]
        databases.append({'path':str(path.relative_to(root)),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                          'counts':counts,'integrity':integrity})
    artifacts=[]
    for folder in ('models','datasets'):
        for path in sorted((root/folder).rglob('*')):
            if path.is_file():
                artifacts.append({'path':str(path.relative_to(root)),'bytes':path.stat().st_size,
                                  'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    report={'created_at':datetime.now(timezone.utc).isoformat(),'databases':databases,'artifacts':artifacts,
            'note':'DB backup is consistent. Model/data artifacts are inventoried, originals remain on persistent volume.'}
    (destination/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    root=Path(os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
    target=root/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    result=backup(root,target)
    print(json.dumps({'backup':str(target),'databases':len(result['databases']),
                      'artifacts':len(result['artifacts']),'integrity':all(d['integrity']=='ok' for d in result['databases'])}))
