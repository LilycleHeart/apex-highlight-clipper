"""Optional prototype tests with generated media, no private replay fixtures."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from fractions import Fraction

@unittest.skipUnless(importlib.util.find_spec('av'),'optional PyAV prototype dependency not installed')
class IndexedReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from apex_clipper import tool
        try:ffmpeg=tool('ffmpeg')
        except RuntimeError as error:raise unittest.SkipTest(str(error))
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'fixture.mp4'
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30',
            '-t','4','-c:v','libx264','-threads','2','-g','30','-keyint_min','30','-sc_threshold','0','-bf','2',
            '-pix_fmt','yuv420p',str(cls.path)],check=True,capture_output=True)
        import av
        cls.reference={};cls.keys=[]
        with av.open(str(cls.path)) as container:
            for frame in container.decode(video=0):
                cls.reference[frame.pts]=frame.to_ndarray(format='bgr24')
                if frame.key_frame:cls.keys.append(frame.pts)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_indexed_keyframes_equal_independent_sequential_decode(self):
        import numpy as np
        from experimental.indexed_reader import IndexedKeyframeReader
        with IndexedKeyframeReader(self.path) as reader:
            self.assertEqual(len(reader.keyframes),len(self.keys))
            for i,pts in enumerate(self.keys):
                frame=reader.read_keyframe(i);self.assertEqual(frame.pts,pts)
                np.testing.assert_array_equal(frame.to_ndarray(format='bgr24'),self.reference[pts])

    def test_burst_pts_and_pixels_are_actual_frames(self):
        import numpy as np
        from experimental.indexed_reader import IndexedKeyframeReader
        with IndexedKeyframeReader(self.path) as reader:
            for i,pts in enumerate(self.keys):
                first,last,decoded=reader.read_burst(i,Fraction(1,8))
                self.assertEqual(first.pts,pts);self.assertLess(decoded,10)
                self.assertGreaterEqual((last.pts-first.pts)*reader.time_base,Fraction(1,8))
                self.assertLess((last.pts-first.pts)*reader.time_base,Fraction(1,8)+Fraction(1,30))
                np.testing.assert_array_equal(last.to_ndarray(format='bgr24'),self.reference[last.pts])
                self.assertEqual(reader.read_keyframe(i).pts,pts)

    def test_closed_reader_and_invalid_span_are_rejected(self):
        from experimental.indexed_reader import IndexedKeyframeReader
        reader=IndexedKeyframeReader(self.path)
        with self.assertRaises(ValueError):reader.read_burst(0,0)
        reader.close();reader.close()
        with self.assertRaises(RuntimeError):reader.read_keyframe(0)

if __name__=='__main__':unittest.main()
