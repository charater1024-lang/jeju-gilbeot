"""Entry point for the unmodified isolated Windows embeddable runtime."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser(description='Jeju Gilbeot local center app')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--no-browser',action='store_true')
    a=p.parse_args()
    if not 1024<=a.port<=65535:p.error('port must be between 1024 and 65535')
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
