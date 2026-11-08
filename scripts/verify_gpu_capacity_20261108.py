"""Read-only verification of archived GPU test and retained project artifacts."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def main():
    m=json.loads((ROOT/'SERVICE_PATCH_GPU_CAPACITY_20261108.json').read_text(encoding='utf-8'))
    expected=dict(m['baseline_files'])
    expected.update({r['path']:r['after_sha256'] for r in m['files']})
    bad=[]
    for name,value in expected.items():
        p=(ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or '.git' in Path(name).parts or not p.is_file() or digest(p)!=value:bad.append(name)
    report=json.loads((ROOT/m['benchmark']['folder']/'summary.json').read_text(encoding='utf-8'))
    for row in report['rows']:
        p=ROOT/m['benchmark']['folder']/'results'/row['stage_file']
        if digest(p)!=row['stage_sha256']:bad.append('raw_stage:'+row['stage_file'])
    passed=not bad and report['valid_stages']==33 and report['performance_requests']==4560 and report['http_and_shape_errors']==0
    print(json.dumps({'pass':passed,'checked_files':len(expected),'patch_files':len(m['files']),'valid_stages':report['valid_stages'],'requests':report['performance_requests'],'http_and_shape_errors':report['http_and_shape_errors'],'failures':bad},ensure_ascii=True))
    return int(not passed)
if __name__=='__main__':raise SystemExit(main())
