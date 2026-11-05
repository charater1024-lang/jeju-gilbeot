"""Fit and evaluate the source 512 historical bus-ticket pattern model offline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jeju_agent.mobility_model import train_mobility


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=ROOT / "data_raw" / "hub" / "hub_512_5856.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "models_mobility")
    args = parser.parse_args()
    metrics = train_mobility(args.csv, args.output_dir)
    search = metrics["hyperparameter_search"]
    print(json.dumps({"source_id": metrics["source_id"], "algorithm": metrics["algorithm"], "data_mode": metrics["data_mode"], "scope": metrics["scope"], "observation_period": metrics["observation_period"], "selection": metrics["selection"], "split": metrics["split"], "validation": metrics["validation"], "test": metrics["test"], "serving_selection": metrics["serving_selection"], "hyperparameter_search": {key: value for key, value in search.items() if key != "candidates"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
