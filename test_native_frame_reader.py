import os
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np

import native_frame_reader as native
from app_cancel import TaskStopped


class NativeFrameReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'bframes.mp4'
        with av.open(str(cls.path),'w') as container:
            stream=container.add_stream('libx264',rate=30)
            stream.width=96;stream.height=64;stream.pix_fmt='yuv420p'
            stream.codec_context.thread_count=1
            stream.options={'g':'30','bf':'2'}
            for index in range(60):
                image=np.zeros((64,96,3),np.uint8)
                image[:,:,0]=index*3;image[:,index%80:index%80+16,1:]=190
                frame=av.VideoFrame.from_ndarray(image,format='bgr24')
                frame.pts=index;frame.time_base=Fraction(1,30)
                for packet in stream.encode(frame):container.mux(packet)
            for packet in stream.encode():container.mux(packet)
        with av.open(str(cls.path)) as container:
            cls.reference=[(frame.pts,float(frame.pts*frame.time_base),frame.to_ndarray(format='bgr24'))
                           for frame in container.decode(video=0)]

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def expected(self,moments):
        result=[];seen=set()
        for second in moments:
            frame=next((row for row in self.reference if row[1]>=second),None)
            if frame is None or frame[0] in seen:continue
            seen.add(frame[0]);result.append((frame[1],frame[2]))
        return result

    def test_forward_backward_duplicate_and_eof_requests_equal_sequential_oracle(self):
        batches=[[.01,.05,.09,.5,.51,.51,1.1],[1.14,1.10,.01,.03,1.98,3.],[-.1,0.,.01]]
        with native.native_frame_session():
            for moments in batches:
                actual=list(native.read_native_frames(self.path,moments));expected=self.expected(moments)
                self.assertEqual([time for time,_ in actual],[time for time,_ in expected])
                for (_,image),(_,reference) in zip(actual,expected):np.testing.assert_array_equal(image,reference)

    def test_recent_backward_request_reuses_already_decoded_native_pts(self):
        reader=native.NativeFrameReader(self.path)
        try:
            reader.read(.5);seeks=reader.seek_count;decoded=reader.decode_count
            value=reader.read(.49);expected=self.expected([.49])[0]
            self.assertEqual(reader.seek_count,seeks);self.assertEqual(reader.decode_count,decoded)
            self.assertEqual(value[1],expected[0]);np.testing.assert_array_equal(value[2],expected[1])
            self.assertLessEqual(reader.frame_bytes+reader.decoded_bytes,reader.max_frame_bytes)
        finally:reader.close()

    def test_half_second_probes_continue_decoding_without_repeated_seeks(self):
        reader=native.NativeFrameReader(self.path)
        try:
            moments=[.01,.51,1.01,1.51]
            actual=[reader.read(second) for second in moments]
            self.assertEqual(reader.seek_count,1)
            for frame,expected in zip(actual,self.expected(moments)):
                self.assertEqual(frame[1],expected[0])
                np.testing.assert_array_equal(frame[2],expected[1])
            self.assertLessEqual(reader.frame_bytes+reader.decoded_bytes,reader.max_frame_bytes)
        finally:reader.close()

    def test_nested_calls_share_one_decoder_and_release_it_on_failure(self):
        close=native.NativeFrameReader.close
        with patch('av.open',wraps=av.open) as opened,patch.object(native.NativeFrameReader,'close',autospec=True,side_effect=close) as closed:
            with self.assertRaisesRegex(RuntimeError,'fixture'):
                with native.native_frame_session():
                    list(native.read_native_frames(self.path,[.1]))
                    with native.native_frame_session():list(native.read_native_frames(self.path,[.14]))
                    self.assertEqual(opened.call_count,1);closed.assert_not_called()
                    raise RuntimeError('fixture')
            closed.assert_called_once();self.assertIsNone(native._SESSION.get())

    def test_cache_is_bounded_and_callers_cannot_mutate_saved_frames(self):
        with patch.object(native,'MAX_FRAMES',2):
            reader=native.NativeFrameReader(self.path)
            reader.max_frame_bytes=96*64*3*2
            try:
                first=reader.read(.1);expected=first[2].copy();first[2][:]=255
                np.testing.assert_array_equal(reader.read(.1)[2],expected)
                reader.read(.2);reader.read(.3)
                self.assertEqual(len(reader.frames),2);self.assertLessEqual(reader.frame_bytes,reader.max_frame_bytes)
                with patch.object(native,'check_cancel',side_effect=TaskStopped()):
                    with self.assertRaises(TaskStopped):reader.read(.3)
            finally:reader.close()

    def test_configured_decoder_threads_preserve_pts_and_frame_pixels(self):
        for threads,cache in [(1,16),(4,128)]:
            with patch.dict(os.environ,{'APEX_DECODE_THREADS':str(threads),'APEX_FRAME_CACHE_MB':str(cache)}):
                reader=native.NativeFrameReader(self.path)
                try:
                    self.assertEqual(reader.stream.codec_context.thread_count,threads)
                    self.assertEqual(reader.max_frame_bytes,cache*1024*1024)
                    for second in [.01,.5,.54,1.9,.1]:
                        actual=reader.read(second);expected=self.expected([second])[0]
                        self.assertEqual(actual[1],expected[0]);np.testing.assert_array_equal(actual[2],expected[1])
                finally:reader.close()

    def test_changed_source_metadata_invalidates_the_open_decoder(self):
        with native.native_frame_session():
            list(native.read_native_frames(self.path,[.1]));session=native._SESSION.get();first=session.reader
            stamp=self.path.stat();os.utime(self.path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+1_000_000))
            list(native.read_native_frames(self.path,[.1]))
            self.assertIsNot(session.reader,first);self.assertEqual(first.frames,{})

    def test_interleaved_source_eviction_does_not_break_a_suspended_generator(self):
        other=Path(self.temp.name)/'other.mp4';other.write_bytes(self.path.read_bytes())
        with native.native_frame_session():
            frames=native.read_native_frames(self.path,[.1,.2])
            first=next(frames);list(native.read_native_frames(other,[.3]));second=next(frames)
            with self.assertRaises(StopIteration):next(frames)
        expected=self.expected([.1,.2])
        self.assertEqual([first[0],second[0]],[row[0] for row in expected])
        np.testing.assert_array_equal(second[1],expected[1][1])


if __name__=='__main__':unittest.main()
