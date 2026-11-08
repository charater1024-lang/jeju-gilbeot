"""Project-local Ubuntu CPU semantic runtime installation with pinned wheel hashes."""
import argparse,hashlib,json,os,platform,subprocess,sys,venv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SUPPORTED={(3,11),(3,12),(3,13)}
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def local(relative):
    path=(ROOT/relative).resolve()
    if not path.is_relative_to(ROOT):raise RuntimeError('Installer asset path leaves project')
    return path
def audit_wheelhouse():
    manifest=json.loads(local('requirements/linux_wheel_manifest.json').read_text(encoding='utf-8'))
    bootstrap=json.loads(local('requirements/bootstrap_manifest.json').read_text(encoding='utf-8'))
    records=[r['offline_wheel'] for r in manifest['records']]+[bootstrap]
    for row in records:
        p=local(row['path'])
        if not p.is_file() or p.stat().st_size!=row['bytes'] or digest(p)!=row['sha256']:
            raise RuntimeError('Missing or damaged installation wheel: '+row['path'])
    return manifest,bootstrap
def probe(executable,target):
    script="""import importlib,json,sys
from pathlib import Path
target=Path(sys.argv[1]).resolve();sys.path.insert(0,str(target))
expected={'numpy':'2.3.5','tokenizers':'0.22.2','onnxruntime':'1.31.1'}
seen={}
for name,version in expected.items():
    module=importlib.import_module(name)
    assert module.__version__==version,(name,module.__version__)
    assert Path(module.__file__).resolve().is_relative_to(target),(name,'wrong runtime path')
    seen[name]=module.__version__
ort=importlib.import_module('onnxruntime');assert 'CPUExecutionProvider' in ort.get_available_providers()
print(json.dumps({'pass':True,'libraries':seen,'providers':ort.get_available_providers(),'scope':'runtime imports; model inference is checked separately'}))
"""
    subprocess.run([str(executable),'-B','-c',script,str(target)],check=True,cwd=ROOT)
def main():
    parser=argparse.ArgumentParser(description='Install same-version Linux CPU semantic dependencies inside this project')
    parser.add_argument('--online',action='store_true',help='Explicitly use PyPI for CPython3.11/3.13 instead of the bundled CP312 wheelhouse')
    parser.add_argument('--verify-only',action='store_true',help='Check imports of an already installed runtime')
    parser.add_argument('--audit-wheelhouse',action='store_true',help='Hash-check bundled wheels without installing or importing native packages')
    args=parser.parse_args()
    if args.audit_wheelhouse:
        manifest,_=audit_wheelhouse();print(json.dumps({'pass':True,'verified_wheels':len(manifest['records'])+1}));return 0
    if not sys.platform.startswith('linux') or platform.machine().lower() not in {'x86_64','amd64'}:
        parser.error('This installer supports Ubuntu Linux x86_64. On Windows use run_center.cmd.')
    version=sys.version_info[:2]
    if version not in SUPPORTED:parser.error('Python3.11,3.12 or3.13 is required. Ubuntu24.04 Python3.12 is the offline setup target.')
    if not args.online and version!=(3,12):
        parser.error('Bundled wheels are for Python3.12. Set JEJU_PYTHON=python3.12 or use --online explicitly for3.11/3.13.')
    environment=local('.venv-linux');executable=environment/'bin'/'python'
    target=local(f'vendor/semantic_linux/cp{version[0]}{version[1]}')
    if args.verify_only:
        if not executable.is_file():raise RuntimeError('No project Linux environment. Run bash setup_ubuntu.sh first.')
        probe(executable,target);return 0
    if environment.exists() and not executable.is_file():raise RuntimeError('Incomplete .venv-linux directory; extract a fresh submission folder to install.')
    if not executable.is_file():
        # Ubuntu may omit ensurepip. The verified local pip wheel below supplies pip
        # for this one invocation without installing it into the system interpreter.
        venv.EnvBuilder(with_pip=False,system_site_packages=False).create(environment)
    actual=json.loads(subprocess.check_output([str(executable),'-c','import sys,json;print(json.dumps(list(sys.version_info[:2])))'],text=True))
    if tuple(actual)!=version:raise RuntimeError('Existing .venv-linux uses a different Python version. Extract a fresh submission folder.')
    bootstrap=json.loads(local('requirements/bootstrap_manifest.json').read_text(encoding='utf-8'))
    if digest(local(bootstrap['path']))!=bootstrap['sha256']:raise RuntimeError('pip bootstrap wheel hash mismatch')
    if not args.online:audit_wheelhouse()
    target.parent.mkdir(parents=True,exist_ok=True)
    args_pip=['install','--disable-pip-version-check','--no-warn-script-location','--no-deps','--only-binary=:all:','--require-hashes','--upgrade','--target',str(target),'-r',str(local('requirements/linux-cpu.lock.txt'))]
    if args.online:args_pip.extend(['--index-url','https://pypi.org/simple'])
    else:args_pip.extend(['--no-index','--find-links',str(local('wheelhouse/linux-cp312'))])
    bootstrap_code="import runpy,sys;sys.path.insert(0,sys.argv.pop(1));sys.argv[0]='pip';runpy.run_module('pip',run_name='__main__')"
    environment_vars={key:value for key,value in os.environ.items() if not key.startswith('PIP_')}
    environment_vars.update(PIP_CONFIG_FILE=os.devnull,PYTHONNOUSERSITE='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
    subprocess.run([str(executable),'-B','-c',bootstrap_code,str(local(bootstrap['path'])),*args_pip],check=True,cwd=ROOT,env=environment_vars)
    probe(executable,target)
    print('Ubuntu CPU runtime ready. Start with: bash run_center.sh')
    return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print('Linux setup failed: '+str(exc),file=sys.stderr);raise SystemExit(1)
