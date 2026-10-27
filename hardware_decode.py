"""FFMPEG 硬件解码选择：识别后端不等于解码器。

DirectML 是 ONNX Runtime 的显卡推理 provider，AMD/Intel 显卡没有 FFmpeg 可用的
CUDA 解码器；把 dml 当成 cuda 会让解码直接失败（Cannot load nvcuda.dll），整段
采样拿不到画面。这里把两件事分开：

* `APEX_HARDWARE_DECODER` 由启动端按识别后端写入：cuda 后端用 cuda 硬解，
  DirectML 后端用 DirectX(d3d11va) 硬解，空字符串表示只做 CPU 解码。
* 真正采样前用本机显卡按真实滤镜图解出两帧确认；确认不了就退回 CPU，不让
  任务因为显卡品牌或驱动中断（识别设备保持不变）。
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

DECODERS={'cuda':['-hwaccel','cuda','-hwaccel_output_format','cuda'],
          'd3d11':['-hwaccel','d3d11va','-hwaccel_output_format','d3d11'],
          # AV1 软解（libaom）不认高 level 码流（seq_level_idx=23），只能用厂商解码器。
          'av1_cuvid':['-c:v','av1_cuvid'],
          'av1_qsv':['-c:v','av1_qsv'],
          'av1_amf':['-c:v','av1_amf']}
# hwaccel 解码留在显存，滤镜前必须 hwdownload；厂商解码器直接输出内存帧。
GPU_MEMORY={'cuda','d3d11'}
AV1_CANDIDATES=['av1_cuvid','av1_qsv','av1_amf','d3d11']
_PROBED={}


def gpu_memory(decoder):
    return decoder in GPU_MEMORY


def requested():
    """启动端请求的解码器；缺省沿用 CUDA，返回 None 表示只解码到内存（CPU）。"""
    name=os.environ.get('APEX_HARDWARE_DECODER','cuda')
    return name if name in DECODERS else None


def arguments(decoder):
    return list(DECODERS[decoder])


def active(source,video,duration):
    """本机确实可用的硬件解码器；不可用时返回 None，采样改走 CPU 解码。"""
    # AV1 的软件解码对高 level 码流会整段失败，因此优先找任一可用的硬件解码器。
    if str(video.get('codec_name') or '').lower()=='av1':
        return _active_av1(source,video,duration)
    decoder=requested()
    if not decoder: return None
    if decoder=='d3d11' and os.name!='nt': return None
    try: stat=Path(source).stat()
    except OSError: return None
    key=(decoder,str(Path(source).resolve()),stat.st_size,stat.st_mtime_ns,
         video.get('width'),video.get('height'),video.get('pix_fmt'))
    if key not in _PROBED:
        _PROBED[key]=_decodes(source,video,duration,decoder)
        if not _PROBED[key]:
            print(f'提示：本机 {decoder.upper()} 硬件解码不可用，改用 CPU 解码画面；识别设备不受影响',flush=True)
    return decoder if _PROBED[key] else None


def _active_av1(source,video,duration):
    from pathlib import Path
    try: stat=Path(source).stat()
    except OSError: return None
    key=('av1',str(Path(source).resolve()),stat.st_size,stat.st_mtime_ns,
         video.get('width'),video.get('height'),video.get('pix_fmt'))
    if key not in _PROBED:
        chosen=None
        for decoder in AV1_CANDIDATES:
            if decoder=='d3d11' and os.name!='nt': continue
            if _decodes(source,video,duration,decoder):
                chosen=decoder;break
        _PROBED[key]=chosen
        print(f'AV1 录像使用硬件解码：{chosen}' if chosen else
              '提示：本机没有可用的 AV1 硬件解码器，AV1 录像可能无法读取',flush=True)
    return _PROBED[key]


def _probe_command(source,video,duration,decoder,folder):
    from apex_clipper import tool
    width,height=video['width'],video['height']
    cx=round(width*.75/2)*2; cy=round(height*5/6/2)*2
    transfer='hwdownload,format=p010le,' if '10' in video.get('pix_fmt','') else 'hwdownload,format=nv12,'
    if not gpu_memory(decoder): transfer=''
    graph=(f'[0:v:0]fps=2,{transfer}split=2[b][h];[b]scale=1280:-2[body];'
           f'[h]crop={width-cx}:{height-cy}:{cx}:{cy}[hud]')
    start=max(0.,min(float(duration)/2,float(duration)-2))
    return [tool('ffmpeg'),'-hide_banner','-loglevel','error','-nostdin',
            '-ss',f'{start:.3f}','-t','3',*DECODERS[decoder],'-i',str(source),
            '-filter_complex',graph,
            '-map','[body]','-frames:v','2','-q:v','2','-n',str(folder/'%06d.jpg'),
            '-map','[hud]','-frames:v','2','-q:v','2','-n',str(folder/'hud/%06d.jpg')]


def _decodes(source,video,duration,decoder):
    folder=Path(tempfile.mkdtemp(prefix='ahc-hwprobe-'))
    try:
        (folder/'hud').mkdir()
        result=subprocess.run(_probe_command(source,video,duration,decoder,folder),
            capture_output=True,encoding='utf-8',errors='replace',timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode: return False
        return len(list(folder.glob('*.jpg')))>=1 and len(list((folder/'hud').glob('*.jpg')))>=1
    except (OSError,subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(folder,ignore_errors=True)
