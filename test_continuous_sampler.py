"""Continuous sampler tests: synthetic CFR only, no personal replays or GPU."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from apex_clipper import BASE,tool
from app_cancel import TaskStopped
from continuous_sampler import sample_continuous_with_resume,_block_closed
from resume_media import sample_with_resume


class ClosedFileTests(unittest.TestCase):
    def test_eoi_alone_is_not_a_close_signal_and_both_successors_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'hud').mkdir()
            for folder in [root,root/'hud']: (folder/'000001.jpg').write_bytes(b'\xff\xd8fixture\xff\xd9')
            self.assertFalse(_block_closed(root,1))
            (root/'000002.jpg').touch(); self.assertFalse(_block_closed(root,1))
            (root/'hud/000002.jpg').touch(); self.assertTrue(_block_closed(root,1))
            self.assertTrue(_block_closed(root,2,True))


class ContinuousMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: ffmpeg=tool('ffmpeg')
        except RuntimeError as error: raise unittest.SkipTest(str(error))
        (BASE/'validation').mkdir(exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(prefix='continuous-fixture-',dir=BASE/'validation')
        cls.root=Path(cls.temp.name); cls.root.resolve().relative_to((BASE/'validation').resolve())
        cls.source=cls.root/'fixture.mp4'
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-f','lavfi','-i',
            'testsrc2=size=320x180:rate=30','-t','64','-c:v','libx264','-preset','ultrafast',
            '-threads','2','-g','30','-keyint_min','30','-sc_threshold','0','-bf','2','-pix_fmt','yuv420p',str(cls.source)],
            check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        from apex_clipper import probe
        _,video=probe(cls.source)
        if video.get('has_b_frames',0)<1: raise AssertionError('The fixture must contain B frames')
        cls.original=(cls.source.stat().st_size,cls.source.stat().st_mtime_ns)
        cls.baseline=cls.root/'baseline'
        sample_with_resume(cls.source,cls.baseline,2,cpu_threads=2)
        cls.reference=cls.hashes(cls.baseline)

    @classmethod
    def tearDownClass(cls):
        cls.root.resolve().relative_to((BASE/'validation').resolve())
        cls.temp.cleanup()

    @staticmethod
    def hashes(folder):
        return {str(path.relative_to(folder)):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in list(folder.glob('*.jpg'))+list((folder/'hud').glob('*.jpg'))}

    def assert_source_unchanged(self):
        self.assertEqual((self.source.stat().st_size,self.source.stat().st_mtime_ns),self.original)

    def test_one_process_spans_30_second_boundaries_with_identical_images(self):
        output=self.root/'whole'; calls=[]; actual=subprocess.Popen
        def launch(*args,**kwargs): calls.append(args[0]); return actual(*args,**kwargs)
        committed=[]
        with patch('continuous_sampler.subprocess.Popen',side_effect=launch):
            sample_continuous_with_resume(self.source,output,2,cpu_threads=2,
                on_checkpoint=lambda state:committed.append([(b['first'],b['count']) for b in state['chunks']]))
        decoder_calls=[args for args in calls if '-filter_complex' in args]
        self.assertEqual(len(decoder_calls),1)
        self.assertEqual(self.hashes(output),self.reference)
        self.assertEqual(committed,[[ (1,60) ],[(1,60),(61,60)],[(1,60),(61,60),(121,8)]])
        self.assert_source_unchanged()

    def test_disjoint_ranges_preserve_global_grid_and_one_process_per_range(self):
        ranges=[[2,65],[75,82],[91,123]]; old=self.root/'sparse-old'; new=self.root/'sparse-new'
        sample_with_resume(self.source,old,2,frame_ranges=ranges,cpu_threads=2)
        calls=[]; actual=subprocess.Popen
        def launch(*args,**kwargs): calls.append(args[0]); return actual(*args,**kwargs)
        with patch('continuous_sampler.subprocess.Popen',side_effect=launch):
            sample_continuous_with_resume(self.source,new,2,frame_ranges=ranges,cpu_threads=2)
        self.assertEqual(sum('-filter_complex' in args for args in calls),3)
        self.assertEqual(self.hashes(new),self.hashes(old))
        self.assertEqual(json.loads((new/'sampling-checkpoint.json').read_text())['info'],json.loads((old/'sampling-checkpoint.json').read_text())['info'])
        self.assert_source_unchanged()

    def test_live_cancellation_and_resume_preserve_committed_prefix(self):
        output=self.root/'cancelled'; marker=self.root/'stop.request'; processes=[]; actual=subprocess.Popen
        def launch(args,**kwargs):
            args=list(args)
            if '-filter_complex' in args:
                # Slow only the generated fixture so cancellation reliably occurs
                # while the child is alive. This does not change sampled pixels.
                at=args.index('-i'); args[at:at]=['-readrate','8']
            process=actual(args,**kwargs)
            if '-filter_complex' in args: processes.append(process)
            return process
        def stop_after_commit(state):
            self.assertIsNone(processes[-1].poll())
            marker.write_text('stop')
        with patch.dict(os.environ,{'APEX_TASK_STOP_FILE':str(marker)}),patch('continuous_sampler.subprocess.Popen',side_effect=launch):
            with self.assertRaises(TaskStopped):
                sample_continuous_with_resume(self.source,output,2,cpu_threads=2,on_checkpoint=stop_after_commit)
        self.assertTrue(all(p.poll() is not None for p in processes))
        self.assertFalse((output/'complete.json').exists())
        state=json.loads((output/'sampling-checkpoint.json').read_text()); self.assertEqual(len(state['chunks']),1)
        prefix={name:(output/name).stat().st_mtime_ns for name in self.hashes(output)}
        marker.unlink()
        sample_continuous_with_resume(self.source,output,2,cpu_threads=2)
        self.assertEqual(self.hashes(output),self.reference)
        self.assertTrue(all((output/name).stat().st_mtime_ns==stamp for name,stamp in prefix.items()))
        self.assert_source_unchanged()

    def test_corrupted_block_rewinds_without_rewriting_valid_prefix(self):
        output=self.root/'corrupt'; sample_continuous_with_resume(self.source,output,2,cpu_threads=2)
        prefix_stamp=(output/'000001.jpg').stat().st_mtime_ns
        (output/'000061.jpg').write_bytes(b'corrupt')
        commits=[]
        sample_continuous_with_resume(self.source,output,2,cpu_threads=2,on_checkpoint=lambda state:commits.append(len(state['chunks'])))
        self.assertEqual(commits,[1,2,3])
        self.assertEqual((output/'000001.jpg').stat().st_mtime_ns,prefix_stamp)
        self.assertEqual(self.hashes(output),self.reference)
        self.assert_source_unchanged()

    def test_legacy_checkpoint_is_reused_without_decoding(self):
        from apex_clipper import probe
        metadata=probe(self.source)
        with patch('continuous_sampler.subprocess.Popen') as launch:
            # probe itself launches ffprobe, so stub only its already-known result.
            with patch('continuous_sampler.probe',return_value=metadata):
                sample_continuous_with_resume(self.source,self.baseline,2,cpu_threads=2)
        self.assertFalse(launch.called)


if __name__=='__main__': unittest.main()
