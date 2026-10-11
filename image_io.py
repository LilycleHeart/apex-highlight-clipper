"""OpenCV image codecs with Python's Unicode-safe filesystem access."""
from pathlib import Path

import cv2
import numpy as np


def read_image(path, flags=cv2.IMREAD_COLOR):
    try:
        data = Path(path).read_bytes()
        return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), flags) if data else None
    except (OSError, cv2.error):
        return None


def write_image(path, image, params=None):
    try:
        path = Path(path)
        ok, data = cv2.imencode(path.suffix, image, params or [])
        if not ok:
            return False
        path.write_bytes(data.tobytes())
        return True
    except (OSError, cv2.error):
        return False
