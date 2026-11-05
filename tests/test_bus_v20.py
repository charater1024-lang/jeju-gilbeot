import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from jeju_agent.bus_v20 import get_bus_candidate,predict_artifact,validate_artifact

ROOT=Path(__file__).resolve().parents[1]


class BusCandidateTests(unittest.TestCase):
    def test_fixed_tolerance_and_frozen_chronological_selection(self):
        for source in ['512','561']:
            report=json.loads((ROOT/'models_candidates_v20/bus'/source/'experiment_report.json').read_text('utf-8'))
            self.assertTrue(report['selected_by_validation_only'])
            self.assertEqual(report['test_config_read_count'],1)
            self.assertIn('20 percent',report['protocol']['metric'])
            self.assertGreaterEqual(report['protocol']['candidate_count'],90)
            self.assertEqual(len(report['protocol']['split']['fold_dates']),2)
            for fold in report['protocol']['split']['fold_dates']:
                self.assertLess(fold['fit_end'],fold['validation_start'])
                self.assertLess(fold['validation_end'],report['protocol']['split']['test_start'])
            self.assertEqual(report['test']['observations'],847 if source=='512' else 28092)

    def test_actual_candidate_predictions_are_finite_and_have_scope(self):
        for source in ['512','561']:
            result=get_bus_candidate(ROOT,source,'2026-11-04')
            self.assertTrue(result['predictions'])
            self.assertFalse(result['runtime_llm'])
            self.assertEqual(result['estimate_type'],'historical_calendar_pattern')
            self.assertTrue(all(p['prediction']>=0 for p in result['predictions']))
            self.assertEqual(result['fit_period']['end'],'2025-10-26' if source=='512' else '2025-10-19')
            self.assertTrue(result['limitations'])

    def test_standard_library_runtime_has_no_training_dependency(self):
        text=(ROOT/'jeju_agent/bus_v20.py').read_text('utf-8')
        self.assertNotIn('import numpy',text)
        self.assertNotIn('import sklearn',text)

    def test_invalid_date_group_and_source_do_not_silently_fallback(self):
        for source,date,groups in [('512','2026-02-31',None),('512','2026-11-04',['NOT_REAL_GROUP']),('invalid','2026-11-04',None),('561','2026-11-04',[])]:
            with self.subTest(source=source,date=date,groups=groups),self.assertRaises(ValueError):get_bus_candidate(ROOT,source,date,groups)

    def test_candidate_artifact_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            copied=Path(directory);target=copied/'models_candidates_v20/bus/512'
            shutil.copytree(ROOT/'models_candidates_v20/bus/512',target)
            path=target/'candidate_model.json';data=json.loads(path.read_text('utf-8'));data['fit_period']['end']='2026-11-04';path.write_text(json.dumps(data),'utf-8')
            with self.assertRaisesRegex(ValueError,'해시'):get_bus_candidate(copied,'512','2026-11-04')

    def test_finite_parameter_validation(self):
        data=json.loads((ROOT/'models_candidates_v20/bus/512/candidate_model.json').read_text('utf-8'))
        data['scales'][next(iter(data['scales']))]=float('nan')
        with self.assertRaises(ValueError):validate_artifact(data)

    def test_exported_predictions_match_training_implementations(self):
        receipt=json.loads((ROOT/'development_support/bus_v20/portable_parity.json').read_text('utf-8'))
        self.assertTrue(receipt['pass'])
        self.assertGreaterEqual(len(receipt['families']),7)
        self.assertLess(receipt['max_absolute_difference'],1e-6)


if __name__=='__main__':unittest.main()
