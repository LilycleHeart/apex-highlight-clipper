"""本人计分栏（击杀、助攻、伤害）数字的专用识别。

通用文字识别模型没有见过 Apex HUD 的字体：十几像素高的白色数字叠在游戏画面上，单独使用哪个通用模型
都会高置信度读错（详见 docs/development.md）。这里的主模型是一个小型 CNN + 双向 GRU + CTC 网络，
训练数据全部是本人 HUD 的真实裁片（只有数字区域，不含玩家名称），参考值取自同一片段前后多帧一致的读数平台。

只有主模型与另一个独立模型（PaddleOCR PP-OCRv6 small 识别模型）读出完全相同的数字时才采用；
任何一方读不出或两者不同，都视为这一帧读不出，不猜测。两帧确认仍由调用方负责。
"""
from functools import lru_cache
import hashlib
from pathlib import Path
import time
import urllib.request

import cv2
import numpy as np

METHOD = 'hud-digits-v1'
BASE = Path(__file__).resolve().parent
MODEL_PATH = BASE / 'assets/counters/hud_digits_v1.onnx'
MODEL_SHA256 = 'b59b9f9a7e174310fbf95931259b1765f8dba2f6a6f05de1bd699818ecf0f5f6'
HEIGHT, WIDTH = 28, 64
# 复核模型：RapidOCR 转换的 PP-OCRv6 small 识别模型（Apache-2.0）。
CHECK_URL = 'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx'
CHECK_SHA256 = '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884'
CHECK_PATH = BASE / 'models/ppocrv6_rec_small.onnx'
# 在没有参与训练的录像上校准（验证组与测试组共 1.5 万张）：主模型最低字符概率不低于 MODEL_MINIMUM、
# 复核模型置信度不低于 CHECK_MINIMUM 且两者一致时，伤害读错率约万分之七，击杀与助攻没有读错。
# 复核模型读出的内容里一个数字都没有（把数字读成符号，等于没给意见）时，主模型不低于 ALONE_MINIMUM 才单独采用；
# 复核模型读出了不同的数字一律不采用。校准集上单独采用的读数没有读错。
MODEL_MINIMUM = .5
CHECK_MINIMUM = .8
ALONE_MINIMUM = .97
# 采用的读数置信度取两者较低值，调用方按这个下限过滤。
MINIMUM = MODEL_MINIMUM
MAX_DIGITS = 5


def prepare(crop):
    """裁片（BGR 或灰度，任意缩放）按高度缩放到 28 像素，左对齐放进 28x64 画布。"""
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = gray.astype(np.float32) / 255.
    width = max(4, round(gray.shape[1] * HEIGHT / gray.shape[0]))
    gray = cv2.resize(gray, (width, HEIGHT), interpolation=cv2.INTER_AREA if gray.shape[0] >= HEIGHT else cv2.INTER_LINEAR)
    canvas = np.zeros((HEIGHT, WIDTH), np.float32)
    canvas[:, :min(WIDTH, width)] = gray[:, :WIDTH]
    return canvas


def decode(probs):
    """CTC 贪心解码；置信度取各输出字符的最大概率中最小的一个。"""
    best = probs.argmax(-1)
    result = []
    for row, path in zip(probs, best):
        text, previous, confidence = [], 0, 1.
        for step, label in enumerate(path.tolist()):
            if label != previous and label != 0:
                text.append(str(label - 1))
                confidence = min(confidence, float(row[step, label]))
            previous = label
        result.append((''.join(text), confidence if text else 0.))
    return result


def agreed(primary, check):
    """主模型与复核模型逐张比对：数字串完全相同且各自达到门槛才采用；复核模型没读出任何数字时见 ALONE_MINIMUM。"""
    result = []
    for (text, confidence), (other, other_confidence) in zip(primary, check):
        other = (other or '').strip()
        usable = bool(text) and len(text) <= MAX_DIGITS and confidence >= MODEL_MINIMUM
        if usable and other == text and float(other_confidence) >= CHECK_MINIMUM:
            result.append((text, min(confidence, float(other_confidence))))
        elif usable and confidence >= ALONE_MINIMUM and not any(character.isdigit() for character in other):
            result.append((text, confidence))
        else:
            result.append(('', 0.))
    return result


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort
    data = MODEL_PATH.read_bytes()
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise ValueError('计分数字识别模型校验失败')
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    return ort.InferenceSession(data, options, providers=['CPUExecutionProvider'])


def ensure_check_model():
    CHECK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CHECK_PATH.exists():
        print('下载计分数字复核模型（约 20 MB，首次运行）…', flush=True)
        temp = CHECK_PATH.with_suffix('.part')
        with urllib.request.urlopen(CHECK_URL, timeout=60) as response, temp.open('wb') as output:
            while data := response.read(1024 * 1024):
                output.write(data)
        if hashlib.sha256(temp.read_bytes()).hexdigest() != CHECK_SHA256:
            temp.unlink(missing_ok=True)
            raise ValueError('下载的计分数字复核模型 SHA256 校验不符')
        temp.replace(CHECK_PATH)
    if hashlib.sha256(CHECK_PATH.read_bytes()).hexdigest() != CHECK_SHA256:
        raise ValueError('计分数字复核模型 SHA256 校验不符')
    return CHECK_PATH


@lru_cache(maxsize=1)
def _check():
    # 两个模型都固定用 CPU：裁片宽度各不相同，GPU 动态形状反而慢，也避免不同后端读数不一致。
    from gpu_ocr_backend import create_ocr_engine
    return create_ocr_engine(backend='cpu', model_path=str(ensure_check_model()), rec_batch_num=24).text_rec


class HudDigitReader:
    """与原读数器相同的调用方式：reader(images) -> ([(text, confidence), ...], elapsed)。"""

    def __call__(self, images):
        started = time.perf_counter()
        if not images:
            return [], 0.
        batch = np.stack([prepare(image) for image in images])[:, None]
        primary = decode(_session().run(None, {'x': batch})[0])
        # 只复核主模型读得出的裁片。
        wanted = [index for index, (text, confidence) in enumerate(primary) if text and confidence >= MODEL_MINIMUM]
        check = [('', 0.)] * len(images)
        if wanted:
            reads, _ = _check()([check_view(images[index]) for index in wanted])
            for index, read in zip(wanted, reads):
                check[index] = (read[0].strip().rstrip(DIVIDER).strip(), float(read[1]))
        return agreed(primary, check), time.perf_counter() - started


# 伤害数字右侧紧贴斜分隔线，复核模型常把它读成末尾的「/」。
DIVIDER = '/|\\ '


def check_view(crop):
    """复核模型的输入（与校准时相同）：放大 3 倍；伤害这类宽裁片先去掉右侧贯穿的斜分隔线。"""
    from stat_counter_fallback import without_counter_divider
    view = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    if crop.shape[1] >= 2 * crop.shape[0]:
        clean = without_counter_divider(view)
        if clean is not None:
            view = clean
    return view
