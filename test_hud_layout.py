from fractions import Fraction
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from apex_clipper import BASE, counter_offset
from image_io import read_image
from hud_layout import make_profile, layout_candidates, template_for, detect_images, detect_video, ensure_activity_is_readable, needs_layout_retry


class HudLayoutTests(unittest.TestCase):
    def test_stretched_counter_moved_below_old_search_is_confirmed(self):
        profile=make_profile(1920,1080,.75)
        marker=read_image(BASE/'templates/damage-marker.png',cv2.IMREAD_GRAYSCALE)
        resized=template_for(profile,marker)
        image=np.zeros((540,960,3),dtype=np.uint8)
        x,y=round(profile['counter_marker_origin'][0]/2),round((profile['counter_marker_origin'][1]+48)/2)
        image[y:y+resized.shape[0],x:x+resized.shape[1]]=resized[:,:,None]
        image=cv2.resize(image,(1920,1080),interpolation=cv2.INTER_NEAREST)
        detected=detect_images([image],1920,1080)
        self.assertEqual(detected['layout_status'],'confirmed')
        self.assertEqual(detected['layout'],'4:3-stretched')
        offset,score=counter_offset(image,detected,marker)
        self.assertGreaterEqual(score,.78)
        self.assertGreaterEqual(offset[1],46)

    def test_pillarboxed_four_by_three_recording_anchors_hud_inside_black_bars(self):
        # 显卡即时回放把未拉伸的 4:3 画面放在 16:9 文件中间，两侧是纯黑边。
        inner=make_profile(1920,1440,.75)
        marker=read_image(BASE/'templates/damage-marker.png',cv2.IMREAD_GRAYSCALE)
        resized=template_for(inner,marker)
        game=np.full((720,960,3),70,dtype=np.uint8)
        x,y=round(inner['counter_marker_origin'][0]/2),round(inner['counter_marker_origin'][1]/2)
        game[y:y+resized.shape[0],x:x+resized.shape[1]]=resized[:,:,None]
        game=cv2.resize(game,(1920,1440),interpolation=cv2.INTER_NEAREST)
        frame=np.zeros((1440,2560,3),np.uint8);frame[:,320:2240]=game
        detected=detect_images([frame],2560,1440)
        self.assertEqual(detected['layout_status'],'confirmed')
        self.assertEqual(detected['content_box'],[320,0,1920,1440])
        self.assertEqual(detected['damage'],[v+320*(i%2==0) for i,v in enumerate(inner['damage'])])
        # 没有黑边的普通宽屏录像不追加黑边候选，原有布局不变。
        self.assertNotIn('content_box',make_profile(2560,1440))

    def test_self_name_row_voice_icon_confirms_native_layout_only_on_two_frames(self):
        # 计分栏被叠加层盖住时，本人名称行的语音图标在两帧中位于固定高度才算原生标准布局。
        from hud_layout import confirm_by_name_row
        profile=make_profile(2560,1080);voice=read_image(BASE/'templates/hud/voice.png',cv2.IMREAD_GRAYSCALE)
        x1,y1,x2,y2=profile['account_roi'];top=round((y1+y2)/2-voice.shape[0]/2)
        frame=np.full((1080,2560,3),40,np.uint8);frame[top:top+voice.shape[0],x1+120:x1+120+voice.shape[1]]=voice[:,:,None]
        blank=np.full((1080,2560,3),40,np.uint8)
        self.assertIsNotNone(confirm_by_name_row([frame,frame],profile))
        self.assertIsNone(confirm_by_name_row([frame,blank],profile))
        shifted=np.full((1080,2560,3),40,np.uint8);shifted[top+60:top+60+voice.shape[0],x1+120:x1+120+voice.shape[1]]=voice[:,:,None]
        self.assertIsNone(confirm_by_name_row([shifted,shifted],profile))
        self.assertIsNone(confirm_by_name_row([frame,frame],make_profile(2560,1080,.75)))

    def _marker_image(self,profile):
        marker=read_image(BASE/'templates/damage-marker.png',cv2.IMREAD_GRAYSCALE)
        resized=template_for(profile,marker);width,height=profile['reference_size']
        image=np.zeros((height//2,width//2,3),dtype=np.uint8)
        x,y=round(profile['counter_marker_origin'][0]/2),round(profile['counter_marker_origin'][1]/2)
        image[y:y+resized.shape[0],x:x+resized.shape[1]]=resized[:,:,None]
        return cv2.resize(image,(width,height),interpolation=cv2.INTER_NEAREST)

    def test_sixteen_by_ten_hud_scales_by_width_not_height(self):
        # 16:10 的 HUD 排在 16:9 安全区内：3456x2160 实测缩放 1.8，不是按高度算的 2.0。
        expected=next(p for p in layout_candidates(3456,2160) if [round(v,3) for v in p['hud_scale']]==[1.8,1.8])
        detected=detect_images([self._marker_image(expected)],3456,2160)
        self.assertEqual(detected['layout_status'],'confirmed')
        self.assertEqual([round(v,3) for v in detected['hud_scale']],[1.8,1.8])

    def test_compact_interface_layout_is_detected_separately(self):
        expected=make_profile(1280,720,.75,ui='compact')
        detected=detect_images([self._marker_image(expected)],1280,720)
        self.assertEqual(detected['layout_status'],'confirmed')
        self.assertEqual(detected.get('ui_layout'),'compact')
        self.assertEqual(detected['account_roi'],expected['account_roi'])
        # 标准界面的配置保持旧版字段，已有识别缓存可继续复用。
        self.assertNotIn('ui_layout',make_profile(1280,720,.75))

    def test_four_hour_probe_is_bounded_and_stops_once_confirmed(self):
        class Container:
            def __init__(self):
                self.streams=SimpleNamespace(video=[SimpleNamespace(time_base=Fraction(1,1),codec_context=SimpleNamespace(thread_count=0))]);self.seeks=[]
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def seek(self,second,**kwargs):self.seeks.append(second)
            def decode(self,stream):return iter([SimpleNamespace(pts=self.seeks[-1]+1,time_base=Fraction(1,1),to_ndarray=lambda **kwargs:np.zeros((4,4,3),np.uint8))])
        container=Container()
        with patch('av.open',return_value=container),patch('hud_layout.detect_images',return_value={'layout_status':'unconfirmed'}):
            result=detect_video('four-hours.mp4',{'width':1920,'height':1080},14400)
        self.assertEqual(result['layout_probe_frames'],8)
        self.assertGreater(max(container.seeks),14400*.9)
        container=Container()
        with patch('av.open',return_value=container),patch('hud_layout.detect_images',side_effect=[{'layout_status':'unconfirmed'},{'layout_status':'confirmed'}]):
            result=detect_video('four-hours.mp4',{'width':1920,'height':1080},14400)
        self.assertEqual(result['layout_probe_frames'],2)

    def test_unreadable_active_hud_is_not_successful_empty_export(self):
        with self.assertRaisesRegex(ValueError,'HUD'):
            ensure_activity_is_readable({'layout_status':'unconfirmed'},[],{'seed_count':637})
        ensure_activity_is_readable({'layout_status':'unconfirmed'},[],{'seed_count':0})
        ensure_activity_is_readable({'layout_status':'confirmed'},[],{'seed_count':637})
        self.assertTrue(needs_layout_retry({'outputs':[]},{'layout_status':'unconfirmed','layout_version':'anchored-hud-v1'}))
        self.assertFalse(needs_layout_retry({'outputs':[]},{**make_profile(1920,1080),'layout_status':'unconfirmed'}))
        self.assertFalse(needs_layout_retry({'outputs':['clip.mp4']},{'layout_status':'unconfirmed','layout_version':'anchored-hud-v1'}))
