import os,unittest
from pathlib import Path
from unittest.mock import patch
from jeju_agent import compute_runtime as runtime
from jeju_agent import semantic_search as semantic

class SubmissionPlatformTests(unittest.TestCase):
    def test_linux_rejects_windows_gpu_backend_without_changing_user_system(self):
        for requested in ['cpu','auto','dml']:
            with self.subTest(device=requested),patch.dict(os.environ,{},clear=True),patch.object(runtime,'_gpu_platform',return_value=False),patch.object(runtime,'preload_models') as preload:
                runtime.configure_compute(Path('.'),requested,road_gpu=True,preload=False)
                self.assertEqual(os.environ['JEJU_SEMANTIC_DEVICE'],'cpu')
                self.assertEqual(os.environ['JEJU_ROAD_GPU'],'0')
                preload.assert_not_called()

    def test_linux_memory_uses_rss_and_high_water_not_virtual_size(self):
        fixture='Name:\tpython\nVmSize:\t999999 kB\nVmRSS:\t1234 kB\nVmHWM:\t2345 kB\n'
        with patch.object(Path,'read_text',return_value=fixture):result=runtime._linux_process_memory()
        self.assertTrue(result['available'])
        self.assertEqual(result['working_set_bytes'],1234*1024)
        self.assertEqual(result['peak_working_set_bytes'],2345*1024)
        self.assertFalse(result['private_commit_available'])
        self.assertNotIn('private_commit_bytes',result)

    def test_missing_linux_semantic_packages_have_actionable_message(self):
        root=Path(__file__).resolve().parent/'missing_semantic_runtime_fixture'
        with patch.object(semantic.os,'name','posix'):
            with self.assertRaises(semantic.SemanticModelUnavailable) as raised:semantic._dependencies(root)
            self.assertIn('setup_ubuntu.sh',str(raised.exception))

if __name__=='__main__':unittest.main()
