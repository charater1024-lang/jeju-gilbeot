"""Explicit, local neural retrieval over authenticated official guide excerpts.

The encoder only ranks existing records. It never generates visitor information,
changes tourist eligibility, or makes a current-operation/individual-preference
claim. The optional CPU runtime is loaded only after this feature is requested.
"""
from functools import lru_cache
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
from threading import RLock

from .assistant_search import (
    HUB_PLACES, PLACE_REQUEST_SUFFIX, UNVERIFIABLE, _attraction_result,
    _evidence, _request_terms, _words,
)
from .discovery import REGIONS
from .place_trust import place_trust, trust_request, _verified_request_guide
from .tourism_access import approved_places

MODEL_DIRECTORY = 'models_semantic'
RUNTIME_DIRECTORY = 'vendor/semantic'
_IMPORT_LOCK = RLock()
_ENGINE_LOCK = RLock()
_SHA = re.compile(r'[0-9a-f]{64}')
# These are separate product tasks with information not established by this
# guide-only index. No matched constraint is silently discarded.
UNSUPPORTED_TOPICS = (
    '맛집', '음식점', '식당', '예약', '무료', '요금', '할인', '날씨', '예보',
    '호텔', '숙소', '버스시간', '배시간', '비행기', '주차', '화장실', '수유실',
    '오늘', '내일', '모레', '서울', '부산', '도쿄',
)


class SemanticModelUnavailable(RuntimeError):
    """A missing/unverified optional model must not trigger fake results."""


def semantic_query_supported(query, region='all'):
    """The same conservative query boundary is used in trials and serving."""
    if (not isinstance(query, str) or len(query) > 160
            or not isinstance(region, str) or region not in REGIONS):
        return False
    compact = ''.join(_words(query))
    return (not any(marker in compact for marker in UNVERIFIABLE + UNSUPPORTED_TOPICS)
            and bool(_request_terms(query, region)))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, maximum):
    with path.open('rb') as source:
        raw = source.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('semantic asset exceeds its bound')
    return raw


def _asset(root, name):
    allowed = (root / MODEL_DIRECTORY).resolve()
    path = (allowed / name).resolve()
    if (not allowed.is_relative_to(root.resolve())
            or not path.is_relative_to(allowed) or path == allowed):
        raise ValueError('invalid semantic asset path')
    return path


