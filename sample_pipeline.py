"""一个解码生产者、一个识别消费者；只消费已提交采样块，队列有界。"""
from concurrent.futures import ThreadPoolExecutor
import math
from queue import Queue,Empty,Full
import threading
from pathlib import Path
from apex_clipper import probe,read_hud,fingerprint
from resume_media import sample_with_resume
from app_cancel import check_cancel

def sample_and_read(source,samples,profile,fps,output,cuda=False,chunk_seconds=30):
    meta,_=probe(source); total=max(1,math.floor(float(meta['format']['duration'])*fps+.5))
    identity=fingerprint(source)
    queue=Queue(maxsize=2); abort=threading.Event(); session={}
    def committed(state):
        count=sum(c['count'] for c in state['chunks'])
        if count==0: return
        while not abort.is_set():
            check_cancel()
            try: queue.put(count,timeout=.2); return
            except Full: continue
    def decode(): return sample_with_resume(source,samples,fps,cuda,chunk_seconds,committed,abort)
    with ThreadPoolExecutor(max_workers=1) as executor:
        producer=executor.submit(decode)
        try:
            while not producer.done() or not queue.empty():
                check_cancel()
                try: ready=queue.get(timeout=.2)
                except Empty: continue
                read_hud(samples,profile,fps,output,resume=True,source_identity=identity,
                    frame_limit=ready,expected_frames=total,partial=True,session=session)
            producer.result()
            if fingerprint(source)!=identity: raise ValueError('解码时源录像发生变化')
            return read_hud(samples,profile,fps,output,resume=True,source_identity=identity,expected_frames=total,session=session)
        finally: abort.set()
