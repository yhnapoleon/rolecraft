import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from career_lab.storage.sessions import digest


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze_selection(path, files, decision):
    path=Path(path)
    if path.exists(): raise ValueError('freeze already exists')
    record=dict(files={str(Path(p).resolve()):sha(p) for p in files.values()},decision=decision,
                frozen_at=datetime.now(timezone.utc).isoformat(),protocol='controlled-v2-freeze-v1')
    record['id']=digest(record)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False,indent=2)
    return record


def verify_freeze(path):
    record=json.loads(Path(path).read_text(encoding='utf-8'))
    if record['id']!=digest({k:v for k,v in record.items() if k!='id'}):raise ValueError('freeze record drift')
    if any(sha(p)!=h for p,h in record['files'].items()):raise ValueError('frozen file drift')
    return record
