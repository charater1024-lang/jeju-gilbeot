"""Entry point for the unmodified isolated Windows embeddable runtime."""
import argparse
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser(description='Tamra Ttara local center app')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--no-browser',action='store_true')
    road=p.add_mutually_exclusive_group()
    road.add_argument('--road-gpu',action='store_true',help='Enable optional OpenCL road-node calculations')
    road.add_argument('--no-road-gpu',action='store_true',help='Keep road-node calculations on CPU')
    p.add_argument('--semantic-device',choices=('auto','cpu','dml'),default='cpu',help='Center default: CPU INT8. Select auto/dml to try verified GPU execution')
    p.add_argument('--no-model-preload',action='store_true',help='Load the optional semantic model on its first request')
    a=p.parse_args()
    if not 1024<=a.port<=65535:p.error('port must be between 1024 and 65535')
    from jeju_agent.compute_runtime import configure_compute
    state=configure_compute(ROOT,a.semantic_device,a.road_gpu,a.no_road_gpu,not a.no_model_preload)
    if not a.no_model_preload:
        print('Semantic runtime: '+state['provider']+' ('+state['status']+')',flush=True)
    from jeju_agent.server import serve
    if not a.no_browser:
        import webbrowser
        from threading import Timer
        launch=Timer(1.0,lambda:webbrowser.open(f'http://127.0.0.1:{a.port}'))
        launch.daemon=True;launch.start()
    try:serve(ROOT/'data',ROOT/'models',a.port)
    except OSError as exc:
        if getattr(exc,'winerror',None)==10048 or getattr(exc,'errno',None)==98:
            print('Port is already in use. Close the previous local app, then try again.')
        else:raise
        return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
