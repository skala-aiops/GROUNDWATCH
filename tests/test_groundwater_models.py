"""Model lifecycle checks with a deterministic backend, not accuracy evidence."""
import copy
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from serving_app.groundwater_models import ModelManager, ModelNotReady, TensorFlowBackend, validate_rows


class Backend:
    def __init__(self):
        self.versions, self.aliases, self.calls = {}, {}, []
        self.fail_alias = False
        self.train_offset = 0.0

    def train(self, x, y, validation, **kwargs):
        self.calls.append((copy.deepcopy(x), copy.deepcopy(y), kwargs))
        return {'offset': self.train_offset}

    def predict(self, model, inputs):
        return [row[-1][0] + model['offset'] for row in inputs]

    def register(self, name, model, bundle, directory):
        entries = self.versions.setdefault(name, {})
        version = str(len(entries)+1)
        entries[version] = (copy.deepcopy(model), copy.deepcopy(bundle))
        return version

    def load(self, name, version):
        return copy.deepcopy(self.versions[name][version])

    def alias(self, name):
        return self.aliases.get(name)

    def set_alias(self, name, version):
        if self.fail_alias:
            self.fail_alias = False
            raise RuntimeError('registry unavailable')
        if version is None:
            self.aliases.pop(name, None)
        else:
            self.aliases[name] = version


def rows(count=410, code='11110', start=date(2020, 1, 1)):
    return [{'date': str(start+timedelta(days=i)), 'groundwater_level': i*.1-5,
             'rainfall_mm': float(i % 7), 'station_id': 'official-well-1',
             'district_code': code, 'level_unit': 'm'} for i in range(count)]


