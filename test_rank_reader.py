import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import cv2
import numpy as np
from rank_reader import RankReader,read_division,recognize_segments,BASE
from apex_clipper import fingerprint

class RankTests(unittest.TestCase):
    def division_refinement(self,frames,values,extra=None):
        reader=RankReader();reader.inspect=Mock(side_effect=values)
        rank={'tier':'platinum','name':'白金','division':None,'confidence':.9}
        observations=[{'time':2.,'rank':{**rank,'division':'III'}}]+(extra or [])
        image=np.zeros((1080,1920,3),np.uint8)
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'clip.mp4';source.write_bytes(b'fixture')
            with patch('apex_clipper.probe',return_value=({'format':{'duration':10}},{})),patch('hud_enrichment.native_frames',return_value=iter((time,image) for time in frames)),patch('apex_clipper.inactive_view',return_value=False),patch('outcome_reader.spectator_view',return_value=False):
                result=reader.confirm_division(source,{},rank,observations)
        self.assertIsNone(rank['division']);return result

    def test_division_confirmation_does_not_count_repeated_decoder_pts(self):
        self.assertIsNone(self.division_refinement([2.,2.],[])['division'])

    def test_division_confirmation_preserves_unknown_when_tier_changes(self):
        values=[{'tier':'platinum','division':'III','confidence':.99},{'tier':'gold','division':'II','confidence':.99}]
        self.assertIsNone(self.division_refinement([1.96,2.04],values)['division'])

    def test_other_fields_reading_the_frame_does_not_exclude_rank_confirmation(self):
        value={'tier':'platinum','division':'III','confidence':.99}
        result=self.division_refinement([1.96],[value],extra=[{'time':1.96,'account':{'name':'SAMPLE'}}])
        self.assertEqual(result['division'],'III');self.assertEqual(len(result['division_evidence']),2)

    def test_native_iv_remains_iv_when_top_serifs_touch(self):
        patch=np.zeros((20,28,3),np.uint8)
        lines=['#######....#.','########..###','.###.###..##.','..##..##..##.',
               '..##..##..##.','..##..#####..','.###...####..','.###...####..','#####..###...','.####...##...']
        for y,line in enumerate(lines,7):
            for x,value in enumerate(line,8):
                if value=='#':patch[y,x]=255
        self.assertEqual(read_division(patch),'IV')

    def test_native_roman_stems_remain_three_when_serifs_touch(self):
        patch=np.zeros((24,32,3),np.uint8)
        for x in [10,15,20]:
            cv2.line(patch,(x,9),(x,18),(255,255,255),2)
            cv2.line(patch,(x-1,9),(x+2,9),(255,255,255),1)
            cv2.line(patch,(x-1,18),(x+2,18),(255,255,255),1)
        cv2.line(patch,(9,9),(22,9),(170,170,170),1)
        self.assertEqual(read_division(patch),'III')

    def test_threshold_broken_side_stems_do_not_reduce_three_to_one(self):
        for broken in [[(7,10),(7,18),(13,10),(13,18)],[(9,10),(13,10)]]:
            with self.subTest(broken=broken):
                patch=np.zeros((20,28,3),np.uint8)
                for x in [10,14,18]:
                    patch[7:16,x]=220
                    patch[8,x-1:x+2]=220;patch[15,x-1:x+2]=220
                # 边侧字干的暗像素在高阈值下断开，残笔仍属于同一行数字。
                for y,x in broken:patch[y,x]=170
                self.assertEqual(read_division(patch),'III')

    def test_intact_threshold_disagreement_still_remains_unknown(self):
        patch=np.zeros((20,28,3),np.uint8)
        for x,value in [(10,170),(14,220),(18,170)]:
            patch[7:16,x]=value
            patch[7,x-1:x+2]=value;patch[15,x-1:x+2]=value
        self.assertIsNone(read_division(patch))

    def test_similar_badge_shapes_still_require_matching_palette(self):
        shape=np.zeros((20,22),np.uint8)
        cv2.polylines(shape,[np.array([[2,18],[11,2],[20,18]],np.int32)],False,255,3)
        gold=np.zeros((20,22,3),np.uint8);gold[shape>0]=(45,165,220)
        platinum=np.zeros_like(gold);platinum[shape>0]=(220,205,110)
        reader=RankReader();reader.templates=[('gold',[gold]),('platinum',[platinum])]
        profile={'reference_size':[2560,1080],'hud_scale':[1,1],'rank_roi':[0,0,120,108]}
        for tier,template in [('gold',gold),('platinum',platinum)]:
            small=np.zeros((54,60,3),np.uint8);small[16:36,19:41]=template
            image=np.zeros((1080,2560,3),np.uint8);image[:108,:120]=cv2.resize(small,(120,108),interpolation=cv2.INTER_NEAREST)
            self.assertEqual(reader.inspect(image,profile)['tier'],tier)

    def test_real_recording_diamond_two(self):
        frame=BASE/'validation/sample100.jpg'
        if not frame.exists(): self.skipTest('本地真实录像样本不存在')
        rank=RankReader().inspect(cv2.imread(str(frame)))
        self.assertEqual(rank['tier'],'diamond');self.assertEqual(rank['division'],'II')
        self.assertGreater(rank['confidence'],.8)

    def test_blank_wrong_layout_and_blurred_rank_are_unknown(self):
        reader=RankReader()
        self.assertIsNone(reader.inspect(np.zeros((540,1280,3),np.uint8)))
        self.assertIsNone(reader.inspect(np.zeros((1080,1920,3),np.uint8)))
        self.assertIsNone(read_division(np.zeros((8,14,3),np.uint8)))

    def test_only_confirmed_empty_hud_defaults_to_matching(self):
        from rank_reader import empty_badge_region
        from hud_enrichment import rank_detail_missing
        image=np.full((1080,2560,3),100,np.uint8)
        profile={'reference_size':[2560,1080],'hud_scale':[1,1],'rank_roi':[2440,0,2560,108],'layout_status':'confirmed'}
        value=RankReader().inspect(image,profile)
        self.assertEqual(value['tier'],'unranked');self.assertFalse(rank_detail_missing(value))
        self.assertEqual(value['method'],'no_badge_matching_rule')
        profile['layout_status']='unknown'
        self.assertIsNone(RankReader().inspect(image,profile))
        # 陌生但可见的图形不能因模板不认识而误判成“无图标”。
        cv2.rectangle(image,(2470,15),(2530,75),(0,0,200),-1)
        self.assertIsNone(empty_badge_region(image[:108,2440:]))

    def test_shifted_squad_panel_means_no_badge_only_on_confirmed_layout(self):
        # 无徽章时「剩余小队数」白底面板右移进徽章位；有徽章时此处是深色徽章。
        from rank_reader import shifted_squad_panel
        image=np.full((1080,2560,3),120,np.uint8);roi=image[:108,2440:]
        roi[48:82,5:65]=(250,250,250);roi[55:75,15:30]=(20,20,20);roi[55:75,40:55]=(20,20,20)
        profile={'reference_size':[2560,1080],'hud_scale':[1,1],'rank_roi':[2440,0,2560,108],'layout_status':'confirmed'}
        self.assertIsNotNone(shifted_squad_panel(roi))
        self.assertEqual(RankReader().inspect(image,profile)['tier'],'unranked')
        profile['layout_status']='unconfirmed';self.assertIsNone(RankReader().inspect(image,profile))
        badge=np.full((108,120,3),120,np.uint8);cv2.circle(badge,(60,45),35,(30,30,30),-1)
        self.assertIsNone(shifted_squad_panel(badge))

    def test_colorless_badge_does_not_match_colored_tier_palette(self):
        from rank_reader import palette_matches
        template=np.zeros((20,22,3),np.uint8);template[4:16,4:18]=(40,110,200)
        gray=np.zeros_like(template);gray[4:16,4:18]=(190,190,190)
        self.assertFalse(palette_matches(template,gray))
        self.assertTrue(palette_matches(template,template))

    def test_bundled_mode_icons_are_recognized_as_other_mode(self):
        # 模板裁自真实 HUD；原图放回徽章位应判为「其他模式」，并标明是哪种图标。
        from rank_reader import mode_clock_evidence
        for name,icon in [('mode-clock.png','clock'),('mode-heart.png','heart')]:
            template=cv2.imread(str(BASE/'assets/modes'/name))
            roi=np.full((108,120,3),90,np.uint8);roi[10:10+template.shape[0],20:20+template.shape[1]]=template
            self.assertEqual(mode_clock_evidence(roi)['icon'],icon)
        self.assertIsNone(mode_clock_evidence(np.full((108,120,3),90,np.uint8)))

    def test_two_existing_samples_confirm_and_checkpoint_reuses_without_ocr(self):
        frame=BASE/'validation/sample100.jpg'
        if not frame.exists(): self.skipTest('本地真实录像样本不存在')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.mp4';source.write_bytes(b'fixture')
            for i in range(3):(root/f'{i:06d}.jpg').write_bytes(frame.read_bytes())
            cache={'source':fingerprint(source),'rows':[{'time':float(i),'frame':f'{i:06d}.jpg'} for i in range(3)]}
            result=recognize_segments(cache,root,[{'start':0,'end':3}],root/'rank.json')
            self.assertEqual(result['segments'][0]['rank']['division'],'II')
            self.assertEqual(result['new_sample_frames'],0);self.assertEqual(result['ocr_calls'],0)
            with patch('rank_reader.RankReader',side_effect=AssertionError('缓存不能重算')):
                self.assertEqual(recognize_segments(cache,root,[{'start':0,'end':3}],root/'rank.json'),result)

    def test_single_frame_is_not_enough_to_claim_rank(self):
        frame=BASE/'validation/sample100.jpg'
        if not frame.exists(): self.skipTest('本地真实录像样本不存在')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.mp4';source.write_bytes(b'fixture');(root/'000000.jpg').write_bytes(frame.read_bytes())
            cache={'source':fingerprint(source),'rows':[{'time':0.,'frame':'000000.jpg'}]}
            result=recognize_segments(cache,root,[{'start':0,'end':3}],root/'rank.json')
            self.assertIsNone(result['segments'][0]['rank'])

if __name__=='__main__':unittest.main()
