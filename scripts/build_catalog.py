from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from jeju_agent.catalog_store import build_store
if __name__=='__main__': print(json.dumps(build_store(ROOT),ensure_ascii=False,indent=2))