META = {'station_id': 'official-well-1', 'level_unit': 'm',
        'dataset_version': 'verified-fixture', 'mapping_version': 'fixed-fixture',
        'manifest_approved': True}


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.backend = Backend()
        self.manager = ModelManager(self.directory.name, backend=self.backend)

    def tearDown(self):
        self.directory.cleanup()

    def train(self, code='11110'):
        return self.manager.train(code, rows(code=code), META)

    def passing_candidate(self, manager=None):
        manager = manager or self.manager
        scaler = manager.list_models()[0]['scaler']
        manager.backend.train_offset = .1 / (scaler['maximum'][0]-scaler['minimum'][0])
        return manager.fine_tune('11110', rows()[-41:])

    def shadow_rows(self):
        return rows(50, start=date(2021, 1, 25))

    def test_live_contract_allows_new_snapshot_but_rejects_changed_source_and_legacy(self):
        live_meta={**META,'training_snapshot_id':'training-v1','feature_contract_id':'contract-v1',
            'preprocessing_version':'strict-v1','rain_source':'kma_asos_sumRn','weather_station_id':'108'}
        self.manager.train('11110',rows(),live_meta)
        self.assertEqual(self.manager.check_ready('11110',{**live_meta,'dataset_version':'new-input-v2'}),'1')
        with self.assertRaisesRegex(ValueError,'weather_station_id'):
            self.manager.check_ready('11110',{**live_meta,'weather_station_id':'109'})
        legacy=ModelManager(self.directory.name+'/legacy',backend=Backend())
        legacy.train('11110',rows(),META)
        with self.assertRaisesRegex(ValueError,'legacy'):
            legacy.check_ready('11110',live_meta)

    def test_temporal_split_scaler_and_identity(self):
        result = self.train()
        self.assertEqual(result['status'], 'promoted')
        self.assertEqual({k:v['count'] for k,v in result['splits'].items()}, {'train':180,'validation':60,'test':60,'replay':90})
        bundle = self.manager.list_models()[0]['versions']['1']
        self.assertAlmostEqual(bundle['scaler']['maximum'][0], 14.9)
        self.assertLess(bundle['splits']['validation']['end'], bundle['splits']['test']['start'])
        result = self.manager.predict('11110', rows()[-20:])
        self.assertEqual(result['model_version'], '1')
        self.assertAlmostEqual(result['prediction'], rows()[-1]['groundwater_level'])
        bad = rows()[-20:]
        for r in bad:
            r['station_id'] = 'another-well'
        with self.assertRaisesRegex(ValueError, 'station_id'):
            self.manager.predict('11110', bad)

    def test_rejects_unapproved_metadata_and_calendar_gaps(self):
        with self.assertRaisesRegex(ValueError, 'approval'):
            self.manager.train('11110', rows(), {**META, 'manifest_approved':False})
        with self.assertRaisesRegex(ValueError, '410'):
            self.manager.train('11110', rows(409), META)
        data = rows()
        data[5]['date'] = data[4]['date']
        with self.assertRaisesRegex(ValueError, 'consecutive'):
            validate_rows(data)

    def test_restart_alias_and_district_isolation(self):
        self.train()
        self.train('11140')
        restored = ModelManager(self.directory.name, backend=self.backend)
        self.assertEqual(restored.predict('11110', rows()[-20:])['model_version'], '1')
        candidate = self.passing_candidate()
        self.manager.evaluate_candidate('11110', candidate['candidate_version'], self.shadow_rows())
        self.assertEqual(self.manager.predict('11110', rows()[-20:])['model_version'], '2')
        self.assertEqual(self.manager.predict('11140', rows(code='11140')[-20:])['model_version'], '1')
        self.assertEqual(self.manager.rollback('11110')['model_version'], '1')

    def test_failed_promotion_preserves_actual_champion(self):
        self.train()
        candidate = self.passing_candidate()
        self.backend.fail_alias = True
        with self.assertRaises(RuntimeError):
            self.manager.evaluate_candidate('11110', candidate['candidate_version'], self.shadow_rows())
        self.assertEqual(self.manager.predict('11110', rows()[-20:])['model_version'], '1')
        restored = ModelManager(self.directory.name, backend=self.backend)
        restored.promote('11110', candidate['candidate_version'])
        self.assertEqual(restored.predict('11110', rows()[-20:])['model_version'], '2')

    def test_shadow_waits_for_new_labels_and_frozen_scaler(self):
        self.train()
        candidate = self.manager.fine_tune('11110', rows()[-41:])
        version = candidate['candidate_version']
        initial = self.manager.list_models()[0]['versions']['1']
        updated = self.manager.list_models()[0]['versions'][version]
        self.assertEqual(initial['scaler'], updated['scaler'])
        old = self.manager.evaluate_candidate('11110', version, rows()[-50:])
        self.assertEqual(old['status'], 'pending')
        new = rows(50, start=date(2021,1,25))
        result = self.manager.evaluate_candidate('11110', version, new)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['metrics']['shadow_candidate']['count'],30)
        self.assertFalse(result['gates']['future_improvement']['passed'])
        self.assertEqual(result['gates']['future_improvement']['limit'],
                         result['metrics']['shadow_champion']['rmse']*.95)
        self.assertEqual(self.manager.predict('11110', rows()[-20:])['model_version'], '1')

    def test_post_promotion_tracking_failure_preserves_success_and_shadow_result(self):
        self.train()
        bundle=self.manager.list_models()[0]
        self.backend.train_offset=.1/(bundle['scaler']['maximum'][0]-bundle['scaler']['minimum'][0])
        candidate=self.manager.fine_tune('11110',rows()[-41:])
        calls=[]
        def record(name,version,result):
            calls.append(result['status'])
            if result['status']=='promoted':raise RuntimeError('tracking unavailable after promotion')
        self.backend.record_evaluation=record
        result=self.manager.evaluate_candidate('11110',candidate['candidate_version'],rows(50,start=date(2021,1,25)))
        self.assertEqual(result['status'],'promoted')
        self.assertTrue(all(g['passed'] for g in result['gates'].values()))
        self.assertEqual(self.manager.current_version('11110'),'2')
        self.assertIn('tracking_warning',result)
        self.assertEqual(self.manager.list_models()[0]['versions']['2']['shadow_result']['status'],'promoted')

    def test_calendar_gap_rejection_is_persisted_for_candidate(self):
        self.train()
        candidate=self.manager.fine_tune('11110',rows()[-41:])
        result=self.manager.reject_candidate('11110',candidate['candidate_version'],'shadow_calendar_gap')
        self.assertEqual(result['status'],'rejected')
        self.assertEqual(self.manager.current_version('11110'),'1')
        self.assertEqual(self.manager.list_models()[0]['versions']['2']['shadow_result']['reason'],'shadow_calendar_gap')

    def test_missing_model_has_no_sample_fallback(self):
        with self.assertRaises(ModelNotReady):
            self.manager.predict('11110', rows()[-20:])
        with self.assertRaisesRegex(ValueError, 'namespace'):
            self.manager.predict('11110', rows()[-20:], namespace='synthetic')

    def test_initial_failed_gate_does_not_serve_registered_candidate(self):
        self.backend.train_offset = 10.0
        result = self.train()
        self.assertEqual(result['status'], 'rejected')
        self.assertFalse(result['gate_passed'])
        self.assertEqual(len(self.manager.list_models()[0]['versions']), 1)
        with self.assertRaises(ModelNotReady):
            self.manager.predict('11110', rows()[-20:])
        with self.assertRaisesRegex(ModelNotReady, 'initial quality gate'):
            self.manager.promote('11110', result['version'])

    def test_unevaluated_pending_and_rejected_candidate_cannot_replace_champion(self):
        self.train()
        before = self.manager.predict('11110', rows()[-20:])
        # A worse model must not change the live weights while being trained.
        self.backend.train_offset = -.01
        candidate = self.manager.fine_tune('11110', rows()[-41:])['candidate_version']
        for observations in (None, rows()[-50:], self.shadow_rows()):
            if observations is not None:
                self.manager.evaluate_candidate('11110', candidate, observations)
            with self.assertRaisesRegex(ModelNotReady, 'shadow quality gate'):
                self.manager.promote('11110', candidate)
            self.assertEqual(self.manager.predict('11110', rows()[-20:]), before)
        restored = ModelManager(self.directory.name, backend=self.backend)
        with self.assertRaises(ModelNotReady):
            restored.promote('11110', candidate)
        self.assertEqual(restored.predict('11110', rows()[-20:]), before)
        self.assertEqual(restored.list_models()[0]['versions'][candidate]['shadow_result']['status'], 'rejected')

    def test_future_improvement_cannot_bypass_historical_guard(self):
        self.train()
        before = self.manager.predict('11110', rows()[-20:])
        scaler = self.manager.list_models()[0]['scaler']
        self.backend.train_offset = .3 / (scaler['maximum'][0]-scaler['minimum'][0])
        candidate = self.manager.fine_tune('11110', rows()[-41:])['candidate_version']
        future = self.shadow_rows()
        for i, row in enumerate(future):
            row['groundwater_level'] = i * .3 - 5
        result = self.manager.evaluate_candidate('11110', candidate, future)
        self.assertEqual(result['status'], 'rejected')
        self.assertTrue(result['gates']['future_improvement']['passed'])
        self.assertFalse(result['gates']['historical_guard']['passed'])
        with self.assertRaises(ModelNotReady):
            self.manager.promote('11110', candidate)
        self.assertEqual(self.manager.predict('11110', rows()[-20:]), before)

    def test_incomplete_or_failed_metrics_cannot_be_promoted_by_pass_flag(self):
        self.train()
        candidate = self.passing_candidate()['candidate_version']
        # Interrupt activation after a real successful evaluation to retain evidence.
        self.backend.fail_alias = True
        with self.assertRaises(RuntimeError):
            self.manager.evaluate_candidate('11110', candidate, self.shadow_rows())
        original = self.manager._state('11110')
        changes = (
            lambda result: result.update(status='rejected'),
            lambda result: result.update(previous_version='999'),
            lambda result: result.update(shadow_start='2020-01-01'),
            lambda result: result['metrics']['shadow_candidate'].update(count=29),
            lambda result: result['metrics']['shadow_candidate'].update(rmse=1),
            lambda result: result['metrics']['historical_guard'].update(rmse=1),
        )
        for change in changes:
            with self.subTest(change=change):
                state = copy.deepcopy(original)
                change(state['versions'][candidate]['shadow_result'])
                self.manager._save('11110', state)
                with self.assertRaises(ModelNotReady):
                    self.manager.promote('11110', candidate)
                self.assertEqual(self.manager.current_version('11110'), '1')

    def test_champion_change_during_evaluation_rejects_stale_candidate(self):
        self.train()
        candidate = self.passing_candidate()['candidate_version']
        original_predict = self.backend.predict
        def switch_champion(model, inputs):
            self.backend.predict = original_predict
            self.train()  # Independently validated initial v3 wins during evaluation.
            return original_predict(model, inputs)
        self.backend.predict = switch_champion
        result = self.manager.evaluate_candidate('11110', candidate, self.shadow_rows())
        self.assertEqual(result['reason'], 'champion_changed')
        self.assertEqual(self.manager.current_version('11110'), '3')
        restored = ModelManager(self.directory.name, backend=self.backend)
        self.assertEqual(restored.list_models()[0]['versions'][candidate]['shadow_result'], result)
        with self.assertRaises(ModelNotReady):
            restored.promote('11110', candidate)

    def test_champion_is_rechecked_after_smoke_before_alias_write(self):
        self.train()
        candidate = self.passing_candidate()['candidate_version']
        original_predict = self.backend.predict
        def switch_during_smoke(model, inputs):
            self.backend.predict = original_predict
            self.train()
            return original_predict(model, inputs)
        def record(name, version, result):
            if result['status'] == 'gate_passed':
                self.backend.predict = switch_during_smoke
        self.backend.record_evaluation = record
        result = self.manager.evaluate_candidate('11110', candidate, self.shadow_rows())
        self.assertEqual(result['reason'], 'champion_changed')
        self.assertEqual(self.manager.current_version('11110'), '3')

    def test_history_write_failure_restores_alias_cache_and_prediction(self):
        self.train()
        before = self.manager.predict('11110', rows()[-20:])
        candidate = self.passing_candidate()['candidate_version']
        original_save = self.manager._save
        def fail_history(code, state):
            if state['champion'] == candidate:
                raise OSError('history unavailable')
            return original_save(code, state)
        self.manager._save = fail_history
        with self.assertRaisesRegex(OSError, 'history unavailable'):
            self.manager.evaluate_candidate('11110', candidate, self.shadow_rows())
        self.assertEqual(self.manager.predict('11110', rows()[-20:]), before)
        self.assertEqual(self.manager._state('11110')['champion'], '1')

    def test_successful_promotion_is_idempotent_and_previous_candidate_can_be_rolled_back(self):
        self.train()
        candidate = self.passing_candidate()['candidate_version']
        result = self.manager.evaluate_candidate('11110', candidate, self.shadow_rows())
        self.assertEqual(result['status'], 'promoted')
        before = self.manager.predict('11110', rows()[-20:])
        restored = ModelManager(self.directory.name, backend=self.backend)
        self.assertEqual(restored.predict('11110', rows()[-20:]), before)
        self.assertEqual(restored.evaluate_candidate('11110', candidate, self.shadow_rows()), result)
        restored.promote('11110', candidate)
        self.assertEqual(len(restored._state('11110')['history']), 2)
        restored.train('11110', rows(), META)
        self.assertEqual(restored.current_version('11110'), '3')
        with self.assertRaisesRegex(ModelNotReady, 'champion_changed'):
            restored.promote('11110', candidate)
        self.assertEqual(restored.rollback('11110', candidate)['status'], 'rolled_back')
        self.assertEqual(restored.predict('11110', rows()[-20:]), before)

    def test_stale_finetuning_is_rejected(self):
        self.train()
        with self.assertRaisesRegex(ValueError, 'new observations'):
            self.manager.fine_tune('11110', rows(41))

    def test_rollback_cannot_promote_unvalidated_registered_candidate(self):
        self.train()
        candidate = self.manager.fine_tune('11110', rows()[-41:])
        with self.assertRaises(ModelNotReady):
            self.manager.rollback('11110', candidate['candidate_version'])
        self.assertEqual(self.manager.predict('11110', rows()[-20:])['model_version'], '1')

    def test_mlflow_missing_champion_alias_distinguished_from_registry_failure(self):
        class RegistryError(Exception):
            error_code = 'INVALID_PARAMETER_VALUE'
        class Client:
            def __init__(self, message):
                self.message = message
            def get_model_version_by_alias(self, name, alias):
                raise RegistryError(self.message)
        backend = TensorFlowBackend('unused', Path(self.directory.name))
        backend._client = lambda: Client('Registered model alias champion not found.')
        self.assertIsNone(backend.alias('GroundWatch_historical_11110'))
        backend._client = lambda: Client('invalid tracking database configuration')
        with self.assertRaises(RegistryError):
            backend.alias('GroundWatch_historical_11110')

    def test_clone_reuses_only_initial_weights_and_isolates_registry_cache(self):
        source = self.train()
        source_bundle = self.manager.list_models()[0]
        target_backend = Backend()
        target = ModelManager(self.directory.name, namespace='replay-fixture', backend=target_backend)
        result = target.clone_from(self.manager, '11110', {**META, 'district_code':'11110'})
        self.assertEqual(result['status'], 'promoted')
        self.assertEqual(result['training_hash'], source_bundle['training_hash'])
        self.assertEqual(result['splits'], source['splits'])
        self.assertEqual(target_backend.calls, [])
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(target.predict('11110', rows()[-20:])['prediction'], self.manager.predict('11110', rows()[-20:])['prediction'])
        candidate = self.passing_candidate(target)
        target.evaluate_candidate('11110', candidate['candidate_version'], self.shadow_rows())
        self.assertEqual(target.predict('11110', rows()[-20:])['model_version'], '2')
        self.assertEqual(self.manager.predict('11110', rows()[-20:])['model_version'], '1')
        with self.assertRaisesRegex(ValueError, 'initial champion'):
            ModelManager(self.directory.name, namespace='third', backend=Backend()).clone_from(target, '11110')
        with self.assertRaisesRegex(ValueError, 'dataset_version'):
            ModelManager(self.directory.name, namespace='fourth', backend=Backend()).clone_from(self.manager, '11110', {**META, 'dataset_version':'different'})

    def test_gap_aware_training_preserves_daily_windows_and_excludes_future_scaler(self):
        data = [r for i,r in enumerate(rows(1000)) if not 220 <= i < 240]
        for record in data:
            if record['date'] >= str(date(2020,1,1)+timedelta(days=890)):
                record['groundwater_level'] = 1000000.
                record['rainfall_mm'] = 1000000.
        metadata = {**META, 'split_policy':'gap_aware',
                    'replay_start':str(date(2020,1,1)+timedelta(days=800))}
        result = self.manager.train('11110', data, metadata)
        self.assertEqual(result['status'], 'promoted')
        self.assertEqual(result['split_policy'], 'gap_aware')
        self.assertFalse(result['splits']['train']['target_dates_continuous'])
        for label in ('validation','test','replay'):
            self.assertTrue(result['splits'][label]['target_dates_continuous'])
        self.assertEqual(result['splits']['replay']['count'],90)
        bundle = self.manager.list_models()[0]
        self.assertAlmostEqual(bundle['scaler']['maximum'][0],62.9)
        self.assertEqual(bundle['scaler_fit_end'],str(date(2020,1,1)+timedelta(days=679)))
        self.assertLess(bundle['splits']['train']['end'],bundle['splits']['validation']['start'])
        self.assertLess(bundle['splits']['validation']['end'],bundle['splits']['test']['start'])
        self.assertLess(bundle['splits']['test']['end'],bundle['splits']['replay']['start'])
        scaled_window_length = 1.9/(bundle['scaler']['maximum'][0]-bundle['scaler']['minimum'][0])
        for window in self.backend.calls[0][0]:
            self.assertAlmostEqual(window[-1][0]-window[0][0],scaled_window_length)
        original_hash = bundle['training_hash']
        changed = [dict(r) for r in data]
        for record in changed:
            if record['date'] >= metadata['replay_start']:
                record['groundwater_level'] = -999999.
        isolated = ModelManager(self.directory.name,namespace='future-changed',backend=Backend())
        isolated.train('11110',changed,metadata)
        self.assertEqual(isolated.list_models()[0]['training_hash'],original_hash)

    def test_gap_aware_training_cap_is_applied_before_scaler_fit(self):
        data = rows(1000)
        metadata = {**META, 'split_policy':'gap_aware', 'train_max_targets':180,
                    'replay_start':str(date(2020,1,1)+timedelta(days=800))}
        self.manager.train('11110',data,metadata)
        bundle = self.manager.list_models()[0]
        self.assertEqual(bundle['splits']['train']['count'],180)
        self.assertAlmostEqual(bundle['scaler']['minimum'][0],43.)
        self.assertEqual(bundle['scaler_fit_start'],str(date(2020,1,1)+timedelta(days=480)))
        with self.assertRaisesRegex(ValueError, 'at least180'):
            self.manager.train('11110',data,{**metadata,'train_max_targets':179})

    def test_residual_architecture_is_explicitly_selected_and_recorded(self):
        self.manager.train('11110',rows(),{**META,'training':{'model_architecture':'residual_lstm','learning_rate':.0001}})
        self.assertEqual(self.backend.calls[0][2]['architecture'],'residual_lstm')
        self.assertEqual(self.backend.calls[0][2]['learning_rate'],.0001)
        self.assertEqual(self.manager.list_models()[0]['model_architecture'],'residual_lstm')
        invalid = ModelManager(self.directory.name,namespace='invalid-architecture',backend=Backend())
        with self.assertRaisesRegex(ValueError,'unsupported model_architecture'):
            invalid.train('11110',rows(),{**META,'model_architecture':'invented_model'})


