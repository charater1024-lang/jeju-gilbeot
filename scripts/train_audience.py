"""Reproduce v14 observed-data consumption fitting and evaluation."""
from pathlib import Path
import json
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
for stream in [sys.stdout,sys.stderr]:
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
from jeju_agent.audience_model import train_audience

if __name__=='__main__':
    started=time.perf_counter()
    result=train_audience(ROOT/'data_raw/hub/hub_1048_5832.csv',ROOT/'models_audience')
    print(json.dumps({'source_id':result['source_id'],'source_sha256':result['source']['source_sha256'],
                     'selection':result['selection'],'validation_model':result['validation']['model'],
                     'test':result['test'],'improvement':result['improvement_vs_same_fit_baseline'],
                     'seconds':round(time.perf_counter()-started,4),
                     'full_metrics':'models_audience/audience_metrics.json'},ensure_ascii=False,indent=2))
