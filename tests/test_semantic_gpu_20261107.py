"""GPU contract tests using a fake provider; real-device proof is separate."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from threading import Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jeju_agent import semantic_gpu as gpu


class FakeArray:
    shape = (1, 384)

    def __init__(self, values=None):
        self.values = values or [1 / math.sqrt(384)] * 384

    def __getitem__(self, index):
        return self

    def tolist(self):
        return list(self.values)


class FakeTokenizer:
    def __init__(self, owner):
        self.owner = owner

    def enable_truncation(self, **kwargs):
        self.owner.truncation = kwargs

    def enable_padding(self, **kwargs):
        self.owner.padding = kwargs

    def encode(self, query):
        self.owner.encoded.append(query)
        count = getattr(self.owner, 'query_token_counts', {}).get(query, 2)
        return SimpleNamespace(ids=[1] * count, attention_mask=[1] * count)


class FakeOptions:
    def __init__(self):
        self.overrides = {}

    def add_free_dimension_override_by_name(self, name, value):
        self.overrides[name] = value


class FakeOrt:
    SessionOptions = FakeOptions
    ExecutionMode = SimpleNamespace(ORT_SEQUENTIAL='sequential')

    def __init__(self, gpu_nodes=1, provider=True):
        self.gpu_nodes = gpu_nodes
        self.available = provider
        self.sessions = []
        self.runs = 0
        self.active = 0
        self.max_active = 0
        self.fail_run = False
        self.output = None
        self.input_names = ['input_ids', 'attention_mask']

    def get_available_providers(self):
        return ['DmlExecutionProvider', 'CPUExecutionProvider'] if self.available else ['CPUExecutionProvider']

    def InferenceSession(self, raw, sess_options, providers):
        owner = self

        class Session:
            def get_providers(self):
                return owner.get_available_providers()

            def get_inputs(self):
                return [SimpleNamespace(name=name) for name in owner.input_names]

            def run(self, names, feeds):
                owner.runs += 1
                owner.active += 1
                owner.max_active = max(owner.max_active, owner.active)
                try:
                    time.sleep(0.002)
                    if owner.fail_run:
                        raise RuntimeError(r'C:\secret-machine-path\native.dll driver error')
                    return [owner.output or FakeArray()]
                finally:
                    owner.active -= 1

            def end_profiling(self):
                events = [{'cat': 'Node', 'args': {'provider': 'DmlExecutionProvider', 'op_name': 'DmlFusedNode'}} for _ in range(owner.gpu_nodes)]
                events.append({'cat': 'Node', 'args': {'provider': 'CPUExecutionProvider', 'op_name': 'Shape'}})
                path = Path(sess_options.profile_file_prefix + '.json')
                path.write_text(json.dumps(events), encoding='utf-8')
                owner.profile_path = path
                return str(path)

        session = Session()
        self.sessions.append({'session': session, 'options': sess_options, 'providers': providers, 'raw': raw})
        return session


class SemanticGpuTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='jeju_gpu_unit_')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.assets = self.root / 'models_semantic'
        self.assets.mkdir()
        self.model = b'fixed fake model for interface verification'
        self.tokenizer = b'fixed fake tokenizer'
        sha = lambda value: hashlib.sha256(value).hexdigest()
        self.reference = {'model_id': 'intfloat/multilingual-e5-small', 'revision': 'fixed-revision',
                          'embedding_dimension': 384, 'max_length': 256, 'query_prefix': 'query: ',
                          'model_sha256': 'a' * 64, 'tokenizer_sha256': sha(self.tokenizer),
                          '_configuration_sha256': 'b' * 64}
        self.config = {key: self.reference[key] for key in ['model_id', 'revision', 'embedding_dimension', 'max_length', 'tokenizer_sha256']}
        self.config.update(schema_version=1, enabled=True, model_file='encoder.fp32.onnx',
                           model_sha256=sha(self.model), reference_cpu_model_sha256='a' * 64,
                           provider='DmlExecutionProvider', provider_options={'performance_preference': 'high_performance', 'device_filter': 'gpu'})
        (self.assets / 'encoder.fp32.onnx').write_bytes(self.model)
        (self.assets / 'tokenizer.json').write_bytes(self.tokenizer)
        self.save_config()
        self.tokens = SimpleNamespace(encoded=[])
        tokenizers = SimpleNamespace(Tokenizer=SimpleNamespace(from_str=lambda _: FakeTokenizer(self.tokens)))
        numpy = SimpleNamespace(int64='int64', asarray=lambda data, dtype: data)
        self.ort = FakeOrt()
        for target, value in [('_MODEL_BYTES', len(self.model)), ('_MODEL_SHA', sha(self.model)),
                              ('_ENGINE', None), ('_FAILED_KEY', None),
                              ('_STATUS', {'state': 'not_loaded', 'gpu_ready': False})]:
            p = patch.object(gpu, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'JEJU_SEMANTIC_DEVICE': 'auto'})
        p.start()
        self.addCleanup(p.stop)
        p = patch('jeju_agent.semantic_search._dependencies', side_effect=lambda _: (numpy, tokenizers, self.ort))
        self.dependencies = p.start()
        self.addCleanup(p.stop)

    def save_config(self):
        (self.assets / 'gpu_config.json').write_text(json.dumps(self.config), encoding='utf-8')

    def test_cpu_selection_never_opens_gpu_assets_or_dependencies(self):
        os.environ['JEJU_SEMANTIC_DEVICE'] = 'cpu'
        (self.assets / 'gpu_config.json').unlink()
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '공개 관광지'))
        self.dependencies.assert_not_called()
        self.assertEqual(gpu.compute_status()['reason_code'], 'cpu_selected')

    def test_missing_assets_return_cpu_fallback(self):
        (self.assets / 'gpu_config.json').unlink()
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '공개 관광지'))
        self.assertFalse(gpu.compute_status()['gpu_ready'])
        self.assertEqual(gpu.compute_status()['reason_code'], 'gpu_assets_missing')

    def test_reference_model_or_tokenizer_identity_mismatch_blocks_before_native_work(self):
        for key, value in [('revision', 'different'), ('reference_cpu_model_sha256', 'c' * 64), ('tokenizer_sha256', 'd' * 64), ('embedding_dimension', 768)]:
            with self.subTest(key=key):
                original = copy.deepcopy(self.config)
                self.config[key] = value
                self.save_config()
                self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
                self.assertEqual(gpu.compute_status()['reason_code'], 'configuration_invalid')
                self.config = original
        self.dependencies.assert_not_called()

    def test_untrusted_model_path_or_hash_is_rejected(self):
        for key, value in [('model_file', '../external.onnx'), ('model_sha256', '0' * 64), ('device_filter', 'npu')]:
            original = copy.deepcopy(self.config)
            if key == 'device_filter':
                self.config['provider_options'][key] = value
            else:
                self.config[key] = value
            self.save_config()
            self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
            self.config = original
        self.dependencies.assert_not_called()

    def test_cpu_only_provider_does_not_claim_gpu_ready(self):
        self.ort.available = False
        status = gpu.preload_gpu(self.root, self.reference)
        self.assertFalse(status['gpu_ready'])
        self.assertEqual(status['reason_code'], 'provider_unavailable')
        self.assertEqual(self.ort.sessions, [])

    def test_same_length_model_corruption_fails_sha_before_session_creation(self):
        (self.assets / 'encoder.fp32.onnx').write_bytes(b'x' * len(self.model))
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
        self.assertEqual(gpu.compute_status()['reason_code'], 'asset_digest_mismatch')
        self.assertEqual(self.ort.sessions, [])

    def test_same_length_tokenizer_corruption_fails_sha(self):
        (self.assets / 'tokenizer.json').write_bytes(b'x' * len(self.tokenizer))
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
        self.assertEqual(gpu.compute_status()['reason_code'], 'asset_digest_mismatch')

    def test_provider_registration_without_profiled_gpu_work_is_not_readiness(self):
        self.ort.gpu_nodes = 0
        self.assertFalse(gpu.preload_gpu(self.root, self.reference)['gpu_ready'])
        self.assertEqual(gpu.compute_status()['reason_code'], 'no_profiled_gpu_nodes')
        self.assertFalse(self.ort.profile_path.exists(), 'temporary profile cleaned')

    def test_success_resides_once_and_reuses_session_with_directml_safety_options(self):
        status = gpu.preload_gpu(self.root, self.reference)
        self.assertTrue(status['gpu_ready'])
        self.assertTrue(status['gpu_resident'])
        self.assertEqual(status['dml_kernel_events'], 1)
        self.assertEqual(status['cpu_kernel_events'], 1)
        self.assertFalse(status['steady_state_profiling'])
        for _ in range(2):
            self.assertEqual(len(gpu.gpu_encode(self.root, self.reference, '공개 숲')), 384)
        self.assertEqual(len(self.ort.sessions), 1)
        options = self.ort.sessions[0]['options']
        self.assertFalse(options.enable_mem_pattern)
        self.assertEqual(options.execution_mode, 'sequential')
        self.assertEqual(options.overrides, {'batch': 1, 'sequence': 256})
        self.assertEqual(self.tokens.padding, {'length': 256, 'pad_id': 1, 'pad_token': '<pad>'})
        self.assertEqual(self.tokens.encoded[0], 'query: ' + gpu._PROBE)
        self.assertEqual(gpu.compute_status()['successful_queries'], 2)
        self.assertFalse(self.ort.profile_path.exists())

    def test_model_failure_is_latched_until_assets_or_configuration_change(self):
        self.ort.gpu_nodes = 0
        for _ in range(3):
            self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
        self.assertEqual(len(self.ort.sessions), 1)

    def test_query_native_error_releases_and_does_not_leak_native_path(self):
        self.assertTrue(gpu.preload_gpu(self.root, self.reference)['gpu_ready'])
        self.ort.fail_run = True
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '다른 질문'))
        self.assertEqual(len(self.ort.sessions), 1)
        status = gpu.compute_status()
        self.assertFalse(status['gpu_resident'])
        self.assertNotIn('secret-machine', json.dumps(status))

    def test_nonfinite_output_returns_fallback(self):
        self.assertTrue(gpu.preload_gpu(self.root, self.reference)['gpu_ready'])
        self.ort.output = FakeArray([float('nan')] * 384)
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
        self.assertEqual(gpu.compute_status()['reason_code'], 'output_numbers')

    def test_unsupported_input_signature_is_rejected(self):
        self.ort.input_names = ['unexpected']
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
        self.assertEqual(gpu.compute_status()['reason_code'], 'input_shape')

    def test_configuration_actual_bytes_are_reread_for_resident_model(self):
        self.assertTrue(gpu.preload_gpu(self.root, self.reference)['gpu_ready'])
        before = (self.assets / 'gpu_config.json').stat()
        self.config['enabled'] = False
        self.save_config()
        os.utime(self.assets / 'gpu_config.json', ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
        self.assertFalse(gpu.compute_status()['gpu_ready'])

    def test_concurrent_queries_are_serialized_on_single_dml_session(self):
        self.assertTrue(gpu.preload_gpu(self.root, self.reference)['gpu_ready'])
        results = []
        threads = [Thread(target=lambda: results.append(gpu.gpu_encode(self.root, self.reference, '공개 질문'))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 4)
        self.assertTrue(all(len(value) == 384 for value in results))
        self.assertEqual(self.ort.max_active, 1)
        self.assertEqual(len(self.ort.sessions), 1)

    def test_gpu64_keeps_reference256_and_fixed64_shape(self):
        self.config['gpu_sequence_length'] = 64
        self.save_config()
        status = gpu.preload_gpu(self.root, self.reference)
        self.assertTrue(status['gpu_ready'])
        self.assertEqual(status['max_length'], 256)
        self.assertEqual(status['gpu_sequence_length'], 64)
        self.assertEqual(self.tokens.truncation, {'max_length': 256})
        self.assertEqual(self.tokens.padding['length'], 64)
        self.assertEqual(self.ort.sessions[0]['options'].overrides['sequence'], 64)

    def test_long_gpu64_query_routes_to_CPU_without_slicing_or_releasing_GPU(self):
        self.config['gpu_sequence_length'] = 64
        self.save_config()
        self.tokens.query_token_counts = {'query: ' + '길게 물어보는 원문': 65}
        self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '길게 물어보는 원문'))
        self.assertEqual(self.ort.runs, 1, 'only fixed public initialization probe ran; no truncated query inference')
        status = gpu.compute_status()
        self.assertTrue(status['gpu_ready'])
        self.assertTrue(status['gpu_resident'])
        self.assertEqual(status['last_execution_provider'], 'CPUExecutionProvider')
        self.assertEqual(status['last_execution_reason'], 'query_too_long_for_gpu_shape')
        self.assertEqual(status['last_query_token_count'], 65)
        self.assertEqual(status['cpu_long_query_fallbacks'], 1)
        self.assertTrue(status['cpu_fallback_may_add_resident_model'])
        self.assertIsNone(status['last_query_ms'])
        self.assertEqual(self.tokens.encoded[-1], 'query: 길게 물어보는 원문')
        self.assertEqual(self.tokens.truncation['max_length'], 256)
        self.assertEqual(len(gpu.gpu_encode(self.root, self.reference, '짧은 질문')), 384)
        self.assertEqual(len(self.ort.sessions), 1, 'same resident GPU session reused')
        self.assertEqual(gpu.compute_status()['last_execution_provider'], 'DmlExecutionProvider')

    def test_invalid_GPU_shape_does_not_initialize_native_model(self):
        for length in [True, 0, 15, 257, '64']:
            self.config['gpu_sequence_length'] = length
            self.save_config()
            self.assertIsNone(gpu.gpu_encode(self.root, self.reference, '질문'))
        self.dependencies.assert_not_called()


if __name__ == '__main__':
    unittest.main()
