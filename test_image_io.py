import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from image_io import read_image, write_image


class ImageIOTests(unittest.TestCase):
    def test_unicode_paths_preserve_pixels_and_decode_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'Apex交战剪辑' / '缓存'
            root.mkdir(parents=True)
            image = np.full((16, 24, 4), (20, 70, 150, 190), dtype=np.uint8)
            png = root / '透明贴图.png'
            self.assertTrue(write_image(png, image))
            np.testing.assert_array_equal(read_image(png, cv2.IMREAD_UNCHANGED), image)
            self.assertEqual(read_image(png, cv2.IMREAD_GRAYSCALE).shape, (16, 24))
            jpeg = root / '预览.jpg'
            self.assertTrue(write_image(jpeg, image[:, :, :3], [cv2.IMWRITE_JPEG_QUALITY, 82]))
            self.assertEqual(read_image(jpeg).shape, (16, 24, 3))

    def test_missing_or_invalid_images_keep_opencv_failure_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(read_image(root / 'missing.jpg'))
            invalid = root / '无效.jpg'
            invalid.write_bytes(b'invalid')
            self.assertIsNone(read_image(invalid))
            self.assertFalse(write_image(root / 'missing-parent' / 'preview.jpg', np.zeros((8, 8, 3), dtype=np.uint8)))
