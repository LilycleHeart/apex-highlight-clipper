import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from apex_clipper import fingerprint
from hud_enrichment import enrich_manifest,FIELDS,VERSION


class HudEnrichmentTests(unittest.TestCase):
    def fixture(self,root):
        files=[root/'selected.mp4',root/'other.mp4']
        clips=[]
        for file in files:
            file.write_bytes(b'exported video fixture')
            account={'name':'old_wrong_account','confidence':.95}
            teammate={'name':'kept_teammate','confidence':.95,'slot':0}
            info={'version':VERSION,'source_identity':fingerprint(file),'requested_fields':FIELDS,
                'field_status':{field:'confirmed' for field in FIELDS},'account':account,
                'teammates':[teammate],'hero':{'id':'pathfinder','name':'探路者'},
                'weapons':[{'id':'r99','name':'R99'}],'rank':{'tier':'gold'},
                'name_observations':[{'time':i,'account':account,'teammates':[teammate]} for i in [1,2,3]]}
            clips.append({'output':str(file),'segment':{'start':0,'end':10},
                'summary':{'kills':2,'damage':123,'weapons':['R99']},'recognition':{'hud_info':info}})
        manifest={'video_directory':str(root),'outputs':[str(file) for file in files],'clips':clips}
        (root/'export.json').write_text(json.dumps(manifest),encoding='utf-8')
        return files,manifest

    def fresh(self,fields,**values):
        return {'profile':{},'checked_frames':3,'frame_times':[1,2,3],'name_observations':[],
            'field_status':{field:'confirmed' if values[field] else 'unknown' for field in fields},**values}

    def test_missing_skips_confirmed_and_only_reads_unknown_selected_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root)
            with patch('hud_enrichment.recognize_video') as read:
                enrich_manifest(root,[str(files[0])],['weapons','rank'])
                read.assert_not_called()
            manifest['clips'][0]['recognition']['hud_info']['field_status']['weapons']='unknown'
            (root/'export.json').write_text(json.dumps(manifest),encoding='utf-8')
            fresh=self.fresh(['weapons'],weapons=[{'id':'r301','name':'R301'}])
            with patch('hud_enrichment.recognize_video',return_value=fresh) as read:
                result=enrich_manifest(root,[str(files[0])],['weapons','rank'])
                read.assert_called_once_with(files[0],['weapons'])
            info=result['clips'][0]['recognition']['hud_info']
            self.assertEqual(info['weapons'],fresh['weapons']);self.assertEqual(info['rank'],{'tier':'gold'})
            self.assertEqual(result['clips'][1],manifest['clips'][1])

    def test_refresh_replaces_confirmed_only_in_scope_and_drops_stale_name_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root);before=copy.deepcopy(manifest)
            fields=['account','weapons','rank'];fresh=self.fresh(fields,account=None,weapons=[],rank=None)
            with patch('hud_enrichment.recognize_video',return_value=fresh) as read:
                result=enrich_manifest(root,[str(files[0])],fields,force=True)
                read.assert_called_once_with(files[0],fields)
            clip=result['clips'][0];info=clip['recognition']['hud_info'];old=before['clips'][0]['recognition']['hud_info']
            self.assertIsNone(info['account']);self.assertEqual(info['weapons'],[]);self.assertIsNone(info['rank'])
            self.assertEqual(info['refreshed_fields'],fields)
            self.assertFalse(any(row.get('account') for row in info['name_observations']))
            self.assertTrue(any(row.get('teammates') for row in info['name_observations']))
            self.assertEqual(info['teammates'],old['teammates']);self.assertEqual(info['hero'],old['hero'])
            self.assertEqual(clip['summary'],before['clips'][0]['summary']);self.assertEqual(clip['segment'],before['clips'][0]['segment'])
            self.assertEqual(result['clips'][1],before['clips'][1])
            self.assertTrue(all(file.read_bytes()==b'exported video fixture' for file in files))

    def test_missing_preserves_confirmed_account_even_with_stronger_name_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,manifest=self.fixture(root)
            for index,name in enumerate(['YURI Liiumeordis','[YURI] Liliumcordis']):
                info=manifest['clips'][index]['recognition']['hud_info']
                account={'name':name,'confidence':.85 if index==0 else .95}
                info['account']=account
                info['name_observations']=[{'time':i,'account':account} for i in range(3 if index==0 else 6)]
            before=copy.deepcopy(manifest)
            (root/'export.json').write_text(json.dumps(manifest),encoding='utf-8')
            with patch('hud_enrichment.recognize_video') as read:
                result=enrich_manifest(root,[str(files[0])],['account'])
                read.assert_not_called()
            self.assertEqual(result,before)


if __name__=='__main__':unittest.main()