def _finite(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _unit(vector, dimension):
    if not isinstance(vector, (list, tuple)) or len(vector) != dimension:
        raise ValueError('invalid semantic embedding shape')
    if not all(_finite(value) for value in vector):
        raise ValueError('invalid semantic embedding values')
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm < 1e-8:
        raise ValueError('empty semantic embedding')
    return tuple(float(value) / norm for value in vector)


def _configuration(root):
    """Read config/corpus actual bytes on every request, independent of mtime."""
    try:
        raw = _read(_asset(root, 'config.json'), 100_000)
        config = json.loads(raw.decode('utf-8'))
        if (not isinstance(config, dict) or config.get('schema_version') != 1
                or type(config.get('schema_version')) is not int
                or config.get('enabled') is not True):
            raise ValueError('semantic feature not enabled')
        for name in ('model_sha256', 'tokenizer_sha256', 'corpus_sha256'):
            if not isinstance(config.get(name), str) or not _SHA.fullmatch(config[name]):
                raise ValueError('invalid semantic asset digest')
        if (not isinstance(config.get('model_id'), str)
                or not 1 <= len(config['model_id']) <= 180
                or not isinstance(config.get('revision'), str)
                or not 1 <= len(config['revision']) <= 180):
            raise ValueError('missing semantic model identity')
        if (type(config.get('embedding_dimension')) is not int
                or not 32 <= config['embedding_dimension'] <= 2048
                or type(config.get('max_length')) is not int
                or not 16 <= config['max_length'] <= 512
                or config.get('query_prefix') != 'query: '
                or not _finite(config.get('score_threshold'))
                or not -1 <= config['score_threshold'] <= 1):
            raise ValueError('unsupported semantic encoder configuration')
        corpus_raw = _read(_asset(root, 'corpus.json'), 8_000_000)
        if _sha(corpus_raw) != config['corpus_sha256']:
            raise ValueError('semantic corpus changed')
        corpus = json.loads(corpus_raw.decode('utf-8'))
        if (not isinstance(corpus, dict) or corpus.get('schema_version') != 1
                or type(corpus.get('schema_version')) is not int
                or corpus.get('model_id') != config['model_id']
                or corpus.get('embedding_dimension') != config['embedding_dimension']
                or not isinstance(corpus.get('items'), list)
                or not 1 <= len(corpus['items']) <= 500):
            raise ValueError('unsupported semantic corpus')
        rows = {}
        for row in corpus['items']:
            if not isinstance(row, dict):
                raise ValueError('invalid semantic corpus record')
            ident = row.get('id')
            if (not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', ident)
                    or ident in rows
                    or not isinstance(row.get('name'), str) or not 1 <= len(row['name']) <= 180
                    or not isinstance(row.get('summary_sha256'), str)
                    or not _SHA.fullmatch(row['summary_sha256'])
                    or not isinstance(row.get('source_url'), str)
                    or not isinstance(row.get('retrieved_at'), str)):
                raise ValueError('invalid semantic corpus identity')
            vector = _unit(row.get('vector'), config['embedding_dimension'])
            # Do not mutate a parsed row or share response objects across calls.
            rows[ident] = dict(row, vector=vector)
        # Model/tokenizer are authenticated when their frozen engine is loaded.
        # Their file signature changes cause a newly authenticated engine.
        model = _asset(root, 'encoder.int8.onnx')
        tokenizer = _asset(root, 'tokenizer.json')
        signature = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                          for path in (model, tokenizer))
        config['_configuration_sha256'] = _sha(raw)
        config['_asset_signature'] = signature
        return config, rows
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise SemanticModelUnavailable('공식 소개 의미 검색 모델을 확인해 주세요. 기본 소개 검색은 계속 사용할 수 있습니다.') from exc


def _dependencies(root):
    """Import an authenticated platform-specific local runtime, never Windows DLLs on Linux."""
    directory = RUNTIME_DIRECTORY if os.name == 'nt' else f'vendor/semantic_linux/cp{sys.version_info.major}{sys.version_info.minor}'
    vendor = (root / directory).resolve()
    gpu_vendor = (root / 'vendor/semantic_gpu').resolve()
    try:
        if not vendor.is_dir() or not vendor.is_relative_to(root.resolve()):
            raise ImportError('optional semantic runtime missing')
        with _IMPORT_LOCK:
            if str(vendor) not in sys.path:sys.path.insert(0, str(vendor))
            packages = [importlib.import_module(name) for name in ('numpy', 'tokenizers')]
            for package in packages:
                if not Path(package.__file__).resolve().is_relative_to(vendor):
                    raise ImportError('semantic package from a different runtime')
            use_gpu = os.name == 'nt' and os.environ.get('JEJU_SEMANTIC_DEVICE','cpu') in {'auto','dml'}
            allowed=[vendor]
            if use_gpu and gpu_vendor.is_dir() and gpu_vendor.is_relative_to(root.resolve()):
                if str(gpu_vendor) not in sys.path:sys.path.insert(0,str(gpu_vendor))
                allowed.append(gpu_vendor)
            try:
                runtime=importlib.import_module('onnxruntime')
            except (ImportError,OSError):
                if not use_gpu:raise
                if str(gpu_vendor) in sys.path:sys.path.remove(str(gpu_vendor))
                for name in list(sys.modules):
                    if name=='onnxruntime' or name.startswith('onnxruntime.'):sys.modules.pop(name,None)
                runtime=importlib.import_module('onnxruntime')
            if not any(Path(runtime.__file__).resolve().is_relative_to(path) for path in allowed):
                raise ImportError('semantic ORT from a different runtime')
            return [*packages,runtime]
    except (ImportError, OSError, AttributeError, ValueError) as exc:
        message = ('의미 검색의 로컬 CPU 실행 패키지가 준비되지 않았습니다. 기본 소개 검색을 사용해 주세요.' if os.name == 'nt' else
                   'Ubuntu 의미 검색 패키지가 준비되지 않았습니다. bash setup_ubuntu.sh로 설치하세요. 기본 소개 검색은 계속 사용할 수 있습니다.')
        raise SemanticModelUnavailable(message) from exc


