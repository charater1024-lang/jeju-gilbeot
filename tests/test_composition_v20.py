import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from jeju_agent.composition_v20 import load_candidate,predict_composition

ROOT=Path(__file__).resolve().parents[1]


class CompositionExperimentTests(unittest.TestCase):
    def test_unpromoted_models_cannot_replace_operating_models(self):
        for ident,group in [('1048','resident'),('1047',None)]:
            with self.subTest(dataset=ident),self.assertRaisesRegex(ValueError,'운영 채택'):
                predict_composition(ROOT,ident,6,audience=group)

    def test_portable_diagnostic_predictions_preserve_full_population(self):
        for ident,groups,count in [('1048',('resident','tourist'),8),('1047',(None,),94)]:
            for group in groups:
                for month in (1,6,12):
                    value=predict_composition(ROOT,ident,month,audience=group,allow_unpromoted=True)
                    self.assertEqual(value['status'],'experimental_not_promoted')
                    self.assertFalse(value['runtime_llm'])
                    self.assertEqual(len(value['categories']),count)
                    self.assertAlmostEqual(sum(row['share'] for row in value['categories']),1)

    def test_protocol_fold_scope_and_frozen_winner_receipts(self):
        protocol=json.loads((ROOT/'development_support/composition_v20/protocol_frozen_before_validation.json').read_text('utf-8'))
        self.assertEqual(protocol['candidate_count'],484)
        for ident in ('1048','1047'):
            dataset=protocol['datasets'][ident]
            self.assertTrue(all(end<start<=finish<dataset['test_start'] for end,start,finish in dataset['rolling_folds']))
            comparison=json.loads((ROOT/f'models_candidates_v20/composition/{ident}_comparison.json').read_text('utf-8'))
            self.assertFalse(comparison['deployment_gate_pass'])
            self.assertFalse(comparison['benchmark_correction']['frozen_winner_changed'])
            self.assertTrue(comparison['benchmark_correction']['validation_mae_guard_exact_pass'])
            self.assertFalse(comparison['selection']['selection_uses_test'])
            self.assertEqual(load_candidate(ROOT,ident)['model_sha256'],comparison['model_sha256'])

    def test_bad_inputs_and_changed_model_are_rejected(self):
        for month in (True,0,13,'6',6.5):
            with self.subTest(month=month),self.assertRaises(ValueError):predict_composition(ROOT,'1048',month,audience='resident',allow_unpromoted=True)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder);(target/'models_candidates_v20/composition').mkdir(parents=True);(target/'data_raw/hub').mkdir(parents=True)
            model_path=target/'models_candidates_v20/composition/1048_candidate_model.json'
            shutil.copyfile(ROOT/'models_candidates_v20/composition/1048_candidate_model.json',model_path)
            shutil.copyfile(ROOT/'data_raw/hub/hub_1048_5832.csv',target/'data_raw/hub/hub_1048_5832.csv')
            model=json.loads(model_path.read_text('utf-8'));model['monthly_profiles']['resident']['1'][0]+=.1
            model_path.write_text(json.dumps(model,ensure_ascii=False),'utf-8')
            with self.assertRaisesRegex(ValueError,'해시'):load_candidate(target,'1048')


if __name__=='__main__':unittest.main()
