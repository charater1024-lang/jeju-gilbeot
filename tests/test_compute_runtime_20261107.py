import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
from jeju_agent import compute_runtime as runtime
from jeju_agent import semantic_search as search
from jeju_agent import semantic_gpu as gpu

class ComputeRuntimeTests(unittest.TestCase):
    def test_both_launchers_use_shared_configuration(self):
        import center_app,dev
        for module,argv in [(center_app,['center_app.py','--no-browser']),(dev,['dev.py','run'])]:
            with self.subTest(launcher=module.__name__),patch.object(sys,'argv',argv+['--semantic-device','cpu','--no-road-gpu','--no-model-preload']),patch.object(runtime,'configure_compute',return_value={'provider':'CPUExecutionProvider','status':'ready'}) as setup,patch('jeju_agent.server.serve') as serve:
                self.assertEqual(module.main(),0)
                setup.assert_called_once_with(module.ROOT,'cpu',False,True,False)
                serve.assert_called_once()

    def test_cpu_mode_disables_automatic_road_and_can_skip_preload(self):
        with patch.dict(os.environ,{},clear=True),patch.object(runtime,'preload_models') as pre:
            runtime.configure_compute(Path('.'),'cpu',preload=False)
            self.assertEqual(os.environ['JEJU_SEMANTIC_DEVICE'],'cpu')
            self.assertEqual(os.environ['JEJU_ROAD_GPU'],'0');pre.assert_not_called()

    def test_auto_uses_road_and_runs_preload(self):
        with patch.dict(os.environ,{},clear=True),patch.object(runtime,'_gpu_platform',return_value=True),patch.object(runtime,'preload_models',return_value={'status':'ready'}) as pre:
            self.assertEqual(runtime.configure_compute(Path('.'),'auto'),{'status':'ready'})
            self.assertEqual(os.environ['JEJU_ROAD_GPU'],'1');pre.assert_called_once()

    def test_center_default_does_not_request_gpu(self):
        with patch.dict(os.environ,{},clear=True),patch.object(runtime,'preload_models',return_value={'status':'ready'}) as pre:
            runtime.configure_compute(Path('.'))
            self.assertEqual(os.environ['JEJU_SEMANTIC_DEVICE'],'cpu')
            self.assertEqual(os.environ['JEJU_ROAD_GPU'],'0');pre.assert_called_once()

    def test_default_launcher_arguments_use_center_cpu(self):
        import center_app,dev
        for module,argv in [(center_app,['center_app.py','--no-browser']),(dev,['dev.py','run'])]:
            with self.subTest(launcher=module.__name__),patch.object(sys,'argv',argv+['--no-model-preload']),patch.object(runtime,'configure_compute',return_value={'provider':'not_loaded','status':'not_preloaded'}) as setup,patch('jeju_agent.server.serve'):
                self.assertEqual(module.main(),0)
                setup.assert_called_once_with(module.ROOT,'cpu',False,False,False)

    def test_explicit_no_road_and_bad_options(self):
        with patch.dict(os.environ,{},clear=True):
            runtime.configure_compute(Path('.'),'auto',no_road_gpu=True,preload=False)
            self.assertEqual(os.environ['JEJU_ROAD_GPU'],'0')
            with self.assertRaises(ValueError):runtime.configure_compute(Path('.'),'cuda')
            with self.assertRaises(ValueError):runtime.configure_compute(Path('.'),road_gpu=True,no_road_gpu=True)

    def test_gpu_failure_preloads_the_cpu_encoder_and_reports_cpu(self):
        previous=runtime._PRELOAD
        try:
            with patch.object(search,'_configuration',return_value=({'embedding_dimension':384},{})),patch.object(search,'_encode',return_value=[1.]*384),patch.object(gpu,'compute_status',return_value={'gpu_ready':False}):
                result=runtime.preload_models(Path('.'))
                self.assertEqual(result['provider'],'CPUExecutionProvider');self.assertEqual(result['status'],'ready')
        finally:runtime._PRELOAD=previous

    def test_optional_encoder_failure_does_not_abort_startup(self):
        previous=runtime._PRELOAD
        try:
            with patch.object(search,'_configuration',side_effect=OSError):
                result=runtime.preload_models(Path('.'))
                self.assertEqual(result['status'],'optional_model_unavailable')
        finally:runtime._PRELOAD=previous

    def test_startup_snapshot_is_labeled_separately_from_current_gpu_state(self):
        from jeju_agent import roads
        fake=type('Cache',(),{'currsize':0})()
        with patch.object(roads._load,'cache_info',return_value=fake),patch.object(gpu,'compute_status',return_value={'gpu_ready':False}),patch.object(runtime,'process_memory',return_value={'available':False}):
            result=runtime.runtime_status(Path('.'))
            self.assertEqual(result['preload']['scope'],'startup_result_not_current_state')
            self.assertFalse(result['semantic']['gpu_ready'])

    def test_cpu_selection_skips_gpu_and_preserves_core_encoding_path(self):
        with patch.dict(os.environ,{'JEJU_SEMANTIC_DEVICE':'cpu'}),patch.object(gpu,'gpu_encode') as action,patch.object(search,'_engine',side_effect=RuntimeError('fixture')):
            with self.assertRaises(search.SemanticModelUnavailable):search._encode(Path('.'),{'_configuration_sha256':'','_asset_signature':(), 'model_sha256':'','tokenizer_sha256':'','max_length':256},'공개 예시')
            action.assert_not_called()
