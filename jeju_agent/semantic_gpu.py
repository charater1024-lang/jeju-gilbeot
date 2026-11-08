"""Optional, resident DirectML encoder; unverified or failed GPU work returns None.

The CPU INT8 encoder remains the fallback. This module never changes retrieval
thresholds, the authenticated guide corpus, or tourist eligibility. Only a
profiled ONNX session that actually executed DML nodes is reported GPU-ready.
"""
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import RLock
import time

_LOCK = RLock()
_ENGINE = None
_FAILED_KEY = None
_SHA = re.compile(r'[0-9a-f]{64}')
_MODEL_NAME = 'encoder.fp32.onnx'
_MODEL_SHA = 'cf3f713592d6a68b340057834342b44812495437749855e43c9af914e739fe54'
_MODEL_BYTES = 470223896
_PROBE = '제주의 숲과 해안 풍경'
_STATUS = {'state': 'not_loaded', 'gpu_ready': False, 'gpu_resident': False,
           'provider': None, 'backend': 'cpu_int8_fallback',
           'reason_code': 'not_requested', 'reason': 'GPU 의미 검색은 아직 준비하지 않았습니다.'}


class _GpuUnavailable(RuntimeError):
    pass


def _mode():
    value = os.environ.get('JEJU_SEMANTIC_DEVICE', 'auto').strip().lower()
    return value if value in {'auto', 'dml', 'cpu'} else 'cpu'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _set_status(**values):
    global _STATUS
    _STATUS = dict(values)


def _failed(code, reason):
    _set_status(state='unavailable', gpu_ready=False, gpu_resident=False,
                provider=None, backend='cpu_int8_fallback', reason_code=code,
                reason=reason)


def compute_status():
    """Copy JSON-only measured state; no machine paths or native errors leak."""
    with _LOCK:
        return dict(_STATUS, requested_device=_mode())