@unittest.skipUnless(os.getenv('GROUNDWATCH_TEST_TENSORFLOW') == '1', 'opt-in actual TensorFlow training smoke')
class TensorFlowGraphTests(unittest.TestCase):
    def test_residual_model_trains_serializes_and_reloads_without_lambda(self):
        import tensorflow as tf
        with tempfile.TemporaryDirectory() as folder:
            backend = TensorFlowBackend('unused',Path(folder))
            inputs = [[[.1+j*.01+i*.001, float(j%3)*.1] for j in range(20)] for i in range(16)]
            targets = [sequence[-1][0]+.05 for sequence in inputs]
            model = backend.train(inputs,targets,(inputs[:4],targets[:4]),max_epochs=2,
                                  architecture='residual_lstm',learning_rate=.0001)
            before = backend.predict(model,inputs[:4])
            self.assertFalse(model.get_layer('last_groundwater_level').trainable)
            self.assertEqual(model.get_layer('last_groundwater_level').get_weights()[0].tolist(),[[1.],[0.]])
            self.assertTrue(any(abs(p-x[-1][0])>1e-8 for p,x in zip(before,inputs[:4])))
            self.assertFalse(any(isinstance(layer,tf.keras.layers.Lambda) for layer in model.layers))
            path = Path(folder)/'residual.keras'
            model.save(path)
            restored = tf.keras.models.load_model(path)
            after = backend.predict(restored,inputs[:4])
            for original,reloaded in zip(before,after):
                self.assertAlmostEqual(original,reloaded,places=7)


if __name__ == '__main__':
    unittest.main()
