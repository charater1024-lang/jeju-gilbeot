"""Render one source-grounded answer per tourism/food source record."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from jeju_agent.chatbot import build_chatbot
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args()
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(build_chatbot(args.root),ensure_ascii=False,indent=2))
