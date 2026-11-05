"""Train source-561 historical route-code demand models with chronological evaluation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from jeju_agent.route_demand import train_route_demand


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=ROOT / "data_raw/hub/hub_561_5842.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "models_route_demand")
    args = parser.parse_args()
    result = train_route_demand(args.csv, args.output_dir)
    print(json.dumps({"algorithm": result["algorithm"], "config": result["selected_config"], "split": result["split"], "test": {key: value for key, value in result["test"].items() if key not in ("selected", "baseline")}, "selected_metrics": {key: value for key, value in result["test"]["selected"].items() if not key.startswith("by_")}, "serving": result["serving"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