@lru_cache(maxsize=2)
def _engine(root_string, config_sha, signature, model_sha, tokenizer_sha, length):
    root = Path(root_string)
    try:
        model_raw = _read(_asset(root, 'encoder.int8.onnx'), 2_000_000_000)
        tokenizer_raw = _read(_asset(root, 'tokenizer.json'), 40_000_000)
        if _sha(model_raw) != model_sha or _sha(tokenizer_raw) != tokenizer_sha:
            raise ValueError('semantic model/tokenizer changed')
        numpy, tokenizers, ort = _dependencies(root)
        tokenizer = tokenizers.Tokenizer.from_str(tokenizer_raw.decode('utf-8'))
        tokenizer.enable_truncation(max_length=length)
        tokenizer.enable_padding(pad_id=1, pad_token='<pad>')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(model_raw, sess_options=options,
                                       providers=['CPUExecutionProvider'])
        if {item.name for item in session.get_inputs()} != {'input_ids', 'attention_mask'}:
            raise ValueError('unsupported semantic ONNX inputs')
        return numpy, tokenizer, session, RLock()
    except SemanticModelUnavailable:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, UnicodeError) as exc:
        raise SemanticModelUnavailable('의미 검색 모델의 무결성이나 CPU 실행 형식을 확인해 주세요.') from exc


def _encode(root, config, query):
    try:
        if os.name == 'nt' and os.environ.get('JEJU_SEMANTIC_DEVICE','cpu') in {'auto','dml'}:
            from .semantic_gpu import gpu_encode
            vector=gpu_encode(root,config,query)
            if vector is not None:return vector
        with _ENGINE_LOCK:
            numpy, tokenizer, session, lock = _engine(
                str(root), config['_configuration_sha256'], config['_asset_signature'],
                config['model_sha256'], config['tokenizer_sha256'], config['max_length'])
        with lock:
            tokens = tokenizer.encode(config['query_prefix'] + query)
            feeds = {'input_ids': numpy.asarray([tokens.ids], dtype=numpy.int64),
                     'attention_mask': numpy.asarray([tokens.attention_mask], dtype=numpy.int64)}
            outputs = session.run(None, feeds)
            if not outputs or outputs[0].shape != (1, config['embedding_dimension']):
                raise ValueError('invalid semantic ONNX output')
            return list(outputs[0][0].tolist())
    except SemanticModelUnavailable:
        raise
    except Exception as exc:
        # Native runtime details and local paths are never sent to the browser.
        raise SemanticModelUnavailable('의미 검색을 실행하지 못했습니다. 기본 소개 검색으로 다시 찾아주세요.') from exc


