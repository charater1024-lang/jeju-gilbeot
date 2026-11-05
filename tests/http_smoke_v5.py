"""HTTP integration smoke against an already running loopback-only v5 app.

No server is started. Only fixed public-place fixture locations are used, never
device GPS. Models and SQLite files are hashed before and after the requests.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import sqlite3
import time
import traceback
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request


ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Smoke tests do not follow redirects or contact external hosts.")


class Client:
    def __init__(self, base_url):
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or not parsed.port or not 1024 <= parsed.port <= 65535:
            raise ValueError("Use an explicit loopback HTTP URL and port.")
        self.base = base_url.rstrip("/")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.exchanges = []

    def request(self, path, body=None, status=200):
        if not path.startswith("/api/"):
            raise ValueError("Only local API paths are accepted.")
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = Request(self.base + path, data=payload, headers={"Accept": "application/json", "Content-Type": "application/json", "Origin": self.base}, method="POST" if body is not None else "GET")
        start = time.perf_counter()
        try:
            with self.opener.open(request, timeout=30) as response:
                actual, content_type, raw = response.status, response.headers.get("Content-Type", ""), response.read()
        except HTTPError as exc:
            actual, content_type, raw = exc.code, exc.headers.get("Content-Type", ""), exc.read()
        self.exchanges.append({"method": request.method, "path": path, "status": actual, "elapsed_ms": round((time.perf_counter() - start) * 1000, 2)})
        assert actual == status, f"{request.method} {path}: expected {status}, got {actual}: {raw[:200]!r}"
        assert "application/json" in content_type
        return json.loads(raw.decode("utf-8"))


def artifact_hashes(root):
    paths = set()
    for folder in root.glob("models*"):
        if folder.is_dir():
            paths.update(path for path in folder.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    paths.update((root / "data_reference").glob("*.sqlite"))
    return {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def smoke(root=ROOT, base_url="http://127.0.0.1:8769", report_path=None):
    root = Path(root)
    sys.path.insert(0,str(root.resolve()))
    from jeju_agent.place_trust import place_trust
    report_path = Path(report_path) if report_path else root / "docs/http_smoke_v5.json"
    client = Client(base_url)
    before = artifact_hashes(root)
    checks, shared = {}, {}
    tourism_profile=json.loads((root/'data_reference/tourism_profile.json').read_text(encoding='utf-8'))
    expected_tourism=tourism_profile['training_rows']
    assert expected_tourism>0 and tourism_profile['source_overlap_verified'] is True
    assert tourism_profile['kind_counts'].get('reference',0)==0
    with sqlite3.connect(root/'data_reference/tourism.sqlite') as db:
        local_tourism=[json.loads(row[0]) for row in db.execute('SELECT data_json FROM places')]
        alias_ids={row[0] for row in db.execute('SELECT source_id FROM aliases')}
    assert len(local_tourism)==expected_tourism
    assert all(p.get('source_overlap_verified') is True for p in local_tourism)
    def assert_approved(rows):
        for point in rows:
            proof=point['cross_source']
            assert point['kind']=='attraction' and point['source_overlap_verified'] is True
            assert proof['hub']['id'] and proof['osm']['id'] and 0<=proof['distance_m']<=250
    assert_approved(local_tourism)

    def run(name, function):
        start = time.perf_counter()
        try:
            summary = function()
            checks[name] = {"pass": True, "elapsed_ms": round((time.perf_counter() - start) * 1000, 2), "summary": summary}
        except Exception as exc:
            checks[name] = {"pass": False, "elapsed_ms": round((time.perf_counter() - start) * 1000, 2), "error": str(exc), "traceback": traceback.format_exc()}

    def models():
        result = client.request("/api/models-info")
        cards = {card["id"]: card for card in result["cards"]}
        assert set(cards)=={'tourism_tfidf','food_tfidf','audience_distribution','mobility_pattern'}
        assert cards["tourism_tfidf"]["sample_count"] == expected_tourism
        assert cards["food_tfidf"]["sample_count"] == 27056
        audience_metrics=json.loads((root/'models_audience/audience_metrics.json').read_text(encoding='utf-8'))
        assert cards['audience_distribution']['selected_serving_model']==audience_metrics['selection']['selected']
        assert cards['audience_distribution']['selected_test_metrics']==audience_metrics['test']['model' if audience_metrics['selection']['selected']!='audience_mean' else 'baseline']
        mobility_metrics=json.loads((root/'models_mobility/mobility_metrics.json').read_text(encoding='utf-8'))
        assert cards['mobility_pattern']['selected_serving_model']==mobility_metrics['serving_selection']['selected_serving_model']
        assert cards['mobility_pattern']['selected_test_metrics']==mobility_metrics['test']['model' if mobility_metrics['serving_selection']['selected_serving_model']!='weekday_bucket_mean' else 'baseline']
        assert client.request('/api/recommend',{},status=410)['code']=='synthetic_service_removed'
        status=client.request('/api/status')
        assert status['data']['data_mode']=='real_sources' and not status['synthetic_service_enabled']
        return {"cards": len(cards), "algorithms": {key: value["algorithm"] for key, value in cards.items()}}

    run("models_four_real_cards_and_synthetic_endpoint_disabled", models)

    def curated_details():
        featured=client.request('/api/destinations')['items']
        assert featured;assert_approved(featured)
        shared['featured']=featured
        point=featured[0]
        result=client.request('/api/place-details?'+urlencode({'id':point['id']}))
        assert result['available'] and result['item']['id']==point['id'];assert_approved([result['item']])
        assert result['item']['official_source_url'].startswith('https://www.visitjeju.net/')
        return {'id':point['id'],'source':result['item']['source_name'],'approved_featured':len(featured)}

    run("curated_place_details", curated_details)

    def attraction_count():
        result = client.request("/api/tourism", {"limit": 5})
        assert result["total"] == expected_tourism and len(result["items"]) == min(5,expected_tourism)
        assert result["has_more"] == (expected_tourism>5)
        assert_approved(result["items"])
        assert all(item["kind"] == "attraction" for item in result["items"])
        return {"total": result["total"], "shown": len(result["items"])}

    run("tourism_default_classified_count", attraction_count)

    def category_pagination():
        categories={row['value']:row['count'] for row in tourism_profile['available_categories']}
        category=max(categories,key=categories.get);expected=categories[category]
        page_size=max(1,min(5,expected-1))
        first=client.request('/api/tourism',{'category':category,'limit':page_size})
        collected=list(first['items']);cursor=first['next_cursor'];pages=[len(first['items'])]
        while cursor:
            page=client.request('/api/tourism',{'category':category,'limit':page_size,'cursor':cursor})
            assert not {p['id'] for p in collected}&{p['id'] for p in page['items']}
            collected.extend(page['items']);pages.append(len(page['items']));cursor=page['next_cursor']
        assert first['total']==expected and len(collected)==expected;assert_approved(collected)
        candidates=client.request('/api/tourism',{'location':{'latitude':33.506,'longitude':126.492},'radius_km':100,'limit':100})['items']
        shared['tourism_place']=next(p for p in candidates if not p.get('featured') and place_trust(root,p)['automatic_eligible'])
        return {'category':category,'total':expected,'page_sizes':pages,'new_osm_plan_id':shared['tourism_place']['id']}

    run("tourism_category_cursor_pages", category_pagination)

    def osm_details():
        ident = shared["tourism_place"]["id"]
        item = client.request("/api/place-details?" + urlencode({"id": ident}))["item"]
        assert item["id"] == ident and isinstance(item["observed_tags"], dict) and item["observed_tags"]
        assert_approved([item])
        assert item["snapshot_at"] and item["individual_edit_timestamp"]
        actual_description = item["observed_tags"].get("description:ko") or item["observed_tags"].get("description") or ""
        if item.get('tourism_guide_available'):
            assert item['description']==item['tourism_guide']['summary']
            assert item.get('map_description','')==actual_description
            assert 'openstreetmap.org' not in item['tourism_guide']['source_url']
        else:
            assert item.get("description", "") == actual_description
        return {"id": ident, "observed_tag_keys": sorted(item["observed_tags"]), "individual_edit_date": item["individual_edit_timestamp"][:10], "snapshot_at": item["snapshot_at"]}

    run("osm_place_details_raw_fields", osm_details)
    run("unknown_details_returns_404", lambda: {"error_present": bool(client.request("/api/place-details?id=not_a_public_place", status=404).get("error"))})

    def radius():
        point = {"latitude": 33.506, "longitude": 126.492}
        small = client.request("/api/tourism", {"location": point, "radius_km": 5, "limit": 100})
        large = client.request("/api/tourism", {"location": point, "radius_km": 20, "limit": 100})
        absent = client.request("/api/tourism", {"radius_km": 5, "limit": 1})
        assert small["radius_applied"] and large["radius_applied"] and small["total"] < large["total"]
        assert all(item["distance_km"] <= 5 for item in small["items"])
        assert not absent["radius_applied"] and absent["total"] == expected_tourism
        assert_approved(small["items"]+large["items"])
        error = client.request("/api/tourism", {"radius_km": float("inf")}, status=400)
        assert error.get("error")
        return {"5km_total": small["total"], "20km_total": large["total"], "no_origin_radius_applied": absent["radius_applied"], "nonfinite_radius_status": 400}

    run("tourism_radius_and_invalid_input", radius)

    def references():
        result = client.request("/api/tourism", {"kind": "reference", "limit": 3})
        assert result["total"] == 0 and result["items"] == []
        all_sources=client.request("/api/tourism",{"kind":"all","limit":100})
        assert all_sources["total"]==expected_tourism;assert_approved(all_sources["items"])
        return {"unclassified_reference_records": result["total"]}

    run("tourism_references_kept_separate", references)

    def roads():
        result = client.request("/api/offline-roads")
        assert len(result["lines"]) > 1000 and result["license"] == "ODbL-1.0"
        assert all(len(line["coordinates"]) >= 2 for line in result["lines"][:20])
        return {"road_lines": len(result["lines"]), "snapshot_at": result.get("snapshot_at"), "license": result["license"]}

    run("offline_road_geometry_available", roads)

    route_body = {"destination_ids": [next(p["id"] for p in shared["featured"] if not p.get("requires_ferry") and not p.get("requires_access_point"))], "origin": {"latitude": 33.506, "longitude": 126.492}, "destination": {"latitude": 33.506, "longitude": 126.492}}

    def car():
        result = client.request("/api/route-geometry", dict(route_body, transport="car"))
        assert result["kind"] == "road" and len(result["coordinates"]) > 3
        assert result["geometry"]["type"] == "LineString" and result["distance_km"] > 0
        assert result["contains_private_location"] is True
        assert result["privacy"]["precise_location_persisted"] is False
        return {"kind": result["kind"], "road_vertices": len(result["coordinates"]), "distance_km": result["distance_km"], "contains_private_location": result["contains_private_location"]}

    run("car_uses_actual_road_topology", car)

    def walk():
        result = client.request("/api/route-geometry", dict(route_body, transport="walk"))
        assert result["kind"] == "straight_line" and len(result["coordinates"]) == 3
        assert result["contains_private_location"] is True
        assert any("실제 도로" in note for note in result["warnings"])
        public_ids=[p["id"] for p in shared["featured"] if not p.get("requires_ferry") and not p.get("requires_access_point")][:2]
        assert len(public_ids)==2
        public = client.request("/api/route-geometry", {"destination_ids": public_ids, "transport": "walk"})
        assert public["contains_private_location"] is False
        return {"kind": result["kind"], "walk_path_claimed": False, "origin_provided_flag": result["contains_private_location"], "public_ids_only_flag": public["contains_private_location"]}

    run("walk_is_explicitly_straight_line_and_flags_privacy", walk)

    def plan_new_tourism_id():
        ident = shared["tourism_place"]["id"]
        body = {"date": "2026-10-28", "transport": "car", "start_lat": 33.506, "start_lon": 126.492, "end_lat": 33.506, "end_lon": 126.492, "start_minute": 540, "end_minute": 1200, "budget_krw": 100000, "max_stops": 1, "interests": [], "avoid_crowds": False, "destination_ids": [ident], "origin_confirmed": True, "origin_source": "landmark", "origin_label": "공개 기준점 제주공항"}
        result = client.request("/api/plan-destinations", body)
        assert result["status"] == "ok" and result["data_mode"] == "reference"
        assert len(result["stops"]) == 1 and result["stops"][0]["poi_id"] == ident
        return {"status": result["status"], "new_tourism_id": ident, "stops": 1}

    run("new_osm_tourism_id_plans_via_server_lookup", plan_new_tourism_id)
    def manual_origin_guard():
        body={'date':'2026-11-03','transport':'car','start_lat':33.506,'start_lon':126.492,
              'end_lat':33.506,'end_lon':126.492,'destination_ids':[shared['tourism_place']['id']],
              'origin_confirmed':True,'origin_source':'landmark','origin_label':'공개 기준점 제주공항'}
        cases=[('unconfirmed',dict(body,origin_confirmed=False)),
               ('outside_jeju',dict(body,start_lat=37.5)),
               ('nonfinite',dict(body,start_lat=float('nan')))]
        for field in ['start_lat','end_lon']:
            missing=dict(body);missing.pop(field);cases.append(('missing_'+field,missing))
        for name,invalid in cases:
            assert client.request('/api/plan-destinations',invalid,status=400).get('error'),name
        return {'invalid_origin_cases':len(cases),'status':400,'default_airport_applied':False}
    run('manual_origin_must_be_confirmed_and_explicit',manual_origin_guard)
    def legacy_rejected():
        raw_map=json.loads((root/'data_reference/osm_tourism_places.json').read_text(encoding='utf-8'))['items']
        unapproved=next(p for p in raw_map if p['id'] not in alias_ids)
        ident=unapproved['id']
        assert client.request('/api/place-details?'+urlencode({'id':ident}),status=404).get('error')
        assert client.request('/api/route-geometry',{'destination_ids':[ident],'transport':'walk'},status=400).get('error')
        request={'date':'2026-10-29','transport':'car','start_lat':33.506,'start_lon':126.492,'end_lat':33.506,'end_lon':126.492,'start_minute':540,'end_minute':1200,'budget_krw':100000,'max_stops':1,'interests':[],'destination_ids':[ident],'origin_confirmed':True,'origin_source':'landmark','origin_label':'공개 기준점 제주공항'}
        assert client.request('/api/plan-destinations',request,status=400).get('error')
        return {'rejected_legacy_map_id':ident,'details_status':404,'route_and_plan_status':400}
    run('unmatched_legacy_tourism_ids_rejected',legacy_rejected)
    after = artifact_hashes(root)
    unchanged = before == after
    checks["model_and_database_artifacts_immutable"] = {"pass": unchanged, "summary": {"files_checked": len(before), "changed_files": sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))}}
    report = {"pass": all(result["pass"] for result in checks.values()), "checked_at_kst": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(), "base_url": client.base, "checks": checks, "http_exchanges": client.exchanges, "artifact_sha256_before": before, "artifact_sha256_after": after, "artifacts_unchanged": unchanged, "realGPS": False, "real_gps_used": False, "location_fixture": "Fixed public Jeju airport reference; no device GPS or user location is read.", "external_hosts_contacted": False, "additional_server_started": False}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8769")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    result = smoke(arguments.root, arguments.base_url, arguments.report)
    print(json.dumps({"pass": result["pass"], "checks": {key: value["pass"] for key, value in result["checks"].items()}, "http_requests": len(result["http_exchanges"]), "artifacts_unchanged": result["artifacts_unchanged"], "realGPS": False}, ensure_ascii=True, indent=2))
    raise SystemExit(0 if result["pass"] else 1)
