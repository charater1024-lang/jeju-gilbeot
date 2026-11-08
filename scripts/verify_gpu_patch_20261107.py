"""Read-only verification of the deployed optional neural-search patch."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    manifest=json.loads((ROOT/'SERVICE_PATCH_GPU_20261107.json').read_text(encoding='utf-8'))
    failures=[]
    for row in manifest['files']:
        path=(ROOT/row['path']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            failures.append({'path':row['path'],'reason':'missing or unsafe path'});continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['after_sha256']:
            failures.append({'path':row['path'],'reason':'changed after patch snapshot'})
    print(json.dumps({'pass':not failures,'files':len(manifest['files']),'failures':failures},ensure_ascii=True,indent=2))
    return int(bool(failures))

if __name__=='__main__':raise SystemExit(main())
