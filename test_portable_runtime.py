import tempfile
from pathlib import Path
import unittest
import zipfile

from scripts.portable_runtime import assemble_runtime, dependency_files


class PortableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sources = {mode: self.root / mode for mode in ['cpu', 'dml']}
        for folder in self.sources.values():
            folder.mkdir()
        self.python = self.root / 'python.zip'
        with zipfile.ZipFile(self.python, 'w') as archive:
            archive.writestr('LICENSE.txt', 'Python license')
        self.bootstrap = self.root / 'bootstrap.py'
        self.bootstrap.write_text('# bootstrap', 'utf-8')

    def put(self, mode, name, data):
        file = self.sources[mode] / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)

    def test_shared_package_keeps_license_and_inputs(self):
        for mode in self.sources:
            self.put(mode, 'cv2/cv2.pyd', b'same native extension')
            self.put(mode, 'cv2/LICENSE.txt', b'license')
            self.put(mode, 'opencv_python-5.0.0.93.dist-info/LICENSE.txt', b'metadata license')
            self.put(mode, 'av/audio/format.pyd', b'audio extension')
            self.put(mode, 'av/video/format.pyd', b'video extension')
            self.put(mode, 'av.libs/decoder.dll', b'decoder')
            self.put(mode, 'onnxruntime/__init__.py', mode.encode())
        target = self.root / 'bundle'
        layout = assemble_runtime(target, self.sources, self.python, self.bootstrap)
        self.assertIn('cv2', layout['shared_units'])
        self.assertNotIn('onnxruntime', layout['shared_units'])
        self.assertTrue((target / 'runtime/shared/Lib/site-packages/cv2/LICENSE.txt').is_file())
        for mode in self.sources:
            self.assertTrue((self.sources[mode] / 'cv2/cv2.pyd').is_file())
            self.assertFalse((target / f'runtime/{mode}/Lib/site-packages/cv2').exists())
            self.assertTrue((target / f'runtime/{mode}/Lib/site-packages/onnxruntime').is_dir())

    def test_native_sibling_difference_keeps_entire_family_private(self):
        for mode in self.sources:
            self.put(mode, 'av/__init__.py', b'same loader')
            self.put(mode, 'av.libs/decoder.dll', mode.encode())
        target = self.root / 'bundle'
        layout = assemble_runtime(target, self.sources, self.python, self.bootstrap)
        self.assertNotIn('av', layout['shared_units'])
        self.assertNotIn('av.libs', layout['shared_units'])
        for mode in self.sources:
            self.assertTrue((target / f'runtime/{mode}/Lib/site-packages/av/__init__.py').is_file())

    def test_unreviewed_dependency_and_ambiguous_dll_rejected(self):
        self.put('cpu', 'unreviewed/__init__.py', b'x')
        with self.assertRaisesRegex(RuntimeError, '白名单'):
            dependency_files(self.sources['cpu'])
        other = self.root / 'other-cpu'
        other.mkdir()
        self.sources['cpu'] = other
        for mode in self.sources:
            self.put(mode, 'cv2/collision.dll', b'cv2')
            self.put(mode, 'PIL/collision.dll', b'PIL')
        with self.assertRaisesRegex(RuntimeError, '同名不同内容'):
            assemble_runtime(self.root / 'bundle', self.sources, self.python, self.bootstrap)


if __name__ == '__main__':
    unittest.main()
