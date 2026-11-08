"""Portable development entry point; works with the isolated bundled Python."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
for stream in [sys.stdout,sys.stderr]:
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')

def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def check(original_transfer=False):
    if not original_transfer and (ROOT/'SUBMISSION_MANIFEST.json').is_file():
        return subprocess.run([sys.executable,'-B',str(ROOT/'scripts'/'verify_submission.py')],cwd=ROOT).returncode
    manifest_path=ROOT/'TRANSFER_MANIFEST.json'
    if not original_transfer:
        for name in ['SERVICE_MANIFEST_v27.json','SERVICE_MANIFEST_v26.json','SERVICE_MANIFEST_v25.json','SERVICE_MANIFEST_v24.json','SERVICE_MANIFEST_v23.json','SERVICE_MANIFEST_v20.json','SERVICE_MANIFEST_v19.json','SERVICE_MANIFEST_v18.json','SERVICE_MANIFEST_v17.json','SERVICE_MANIFEST_v16.json','SERVICE_MANIFEST_v15.json','SERVICE_MANIFEST_v14.json']:
            if (ROOT/name).is_file():manifest_path=ROOT/name;break
    if not manifest_path.is_file():
        print(f'{manifest_path.name} is missing.',file=sys.stderr);return 1
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    failures=[]
    for item in manifest['files']:
        path=(ROOT/item['path']).resolve()
        if not path.is_relative_to(ROOT):failures.append({'path':item['path'],'reason':'unsafe path'});continue
        if not path.is_file():failures.append({'path':item['path'],'reason':'missing'});continue
        if path.stat().st_size!=item['bytes'] or sha256(path)!=item['sha256']:
            failures.append({'path':item['path'],'reason':'content changed or damaged'})
    result={'pass':not failures,'checked_files':len(manifest['files']),'failures':failures,'manifest':manifest_path.name,'note':'Original transfer hashes change after intended edits.' if original_transfer or manifest_path.name=='TRANSFER_MANIFEST.json' else f"Current v{manifest.get('service_version','?')} service files, source snapshots and model artifacts."}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['pass'] else 1

def find_node(explicit=None):
    if explicit:
        path=Path(explicit).expanduser();return str(path) if path.is_file() else None
    candidates=[os.environ.get('CODEX_NODE'),shutil.which('node')]
    profile=os.environ.get('USERPROFILE')
    if profile:candidates.append(str(Path(profile)/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'))
    return next((str(Path(path)) for path in candidates if path and Path(path).is_file()),None)

def test(node=None,python_only=False):
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    scope_file=ROOT/'tests'/'release_scope.json'
    scoped=[]
    if scope_file.is_file():
        declared={row['id']:row['reason'] for row in json.loads(scope_file.read_text(encoding='utf-8'))['skipped_checks']}
        def leaf_cases(part):
            for item in part:
                if isinstance(item,unittest.TestSuite):yield from leaf_cases(item)
                else:yield item
        found=set()
        for case in leaf_cases(suite):
            if case.id() in declared:
                def historical_skip(reason=declared[case.id()]):raise unittest.SkipTest(reason)
                setattr(case,case._testMethodName,historical_skip)
                found.add(case.id());scoped.append(case.id())
        if found!=set(declared):raise ValueError('Release test scope references an unknown test')
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report={'python':{'pass':result.wasSuccessful(),'tests':result.testsRun,'skipped_historical':len(result.skipped),'executed':result.testsRun-len(result.skipped),'scope_file':'tests/release_scope.json' if scoped else None},'ui':{'status':'not_run'}}
    if python_only:
        report['ui']['reason']='Explicit --python-only; UI checks were not run.'
        print(json.dumps(report,ensure_ascii=False));return 0 if result.wasSuccessful() else 1
    executable=find_node(node)
    if not executable:
        report['ui']['reason']='Node not found. Use --node PATH or run inside a Codex environment with Node.'
        print(json.dumps(report,ensure_ascii=False));return 2 if result.wasSuccessful() else 1
    checks=[]
    for path in sorted((ROOT/'tests').glob('ui_*.cjs')):
        p=subprocess.run([executable,str(path)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
        checks.append({'name':path.name,'pass':p.returncode==0,'stdout':p.stdout.strip(),'stderr':p.stderr.strip()})
    for path in sorted((ROOT/'ui').glob('*.js')):
        p=subprocess.run([executable,'--check',str(path)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
        checks.append({'name':'syntax:'+path.name,'pass':p.returncode==0,'stderr':p.stderr.strip()})
    report['ui']={'status':'completed','pass':all(c['pass'] for c in checks),'checks':checks}
    print(json.dumps(report,ensure_ascii=False));return 0 if result.wasSuccessful() and report['ui']['pass'] else 1

def main():
    parser=argparse.ArgumentParser(description='Tamra Ttara transfer verification, tests and local server')
    sub=parser.add_subparsers(dest='command',required=True)
    integrity=sub.add_parser('check')
    mode=integrity.add_mutually_exclusive_group()
    mode.add_argument('--original-transfer',action='store_true',help='Check historical v13 transfer hashes instead of current service manifest')
    mode.add_argument('--service',action='store_true',help='Check assets needed for a restored service')
    sub.add_parser('restore',help='Download pinned public inputs and rebuild operating assets')
    tests=sub.add_parser('test');tests.add_argument('--node');tests.add_argument('--python-only',action='store_true')
    run=sub.add_parser('run');run.add_argument('--port',type=int,default=8765)
    road=run.add_mutually_exclusive_group()
    road.add_argument('--road-gpu',action='store_true',help='Enable optional OpenCL road-node calculations')
    road.add_argument('--no-road-gpu',action='store_true',help='Keep road-node calculations on CPU')
    run.add_argument('--semantic-device',choices=('auto','cpu','dml'),default='cpu')
    run.add_argument('--no-model-preload',action='store_true')
    args=parser.parse_args()
    if (ROOT/'SUBMISSION_MANIFEST.json').is_file() and args.command=='check' and args.service:
        return check()
    if (ROOT/'SUBMISSION_MANIFEST.json').is_file() and args.command=='restore':
        print(json.dumps({'pass':False,'message':'최종 제출 패키지는 자료와 모델을 동봉했습니다. 손상 시 원래 ZIP을 새 폴더에 다시 풀어 주세요. 과거 Git 복구 manifest용 restore는 이 배포본에서 실행하지 않습니다.'},ensure_ascii=False))
        return 2
    if args.command=='restore' or (args.command=='check' and args.service):
        from jeju_agent.restore_service import restore_service, service_report
        try:
            report = restore_service(ROOT) if args.command=='restore' else service_report(ROOT)
        except (OSError, ValueError, RuntimeError) as exc:
            report = {'pass': False, 'failures': [str(exc)]}
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if report['pass'] else 1
    if args.command=='check':return check(args.original_transfer)
    if args.command=='test':return test(args.node,args.python_only)
    if not 1024<=args.port<=65535:parser.error('port must be 1024..65535')
    from jeju_agent.compute_runtime import configure_compute
    state=configure_compute(ROOT,args.semantic_device,args.road_gpu,args.no_road_gpu,not args.no_model_preload)
    if not args.no_model_preload:print('Semantic runtime: '+state['provider']+' ('+state['status']+')',flush=True)
    from jeju_agent.server import serve
    try:serve(ROOT/'data',ROOT/'models',args.port)
    except KeyboardInterrupt:return 0
    return 0

if __name__=='__main__':raise SystemExit(main())
