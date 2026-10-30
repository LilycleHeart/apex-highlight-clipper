import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hud_enrichment
from app_cancel import TaskStopped


class ImportedStatisticsWriteBackTests(unittest.TestCase):
    def test_stop_mid_batch_keeps_completed_clip_statistics(self):
        # 暂停时已完成的导入片段必须写回清单后再标完成，否则检查点跳过它、界面却没有数据。
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();files=[str(root/f'{name}.mp4') for name in ['a','b']]
            manifest=root/'export.json'
            manifest.write_text(json.dumps({'mode':'imported','clips':[{'output':file} for file in files]}),'utf-8')
            committed=[]
            def build(file,profile=None,on_activity=None):
                if file.endswith('b.mp4'):raise TaskStopped()
                return {'counts':{'kills':2,'damage':300},'version':1}
            def commit(directory,file,fields,computed=()):
                # 推进检查点时结果必须已在清单里
                clip=next(c for c in json.loads(manifest.read_text('utf-8'))['clips'] if c['output']==file)
                self.assertIn('statistics',clip);committed.append(file)
            request={'fields':['statistics'],'jobs':[{'directory':str(root),'files':files,'fields':['statistics']}]}
            with patch.dict('os.environ',{'APEX_HUD_WORKERS':'1'}),patch('imported_statistics.build_statistics',side_effect=build),\
                 patch('hud_recovery.claim'),patch('hud_recovery.commit_extra',side_effect=commit),patch('hud_recovery.failed'),\
                 self.assertRaises(TaskStopped):
                hud_enrichment._run_job_sequence(request,True,lambda event:None)
            clips={c['output']:c for c in json.loads(manifest.read_text('utf-8'))['clips']}
            self.assertEqual(clips[files[0]]['statistics']['counts']['kills'],2)
            self.assertNotIn('statistics',clips[files[1]])
            self.assertEqual(committed,[files[0]])


class ImportedEventWeaponTests(unittest.TestCase):
    def test_event_weapons_read_at_video_pts_and_bind_to_clip_time(self):
        from imported_statistics import attach_event_weapons
        statistics={'counts':{'kills':1},'events':[{'kind':'knock','time':5.,'text':'击倒'}]}
        seen=[]
        def recheck(source,events,profile,force=False,on_activity=None):
            seen.extend(events)
            return [{**e,'weapon_context':{'event':{'kind':e['kind'],'action':None,'time':e['time']},'status':'observed'}} for e in events]
        with patch('imported_statistics.confirmed_profile',return_value={'layout_status':'confirmed'}),\
             patch('imported_statistics.video_origin',return_value=.04),patch('event_weapon_reader.recheck_event_weapons',side_effect=recheck):
            result=attach_event_weapons('clip.mp4',statistics)
        # 旧导入统计没有归属字段：按本人中心提示补上，并按首帧 PTS 读画面。
        self.assertEqual(seen[0]['ownership'],'self');self.assertAlmostEqual(seen[0]['time'],5.04)
        event=result['events'][0]
        self.assertEqual(event['time'],5.);self.assertEqual(event['weapon_context']['event']['time'],5.)
        self.assertAlmostEqual(event['weapon_context']['event']['source_time'],5.04)

    def test_recomputed_statistics_keep_context_only_for_same_event_time(self):
        from imported_statistics import carry_weapon_contexts
        previous={'events':[{'kind':'knock','time':5.,'weapon_context':{'status':'observed'}}]}
        fresh={'events':[{'kind':'knock','time':5.},{'kind':'knock','time':9.}]}
        result=carry_weapon_contexts(previous,fresh)
        self.assertEqual(result['events'][0]['weapon_context']['status'],'observed');self.assertNotIn('weapon_context',result['events'][1])


if __name__=='__main__':unittest.main()
