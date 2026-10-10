import unittest
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from apex_clipper import write_json,fingerprint
from test_core import row
from app_options import parse_options
from smart_scan import activity_brackets,merge_windows,frame_ranges,audit_counters,smart_read

class SmartTests(unittest.TestCase):
    def test_flat_damage_and_stable_ammo_does_not_request_dense_scan(self):
        rows=[row(t,ammo=None,damage=None,kills=None) for t in [0,2,4,6]]
        self.assertEqual(activity_brackets(rows),[])

    def test_damage_growth_and_ammo_decrease_both_trigger_local_check(self):
        a=row(20,ammo=20,damage=100,kills=1); b=row(22,ammo=17,damage=145,kills=1)
        seeds=activity_brackets([a,b]); reasons={s['reason'] for s in seeds}
        self.assertIn('damage',reasons); self.assertIn('ammo_change',reasons)

    def test_downed_and_friend_spectate_keep_tail_even_without_damage(self):
        rows=[row(20,ammo=None,damage=0,kills=0),row(22,ammo=None,damage=0,kills=0)]
        rows[1].update(downed=True,friend_spectate=True,inactive_view=True)
        seeds=activity_brackets(rows)
        self.assertIn('team_or_downed',{s['reason'] for s in seeds})

    def test_ranges_preserve_global_sampling_grid_and_merge(self):
        ranges=frame_ranges([[10,12],[12,14]],30,2)
        self.assertEqual(ranges,[[21,28]])
        self.assertEqual(merge_windows([{'start':20,'end':22},{'start':30,'end':32}],60,5),[[15,37]])

    def test_counter_mismatch_requests_fallback(self):
        coarse={'rows':[row(20,ammo=20,damage=100,kills=1),row(22,ammo=20,damage=145,kills=1)],'outcome_events':[]}
        fine=[row(20,ammo=20,damage=100,kills=1),row(22,ammo=20,damage=120,kills=1)]
        self.assertFalse(audit_counters(coarse,fine,30)['passed'])

    def test_legacy_settings_migrate_to_indexed_without_changing_recycle_switch(self):
        for old_mode in ['smart','complete']:
            options=parse_options({'scan_mode':old_mode,'delete_source':True,'verify':False})
            self.assertEqual(options['scan_mode'],'indexed')
            self.assertTrue(options['delete_source']);self.assertFalse(options['verify'])

    def test_legacy_failed_audit_resumes_in_original_full_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.mp4'; source.write_bytes(b'fixture')
            coarse={'rows':[row(20,ammo=20,damage=100,kills=1),row(22,ammo=20,damage=145,kills=1)],'numeric_frames':2}
            profile={'reference_size':[2560,1080]}; output=root/'hud.json'
            config={'source':fingerprint(source),'profile':profile,'fps':2,'gap':35,'pre':10,'post':15,'version':2}
            write_json(root/'smart-plan.json',{'signature':hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),
                'frame_ranges':[[1,60]],'coarse_frames':2,'binary_probes':0,'need_full_fallback':True})
            def reader(samples,profile,fps,path,**kwargs):
                rows=[row(20,ammo=20,damage=100,kills=1),row(22,ammo=20,damage=145,kills=1)]
                write_json(path,{'rows':rows,'outcome_events':[],'complete':True}); return rows
            with patch('smart_scan.probe',return_value=({'format':{'duration':'30'}},{'width':2560,'height':1080})),patch('smart_scan.coarse_scan',return_value=coarse),patch('smart_scan.bisect_edges',return_value=([],0)),patch('smart_scan.sample_with_resume') as sampler,patch('smart_scan.read_hud',side_effect=reader),patch('smart_scan.enrich_outcomes',side_effect=lambda cache,*a,**k:cache),patch('smart_scan.audit_counters',return_value={'passed':False,'checks':[]}):
                rows,folder=smart_read(source,root,root/'samples',profile,2,output)
                self.assertEqual(folder,root/'full-fallback')
                self.assertEqual(sampler.call_count,1)
                sampler.reset_mock()
                rows,folder=smart_read(source,root,folder,profile,2,output)
                self.assertEqual(sampler.call_count,1)
                self.assertEqual(sampler.call_args.args[1],root/'full-fallback')


if __name__=='__main__': unittest.main()
