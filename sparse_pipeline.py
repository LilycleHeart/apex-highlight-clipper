"""Overlap sparse-range sampling and OCR using committed global sample IDs."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Full, Queue
import threading

from apex_clipper import fingerprint, read_hud, HUD_BATCH_SIZE
from app_cancel import check_cancel


def sample_and_read_sparse(source,samples,profile,fps,output,frame_ranges,cuda=False,cpu_threads=None,chunk_seconds=30):
    from continuous_sampler import sample_continuous_with_resume
    ids=[]
    for first,last in frame_ranges:
        if not isinstance(first,int) or not isinstance(last,int) or first<1 or last<first or (ids and first<=ids[-1]):
            raise ValueError('局部采样计划无效')
        ids.extend(range(first,last+1))
    names=[f'{i:06d}.jpg' for i in ids]
    source=Path(source); identity=fingerprint(source)
    notifications=Queue(maxsize=2); abort=threading.Event(); session={}; acknowledged=[0]
    def committed(state):
        current=[i for block in state['chunks'] for i in range(block['first'],block['first']+block['count'])]
        if current!=ids[:len(current)]: raise ValueError('解码提交与全局采样计划不一致')
        if not current:return
        if len(current)<acknowledged[0]: raise ValueError('解码提交发生回退')
        while not abort.is_set():
            check_cancel()
            try:notifications.put((len(current),current[-1]),timeout=.2);return
            except Full:continue
        raise RuntimeError('识别端已停止')
    def decode():
        return sample_continuous_with_resume(source,samples,fps,cuda,chunk_seconds=chunk_seconds,
            frame_ranges=frame_ranges,cpu_threads=cpu_threads,on_checkpoint=committed,abort_event=abort)
    with ThreadPoolExecutor(max_workers=1) as pool:
        producer=pool.submit(decode)
        try:
            while not producer.done() or not notifications.empty():
                check_cancel()
                try:count,last_id=notifications.get(timeout=.2)
                except Empty:continue
                # Preserve the old global OCR batch boundaries across sparse
                # decode blocks; do not infer a 3-frame partial batch at a gap.
                readable=count//HUD_BATCH_SIZE*HUD_BATCH_SIZE
                if readable<=acknowledged[0]:continue
                last_id=ids[readable-1]
                rows=read_hud(samples,profile,fps,output,resume=True,source_identity=identity,
                    expected_names=names,frame_limit=last_id,partial=True,session=session)
                acknowledged[0]=readable
                print(f'SMART_PROGRESS: {30+28*readable/max(1,len(ids)):.1f}',flush=True)
            producer.result()
            if fingerprint(source)!=identity:raise ValueError('流水线处理时源录像发生变化')
            rows=read_hud(samples,profile,fps,output,resume=True,source_identity=identity,
                expected_names=names,session=session)
            if [r['frame'] for r in rows]!=names:raise ValueError('局部细查没有完整覆盖采样计划')
            return rows
        finally:abort.set()
