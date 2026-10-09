import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from app_options import parse_options,recycle_source
from apex_clipper import fingerprint

class AppOptionsTests(unittest.TestCase):
    def test_defaults_and_delete_force_verification(self):
        self.assertEqual(parse_options({})['gap'],35)
        self.assertFalse(parse_options({})['delete_source'])
        self.assertTrue(parse_options({'delete_source':True,'verify':False})['verify'])
        custom=parse_options({'gap':20,'pre':8,'post':10,'fps':3})
        self.assertEqual([custom[k] for k in ['gap','pre','post','fps']],[20,8,10,3])

    def test_invalid_parameters_are_rejected(self):
        for key,value in [('gap',-1),('fps',0),('fps',6),('pre',float('nan')),('post',float('inf')),('gap',True),('delete_source','yes')]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError): parse_options({key:value})

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/'source.mp4'; self.source.write_bytes(b'source')
        self.output=Path(self.temp.name)/'clip.mp4'; self.output.write_bytes(b'clip')
        self.identity=fingerprint(self.source)
        self.verification={'source':str(self.source),'outputs':[str(self.output)],'passed':True,
            'encoded_payloads_unchanged':True,'all_tracks_preserved':True,'monotonic_dts':True}
        self.recycler=Mock()

    def recycle(self,**overrides):
        values=dict(source=self.source,identity=self.identity,outputs=[self.output],verification=self.verification,
                    review=[],segments=[],recycler=self.recycler)
        values.update(overrides); return recycle_source(**values)

    def test_review_and_unresolved_end_keep_source(self):
        for values in [dict(review=[{'start':30,'end':40}]),dict(segments=[{'team_end_needs_review':True}])]:
            self.assertEqual(self.recycle(**values)['status'],'kept')
        self.recycler.assert_not_called()

    def test_missing_outputs_and_failed_verification_keep_source(self):
        self.assertEqual(self.recycle(outputs=[])['status'],'kept')
        self.assertEqual(self.recycle(verification={**self.verification,'passed':False})['status'],'kept')
        self.output.unlink()
        self.assertEqual(self.recycle()['status'],'kept')
        self.recycler.assert_not_called()

    def test_changed_source_and_wrong_manifest_keep_source(self):
        self.source.write_bytes(b'changed source')
        self.assertEqual(self.recycle()['status'],'kept')
        self.assertEqual(self.recycle(verification={**self.verification,'outputs':[]})['status'],'kept')
        self.recycler.assert_not_called()

    def test_recycle_failure_keeps_source_without_permanent_fallback(self):
        self.recycler.side_effect=OSError('回收站不可用')
        result=self.recycle()
        self.assertEqual(result['status'],'kept')
        self.assertTrue(self.source.exists())
        self.assertIn('回收站不可用',result['reason'])

    def test_confirmed_success_invokes_only_selected_source(self):
        self.recycler.side_effect=lambda path:Path(path).unlink()
        self.assertEqual(self.recycle()['status'],'recycled')
        self.recycler.assert_called_once_with(str(self.source.resolve()))
        self.assertTrue(self.output.exists())

if __name__=='__main__': unittest.main()
