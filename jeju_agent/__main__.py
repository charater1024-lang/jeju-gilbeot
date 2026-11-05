import argparse
import json
from pathlib import Path
from .data_contract import validate, import_data
from .engine import train, recommend

ROOT = Path(__file__).resolve().parent.parent

def main():
    p = argparse.ArgumentParser(description='제주 여행 ML 에이전트 로컬 시제품')
    p.add_argument('command', choices=['train','recommend','serve','validate','import','train-context','forecast-context'])
    p.add_argument('--data',type=Path,default=ROOT/'data')
    p.add_argument('--models',type=Path,default=ROOT/'models')
    p.add_argument('--request',type=Path,default=ROOT/'examples'/'request.json')
    p.add_argument('--target',type=Path,default=ROOT/'data_real')
    p.add_argument('--real',action='store_true')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--open-browser',action='store_true')
    p.add_argument('--csv',type=Path,default=ROOT/'examples'/'region_demand_example.csv')
    p.add_argument('--month',default='2026-01')
    a=p.parse_args()
    if a.command=='train-context':
        from .context_model import train_context
        result=train_context(a.csv,a.models)
    elif a.command=='forecast-context':
        from .context_model import forecast_context
        result=forecast_context(a.models/'model_context.json',a.month)
    elif a.command=='train':
        validate(a.data,require_real=a.real)
        result=train(a.data,a.models)
    elif a.command=='recommend':
        result=recommend(a.data,a.models/'model.json',json.loads(a.request.read_text(encoding='utf-8-sig')))
    elif a.command=='validate': result=validate(a.data,require_real=a.real)
    elif a.command=='import': result=import_data(a.data,a.target)
    else:
        from .server import serve
        if a.open_browser:
            import webbrowser
            from threading import Timer
            Timer(1.0,lambda:webbrowser.open(f'http://127.0.0.1:{a.port}')).start()
        return serve(a.data,a.models,a.port)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
