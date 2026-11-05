"""Reproduce Hub 1047 food-class models and a temporal evaluation on a CPU."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
from jeju_agent.dining_model import train_dining


if __name__ == "__main__":
    started = time.perf_counter()
    result = train_dining(ROOT / "data_raw/hub/hub_1047_5831.csv", ROOT / "models_dining")
    print(json.dumps({"dataset_id": "1047", "source": result["source"], "split": result["split"],
                      "selection": result["selection"],
                      "test_mae_percentage_points": result["test"]["model"]["mae_percentage_points"],
                      "baseline_mae_percentage_points": result["test"]["same_fit_mean"]["mae_percentage_points"],
                      "improvement_percent": result["improvement_vs_same_fit_mean_percent"],
                      "seconds": round(time.perf_counter() - started, 4)}, ensure_ascii=False, indent=2))