def _read(path, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise _GpuUnavailable('asset_size')
    return raw


def _configuration(root, reference):
    root = Path(root).resolve()
    directory = (root / 'models_semantic').resolve()
    if not directory.is_relative_to(root):
        raise _GpuUnavailable('asset_path')
    config_path = (directory / 'gpu_config.json').resolve()
    if not config_path.is_relative_to(directory):
        raise _GpuUnavailable('asset_path')
    raw = _read(config_path, 100_000)
    try:
        config = json.loads(raw.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if (type(config.get('schema_version')) is not int or config['schema_version'] != 1
                or config.get('enabled') is not True
                or config.get('provider') != 'DmlExecutionProvider'
                or config.get('model_file') != _MODEL_NAME
                or config.get('model_sha256') != _MODEL_SHA):
            raise ValueError('unsupported GPU configuration')
        if any(config.get(key) != reference.get(key) for key in
               ['model_id', 'revision', 'embedding_dimension', 'max_length', 'tokenizer_sha256']):
            raise ValueError('encoder identity mismatch')
        if (config.get('reference_cpu_model_sha256') != reference.get('model_sha256')
                or not _SHA.fullmatch(config.get('reference_cpu_model_sha256') or '')
                or type(config.get('embedding_dimension')) is not int
                or config['embedding_dimension'] != 384
                or type(config.get('max_length')) is not int or not 16 <= config['max_length'] <= 512
                or reference.get('query_prefix') != 'query: '):
            raise ValueError('encoder reference mismatch')
        sequence_length = config.get('gpu_sequence_length', config['max_length'])
        if type(sequence_length) is not int or not 16 <= sequence_length <= config['max_length']:
            raise ValueError('GPU sequence length')
        provider_options = config.get('provider_options', {})
        allowed = {'device_id', 'performance_preference', 'device_filter'}
        if not isinstance(provider_options, dict) or set(provider_options) - allowed:
            raise ValueError('provider options')
        if 'device_id' in provider_options and (not isinstance(provider_options['device_id'], str)
                or not re.fullmatch(r'\d{1,2}', provider_options['device_id'])):
            raise ValueError('device id')
        if provider_options.get('performance_preference', 'high_performance') not in {'default', 'high_performance', 'minimum_power'}:
            raise ValueError('performance preference')
        if provider_options.get('device_filter', 'gpu') != 'gpu':
            raise ValueError('GPU device filter')
        model = (directory / _MODEL_NAME).resolve()
        tokenizer = (directory / 'tokenizer.json').resolve()
        if any(not p.is_relative_to(directory) for p in (model, tokenizer)):
            raise ValueError('asset path')
        signature = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in (model, tokenizer))
        if model.stat().st_size != _MODEL_BYTES:
            raise ValueError('model size')
        key = (str(root), _sha(raw), reference.get('_configuration_sha256'),
               reference['model_sha256'], reference['tokenizer_sha256'], signature)
        return config, key, model, tokenizer
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise _GpuUnavailable('configuration_invalid') from exc


def _feed_tokens(numpy, tokens):
    return {'input_ids': numpy.asarray([tokens.ids], dtype=numpy.int64),
            'attention_mask': numpy.asarray([tokens.attention_mask], dtype=numpy.int64)}


def _feeds(numpy, tokenizer, prefix, query):
    return _feed_tokens(numpy, tokenizer.encode(prefix + query))


def _vector(outputs, dimension):
    if not outputs or outputs[0].shape != (1, dimension):
        raise _GpuUnavailable('output_shape')
    vector = outputs[0][0].tolist()
    if len(vector) != dimension or not all(not isinstance(v, bool) and isinstance(v, (float, int)) and math.isfinite(v) for v in vector):
        raise _GpuUnavailable('output_numbers')
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm < 1e-8:
        raise _GpuUnavailable('output_empty')
    return [float(v) for v in vector]


def _profile(path):
    path = Path(path)
    events = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(events, list):
        raise _GpuUnavailable('profile_invalid')
    providers = Counter()
    operations = Counter()
    for event in events:
        if not isinstance(event, dict) or event.get('cat') != 'Node':
            continue
        args = event.get('args')
        if not isinstance(args, dict):
            continue
        provider = args.get('provider')
        if not isinstance(provider, str):
            continue
        providers[provider] += 1
        if provider == 'DmlExecutionProvider':
            operations[str(args.get('op_name', 'unknown'))] += 1
    if not providers['DmlExecutionProvider']:
        raise _GpuUnavailable('no_profiled_gpu_nodes')
    return {'dml_kernel_events': providers['DmlExecutionProvider'],
            'cpu_kernel_events': providers['CPUExecutionProvider'],
            'dml_operations': dict(sorted(operations.items())),
            'gpu_execution_profiled': True,
            'steady_state_profiling': False}


def _build(root, reference, gpu_config, key, model_path, tokenizer_path):
    # Lazy circular import: the caller chooses one ORT wheel for the process.
    from .semantic_search import _dependencies
    started = time.perf_counter()
    numpy, tokenizers, ort = _dependencies(root)
    if 'DmlExecutionProvider' not in ort.get_available_providers():
        raise _GpuUnavailable('provider_unavailable')
    model_raw = _read(model_path, _MODEL_BYTES)
    tokenizer_raw = _read(tokenizer_path, 40_000_000)
    if _sha(model_raw) != _MODEL_SHA or _sha(tokenizer_raw) != reference['tokenizer_sha256']:
        raise _GpuUnavailable('asset_digest_mismatch')
    tokenizer = tokenizers.Tokenizer.from_str(tokenizer_raw.decode('utf-8'))
    length = reference['max_length']
    gpu_length = gpu_config.get('gpu_sequence_length', length)
    tokenizer.enable_truncation(max_length=length)
    # Padding to a smaller fixed GPU shape never changes the original 256-token
    # truncation boundary. Longer encodings are routed intact to the CPU path.
    tokenizer.enable_padding(length=gpu_length, pad_id=1, pad_token='<pad>')
    options = ort.SessionOptions()
    options.enable_mem_pattern = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.add_free_dimension_override_by_name('batch', 1)
    options.add_free_dimension_override_by_name('sequence', gpu_length)
    options.enable_profiling = True
    with TemporaryDirectory(prefix='jeju_gpu_probe_') as temporary:
        options.profile_file_prefix = str(Path(temporary) / 'semantic_probe')
        provider_options = dict(gpu_config.get('provider_options') or
                                {'performance_preference': 'high_performance', 'device_filter': 'gpu'})
        session = ort.InferenceSession(model_raw, sess_options=options,
                                       providers=[('DmlExecutionProvider', provider_options), 'CPUExecutionProvider'])
        del model_raw
        if 'DmlExecutionProvider' not in session.get_providers():
            raise _GpuUnavailable('provider_not_registered')
        if {item.name for item in session.get_inputs()} != {'input_ids', 'attention_mask'}:
            raise _GpuUnavailable('input_shape')
        probe = _feeds(numpy, tokenizer, reference['query_prefix'], _PROBE)
        probe_started = time.perf_counter()
        _vector(session.run(None, probe), reference['embedding_dimension'])
        probe_ms = (time.perf_counter() - probe_started) * 1000
        profile_path = Path(session.end_profiling()).resolve()
        if not profile_path.is_relative_to(Path(temporary).resolve()):
            raise _GpuUnavailable('profile_path')
        profile = _profile(profile_path)
    engine = {'key': key, 'numpy': numpy, 'tokenizer': tokenizer, 'session': session,
              'prefix': reference['query_prefix'], 'dimension': reference['embedding_dimension'],
              'sequence_length': gpu_length}
    _set_status(state='ready', gpu_ready=True, gpu_resident=True, backend='directml_fp32',
                provider='DmlExecutionProvider', reason_code='profiled_gpu_execution',
                reason='실제 DirectML 커널 실행을 확인한 모델이 GPU에 상주합니다.',
                model_id=reference['model_id'], model_sha256=_MODEL_SHA, model_bytes=_MODEL_BYTES,
                max_length=length, gpu_sequence_length=gpu_length, fixed_batch_size=1,
                initialized_ms=round((time.perf_counter() - started) * 1000, 3),
                probe_ms=round(probe_ms, 3), successful_queries=0,
                cpu_long_query_fallbacks=0, last_execution_provider='DmlExecutionProvider',
                last_execution_reason='initialization_probe', **profile)
    return engine


def _get_engine(root, reference):
    global _ENGINE, _FAILED_KEY
    if _mode() == 'cpu':
        _ENGINE = None
        _FAILED_KEY = None
        _set_status(state='disabled', gpu_ready=False, gpu_resident=False,
                    provider=None, backend='cpu_int8', reason_code='cpu_selected',
                    reason='CPU 의미 검색을 선택했습니다.')
        return None
    gpu_config, key, model_path, tokenizer_path = _configuration(root, reference)
    if _ENGINE is not None and _ENGINE['key'] == key:
        return _ENGINE
    if _FAILED_KEY == key:
        return None
    _ENGINE = None
    try:
        _ENGINE = _build(Path(root), reference, gpu_config, key, model_path, tokenizer_path)
        _FAILED_KEY = None
        return _ENGINE
    except Exception:
        _FAILED_KEY = key
        raise


def gpu_encode(root, config, query):
    """Encode a supported query, or return None so the caller uses its CPU path."""
    global _ENGINE, _FAILED_KEY
    with _LOCK:
        try:
            engine = _get_engine(root, config)
            if engine is None:
                return None
            started = time.perf_counter()
            tokens = engine['tokenizer'].encode(engine['prefix'] + query)
            if len(tokens.ids) > engine['sequence_length']:
                _STATUS.update(last_execution_provider='CPUExecutionProvider',
                               last_execution_reason='query_too_long_for_gpu_shape',
                               last_query_token_count=len(tokens.ids), last_query_ms=None,
                               cpu_fallback_may_add_resident_model=True)
                _STATUS['cpu_long_query_fallbacks'] += 1
                return None
            vector = _vector(engine['session'].run(None, _feed_tokens(engine['numpy'], tokens)), engine['dimension'])
            _STATUS['last_query_ms'] = round((time.perf_counter() - started) * 1000, 3)
            _STATUS['successful_queries'] += 1
            _STATUS.update(last_execution_provider='DmlExecutionProvider',
                           last_execution_reason='gpu_encoded', last_query_token_count=len(tokens.ids))
            return vector
        except Exception as exc:
            if _ENGINE is not None:
                _FAILED_KEY = _ENGINE['key']
            _ENGINE = None
            code = str(exc) if isinstance(exc, _GpuUnavailable) else 'gpu_assets_missing' if isinstance(exc, FileNotFoundError) else 'native_gpu_error'
            _failed(code, 'GPU 의미 검색 준비 또는 실행에 실패해 CPU 의미 검색으로 전환합니다.')
            return None


def preload_gpu(root, config):
    """Initialize and profile one resident session without any user/location data."""
    global _ENGINE
    with _LOCK:
        try:
            _get_engine(root, config)
        except Exception as exc:
            _ENGINE = None
            code = str(exc) if isinstance(exc, _GpuUnavailable) else 'gpu_assets_missing' if isinstance(exc, FileNotFoundError) else 'native_gpu_error'
            _failed(code, 'GPU 모델을 미리 준비하지 못해 CPU 의미 검색을 사용할 수 있습니다.')
        return compute_status()
