from fractions import Fraction
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from apex_clipper import BASE, counter_offset
from image_io import read_image
from hud_layout import make_profile, template_for, detect_images, detect_video, ensure_activity_is_readable, needs_layout_retry


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
