"""Verify the submitted static files without loading a model or changing data."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def main():
    manifest=ROOT/'SUBMISSION_MANIFEST.json'
    if not manifest.is_file():
        print(json.dumps({'pass':False,'error':'SUBMISSION_MANIFEST.json is missing. Extract the entire ZIP.'}));return 1
    data=json.loads(manifest.read_text(encoding='utf-8'));bad=[]
    for row in data['files']:
        path=(ROOT/row['path']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']:bad.append(row['path'])
    print(json.dumps({'pass':not bad,'checked_files':len(data['files']),'failures':bad,'scope':'Submitted static files only; installed Linux venv/vendor and browser/OS data are outside this inventory.'},ensure_ascii=False,indent=2))
    return int(bool(bad))
if __name__=='__main__':raise SystemExit(main())
