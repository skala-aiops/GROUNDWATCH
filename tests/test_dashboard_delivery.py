"""Production static build must coexist with API and the preserved original UI."""
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from serving_app.main import create_app
from serving_app.groundwater_service import GroundwaterService
from tests.test_groundwater_service import FakeManager

@unittest.skipUnless((Path(__file__).parents[1]/'serving_app/dashboard/index.html').exists(), 'requires Docker frontend build')
class DashboardDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.client=TestClient(create_app(GroundwaterService(self.tmp.name,lambda namespace:FakeManager())))
    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()
    def test_entry_keeps_replay_query_and_delivers_react_build(self):
        response=self.client.get('/?replay_id=example',follow_redirects=False)
        self.assertEqual(response.status_code,307)
        self.assertEqual(response.headers['location'],'/dashboard/?replay_id=example')
        html=self.client.get('/dashboard/')
        self.assertEqual(html.status_code,200)
        self.assertIn('id="root"',html.text)
        self.assertIn('/dashboard/assets/',html.text)
    def test_legacy_api_and_geometry_remain_available(self):
        self.assertIn('forecast-rows',self.client.get('/legacy/').text)
        self.assertEqual(self.client.get('/health/live').status_code,200)
        geometry=self.client.get('/dashboard/geo/seoul.json')
        self.assertEqual(geometry.status_code,200)
        self.assertEqual(len(geometry.json()['features']),25)
