"""Read-only verification of proposal files and all retained service artifacts."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    m=json.loads((ROOT/'SERVICE_PATCH_PROPOSAL_20261108.json').read_text(encoding='utf-8'))
    expected=dict(m['baseline_files'])
    expected.update({r['path']:r['after_sha256'] for r in m['files']})
    failures=[]
    for name,sha in expected.items():
        p=(ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or '.git' in Path(name).parts or not p.is_file() or digest(p)!=sha:failures.append(name)
    print(json.dumps({'pass':not failures,'checked_files':len(expected),'documentation_patch_files':len(m['files']),'failures':failures},ensure_ascii=True))
    return int(bool(failures))
if __name__=='__main__':raise SystemExit(main())
