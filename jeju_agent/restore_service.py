"""Rebuild the runnable service from a Git checkout and official public inputs."""
from contextlib import closing, redirect_stdout
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

from .restore_sources import restore_sources, source_paths, source_problems


PACKAGED = (
    'data_raw/osm/jeju_food_overpass.json',
    'data_raw/osm/jeju_tourism_v5.json',
    'data_raw/osm/jeju_roads_v5.json',
    'data_reference/destinations.json',
    'data_reference/model_portfolio_v20.json',
    'data_reference/osm_food_places.json',
    'data_reference/osm_tourism_places.json',
    'data_reference/tourism_guides_v12.json',
)
PHOTOS = (
    'cheonjiyeon.jpg', 'hallasan.jpg', 'hamdeok.jpg', 'hero-jeju.jpg',
    'hyeopjae.jpg', 'jeongbang.jpg', 'osulloc.jpg', 'saryeoni.jpg',
    'seongsan.jpg', 'seopjikoji.jpg', 'udo.jpg',
)
GENERATED = (
    'data_reference/restaurants.json',
    'data_reference/restaurant_profile.json',
    'data_reference/card_industry_month.csv',
    'data_reference/real_model_report.json',
    'data_reference/catalog.sqlite',
    'data_reference/catalog_profile.json',
    'data_reference/parking_reference.json',
    'data_reference/discovery.sqlite',
    'data_reference/discovery_profile.json',
    'data_reference/tourism.sqlite',
    'data_reference/tourism_profile.json',
    'data_reference/tourism_overlap_audit.json',
    'data_reference/chatbot.sqlite',
    'data_reference/chatbot_profile.json',
    'data_reference/roads.sqlite',
    'data_reference/roads_profile.json',
    'data_reference/offline_roads.json',
    'data_reference/travel_context_v18.json',
    'data_raw/hub_v18/BUILD_RECEIPT.json',
    'models_real_context/model_context.json',
    'models_real_context/metrics_context.json',
    'models_discovery/tfidf_model.json',
    'models_tourism/tourism_tfidf.json',
    'models_audience/audience_model.json',
    'models_audience/audience_metrics.json',
    'models_candidates_v23/audience/protocol.json',
    'models_candidates_v23/audience/selection.json',
    'models_candidates_v23/audience/result.json',
    'models_candidates_v23/audience/serving_profile.json',
    'models_dining/dining_model.json',
    'models_dining/dining_metrics.json',
)


def _packaged_problems(root):
    files = PACKAGED + tuple(f'ui/assets/{name}' for name in PHOTOS)
    manifest = json.loads((root / 'SERVICE_MANIFEST_v27.json').read_text(encoding='utf-8'))
    receipts = {item['path']: item for item in manifest['files']}
    problems = []
    for name in files:
        path = root / name
        item = receipts[name]
        if not path.is_file():
            problems.append(f'{name}: Git에 포함된 파일이 없습니다.')
            continue
        with path.open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if path.stat().st_size != item['bytes'] or digest.hexdigest() != item['sha256']:
            problems.append(f'{name}: v27 명세와 다른 파일입니다.')
    return problems


def _build_parking(root):
    source = root / 'data_raw/hub/hub_1349_5802.csv'
    items = []
    with source.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            name = row['장소명'].strip()
            if '주차' not in name:
                continue
            try:
                lat, lon = float(row['위도']), float(row['경도'])
            except (TypeError, ValueError):
                continue
            if not (32.9 <= lat <= 33.7 and 126 <= lon <= 127):
                continue
            address = (row['도로명주소'] or row['지번주소']).strip()
            items.append({
                'id': f'hub1349_parking_{len(items) + 1}', 'name': name,
                'address': address, 'latitude': lat, 'longitude': lon,
                'source_date': row['수정일시'][:10],
                'source_url': 'https://www.jejudatahub.net/data/view/data/1349',
                'classification': 'source_name_contains_parking',
                'is_public_in_source_name': '공영' in name,
                'operating_hours': None, 'price_krw': None, 'available_spaces': None,
            })
    output = root / 'data_reference/parking_reference.json'
    output.write_text(json.dumps({'items': items}, ensure_ascii=False, indent=2), encoding='utf-8')


