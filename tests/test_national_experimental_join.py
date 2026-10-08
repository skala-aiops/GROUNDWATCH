"""Audit actual joined candidate data; do not grant operational approval."""
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class ExperimentalJoinAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((ROOT/'data/national_experimental_joined.json').read_text())

    def test_contract_and_date_uniqueness(self):
        self.assertFalse(self.data['operational_approved'])
        self.assertEqual(len(self.data['mappings']),6)
        for mapping in self.data['mappings']:
            self.assertTrue(mapping['source_contract_verified'])
            self.assertFalse(mapping['operational_approved'])
            self.assertFalse(mapping['geographic_representativeness_verified'])
            rows=mapping['observations'];dates=[r['date'] for r in rows]
            self.assertEqual(len(dates),len(set(dates)))
            self.assertEqual(len(rows),mapping['quality']['joined_days'])
            for row in rows:
                self.assertEqual((row['level_unit'],row['level_reference']),('m','elevation'))
                self.assertGreaterEqual(row['rainfall_mm'],0)
                self.assertEqual(len(row['source_revisions']),2)
                self.assertGreater(row['available_at'][:10],row['date'])

    def test_official_name_candidates_have_exact_rainy_identity(self):
        mappings=[m for m in self.data['mappings'] if m['selection_basis']=='official_station_name']
        for mapping in mappings:
            self.assertEqual(mapping['quality']['latest'],280)
            self.assertTrue(mapping['mapping_evidence']['selected_by_name_matches'])
            self.assertEqual(mapping['rainy_region'],'kma_asos:'+mapping['weather_source_station_id'])
            self.assertEqual(len(mapping['rainy_periods']),54)
            self.assertTrue(all(p['source_station_id']==mapping['weather_source_station_id'] for p in mapping['rainy_periods']))
        for mapping in self.data['mappings']:
            if mapping['selection_basis']=='nearest_available_candidate':
                self.assertIsNone(mapping['rainy_region'])
                self.assertTrue(all(r['rainy_season_evaluation_label'] is None for r in mapping['observations']))

if __name__=='__main__':unittest.main()
