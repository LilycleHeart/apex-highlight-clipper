"""目录、语言/形态解析及低频射击回归。真实画面在独立验证脚本中测试。"""
import json
import unittest
from pathlib import Path
from weapon_reader import load_catalog, resolve_weapon_text, active_slot,ctc_label_score,WeaponTextReader
import numpy as np
from types import SimpleNamespace
from apex_clipper import ammo_number, classify_combat_candidates, detect_events,label_event_weapons
from test_core import row

EXPECTED_IDS={'havoc','flatline','hemlok','r301','nemesis','alternator','prowler','r99','volt','car',
              'devotion','lstar','spitfire','rampage','g7','triple_take','repeater3030','bocek',
              'charge_rifle','longbow','kraber','sentinel','eva8','mastiff','mozambique',
              'peacekeeper','re45','p2020','wingman'}

class WeaponCoverageTests(unittest.TestCase):
    def test_weak_gun_label_requires_temporal_confirmation(self):
        sample={'time':1,'current_weapon':{'id':'nemesis','name':'死敌'},'current_weapon_confidence':.75}
        event={'time':1,'kind':'shoot'}
        self.assertEqual(label_event_weapons([dict(event)],[sample])[0]['weapon'],'未知枪')
        self.assertEqual(label_event_weapons([dict(event)],[sample,{**sample,'time':1.5}])[0]['weapon'],'死敌')

    def test_closed_dictionary_recovers_supported_character_but_never_blank_noise(self):
        # 贪心漏读第二字，但模型仍给“兽”明确概率；完全无文字则保持未知。
        chars=['blank','獵','獸','死','敵']
        reader=WeaponTextReader(SimpleNamespace(postprocess_op=SimpleNamespace(dict={c:i for i,c in enumerate(chars)})))
        p=np.array([[.01,.98,.01,0,0],[.9,.05,.05,0,0],[.48,0,.52,0,0],[.98,0,.02,0,0]])
        text,confidence=reader.constrained(p,('獵',.98))
        self.assertEqual(resolve_weapon_text(text,confidence)['id'],'prowler')
        blank=np.zeros_like(p);blank[:,0]=1
        self.assertEqual(reader.constrained(blank,('',0)),('',0))
        self.assertLess(ctc_label_score(blank,[1,2]),.001)

    def test_official_roster_and_all_three_language_aliases(self):
        catalog=load_catalog()
        self.assertEqual({w['id'] for w in catalog['weapons']},EXPECTED_IDS)
        for weapon in catalog['weapons']:
            for label in [weapon['english_name'],weapon['traditional_name'],weapon['name']]+weapon['aliases']:
                with self.subTest(id=weapon['id'],label=label):
                    match=resolve_weapon_text(label)
                    self.assertIsNotNone(match)
                    self.assertEqual(match['id'],weapon['id'])

    def test_akimbo_elite_and_legacy_names(self):
        for text,ident,variant in [('雙持 P2020','p2020','akimbo'),('Akimbo Mozambique','mozambique','akimbo'),
                                    ('RE-45 Burst','re45','burst'),('Hemlok Breach AR','hemlok','breach')]:
            result=resolve_weapon_text(text)
            self.assertEqual((result['id'],result['variant']),(ident,variant))
        self.assertIsNone(resolve_weapon_text('Akimbo R301'))

    def test_similar_energy_names_are_not_conflated(self):
        self.assertEqual(resolve_weapon_text('電能步槍')['id'],'charge_rifle')
        self.assertEqual(resolve_weapon_text('電能衝鋒槍')['id'],'volt')
        self.assertIsNone(resolve_weapon_text('電能'))

    def test_garbage_and_ambiguous_labels_remain_unknown(self):
        for text in ['','死','R','冲锋枪','完全不认识的枪','R-99 CAR']:
            self.assertIsNone(resolve_weapon_text(text))
        self.assertIsNone(resolve_weapon_text('Peacekeeper',.2))
        self.assertIsNone(active_slot([240,235]))
        self.assertEqual(active_slot([180,255]),1)

    def test_large_stockpile_and_last_round(self):
        self.assertEqual(ammo_number('240',.99),240)
        self.assertEqual(ammo_number('O',.95),0)
        events=detect_events([row(0,1),row(.5,0),row(1,0)])
        self.assertTrue(any(e['kind']=='shoot' and e['before']==1 and e['after']==0 for e in events))

    def test_one_missed_ammo_sample_is_bridged(self):
        events=detect_events([row(0,4),row(.5,None),row(1,3)])
        self.assertTrue(any(e['kind']=='shoot' for e in events))

    def test_single_strong_hit_without_kill_is_kept_but_17_damage_poke_is_not(self):
        for damage,expected in [(100,True),(80,True),(17,False)]:
            events=[{'time':100,'kind':'shoot'},{'time':100.5,'kind':'hit','before':0,'after':damage}]
            confirmed,review=classify_combat_candidates(events,[{'start':90,'end':115}])
            self.assertEqual(bool(confirmed),expected)
            self.assertEqual(bool(review),not expected)
        confirmed,_=classify_combat_candidates([{'time':100,'kind':'hit','before':0,'after':100}],
                                                [{'start':90,'end':115}])
        self.assertEqual(confirmed,[])

if __name__=='__main__': unittest.main()
