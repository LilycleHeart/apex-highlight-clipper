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

    def test_replay_starting_between_keyframes_keeps_exact_index_positions(self):
        import av
        import numpy as np
        from apex_clipper import tool
        from experimental.indexed_reader import IndexedKeyframeReader
        path=Path(self.temp.name)/'mid-gop.mp4'
        subprocess.run([tool('ffmpeg'),'-hide_banner','-loglevel','error','-i',str(self.path),
            '-ss','0.3','-t','3','-c','copy','-copyinkf',str(path)],check=True,capture_output=True)
        with av.open(str(path)) as container:
            entries=container.streams.video[0].index_entries
            self.assertFalse(entries[0].is_keyframe)
            reference={frame.pts:frame.to_ndarray(format='bgr24') for frame in container.decode(video=0)}
        with IndexedKeyframeReader(path) as reader:
            for index in [0,len(reader.keyframes)-1]:
                frame=reader.read_keyframe(index)
                np.testing.assert_array_equal(frame.to_ndarray(format='bgr24'),reference[frame.pts])
            first,last,_=reader.read_burst(0)
            np.testing.assert_array_equal(first.to_ndarray(format='bgr24'),reference[first.pts])
            np.testing.assert_array_equal(last.to_ndarray(format='bgr24'),reference[last.pts])

    def test_nonzero_stream_origin_is_normalized_to_first_frame(self):
        from apex_clipper import keyframes, tool
        from experimental.indexed_reader import IndexedKeyframeReader
        from experimental.in_memory_hud import iter_indexed_images
        path=Path(self.temp.name)/'offset.mp4'
        subprocess.run([tool('ffmpeg'),'-hide_banner','-loglevel','error','-i',str(self.path),
            '-c','copy','-output_ts_offset','10',str(path)],check=True,capture_output=True)
        with IndexedKeyframeReader(path) as reader:
            self.assertEqual(reader.time_origin,Fraction(10))
            frame=reader.read_keyframe(0)
            self.assertEqual(frame.pts*reader.time_base-reader.time_origin,Fraction(0))
        frames=list(iter_indexed_images(path,mode='keyframes',workers=1,prefetch=1))
        self.assertEqual([float(f.timestamp) for f in frames],[0.,1.,2.,3.])
        self.assertEqual(keyframes(path),[0.,1.,2.,3.])

    def test_closed_reader_and_invalid_span_are_rejected(self):
        from experimental.indexed_reader import IndexedKeyframeReader
        reader=IndexedKeyframeReader(self.path)
        with self.assertRaises(ValueError):reader.read_burst(0,0)
        reader.close();reader.close()
        with self.assertRaises(RuntimeError):reader.read_keyframe(0)

if __name__=='__main__':unittest.main()
