"""验证压缩包序列原样复制、起始关键帧、全部音轨和时间戳。"""
from pathlib import Path
import argparse
import json
import statistics
from apex_clipper import run, tool, probe, write_json,fingerprint
import hashlib

def packets(path,interval=None):
    args=[tool('ffprobe'),'-v','error']
    if interval is not None:
        args+=['-read_intervals',f'{interval[0]:.9f}%{interval[1]:.9f}']
    data=json.loads(run(args+['-show_packets','-show_data_hash','sha256',
                        '-show_entries','packet=stream_index,pts_time,dts_time,duration_time,flags,data_hash',
                        '-of','json',str(path)]))
    streams={}
    for p in data['packets']: streams.setdefault(p['stream_index'],[]).append(p)
    return streams

def subsequence(source, target):
    """重复静音包可能有相同哈希；用前几个包定位，再核对完整连续序列。"""
    if not target: return None
    first=target[:min(6,len(target))]
    for i,h in enumerate(source):
        if h==first[0] and source[i:i+len(first)]==first and source[i:i+len(target)]==target:
            return i
    return None

def validate(source, directory):
    directory=Path(directory)
    manifest=json.loads((directory/'export.json').read_text(encoding='utf-8'))
    if manifest.get('mode')=='segments':
        return validate_segments(source,directory,manifest)
    output=Path(manifest['output'])
    src_meta,_=probe(source); dst_meta,_=probe(output)
    expected_types=[(s['codec_type'],s['codec_name']) for s in src_meta['streams']]
    actual_types=[(s['codec_type'],s['codec_name']) for s in dst_meta['streams']]
    assert expected_types==actual_types,'编码/音轨变化'
    print('读取源文件压缩包 SHA256…',flush=True)
    src_packets=packets(source)
    hashes={i:[p['data_hash'] for p in ps] for i,ps in src_packets.items()}
    joins={i:[] for i in src_packets}
    clips=[]
    for clip in sorted((directory/'parts').glob('*.mp4')):
        ps=packets(clip)
        assert 'K' in ps[0][0]['flags'],'片段第一帧不是关键帧'
        streams=[]
        for i,stream in ps.items():
            sequence=[p['data_hash'] for p in stream]
            offset=subsequence(hashes[i],sequence)
            assert offset is not None,f'{clip.name} 流 {i} 不是原片连续包序列'
            joins[i].extend(sequence)
            streams.append({'stream':i,'packets':len(sequence),'source_packet_index':offset,
                            'source_first_pts':float(src_packets[i][offset]['pts_time']),
                            'source_last_pts':float(src_packets[i][offset+len(sequence)-1]['pts_time'])})
        clips.append({'file':str(clip),'streams':streams})
        print(f'{clip.name}: 视频与全部音轨的压缩包均匹配原片',flush=True)
    print('验证合集及时间戳…',flush=True)
    dst_packets=packets(output)
    timelines=[]
    for i,stream in dst_packets.items():
        assert [p['data_hash'] for p in stream]==joins[i],f'合集流 {i} 包序列变化'
        dts=[float(p['dts_time']) for p in stream if 'dts_time' in p]
        assert all(b>a for a,b in zip(dts,dts[1:])),f'流 {i} DTS 非严格递增'
        pts=[float(p['pts_time']) for p in stream]
        ends=[float(p['pts_time'])+float(p.get('duration_time',0)) for p in stream]
        steps=[b-a for a,b in zip(pts,pts[1:])]
        timelines.append({'stream':i,'start':min(pts),'end':max(ends),
                          'max_pts_gap':max(steps),'median_pts_gap':statistics.median(steps)})
    end_spread=max(t['end'] for t in timelines)-min(t['end'] for t in timelines)
    start_spread=max(t['start'] for t in timelines)-min(t['start'] for t in timelines)
    result={'passed':True,'source':str(source),'output':str(output),
            'encoded_payloads_unchanged':True,'all_tracks_preserved':True,
            'monotonic_dts':True,'clips':clips,'timelines':timelines,
            'stream_start_spread_seconds':start_spread,'stream_end_spread_seconds':end_spread,
            'note':'时间戳校验验证结构同步；听感和剪辑取舍仍需实际播放检查。'}
    write_json(directory/'verification.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['clips']},ensure_ascii=False,indent=2))
    return result

def validate_segments(source,directory,manifest):
    src_meta,_=probe(source)
    expected=[(s['codec_type'],s['codec_name']) for s in src_meta['streams']]
    print('按成片区间读取原片 SHA256，完整核对各成片全部压缩包…',flush=True)
    source_packets=None; full_hashes=None; duration=float(src_meta['format']['duration'])
    source_identity=fingerprint(source)
    signature=hashlib.sha256(json.dumps({'source':source_identity,'outputs':manifest['outputs'],
        'segments':[c['segment'] for c in manifest['clips']]},sort_keys=True).encode()).hexdigest()
    checkpoint=Path(directory)/'verification-checkpoint.json'
    saved=json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {}
    saved=saved if saved.get('signature')==signature else {'signature':signature,'clips':[]}
    verified=[]
    for clip in manifest['clips']:
        from app_cancel import check_cancel
        check_cancel()
        path=Path(clip['output'])
        previous=next((entry for entry in saved['clips'] if entry['file']==str(path)),None)
        if previous and path.is_file() and previous.get('output_identity')==fingerprint(path):
            verified.append(previous); print(f'校验续接：跳过已验证 {path.name}',flush=True); continue
        meta,_=probe(path)
        assert expected==[(s['codec_type'],s['codec_name']) for s in meta['streams']],'音视频轨变化'
        ps=packets(path)
        bounds=clip['segment']
        interval=(max(0,bounds['start']-2),min(duration,bounds['end']+2))
        source_window=packets(source,interval)
        hashes={i:[p['data_hash'] for p in stream] for i,stream in source_window.items()}
        assert set(ps)=={s['index'] for s in src_meta['streams']},'音视频轨数量不符'
        assert 'K' in ps[0][0]['flags'],'第一帧不是关键帧'
        streams=[]
        for i,stream in ps.items():
            offset=subsequence(hashes.get(i,[]),[p['data_hash'] for p in stream])
            basis='source_window'
            if offset is None:
                # 容器寻址/音频预滚不在读取窗口内时，回退全片，不能降低校验强度。
                if source_packets is None:
                    print('区间未覆盖完整预滚包，回退全片校验…',flush=True)
                    source_packets=packets(source)
                    full_hashes={j:[p['data_hash'] for p in packets_] for j,packets_ in source_packets.items()}
                offset=subsequence(full_hashes.get(i,[]),[p['data_hash'] for p in stream]); basis='full_source'
            assert offset is not None,f'{path.name} 流{i}压缩包与原片不一致'
            dts=[float(p['dts_time']) for p in stream if 'dts_time' in p]
            assert all(b>a for a,b in zip(dts,dts[1:])),'DTS 非严格递增'
            streams.append({'stream':i,'packets':len(stream),'source_packet_index':offset,'source_index_basis':basis})
        verified.append({'file':str(path),'streams':streams,'duration':meta['format']['duration'],'source_read_interval':interval,'output_identity':fingerprint(path)})
        saved['clips']=[entry for entry in saved['clips'] if entry['file']!=str(path)]+[verified[-1]]
        write_json(checkpoint,saved)
        print(f'{path.name}: 视频和全部音轨的压缩包匹配原片',flush=True)
    assert fingerprint(source)==source_identity,'校验时源录像发生变化'
    result={'passed':True,'mode':'segments','source':str(source),'outputs':manifest['outputs'],
            'encoded_payloads_unchanged':True,'all_tracks_preserved':True,'monotonic_dts':True,'clips':verified,
            'verification_scope':'all_output_packets_against_source_ranges','full_source_fallback_used':source_packets is not None}
    write_json(Path(directory)/'verification.json',result)
    print(f'分段验证通过: {len(verified)} 个独立视频',flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('source'); p.add_argument('directory')
    a=p.parse_args(); validate(a.source,a.directory)
