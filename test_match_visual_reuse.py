"""同一局的 hero/rank 只识别一次：验证复用、跨局隔离与手动重读。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hud_enrichment as enrichment


class MatchVisualReuseTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.writes=0
        self.clips=[]

    def tearDown(self):
        self.temp.cleanup()

    def add(self,name,match_key):
        path=self.root/name
        path.write_bytes(b'fake-video-bytes')
        clip={'output':str(path),'recognition':{'match_key':match_key}}
        self.clips.append(clip)
        return clip

    def share(self,fields=('hero',),force=False):
        return enrichment.share_match_fields({'clips':self.clips},self.clips,list(fields),force,
                                                    lambda:self.__setattr__('writes',self.writes+1))

    def test_same_match_recognizes_once_and_copies(self):
        first=self.add('a.mp4','match-1');second=self.add('b.mp4','match-1')
        calls=[]
        def fake(source,fields,**kwargs):
            calls.append((str(source),list(fields)))
            return {'hero':{'name':'Wraith'},'hero_observations':[{'time':1.0}],
                    'field_status':{'hero':'confirmed'}}
        with patch.object(enrichment,'recognize_video',side_effect=fake):
            shared=self.share()
        self.assertEqual(shared,1)
        self.assertEqual(len(calls),1)
        info=second['recognition']['hud_info']
        self.assertEqual(info['hero'],{'name':'Wraith'})
        self.assertEqual(info['field_status']['hero'],'confirmed')
        self.assertEqual(info['field_source_identities']['hero'],enrichment.fingerprint(Path(second['output'])))
        self.assertIn('hero',info['requested_fields'])
        self.assertGreaterEqual(self.writes,1)
        # 复用后第二次调用不应再判定为待读。
        pending=enrichment._pending_visual_fields(second['recognition'],info,
            enrichment.fingerprint(Path(second['output'])),['hero'],False)
        self.assertEqual(pending,[])

    def test_different_match_not_shared(self):
        self.add('a.mp4','match-1');self.add('b.mp4','match-2')
        calls=[]
        def fake(source,fields,**kwargs):
            calls.append(str(source))
            return {'hero':{'name':'Wraith'},'field_status':{'hero':'confirmed'}}
        with patch.object(enrichment,'recognize_video',side_effect=fake):
            shared=self.share()
        self.assertEqual(shared,0)
        self.assertEqual(len(calls),0)

    def test_force_reads_every_clip(self):
        self.add('a.mp4','match-1');self.add('b.mp4','match-1')
        with patch.object(enrichment,'recognize_video') as recognize:
            shared=self.share(force=True)
        self.assertEqual(shared,0)
        recognize.assert_not_called()

    def test_existing_confirmed_value_is_donor(self):
        first=self.add('a.mp4','match-1');second=self.add('b.mp4','match-1')
        identity=enrichment.fingerprint(Path(first['output']))
        first['recognition']['hud_info']={'hero':{'name':'Octane'},'field_status':{'hero':'confirmed'},
            'field_versions':{'hero':enrichment.field_version('hero')},
            'field_source_identities':{'hero':identity},'requested_fields':['hero']}
        with patch.object(enrichment,'recognize_video') as recognize:
            shared=self.share()
        recognize.assert_not_called()
        self.assertEqual(shared,1)
        self.assertEqual(second['recognition']['hud_info']['hero'],{'name':'Octane'})

    def confirmed(self,clip,field,value):
        identity=enrichment.fingerprint(Path(clip['output']))
        info=clip['recognition'].setdefault('hud_info',{})
        info[field]=value
        info.setdefault('field_status',{})[field]='confirmed'
        info.setdefault('field_versions',{})[field]=enrichment.field_version(field)
        info.setdefault('field_source_identities',{})[field]=identity
        info['requested_fields']=list(dict.fromkeys(info.get('requested_fields',[])+[field]))
        return clip

    def share_names(self,fields=('account',),force=False):
        return enrichment.share_match_name_fields({'clips':self.clips},self.clips,list(fields),force,
                                                  lambda:self.__setattr__('writes',self.writes+1))

    def test_account_needs_two_independent_votes(self):
        first=self.add('a.mp4','match-1');second=self.add('b.mp4','match-1');third=self.add('c.mp4','match-1')
        self.confirmed(first,'account',{'name':'Lily','confidence':.9})
        self.confirmed(second,'account',{'name':'Lily','confidence':.8})
        shared=self.share_names()
        self.assertEqual(shared,1)
        self.assertEqual(third['recognition']['hud_info']['account']['name'],'Lily')
        self.assertEqual(third['recognition']['hud_info']['field_status']['account'],'confirmed')

    def test_account_single_vote_not_shared(self):
        first=self.add('a.mp4','match-1');third=self.add('c.mp4','match-1')
        self.confirmed(first,'account',{'name':'Lily','confidence':.9})
        shared=self.share_names()
        self.assertEqual(shared,0)
        self.assertNotIn('account',third['recognition']['hud_info'])

    def test_account_conflicting_votes_not_shared(self):
        first=self.add('a.mp4','match-1');second=self.add('b.mp4','match-1');third=self.add('c.mp4','match-1')
        self.confirmed(first,'account',{'name':'Lily','confidence':.9})
        self.confirmed(second,'account',{'name':'Other','confidence':.9})
        shared=self.share_names()
        self.assertEqual(shared,0)
        self.assertNotIn('account',third['recognition']['hud_info'])

    def test_teammates_share_only_slots_with_two_votes(self):
        first=self.add('a.mp4','match-1');second=self.add('b.mp4','match-1');third=self.add('c.mp4','match-1')
        self.confirmed(first,'teammates',[{'slot':0,'name':'Ann','confidence':.9},{'slot':1,'name':'Bob','confidence':.9}])
        self.confirmed(second,'teammates',[{'slot':0,'name':'Ann','confidence':.9}])
        shared=self.share_names(('teammates',))
        self.assertEqual(shared,1)
        values={value['slot']:value['name'] for value in third['recognition']['hud_info']['teammates']}
        self.assertEqual(values,{0:'Ann'})
        self.assertEqual(third['recognition']['hud_info']['field_status']['teammates'],'confirmed')

    def test_first_run_reads_two_voters_then_shares(self):
        first=self.add('a.mp4','match-1');second=self.add('b.mp4','match-1');third=self.add('c.mp4','match-1')
        calls=[]
        def fake(source,fields,**kwargs):
            calls.append(str(source))
            return {'account':{'name':'Lily','confidence':.9},'field_status':{'account':'confirmed'}}
        with patch.object(enrichment,'recognize_video',side_effect=fake):
            shared=self.share_names()
        self.assertEqual(len(calls),2)
        self.assertEqual(shared,1)
        for clip in (first,second,third):
            self.assertEqual(clip['recognition']['hud_info']['account']['name'],'Lily')


if __name__=='__main__':
    unittest.main()



