"""Bounded native-frame reuse for a synchronous recognition operation.

Keep the original seek/PTS selection for distant or backward requests; adjacent
forward requests can continue the same decoder. No change to sample times,
OCR settings, or voting over distinct decoded PTS.
"""
from collections import OrderedDict,deque
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from app_cancel import check_cancel

_SESSION=ContextVar('native_frame_session',default=None)
MAX_FRAMES=16
# Event-weapon and endpoint probes commonly sit half a second apart. Seeking
# for each one repeats the same GOP; keep up to one second of forward decode.
FORWARD_WINDOW=1.


class NativeFrameReader:
    def __init__(self,source):
        import av
        self.container=av.open(str(source))
        self.stream=self.container.streams.video[0]
        from performance_options import native_resources
        settings=native_resources()
        self.stream.codec_context.thread_count=settings['decode_threads']
        self.max_frame_bytes=settings['frame_cache_mb']*1024*1024
        self.iterator=None;self.last_time=None
        self.frames=OrderedDict();self.frame_bytes=0
        self.decoded=deque();self.decoded_bytes=0
        self.decode_count=0;self.seek_count=0

    def close(self):
        try:
            if self.iterator is not None:self.iterator.close()
        finally:
            self.iterator=None
            self.container.close()
            self.frames.clear();self.frame_bytes=0
            self.decoded.clear();self.decoded_bytes=0

    def _retain(self,frame,previous):
        size=sum(plane.buffer_size for plane in frame.planes)
        if size>self.max_frame_bytes//4:return
        self.decoded.append((previous,float(frame.pts*frame.time_base),frame,size));self.decoded_bytes+=size
        while self.decoded and (len(self.decoded)>MAX_FRAMES or self.decoded_bytes>self.max_frame_bytes//4 or self.decoded_bytes+self.frame_bytes>self.max_frame_bytes):
            self.decoded_bytes-=self.decoded.popleft()[3]

    def _selected(self,second,frame):
        time=float(frame.pts*frame.time_base);image=frame.to_ndarray(format='bgr24')
        if image.nbytes<=self.max_frame_bytes:
            self.frames[second]=(frame.pts,time,image);self.frame_bytes+=image.nbytes
            while self.decoded and self.decoded_bytes+self.frame_bytes>self.max_frame_bytes:
                self.decoded_bytes-=self.decoded.popleft()[3]
            while self.frame_bytes>self.max_frame_bytes or len(self.frames)>MAX_FRAMES:
                _,(_,_,old)=self.frames.popitem(last=False);self.frame_bytes-=old.nbytes
        return frame.pts,time,image.copy()

    def read(self,second):
        check_cancel()
        if second in self.frames:
            self.frames.move_to_end(second)
            pts,time,image=self.frames[second]
            return pts,time,image.copy()
        # Reuse only a proven consecutive PTS interval. Frames already passed
        # by the decoder stay in native YUV form; no speculative decoding or
        # conversion of every source frame to BGR is needed.
        for previous,time,frame,_ in reversed(self.decoded):
            if time==second or previous is not None and previous<second<=time:
                return self._selected(second,frame)
        if self.iterator is None or self.last_time is None or not self.last_time<second<=self.last_time+FORWARD_WINDOW:
            if self.iterator is not None:self.iterator.close()
            self.container.seek(int(second/self.stream.time_base),stream=self.stream,backward=True,any_frame=False)
            self.seek_count+=1;self.last_time=None
            self.iterator=self.container.decode(self.stream)
        frame=None
        for candidate in self.iterator:
            check_cancel()
            self.decode_count+=1
            if candidate.pts is None:continue
            self._retain(candidate,self.last_time)
            self.last_time=float(candidate.pts*candidate.time_base)
            if self.last_time>=second:
                frame=candidate;break
        if frame is None:
            self.last_time=None
            return None
        return self._selected(second,frame)


class _Session:
    def __init__(self):self.identity=None;self.reader=None

    def close(self):
        if self.reader is not None:self.reader.close()
        self.reader=None;self.identity=None

    def open(self,source):
        path=Path(source).resolve();stat=path.stat()
        identity=(str(path),stat.st_size,stat.st_mtime_ns,stat.st_ino)
        if identity!=self.identity:
            self.close()
            self.reader=NativeFrameReader(path);self.identity=identity
        return self.reader


@contextmanager
def native_frame_session():
    """Nested calls share at most one decoder and 64 MiB of selected frames."""
    if _SESSION.get() is not None:
        yield
        return
    session=_Session();token=_SESSION.set(session)
    try:yield
    finally:
        try:session.close()
        finally:_SESSION.reset(token)


def read_native_frames(source,moments):
    with native_frame_session():
        session=_SESSION.get();reader=session.open(source);seen=set()
        for second in moments:
            # A nested consumer may read another source while this generator is
            # suspended at yield. Reacquire rather than use its evicted decoder.
            if session.reader is not reader:reader=session.open(source)
            result=reader.read(second)
            if result is None or result[0] in seen:continue
            pts,time,image=result;seen.add(pts)
            yield time,image
