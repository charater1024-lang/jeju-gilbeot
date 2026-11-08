"""Read-only verification of the latest center configuration and prior files."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    m=json.loads((ROOT/'SERVICE_PATCH_CENTER_20261107.json').read_text(encoding='utf-8'));expected=dict(m['baseline_files']);expected.update({r['path']:r['after_sha256'] for r in m['files']});bad=[]
    for name,digest in expected.items():
        p=(ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or not p.is_file() or '.git' in Path(name).parts:bad.append({'path':name,'reason':'missing or unsafe'});continue
        if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:bad.append({'path':name,'reason':'changed'})
    print(json.dumps({'pass':not bad,'checked_files':len(expected),'patch_files':len(m['files']),'failures':bad},ensure_ascii=True,indent=2));return int(bool(bad))
if __name__=='__main__':raise SystemExit(main())
