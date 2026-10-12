import unittest
from player_names import player_name,consensus_name,canonical_name
from hud_enrichment import reconcile_manifest_names,VERSION


class PlayerNameTests(unittest.TestCase):
    def test_fixed_hud_text_and_conflicting_names_are_not_confirmed(self):
        for text in ['MAX LEVEL','下個等級 749 進化','造成150伤害','KNOCKED DOWN','\ufffd口□']:
            self.assertEqual(player_name(text),'')
        values=[{'name':name,'confidence':.95} for name in ['PLAYER_ONE','PLAYER_ONE','OTHER_NAME','OTHER_NAME']]
        self.assertIsNone(consensus_name(values))
        self.assertEqual(player_name('YURI] Liliumcordis'),'[YURI] Liliumcordis')

    def test_account_aliases_reconcile_with_real_repeated_name_and_teammates_stay_per_match(self):
        real={'name':'[YURI] Liliumcordis','confidence':.95}
        weak={'name':'YURI Liiumeordis','confidence':.85}
        def clip(key,value,team):
            return {'recognition':{'match_key':key,'hud_info':{'version':VERSION,'account':value,'teammates':[team],
                'name_observations':[{'account':value,'teammates':[team]} for _ in range(3)]}}}
        team={'name':'badya','confidence':.95,'slot':0}
        manifest={'clips':[clip('a',real,team),clip('a',weak,team),clip('b',real,{'name':'other','confidence':.95,'slot':0})]}
        reconcile_manifest_names(manifest)
        self.assertEqual(manifest['clips'][1]['recognition']['hud_info']['account']['name'],real['name'])
        self.assertEqual(manifest['clips'][2]['recognition']['hud_info']['teammates'][0]['name'],'other')
        self.assertEqual(canonical_name({'name':'PLAYER_TWO','confidence':.99},{'name':'PLAYER_ONE','confidence':.99,'votes':6})['name'],'PLAYER_TWO')