def _verified_candidates(root, keys, region, include_route_restricted):
    prepared = []
    exact = []
    exact_priorities = set()
    for item in approved_places(root):
        hub = item['cross_source']['hub']
        if hub.get('source_url') != HUB_PLACES:
            continue
        names = {''.join(_words(hub['name'])), ''.join(_words(item['cross_source']['osm'].get('name') or ''))}
        priorities = [(index, 0) for index, key in enumerate(keys) if key in names]
        # Even an unusable exact name cannot turn into a different attraction.
        exact_priorities.update(priorities)
        trust = place_trust(root, item, purpose='automatic')
        checks = trust['checks']
        if (checks['identity']['status'] != 'cross_source_verified'
                or checks['official_guide']['status'] != 'official_source_record_verified'):
            continue
        guide = item.get('tourism_guide') or {}
        verified = _verified_request_guide(root, item['id']) or {}
        if (guide.get('summary') != str(verified.get('summary') or '').strip()
                or guide.get('source_url') != verified.get('source_url')
                or guide.get('retrieved_at') != verified.get('retrieved_at')
                or guide.get('source_title') != str(verified.get('source_title') or verified.get('name') or '')[:180]):
            continue
        sources = {source['kind']: source for source in trust['sources']}
        source = sources.get('tourism_guide')
        if (not source or 'hub_registry' not in sources or 'map_record' not in sources
                or not guide.get('summary') or guide['source_url'] != source.get('url')
                or guide['retrieved_at'] != source.get('checked_at')):
            continue
        if checks['specific_review']['status'] != 'excluded_pending_recheck':
            title = ''.join(_words(guide['source_title']))
            priorities.extend((index, 1) for index, key in enumerate(keys) if key == title)
            exact_priorities.update(priorities)
        if ((region != 'all' and item['region'] != region)
                or (not include_route_restricted and not trust['automatic_eligible'])):
            continue
        primary = {'name': '제주데이터허브 여행장소 명부', 'url': HUB_PLACES,
                   'dataset_id': 1349, 'source_date': hub.get('source_date'), 'date_kind': 'hub_reference'}
        secondary = {'name': source['name'], 'url': source['url'],
                     'source_date': source['checked_at'], 'date_kind': 'guide_review'}
        intro = _evidence(guide['summary'], secondary, [])
        result = _attraction_result(item, trust, primary, intro, intro, 'semantic_guide_text')
        result['ranking_method'] = 'verified_guide_neural_embedding'
        prepared.append((item, guide, result))
        if priorities:
            priority = min(priorities)
            index, alias = priority
            evidence = _evidence(guide['source_title'] if alias else ' '.join(filter(None, [hub['name'], hub.get('address')])),
                                 secondary if alias else primary, [keys[index]])
            exact.append((priority, _attraction_result(item, trust, primary, intro, evidence, 'exact_name')))
    return prepared, exact, exact_priorities


def search_semantic(root, query, limit=5, *, region='all', include_route_restricted=True):
    """Explicit official-guide meaning search; score is not a probability."""
    if not isinstance(query, str) or len(query) > 160:
        raise ValueError('장소 검색어는 160자 이내 문자열이어야 합니다.')
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError('검색 개수는 1~12 정수여야 합니다.')
    if not isinstance(region, str) or region not in REGIONS:
        raise ValueError('지원하지 않는 지역입니다.')
    if type(include_route_restricted) is not bool:
        raise ValueError('공식 소개 조회 범위를 확인하세요.')
    words = _words(query)
    compact = ''.join(words)
    if not semantic_query_supported(query, region):
        return []
    place_queries = [compact]
    if len(words) > 1 and words[0] in {'제주', '제주도'}:
        place_queries.append(''.join(words[1:]))
    keys = tuple(dict.fromkeys(key for value in place_queries
                              for key in (value, PLACE_REQUEST_SUFFIX.sub('', value)) if len(key) >= 2))
    root = Path(root).resolve()
    with trust_request(root):
        candidates, exact, priorities = _verified_candidates(root, keys, region, include_route_restricted)
        if priorities:
            best = min(priorities)
            return sorted((result for priority, result in exact if priority == best),
                          key=lambda result: (result['name'], result['id']))[:limit]
        config, corpus = _configuration(root)
        if not candidates:
            return []
        try:
            vector = _unit(_encode(root, config, query.strip()), config['embedding_dimension'])
        except ValueError as exc:
            raise SemanticModelUnavailable('의미 검색 모델의 출력 형식을 확인해 주세요.') from exc
        ranked = []
        for item, guide, result in candidates:
            row = corpus.get(item['id'])
            if (row is None or row['name'] != result['name']
                    or row['summary_sha256'] != _sha(guide['summary'].encode('utf-8'))
                    or row['source_url'] != guide['source_url']
                    or row['retrieved_at'] != guide['retrieved_at']):
                continue
            score = sum(a * b for a, b in zip(vector, row['vector']))
            if score < config['score_threshold']:
                continue
            result['retrieval_score'] = round(score, 6)
            result['score_kind'] = 'cosine_similarity_not_probability'
            result['model_id'] = config['model_id']
            ranked.append((-score, result['name'], result['id'], result))
        return [row[-1] for row in sorted(ranked, key=lambda row: row[:3])[:limit]]
