"""解码器选择回归：DirectML 只做识别推理，不得让 FFmpeg 去加载 CUDA 解码器。"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hardware_decode


class DecoderSelectionTests(unittest.TestCase):
    def setUp(self):
        self.patch=patch.dict(hardware_decode._PROBED,{},clear=True); self.patch.start()
        self.folder=tempfile.TemporaryDirectory(prefix='hwdecode-')
        self.source=Path(self.folder.name)/'clip.mp4'; self.source.write_bytes(b'fixture')
        self.video={'width':2560,'height':1080,'pix_fmt':'yuv420p'}

    def tearDown(self):
        self.folder.cleanup(); self.patch.stop()

    def test_requested_decoder_follows_startup_environment(self):
        with patch.dict(os.environ,{'APEX_HARDWARE_DECODER':'cuda'}):
            self.assertEqual(hardware_decode.requested(),'cuda')
        with patch.dict(os.environ,{'APEX_HARDWARE_DECODER':'d3d11'}):
            self.assertEqual(hardware_decode.requested(),'d3d11')
        with patch.dict(os.environ,{'APEX_HARDWARE_DECODER':''}):
            self.assertIsNone(hardware_decode.requested())
        with patch.dict(os.environ,{'APEX_HARDWARE_DECODER':'cuda','APEX_OCR_BACKEND':'dml'}):
            self.assertEqual(hardware_decode.requested(),'cuda')

    def test_directml_decode_uses_directx_arguments_not_cuda(self):
        arguments=' '.join(hardware_decode.arguments('d3d11'))
        self.assertIn('d3d11va',arguments)
        self.assertNotIn('cuda',arguments)

    def test_probe_failure_falls_back_to_cpu_instead_of_failing_the_task(self):
        with patch.dict(os.environ,{'APEX_HARDWARE_DECODER':'d3d11'}),patch.object(hardware_decode,'_decodes',return_value=False):
            self.assertIsNone(hardware_decode.active(self.source,self.video,60.))
        working=Path(self.folder.name)/'working.mp4'; working.write_bytes(b'working')
        with patch.dict(os.environ,{'APEX_HARDWARE_DECODER':'d3d11'}),patch.object(hardware_decode,'_decodes',return_value=True) as probe:
            self.assertEqual(hardware_decode.active(working,self.video,60.),'d3d11')
            hardware_decode.active(working,self.video,61.)
        self.assertEqual(probe.call_count,1)

    def test_empty_request_never_probes_hardware(self):
        with patch.dict(os.environ,{'APEX_HARDWARE_DECODER':''}),patch.object(hardware_decode,'_decodes') as probe:
            self.assertIsNone(hardware_decode.active(self.source,self.video,60.))
        self.assertFalse(probe.called)


if __name__=='__main__': unittest.main()
