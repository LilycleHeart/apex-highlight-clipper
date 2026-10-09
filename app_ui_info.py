"""独立的只读录像信息查询，供桌面主进程异步调用。"""
import json
import sys
from pathlib import Path
from apex_clipper import probe

if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
if __name__=='__main__':
    try:
        source=Path(sys.argv[1]); meta,video=probe(source)
        ratio=video.get('avg_frame_rate','0/1').split('/')
        fps=float(ratio[0])/float(ratio[1]) if float(ratio[1]) else 0
        print(json.dumps({'path':str(source),'duration':float(meta['format']['duration']),
            'width':video['width'],'height':video['height'],'fps':fps},ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'path':sys.argv[1],'error':str(error)},ensure_ascii=False))
