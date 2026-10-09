import unittest
import json
import numpy as np
from outcome_reader import result_kind,cap_segment_ends,preserve_team_continuation,friend_view

class OutcomeTests(unittest.TestCase):
    def test_friend_banner_returns_json_serializable_boolean(self):
        image=np.zeros((540,1280,3),dtype=np.uint8)
        image[round(540*.93):round(540*.98),round(1280*.36):round(1280*.64)]=(0,255,0)
        flag=friend_view(image,True)
        self.assertIs(flag,True)
        self.assertEqual(json.loads(json.dumps({'friend_spectate':flag})),{'friend_spectate':True})

    def test_only_end_words_with_after_game_view_count(self):
        self.assertEqual(result_kind('小隊全滅 排名#14',True),'end')
        self.assertIsNone(result_kind('小隊全滅',False))
        self.assertIsNone(result_kind('冠軍小隊',True))
        self.assertEqual(result_kind('YOU ARE THE CHAMPION',False),'win')

    def test_postroll_is_capped_after_verified_squad_wipe(self):
        s={'start':280,'end':310,'last_signal':295}
        out=cap_segment_ends([s],[{'time':298,'kind':'end','text':'小隊全滅'}])
        self.assertEqual(out[0]['end'],300)

    def test_teammate_continues_after_my_death_until_clip_boundary(self):
        s={'start':880,'end':1015,'last_signal':1005}
        rows=[{'time':1010,'inactive_view':True,'friend_spectate':True},
              {'time':1060,'inactive_view':True,'friend_spectate':True}]
        out=preserve_team_continuation([s],rows,[],1080)
        self.assertEqual(out[0]['end'],1080)
        self.assertTrue(out[0]['team_end_needs_review'])

    def test_enemy_spectate_does_not_extend_own_fight(self):
        s={'start':280,'end':310,'last_signal':295}
        rows=[{'time':300,'inactive_view':True,'friend_spectate':False}]
        self.assertEqual(preserve_team_continuation([s],rows,[],360)[0]['end'],310)

    def test_later_round_end_cannot_bridge_return_to_own_view(self):
        s={'start':100,'end':150,'last_signal':140}
        rows=[{'time':145,'inactive_view':True,'friend_spectate':True},
              {'time':170,'inactive_view':False}]
        out=preserve_team_continuation([s],rows,[{'time':700,'kind':'end'}],800)
        self.assertEqual(out[0]['end'],185)

    def test_end_screen_transition_may_hide_spectate_controls(self):
        s={'start':100,'end':150,'last_signal':140}
        rows=[{'time':145,'inactive_view':True,'friend_spectate':True},
              {'time':170,'inactive_view':False}]
        out=preserve_team_continuation([s],rows,[{'time':172,'kind':'end'}],200)
        self.assertEqual(out[0]['end'],174)

if __name__=='__main__': unittest.main()
