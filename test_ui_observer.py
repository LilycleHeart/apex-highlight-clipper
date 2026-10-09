import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import ui_observer as ui

class ObserverTests(unittest.TestCase):
    def tearDown(self): ui.configure()
    def test_observer_optional(self):
        ui.configure(); ui.phase('fine','细查'); ui.preview(Path('missing.jpg'),1)
    def test_committed_preview_throttled_and_source_stage(self):
        events=[]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'帧 #%.jpg';p.write_bytes(b'jpeg')
            ui.configure(lambda kind,**v:events.append({'type':kind,**v}),'录像.mp4');ui.phase('bisect','二分',20)
            with patch('ui_observer.time.monotonic',side_effect=[10,10.2,11.1]):
                ui.preview(p,20);ui.preview(p,10);ui.preview(p,8)
        self.assertEqual(len(events),3);self.assertEqual(events[-1]['timestamp_seconds'],8)
        self.assertEqual(events[-1]['stage'],'bisect');self.assertEqual(events[-1]['source'],'录像.mp4')
    def test_missing_frame_does_not_emit(self):
        events=[];ui.configure(lambda *a,**k:events.append(k),'source');ui.preview('missing.jpg',10,force=True)
        self.assertEqual(events,[])

if __name__=='__main__':unittest.main()
