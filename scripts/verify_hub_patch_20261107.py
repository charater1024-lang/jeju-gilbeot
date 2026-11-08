"""Read-only verification of the latest Hub patch plus untouched prior files."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    manifest=json.loads((ROOT/'SERVICE_PATCH_HUB_20261107.json').read_text(encoding='utf-8'))
    expected=dict(manifest['baseline_files'])
    expected.update({row['path']:row['after_sha256'] for row in manifest['files']})
    failures=[]
    for name,digest in expected.items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or '.git' in Path(name).parts:
            failures.append({'path':name,'reason':'missing or unsafe'});continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:failures.append({'path':name,'reason':'changed'})
    print(json.dumps({'pass':not failures,'checked_files':len(expected),'patch_files':len(manifest['files']),'failures':failures},ensure_ascii=True,indent=2))
    return int(bool(failures))
if __name__=='__main__':raise SystemExit(main())
