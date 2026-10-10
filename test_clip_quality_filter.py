import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from app_options import parse_options
from app_task import open_task,save_task
from clip_quality_filter import assess,apply_thresholds

class QualityTests(unittest.TestCase):
    def options(self,**extras):return parse_options(dict(filter_enabled=True,min_damage=300,min_kills=1,min_assists=2,**extras))
    def stats(self,damage=100,kills=0,assists=0,partial=None):return dict(counts=dict(damage=damage,kills=kills,assists=assists),partial=partial or {})
    def test_any_and_all_are_distinct_and_equal_threshold_passes(self):
        r=self.stats(300,0,0)
        self.assertEqual(assess(r,self.options())['status'],'kept')
        self.assertEqual(assess(r,self.options(filter_mode='all'))['status'],'rejected')
        self.assertEqual(assess(self.stats(300,1,2),self.options(filter_mode='all'))['status'],'kept')
    def test_unknown_and_insufficient_lower_bound_go_to_review(self):
        self.assertEqual(assess(self.stats(None,0,0),self.options())['status'],'review')
        self.assertEqual(assess(self.stats(100,0,0,{'damage':True}),self.options())['status'],'review')
        self.assertEqual(assess(self.stats(400,None,None,{'damage':True}),self.options())['status'],'kept')
        self.assertEqual(assess(self.stats(None,0,None),self.options(filter_mode='all'))['status'],'rejected')
    def test_disabled_and_zero_thresholds_leave_clips_unchanged(self):
        self.assertEqual(assess(self.stats(None,None,None),parse_options({}))['status'],'kept')
        self.assertEqual(assess(self.stats(None,None,None),parse_options({'filter_enabled':True}))['status'],'kept')
    def test_select_kept_records_without_realigning_or_mismatching_statistics(self):
        aligned=[{'start':i*10,'end':i*10+5} for i in range(3)]
        statistics={'segments':[dict(s,**r) for s,r in zip(aligned,[self.stats(100,0,0),self.stats(400,0,0),self.stats(None,0,0)])]}
        kept,stats,report,rejected,review=apply_thresholds(aligned,statistics,self.options())
        self.assertEqual(kept,[aligned[1]]);self.assertEqual(stats['segments'][0]['counts']['damage'],400)
        self.assertEqual(report['summary'],{'kept':1,'rejected':1,'review':1});self.assertEqual(len(review),1)
    def test_invalid_thresholds_are_rejected(self):
        for request in [{'min_damage':-1},{'min_kills':1.5},{'min_assists':True},{'filter_mode':'maybe'},{'filter_enabled':'yes'}]:
            with self.assertRaises(ValueError):parse_options(request)
    def test_resume_freezes_filter_settings_instead_of_using_new_global_values(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'APEX_DISABLE_LAST_TASK':'1'}):
            source=Path(tmp)/'clip.mp4';source.write_bytes(b'fixture')
            path,task,_,_=open_task(dict(files=[str(source)],output=tmp,backend='cpu',filter_enabled=True,min_damage=300))
            save_task(path,task);_,_,_,options=open_task(dict(resume_task=str(path),min_damage=999,filter_enabled=False))
            self.assertTrue(options['filter_enabled']);self.assertEqual(options['min_damage'],300)
