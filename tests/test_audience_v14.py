"""Serving/provenance checks for the observed-data consumption model."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from jeju_agent.audience_model import CATEGORIES, GROUPS, SERVING_MODEL, _hash, predict_audience

ROOT=Path(__file__).resolve().parents[1]


class AudienceV14Tests(unittest.TestCase):
    def test_serving_model_matches_preserved_observed_source(self):
        model=json.loads((ROOT/'models_audience/audience_model.json').read_text(encoding='utf-8'))
        source=ROOT/'data_raw/hub/hub_1048_5832.csv'
        self.assertEqual(model['source_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(model['selected_serving_model'],SERVING_MODEL)
        self.assertFalse(model['metrics']['selection']['test_used_for_selection'])
        self.assertEqual(model['metrics']['split']['test_fit_scope'],'training_plus_validation_for_all_comparators')
        self.assertEqual(model['metrics']['source']['missing_cells_imputed'],0)

    def test_all_service_months_return_bounded_group_distributions(self):
        path=ROOT/'models_audience/audience_model.json'
        for group in GROUPS:
            distributions=[]
            for month in range(1,13):
                result=predict_audience(path,group,month)
                self.assertEqual(result['model']['selected_serving_model'],SERVING_MODEL)
                self.assertEqual(result['status'],'historical_pattern')
                self.assertEqual(len(result['categories']),len(CATEGORIES))
                self.assertTrue(all(0<=row['share']<=1 for row in result['categories']))
                self.assertAlmostEqual(sum(row['share'] for row in result['categories']),1,places=5)
                distributions.append(tuple(sorted((row['name'],row['share']) for row in result['categories'])))
            self.assertGreater(len(set(distributions)),1)

    def test_rehashed_but_malformed_regression_coefficients_are_rejected(self):
        model=json.loads((ROOT/'models_audience/audience_model.json').read_text(encoding='utf-8'))
        model['coefficients']['resident'][0].pop()
        model.pop('model_sha256');model['model_sha256']=_hash(model)
        with tempfile.TemporaryDirectory() as scratch:
            path=Path(scratch)/'audience.json';path.write_text(json.dumps(model),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'계수'):predict_audience(path,'resident',1)


if __name__=='__main__':unittest.main()
