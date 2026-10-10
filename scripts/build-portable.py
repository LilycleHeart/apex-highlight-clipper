"""构建可移植 Windows 包；依赖只能来自指定且已验证的 Python 3.11 环境。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'publish'
PYTHON_URL = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'

def copy_tree(source, destination):
    shutil.copytree(source, destination, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'pip', 'pip-*',
            'setuptools', 'setuptools-*', 'pkg_resources', '_distutils_hack', 'distutils-precedence.pth'))

def release_files(target):
    # 依赖的测试目录、pip生成的pyc和运行时诊断也不进入发布包。
    for p in target.rglob('*'):
        rel=p.relative_to(target)
        if not p.is_file() or any(part in {'__pycache__','tests','validation','output'} for part in rel.parts): continue
        if p.suffix=='.pyc' or rel.parts[0]=='tools' or rel.as_posix()=='FILES.sha256.json': continue
        yield p

def validate_worker(target):
    # 无交战合成录像仍会经过默认索引、局部OCR、战果/枪械/段位配置加载。
    # 真正调用发布包worker，避免只验证第三方import而漏掉内核模块/配置。
    from apex_clipper import tool
    ffmpeg=Path(tool('ffmpeg'));probe=Path(tool('ffprobe'))
    if ffmpeg.parent!=probe.parent: raise RuntimeError('验证需要同目录FFmpeg与FFprobe')
    folder=target/'validation'/('build-smoke-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    source=folder/'Replay 2026-10-10 09-00-00.mp4'
    subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-f','lavfi','-i',
        'color=c=black:s=2560x1080:r=30','-t','3','-c:v','libx264','-preset','ultrafast',
        '-g','30','-bf','0','-pix_fmt','yuv420p',str(source)],check=True)
    request=folder/'request.json'
    request.write_text(json.dumps({'files':[str(source)],'output':str(folder/'results'),
        'backend':'cpu','scan_mode':'indexed','fps':2,'gpu_load':'low','verify':True,
        'delete_source':False}),'utf-8')
    result=subprocess.run([str(target/'runtime/cpu/python.exe'),str(target/'app_worker.py'),str(request)],
        cwd=target,env={**os.environ,'APEX_FFMPEG_DIR':str(ffmpeg.parent),'PYTHONUTF8':'1'},
        capture_output=True,text=True,encoding='utf-8',timeout=120)
    events=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    if result.returncode or not events or events[-1].get('type')!='done' or events[-1].get('failures')!=0:
        raise RuntimeError('发布内核验证失败：'+result.stdout[-4000:]+result.stderr[-2000:])
    if not source.exists(): raise RuntimeError('验证原片意外丢失')
    print('Portable indexed worker end-to-end OK')

def build(args):
    version = json.loads((ROOT/'electron-ui/package.json').read_text('utf-8'))['version']
    target = OUT / f'Apex-Clipper-{version}-Windows-x64'
    if target.exists() and not args.refresh:
        raise RuntimeError('目标包目录已存在，保留已有包；请先改名备份再重新构建。')
    target.mkdir(parents=True, exist_ok=args.refresh)
    # 明确白名单：不带私有录像、断点、测试输出、配置和开发环境。
    extra = [p.name for p in ROOT.glob('*.py') if not p.name.startswith(('test_', 'validate_', 'probe_', 'audit_', 'evaluate_', 'gpu_validation', 'gpu_stress', 'benchmark_', 'run_day', 'revise_day', 'write_day', 'gpu_outcome', 'gpu_quality'))]
    selected = set(extra + ['profile-ultrawide.json', 'combat-outcome-profile.json', 'weapon-catalog.json', 'weapon-catalog.v1.json', 'README.md', 'requirements.txt', 'requirements-gpu.txt'])
    for name in sorted(selected):
        p=ROOT/name
        if p.is_file(): shutil.copy2(p,target/name)
    for name in ['templates', 'models', 'assets/ranks']:
        copy_tree(ROOT/name, target/name)
    (target/'experimental').mkdir(exist_ok=True)
    for name in ['__init__.py','indexed_reader.py','in_memory_hud.py']:
        shutil.copy2(ROOT/'experimental'/name,target/'experimental'/name)
    for name in ['docs/third-party.md', 'docs/assets', 'scripts/setup-ffmpeg.ps1']:
        p=ROOT/name; dest=target/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if p.is_dir(): copy_tree(p,dest)
        elif p.exists(): shutil.copy2(p,dest)
    copy_tree(ROOT/'electron-ui'/args.electron/'Apex Highlight Clipper-win32-x64', target/'app')
    cache=OUT/'downloads';cache.mkdir(exist_ok=True)
    archive=cache/'python-3.11.9-embed-amd64.zip'
    if not archive.exists(): urllib.request.urlretrieve(PYTHON_URL,archive)
    # 官方发布页 MD5 用于供应包完整性；资产总清单另外使用 SHA256。
    if hashlib.md5(archive.read_bytes()).hexdigest() != '6d9aa08531d48fcc261ba667e2df17c4':
        raise RuntimeError('Python 官方嵌入包校验失败')
    for mode, environment in ([] if args.refresh else [('cpu',args.cpu), ('dml',args.gpu)]):
        env=Path(environment).resolve()
        if not (env/'Lib/site-packages/rapidocr_onnxruntime').exists():
            raise RuntimeError(f'{mode} 环境缺少 RapidOCR')
        runtime=target/'runtime'/mode;runtime.mkdir(parents=True)
        with zipfile.ZipFile(archive) as z: z.extractall(runtime)
        if mode=='cpu':
            # 开发环境可能继承系统site-packages；从requirements完整独立安装，
            # 不能只复制venv目录后漏掉NumPy/ORT等继承依赖。
            subprocess.run([str(env/'Scripts/python.exe'),'-m','pip','install',
                '--ignore-installed','--target',str(runtime/'Lib/site-packages'),
                '-r',str(ROOT/'requirements.txt'),'-c',str(ROOT/'requirements-portable-lock.txt')],check=True)
        else:
            copy_tree(env/'Lib/site-packages',runtime/'Lib/site-packages')
    for mode in ['cpu','dml']:
        runtime=target/'runtime'/mode
        # Windows的_pth对无尾分隔符的../..会裁掉末尾点；原生路径并保留尾分隔符。
        (runtime/'python311._pth').write_text('\n'.join([
            'python311.zip','.',str(Path('..')/'..')+os.sep,
            'Lib/site-packages','import site','']),'utf-8')
        subprocess.run([str(runtime/'python.exe'),'-c',
            "import os,numpy as np,sys,send2trash,pythoncom,av; os.environ['APEX_GPU_LOAD']='low'; "
            "from indexed_coarse import indexed_coarse_scan; "
            "from gpu_ocr_backend import create_ocr_engine; "
            "e=create_ocr_engine(backend=sys.argv[1],model_path='models/numeric_rec_en_v4.onnx'); "
            "print('Portable core inference OK',sys.argv[1],len(e.text_rec([np.full((32,96,3),255,np.uint8)])))",mode],cwd=target,check=True)
    validate_worker(target)
    (target/'Start.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nif not exist "tools\\ffmpeg.exe" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\\setup-ffmpeg.ps1"\r\nif not exist "tools\\ffmpeg.exe" (echo FFmpeg setup failed. See README.md. & pause & exit /b 1)\r\nstart "" "%~dp0app\\Apex Highlight Clipper.exe" %*\r\n','utf-8')
    inventory={str(p.relative_to(target)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in release_files(target)}
    (target/'FILES.sha256.json').write_text(json.dumps(inventory,indent=2),'utf-8')
    archive=OUT/(target.name+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in [*release_files(target),target/'FILES.sha256.json']:
            z.write(p,Path(target.name)/p.relative_to(target))
    (OUT/'SHA256SUMS.txt').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n','utf-8')
    print(archive)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cpu',default=str(ROOT/'.venv'))
    parser.add_argument('--gpu',default=str(ROOT/'.gpu-venv'))
    parser.add_argument('--electron',default='release-v3')
    parser.add_argument('--refresh',action='store_true',help='更新本次未发布暂存包的产品文件，保留已验证runtime并重写校验和ZIP')
    build(parser.parse_args())
