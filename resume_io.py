"""逐批落盘的行日志；未提交尾部在恢复时截断，不重复已提交记录。"""
import json
import os
from pathlib import Path
import uuid

class RowJournal:
    def __init__(self,path,signature,validator=None):
        from apex_clipper import write_json
        self.path=Path(path); self.header=self.path.with_suffix(self.path.suffix+'.checkpoint.json')
        self.path.parent.mkdir(parents=True,exist_ok=True); self.signature=signature; self.rows=[]
        try: meta=json.loads(self.header.read_text(encoding='utf-8')) if self.header.exists() else {}
        except (ValueError,UnicodeError): meta={}
        if meta.get('signature')!=signature:
            for existing in [self.path,self.header]:
                if existing.exists():
                    archived=existing.with_name(existing.name+'.previous-'+uuid.uuid4().hex[:8])
                    archived.resolve().relative_to(existing.parent.resolve())
                    existing.replace(archived)
            self.path.touch(); write_json(self.header,{'signature':signature,'committed':0})
            meta={'committed':0}
        if not self.path.exists(): self.path.touch()
        offset=0
        with self.path.open('rb') as stream:
            for i in range(int(meta.get('committed',0))):
                line=stream.readline()
                try:
                    row=json.loads(line)
                    if validator and not validator(row,i): break
                except (ValueError,TypeError,KeyError): break
                self.rows.append(row); offset=stream.tell()
        with self.path.open('r+b') as stream: stream.truncate(offset)
        write_json(self.header,{'signature':signature,'committed':len(self.rows)})

    def append(self,rows):
        from apex_clipper import write_json
        with self.path.open('ab') as stream:
            for row in rows: stream.write((json.dumps(row,ensure_ascii=False)+'\n').encode('utf-8'))
            stream.flush(); os.fsync(stream.fileno())
        self.rows.extend(rows)
        write_json(self.header,{'signature':self.signature,'committed':len(self.rows)})
