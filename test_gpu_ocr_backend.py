import gc
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import weakref

import gpu_ocr_backend as backend


class DeviceModelLifetimeTests(unittest.TestCase):
    def test_model_survives_between_clip_owners_and_is_reused(self):
        class Session:
            def get_character_list(self):return ['A','B']
            def describe(self):return {'backend':'dml'}
        references=[]
        def create(*args):
            session=Session();references.append(weakref.ref(session));return session
        with tempfile.TemporaryDirectory() as temporary,patch.dict(backend._LIVE_SESSIONS,{},clear=True),patch.object(backend,'ExplicitOrtSession',side_effect=create):
            model=Path(temporary)/'model.onnx';model.write_bytes(b'test')
            owner=backend.create_ocr_engine(backend='dml',model_path=model)
            del owner;gc.collect()
            self.assertIsNotNone(references[0]())
            next_clip=backend.create_ocr_engine(backend='dml',model_path=model)
            self.assertIs(next_clip.text_rec.session,references[0]())
            self.assertTrue(next_clip.backend_info['session_reused']);self.assertEqual(len(references),1)

    def test_capacity_does_not_evict_a_device_graph_during_work(self):
        class Session:
            def get_character_list(self):return ['A']
            def describe(self):return {'backend':'dml'}
        with tempfile.TemporaryDirectory() as temporary,patch.dict(backend._LIVE_SESSIONS,{},clear=True),patch.object(backend,'_MAX_DML_SESSIONS',2),patch.object(backend,'ExplicitOrtSession',side_effect=lambda *args:Session()):
            paths=[Path(temporary)/f'{i}.onnx' for i in range(3)]
            for path in paths:path.write_bytes(b'test')
            first=backend.create_ocr_engine(backend='dml',model_path=paths[0]);backend.create_ocr_engine(backend='dml',model_path=paths[1])
            with self.assertRaisesRegex(RuntimeError,'模型会话上限'):backend.create_ocr_engine(backend='dml',model_path=paths[2])
            self.assertIs(backend.create_ocr_engine(backend='dml',model_path=paths[0]).text_rec.session,first.text_rec.session)


if __name__=='__main__':unittest.main()
