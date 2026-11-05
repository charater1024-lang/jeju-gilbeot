from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from jeju_agent.roads import build_roads
if __name__=='__main__':print(json.dumps(build_roads(ROOT),ensure_ascii=True))