def _service_report(root, failures):
    from .catalog_store import food_search, parking
    from .chatbot import chat_status
    from .discovery import discovery_recommend
    from .server import operational_check
    from .tourism import search_tourism
    from .travel_context import search_travel_context

    failures = list(failures)
    failures.extend(f'{name}: 생성 파일이 없습니다.' for name in GENERATED if not (root / name).is_file())
    report = {'pass': False, 'failures': failures}
    if failures:
        return report
    try:
        status = operational_check(root)
        if not status['models_ready'] or status['model_count'] != 3:
            failures.append('운영 모델 3종의 검증 자료를 확인하세요.')
        if not status['guides_current'] and not status['guides_overdue']:
            failures.append('공식 관광 안내의 출처 기록을 확인하세요.')
        if not status['road_file_present'] or not chat_status(root, learned_search=False).get('ready'):
            failures.append('도로 또는 상담 색인을 확인하세요.')
        food_search(root, limit=1)
        parking(root)
        search_tourism(root, {'limit': 1})
        discovery_recommend(root, {'limit': 1})
        search_travel_context(root, limit=1)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, sqlite3.Error) as exc:
        failures.append(f'운영 자산 검증 실패: {exc}')
    else:
        report['operation'] = status
    report['pass'] = not failures
    return report


def service_report(root):
    """Check service readiness independently from the historical full archive."""
    root = Path(root).resolve()
    return _service_report(root, _packaged_problems(root) + source_problems(root))


def _build_service(root):
    from scripts import build_travel_context, prepare_reference_data
    from .catalog_store import build_store
    from .chatbot import build_chatbot
    from .discovery import build_discovery
    from .restore_models import restore_models
    from .roads import build_roads
    from .tourism import build_tourism

    steps = (
        ('카드 모델 학습과 고정 평가', restore_models),
        ('공개 음식점·카드 자료 변환', prepare_reference_data.main),
        ('장소와 음식점 색인', build_store),
        ('주차 위치 참고 자료', _build_parking),
        ('음식점 검색 색인', build_discovery),
        ('관광지 교차확인과 검색 색인', build_tourism),
        ('상담 색인', build_chatbot),
        ('도로 그래프', build_roads),
        ('여행 참고 자료', build_travel_context.build),
    )
    with redirect_stdout(sys.stderr):
        for label, build in steps:
            print(f'[복원] {label}', flush=True)
            build(root)


def restore_service(root):
    """Fetch sources and validate newly generated files before installing them."""
    root = Path(root).resolve()
    staging = root / '.restore'
    staging.mkdir(exist_ok=True)
    with closing(sqlite3.connect(staging / 'lock.sqlite', timeout=1)) as lock:
        try:
            lock.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as exc:
            raise RuntimeError('다른 복원 작업이 진행 중이거나 복원 폴더를 열 수 없습니다.') from exc
        packaged_problems = _packaged_problems(root)
        if packaged_problems:
            return {'pass': False, 'failures': packaged_problems}
        print('[복원] 공식 원자료와 체크섬 확인', file=sys.stderr, flush=True)
        sources = restore_sources(root)
        current = _service_report(root, [])
        if current['pass']:
            return dict(current, sources=sources, rebuilt=False)

        with tempfile.TemporaryDirectory(prefix='build-', dir=staging) as temp:
            work = Path(temp)
            shutil.copytree(root / 'config', work / 'config')
            for name in (*PACKAGED, *source_paths(root), 'SERVICE_MANIFEST_v27.json'):
                target = work / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / name, target)
            _build_service(work)
            check = _service_report(work, [])
            if not check['pass']:
                return dict(check, sources=sources, rebuilt=False)
            for name in GENERATED:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(work / name, target)
            return dict(check, sources=sources, rebuilt=True)
