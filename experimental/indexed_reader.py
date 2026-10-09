"""Read indexed H.264 keyframes without demuxing every intervening video packet.

Experimental: no production detection or export rules are changed. A seek must
land on the exact indexed packet, and the decoded frame must retain its PTS.
"""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


class UnsupportedIndexedVideo(ValueError):
    pass


@dataclass(frozen=True)
class KeyframeEntry:
    dts: int
    position: int
    size: int


class IndexedKeyframeReader:
    def __init__(self, source, threads=2):
        import av
        self.source=Path(source)
        if not self.source.is_file():raise FileNotFoundError('A local video file is required')
        self.container=av.open(str(self.source))
        self.closed=False
        try:
            if 'mov' not in self.container.format.name.split(','):
                raise UnsupportedIndexedVideo('Prototype currently supports indexed MP4/MOV only')
            self.stream=self.container.streams.video[0]
            if self.stream.codec_context.name!='h264':
                raise UnsupportedIndexedVideo('Prototype currently validates H.264 only')
            entries=self.stream.index_entries
            if not 0<len(entries)<=2_000_000:
                raise UnsupportedIndexedVideo('Missing or oversized container index')
            # Copy values while the container is alive; never retain raw index entries.
            self.keyframes=tuple(KeyframeEntry(e.timestamp,e.pos,e.size) for e in entries if e.is_keyframe)
            if not self.keyframes or any(e.position<0 or e.size<=0 for e in self.keyframes):
                raise UnsupportedIndexedVideo('Missing packet positions or keyframes')
            if any(b.dts<=a.dts for a,b in zip(self.keyframes,self.keyframes[1:])):
                raise UnsupportedIndexedVideo('Keyframe decode timestamps are not increasing')
            if self.stream.start_time is None or self.stream.time_base is None:
                raise UnsupportedIndexedVideo('Missing authoritative stream timestamps')
            self.time_base=Fraction(self.stream.time_base)
            self.source_frames=len(entries)
            self.seek_bias=self.stream.start_time-self.keyframes[0].dts
            self.stream.codec_context.thread_count=threads
            self.stream.codec_context.thread_type='SLICE'
            self.stream.codec_context.skip_frame='NONKEY'
            self.width=self.stream.width;self.height=self.stream.height
        except BaseException:
            self.close();raise

    def close(self):
        if not self.closed:
            self.container.close();self.closed=True

    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def read_keyframe(self,index):
        if self.closed:raise RuntimeError('Reader is closed')
        entry=self.keyframes[index]
        self.stream.codec_context.skip_frame='NONKEY'
        self.container.seek(entry.dts+self.seek_bias,stream=self.stream,backward=True,any_frame=False)
        packet=next((p for p in self.container.demux(self.stream) if p.size),None)
        if packet is None or packet.pos!=entry.position or not packet.is_keyframe:
            raise UnsupportedIndexedVideo('Seek did not land on the requested indexed keyframe')
        packet_pts=packet.pts
        frames=list(self.stream.codec_context.decode(packet))
        # Drain the reorder queue after this one packet; the next seek resets it.
        frames.extend(self.stream.codec_context.decode(None))
        if len(frames)!=1:
            raise UnsupportedIndexedVideo('An indexed packet did not produce exactly one frame')
        frame=frames[0]
        if not frame.key_frame or frame.is_corrupt or frame.pts is None or frame.pts!=packet_pts:
            raise UnsupportedIndexedVideo('Corrupt frame or inconsistent presentation timestamp')
        frame.time_base=self.time_base
        return frame

    def read_burst(self,index,span=Fraction(1,8)):
        """Decode one keyframe and the first real frame at/after a short offset.

        Returned timestamps are decoder PTS, never a fabricated uniform grid.
        This only tests an IO strategy; two frames do not prove absence of combat.
        """
        if self.closed:raise RuntimeError('Reader is closed')
        span=Fraction(span)
        if not 0<span<=1:raise ValueError('Burst span must be in (0, 1] seconds')
        entry=self.keyframes[index];self.stream.codec_context.skip_frame='DEFAULT'
        self.container.seek(entry.dts+self.seek_bias,stream=self.stream,backward=True,any_frame=False)
        packets=self.container.demux(self.stream);packet=next((p for p in packets if p.size),None)
        if packet is None or packet.pos!=entry.position or not packet.is_keyframe:
            raise UnsupportedIndexedVideo('Seek did not land on the burst keyframe')
        start_pts=packet.pts
        if start_pts is None:raise UnsupportedIndexedVideo('Missing keyframe PTS')
        first=None;submitted=1
        def frames():
            nonlocal submitted
            yield from self.stream.codec_context.decode(packet)
            for following in packets:
                if following.size:submitted+=1
                if submitted>4096:raise UnsupportedIndexedVideo('Burst packet budget exceeded')
                yield from self.stream.codec_context.decode(following if following.size else None)
        for frame in frames():
            if frame.is_corrupt or frame.pts is None:raise UnsupportedIndexedVideo('Invalid burst frame')
            frame.time_base=self.time_base
            if first is None:
                if not frame.key_frame or frame.pts!=start_pts:raise UnsupportedIndexedVideo('Wrong burst origin')
                first=frame
            elif (frame.pts-first.pts)*self.time_base>=span:
                return first,frame,submitted
        raise UnsupportedIndexedVideo('Video ended before the requested burst interval')

    @staticmethod
    def body_image(frame,width=1280):
        height=round(frame.height*width/frame.width/2)*2
        return frame.reformat(width=width,height=height,format='bgr24',interpolation='BICUBIC').to_ndarray()
