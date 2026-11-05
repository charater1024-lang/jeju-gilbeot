"""Create fictional places and synthetic visit counts for a reproducible demo.

This is never a downloader. No row in this output is a real venue observation.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
from pathlib import Path
import random


def generate(data_dir: Path) -> dict:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261026)
    areas = [("제주시권", 33.486, 126.515), ("애월권", 33.457, 126.344), ("조천권", 33.523, 126.667), ("서귀포권", 33.252, 126.557), ("성산권", 33.442, 126.884), ("안덕권", 33.275, 126.345)]
    categories = [("tourism", "가상 해안 산책지", "자연|바다|산책|nature|sea|walk", 65, 0, 480, 1140), ("restaurant", "가상 제주 식당", "음식|한식|restaurant|food", 55, 14000, 660, 1260), ("cafe", "가상 전망 카페", "카페|휴식|바다|cafe|sea", 40, 7000, 600, 1200), ("experience", "가상 실내 체험관", "실내|문화|가족|indoor|culture|family", 80, 12000, 540, 1080), ("tourism", "가상 숲 산책지", "자연|숲|산책|nature|forest|walk", 70, 3000, 480, 1080)]
    pois = []
    for region_idx, (region, lat, lon) in enumerate(areas):
        for cat_idx, (category, name, tags, stay, cost, opened, closed) in enumerate(categories):
            index = len(pois) + 1
            pois.append({"poi_id": f"DEMO{index:03}", "name": f"[가상] {region} {name} {cat_idx + 1}", "category": category, "region": region, "latitude": round(lat + rng.uniform(-0.022, 0.022), 6), "longitude": round(lon + rng.uniform(-0.025, 0.025), 6), "tags": tags, "indoor": int(category in {"restaurant", "cafe", "experience"}), "stay_minutes": stay, "cost_krw": cost, "open_minute": opened, "close_minute": closed, "source_id": "SYNTHETIC_POI_V1"})
    with (data_dir / "pois.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pois[0]))
        writer.writeheader()
        writer.writerows(pois)
    start, end = dt.date(2026, 5, 1), dt.date(2026, 10, 25)
    rows = []
    base = {poi["poi_id"]: rng.uniform(30, 320) for poi in pois}
    for offset in range((end - start).days + 1):
        day = start + dt.timedelta(days=offset)
        for poi in pois:
            phase = day.weekday() * 2 * math.pi / 7
            yearphase = (day.timetuple().tm_yday - 1) * 2 * math.pi / 365.25
            log_visits = math.log1p(base[poi["poi_id"]]) - 0.12 * math.sin(phase) - 0.15 * math.cos(phase) + 0.22 * math.sin(yearphase) + 0.12 * math.cos(yearphase) + 0.08 * offset / 365.25 + rng.gauss(0, 0.10)
            rows.append({"date": day.isoformat(), "poi_id": poi["poi_id"], "visits": round(math.expm1(log_visits)), "source_id": "SYNTHETIC_DEMAND_V1"})
    with (data_dir / "demand.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "poi_id", "visits", "source_id"])
        writer.writeheader()
        writer.writerows(rows)
    metadata = {"synthetic": True, "seed": 20261026, "purpose": "기능·재현성 검증 전용 합성 데이터", "disclaimer": "실제 제주 음식점·장소·관측 방문량·영업시간·가격이 아닙니다. 실제 데이터가 확보되기 전의 개발 검증용입니다.", "poi_count": len(pois), "demand_rows": len(rows), "start_date": start.isoformat(), "end_date": end.isoformat(), "source_ids": ["SYNTHETIC_POI_V1", "SYNTHETIC_DEMAND_V1"]}
    (data_dir / "demo_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = parser.parse_args()
    print(json.dumps(generate(args.data_dir), ensure_ascii=False, indent=2))
