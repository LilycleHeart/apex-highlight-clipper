"""只复用逐像素完全一致的 OCR 区域；不使用相似度或模糊图像哈希。"""
from collections import OrderedDict
import hashlib
import time

class ExactTextCache:
    def __init__(self,recognizer,capacity=4096):
        self.recognizer=recognizer; self.capacity=capacity
        self.cache=OrderedDict(); self.requested=0; self.inferred=0; self.hits=0

    def __getattr__(self,key): return getattr(self.recognizer,key)

    @staticmethod
    def key(image):
        return (image.shape,image.dtype.str,hashlib.blake2b(image.tobytes(),digest_size=20).digest())

    def __call__(self,images):
        started=time.perf_counter(); keys=[]; pending=OrderedDict(); result={}
        self.requested+=len(images)
        for image in images:
            key=self.key(image); keys.append(key)
            if key in self.cache:
                result[key]=self.cache[key]; self.cache.move_to_end(key); self.hits+=1
            elif key not in pending: pending[key]=image
            else: self.hits+=1
        if pending:
            values,_=self.recognizer(list(pending.values()))
            if len(values)!=len(pending): raise ValueError('OCR 返回区域数量不一致')
            self.inferred+=len(pending)
            for key,value in zip(pending,values):
                result[key]=value
                # 不跨批次复用接近解析门槛的结果，避免舍入差异越过阈值。
                confidence=float(value[1])
                if all(abs(confidence-threshold)>.002 for threshold in [.67,.75,.80,.86,.88]):
                    self.cache[key]=value; self.cache.move_to_end(key)
            while len(self.cache)>self.capacity: self.cache.popitem(last=False)
        return [result[key] for key in keys],time.perf_counter()-started

    def stats(self): return {'requested':self.requested,'inferred':self.inferred,'exact_reuse':self.hits}
