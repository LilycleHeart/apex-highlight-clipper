"""构建可移植 Windows 包；依赖只能来自指定且已验证的 Python 3.11 环境。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import tempfile
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.portable_runtime import assemble_runtime, dependency_files
OUT = ROOT / 'publish'
PYTHON_URL = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'
PRODUCT_MODULES = '''adaptive_evidence apex_clipper app_cancel app_options app_task app_ui_info app_worker clip_deletions
    build_weapon_catalog clip_quality_filter combat_candidate_completion combat_outcome_reader combat_statistics continuous_sampler
    damage_bisection early_round_end engine_pool event_weapon_reader evidence_completion gpu_load gpu_ocr_backend hero_reader hero_portrait_reader hud_layout hud_enrichment image_io indexed_coarse
    inspect_video japanese_name_reader latin_word_boundaries name_reader numeric_reader ocr_cache outcome_reader player_names planning_evidence rank_reader rename_exports repair_cached_statistics
    resume_io resume_media sample_locations sample_pipeline setup_weapon_model smart_scan sparse_pipeline
    stat_counter_fallback target_name_reader ui_observer verify_export weapon_reader'''.split()

def copy_tree(source, destination):
    shutil.copytree(source, destination, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'pip', 'pip-*',
            'setuptools', 'setuptools-*', 'pkg_resources', '_distutils_hack', 'distutils-precedence.pth'))

def assert_bundle_not_running(bundle):
    if os.name!='nt' or not bundle.exists():return
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',
        'Get-CimInstance Win32_Process | Select-Object -ExpandProperty ExecutablePath | ConvertTo-Json -Compress'],
        capture_output=True,text=True,encoding='utf-8',timeout=30,check=True)
    paths=json.loads(result.stdout or '[]')
    if isinstance(paths,str):paths=[paths]
    root=bundle.resolve()
    if any(path and Path(path).resolve().is_relative_to(root) for path in paths):
        raise RuntimeError('目标应用正在运行，不能刷新；请使用独立暂存目录')

def release_files(target):
    # 依赖的测试目录、pip生成的pyc和运行时诊断也不进入发布包。
    for p in target.rglob('*'):
        rel=p.relative_to(target)
        if not p.is_file() or any(part in {'__pycache__','tests','validation','output'} for part in rel.parts): continue
        if p.suffix=='.pyc' or rel.as_posix().startswith(('tools/','resources/tools/')) or p.name in {'FILES.sha256.json','ffmpeg.local.json'}: continue
        yield p

def verified_shared_source(source):
    """只读预检必须在标记构建或覆盖既有包之前完成。"""
    source=Path(source).resolve()
    source_content=source/'resources' if (source/'resources/app_worker.py').is_file() else source
    manifest=source_content/'FILES.sha256.json'
    report=json.loads((source.parent/'validation-report.json').read_text('utf-8'))
    archive=source.parent/(source.name+'.zip')
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=report.get('sha256'):
        raise RuntimeError('共享候选ZIP与既有验证报告不一致')
    if {item['mode'] for item in report.get('inference',[])}!={'cpu','dml'}:
        raise RuntimeError('共享候选缺少CPU/DirectML独立推理记录')
    with zipfile.ZipFile(archive) as z:
        inventory=json.loads(z.read(source.name+'/'+manifest.relative_to(source).as_posix()))
    if inventory!=json.loads(manifest.read_text('utf-8')):
        raise RuntimeError('共享候选文件清单已变化')
    return source,source_content,inventory


def reuse_shared_runtime(source,target,verified=None):
    """复用逐文件未变的运行库；产品代码或识别资源改变时重新验证推理与内核。"""
    source,source_content,inventory=verified or verified_shared_source(source)
    kernel_changed=[]
    for name,digest in inventory.items():
        file=(source/name).resolve()
        if not file.is_relative_to(source_content):continue
        relative=file.relative_to(source_content).as_posix()
        if relative.startswith('runtime/'):
            if not file.is_relative_to(source) or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:
                raise RuntimeError('已验证运行库内容已变化：'+name)
            dest=target/relative
            if file!=dest.resolve():
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,dest)
        elif relative.endswith('.py') or relative.startswith(('models/','templates/','assets/ranks/')) or relative in {'profile-ultrawide.json','combat-outcome-profile.json','weapon-catalog.json','weapon-catalog.v1.json'}:
            file=target/relative
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:
                if file.is_file():kernel_changed.append(relative)
                else:raise RuntimeError('识别资源已改变，需要重新验证运行库：'+name)
    for mode in ['cpu','dml']:
        if (target/'runtime'/mode/'sitecustomize.py').read_bytes()!=(ROOT/'scripts/portable_sitecustomize.py').read_bytes():
            raise RuntimeError('共享加载器已修改，需要重新构建并验证运行库')
    print('Reused previously validated, byte-identical CPU/DirectML runtime')
    if kernel_changed:print('Changed product modules/resources require inference and worker smoke:',','.join(kernel_changed))
    return not kernel_changed

def validate_worker(target):
    folder=target/'validation';folder.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='build-smoke-中文路径-',dir=folder) as temporary:
        _validate_worker(target,Path(temporary))
    if not any(folder.iterdir()):folder.rmdir()

def build_launcher(target,version):
    framework=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET'
    compiler=next((framework/mode/'v4.0.30319/csc.exe' for mode in ['Framework64','Framework']
        if (framework/mode/'v4.0.30319/csc.exe').is_file()),None)
    if compiler is None:raise RuntimeError('构建启动EXE需要Windows自带的.NET Framework C#编译器')
    with tempfile.TemporaryDirectory(prefix='launcher-',dir=target.parent) as temporary:
        metadata=Path(temporary)/'version.cs'
        metadata.write_text('using System.Reflection;\n[assembly: AssemblyVersion("'+version+'.0")]\n'
            '[assembly: AssemblyFileVersion("'+version+'.0")]\n','utf-8')
        subprocess.run([str(compiler),'/nologo','/codepage:65001','/target:winexe','/platform:x64','/optimize+',
            '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
            '/win32icon:'+str(ROOT/'electron-ui/public/brand/cat-clapperboard.ico'),
            '/out:'+str(target/'Apex Highlight Clipper.exe'),str(ROOT/'scripts/windows-launcher.cs'),
            str(metadata)],check=True)

def _validate_worker(target,folder):
    # 无交战合成录像仍会经过默认索引、局部OCR、战果/枪械/段位配置加载。
    # 真正调用发布包worker，避免只验证第三方import而漏掉内核模块/配置。
    from apex_clipper import tool
    ffmpeg=Path(tool('ffmpeg'));probe=Path(tool('ffprobe'))
    if ffmpeg.parent!=probe.parent: raise RuntimeError('验证需要同目录FFmpeg与FFprobe')
    source=folder/'Replay 2026-10-10 09-00-00.mp4'
    subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-f','lavfi','-i',
        'color=c=black:s=2560x1080:r=30','-t','3','-c:v','libx264','-preset','ultrafast',
        '-g','30','-bf','0','-pix_fmt','yuv420p',str(source)],check=True)
    request=folder/'request.json'
    request.write_text(json.dumps({'files':[str(source)],'output':str(folder/'results'),
        'backend':'cpu','scan_mode':'indexed','fps':2,'gpu_load':'low',
        'delete_source':False}),'utf-8')
    result=subprocess.run([str(target/'runtime/cpu/python.exe'),str(target/'app_worker.py'),str(request)],
        cwd=target,env={**os.environ,'APEX_FFMPEG_DIR':str(ffmpeg.parent),'APEX_DATA_ROOT':str(folder/'app-data'),'PYTHONUTF8':'1'},
        capture_output=True,text=True,encoding='utf-8',timeout=120)
    events=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    if result.returncode or not events or events[-1].get('type')!='done' or events[-1].get('failures')!=0:
        raise RuntimeError('发布内核验证失败：'+result.stdout[-4000:]+result.stderr[-2000:])
    if not source.exists(): raise RuntimeError('验证原片意外丢失')
    print('Portable indexed worker end-to-end OK')

def build(args):
    version = json.loads((ROOT/'electron-ui/package.json').read_text('utf-8'))['version']
    out=OUT/args.stage if args.stage else OUT
    if not args.stage or Path(args.stage).name!=args.stage or args.stage in {'.','..','downloads'}:
        raise ValueError('暂存目录必须是publish内的单个构建目录')
    if not out.resolve().is_relative_to(OUT.resolve()): raise ValueError('暂存目录超出publish范围')
    bundle = out / f'Apex-Clipper-{version}-Windows-x64'
    target = bundle/'resources'
    if bundle.exists() and not args.refresh:
        raise RuntimeError('目标包目录已存在，保留已有包；请先改名备份再重新构建。')
    if args.refresh and not (target/'runtime/runtime-layout.json').is_file():
        raise RuntimeError('只允许刷新本次共享依赖候选，不可覆盖旧版双环境发布包')
    shared_source=verified_shared_source(bundle if args.refresh else args.shared_runtime_source) if args.refresh or args.shared_runtime_source else None
    assert_bundle_not_running(bundle)
    from target_name_reader import ensure_model as ensure_name_model
    ensure_name_model()
    ensure_name_model(latin=True)
    from japanese_name_reader import ensure_model as ensure_japanese_name_model
    ensure_japanese_name_model()
    target.mkdir(parents=True, exist_ok=args.refresh)
    args.managed_stage=out
    build_state(out,'building','portable')
    # 明确白名单：不带私有录像、断点、测试输出、配置和开发环境。
    extra = [name+'.py' for name in PRODUCT_MODULES]
    selected = set(extra + ['profile-ultrawide.json', 'combat-outcome-profile.json', 'weapon-catalog.json', 'weapon-catalog.v1.json', 'README.md', 'requirements.txt', 'requirements-gpu.txt'])
    for name in sorted(selected):
        p=ROOT/name
        if not p.is_file(): raise RuntimeError('缺少白名单产品文件：'+name)
        shutil.copy2(p,target/name)
    for name in ['templates', 'models', 'assets/ranks', 'assets/legends']:
        copy_tree(ROOT/name, target/name)
    (target/'experimental').mkdir(exist_ok=True)
    for name in ['__init__.py','indexed_reader.py','in_memory_hud.py']:
        shutil.copy2(ROOT/'experimental'/name,target/'experimental'/name)
    for name in ['docs/third-party.md', 'docs/user-guide.md', 'docs/assets', 'scripts/setup-ffmpeg.ps1', 'scripts/update-install.ps1', 'scripts/migrate-layout.ps1', 'scripts/cleanup-validation.ps1', 'scripts/validation-task-caches.py']:
        p=ROOT/name; dest=target/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if p.is_dir(): copy_tree(p,dest)
        elif p.exists(): shutil.copy2(p,dest)
    copy_tree(ROOT/'electron-ui'/args.electron/'Apex Highlight Clipper-win32-x64', target/'desktop')
    cache=OUT/'downloads';cache.mkdir(exist_ok=True)
    archive=cache/'python-3.11.9-embed-amd64.zip'
    if not archive.exists(): urllib.request.urlretrieve(PYTHON_URL,archive)
    # 官方发布页 MD5 用于供应包完整性；资产总清单另外使用 SHA256。
    if hashlib.md5(archive.read_bytes()).hexdigest() != '6d9aa08531d48fcc261ba667e2df17c4':
        raise RuntimeError('Python 官方嵌入包校验失败')
    runtime_reused=False;kernel_reused=False
    if args.refresh:
        # A UI-only refresh can reuse the already verified byte-identical kernel.
        kernel_reused=reuse_shared_runtime(bundle,target,shared_source)
        runtime_reused=True
    elif args.shared_runtime_source:
        kernel_reused=reuse_shared_runtime(args.shared_runtime_source,target,shared_source)
        runtime_reused=True
    elif not args.refresh:
        if args.runtime_source:
            baseline=Path(args.runtime_source).resolve()
            content=baseline/'resources' if (baseline/'resources/app_worker.py').is_file() else baseline
            inventory=json.loads((content/'FILES.sha256.json').read_text('utf-8'))
            for name,digest in inventory.items():
                if name.startswith(tuple((content.relative_to(baseline)/f'runtime/{mode}').as_posix()+'/' for mode in ['cpu','dml'])):
                    file=(baseline/name).resolve()
                    if not file.is_relative_to(baseline) or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:
                        raise RuntimeError('输入运行库校验失败：'+name)
            sources={mode:content/'runtime'/mode/'Lib/site-packages' for mode in ['cpu','dml']}
            for mode,source in sources.items():
                prefix=(content.relative_to(baseline)/f'runtime/{mode}/Lib/site-packages').as_posix()+'/'
                expected={name[len(prefix):]:digest for name,digest in inventory.items() if name.startswith(prefix)}
                if dependency_files(source)!=expected:
                    raise RuntimeError(f'{mode}输入依赖与发布清单不一致')
        else:
            # CPU开发环境可继承系统包；使用固定依赖安装完整输入，GPU只复制白名单。
            cpu_source=target/'validation/dependency-input/cpu'
            subprocess.run([str(Path(args.cpu)/'Scripts/python.exe'),'-m','pip','install',
                '--ignore-installed','--target',str(cpu_source),
                '-r',str(ROOT/'requirements.txt'),'-c',str(ROOT/'requirements-portable-lock.txt')],check=True)
            sources={'cpu':cpu_source,'dml':Path(args.gpu)/'Lib/site-packages'}
        layout=assemble_runtime(target,sources,archive,ROOT/'scripts/portable_sitecustomize.py')
        print('Shared dependency bytes saved:',layout['shared_bytes_saved'])
    for mode in ([] if runtime_reused and kernel_reused else ['cpu','dml']):
        runtime=target/'runtime'/mode
        subprocess.run([str(runtime/'python.exe'),'-c',
            "import os,numpy as np,sys,send2trash,pythoncom,av; os.environ['APEX_GPU_LOAD']='low'; "
            "from indexed_coarse import indexed_coarse_scan; "
            "from gpu_ocr_backend import create_ocr_engine; "
            "e=create_ocr_engine(backend=sys.argv[1],model_path='models/numeric_rec_en_v4.onnx'); "
            "print('Portable core inference OK',sys.argv[1],len(e.text_rec([np.full((32,96,3),255,np.uint8)])))",mode],cwd=target,check=True)
    if not kernel_reused:validate_worker(target)
    build_launcher(bundle,version)
    package_archive(bundle,out)

def package_archive(target,out):
    manifest=target/'resources/FILES.sha256.json'
    inventory={str(p.relative_to(target)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(release_files(target))}
    manifest.write_text(json.dumps(inventory,indent=2),'utf-8')
    archive=out/(target.name+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted([*release_files(target),manifest]):
            info=zipfile.ZipInfo((Path(target.name)/p.relative_to(target)).as_posix(),(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            z.writestr(info,p.read_bytes(),compresslevel=6)
    (out/'SHA256SUMS.txt').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n','utf-8')
    print(archive)

def build_state(folder,status,kind):
    (folder/'.apex-build.json').write_text(json.dumps({'schema':1,'owner':'apex-auto-clipper',
        'kind':kind,'status':status,'pid':os.getpid(),'updated':datetime.now(timezone.utc).isoformat()}),'utf-8')

def cleanup_builds(args):
    protected=[value for value in [args.runtime_source,args.shared_runtime_source] if value]
    command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
        str(ROOT/'scripts/cleanup-generated.ps1'),'-Apply']
    if protected: command+=['-Protect','|'.join(str(Path(p).resolve()) for p in protected)]
    result=subprocess.run(command,cwd=ROOT)
    if result.returncode: print('构建产物清理失败，请检查 cleanup-generated.ps1 的输出',file=sys.stderr)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cpu',default=str(ROOT/'.venv'))
    parser.add_argument('--gpu',default=str(ROOT/'.gpu-venv'))
    parser.add_argument('--electron',default='release-v5')
    parser.add_argument('--stage',default='v5-shared',help='publish内独立暂存目录，避免覆盖旧运行包')
    parser.add_argument('--runtime-source',help='复用已校验发布包中的依赖输入，逐文件验证FILES.sha256.json')
    parser.add_argument('--shared-runtime-source',help='仅复用已有独立推理报告且内容未变化的共享运行库/内核，避免重复测试')
    parser.add_argument('--refresh',action='store_true',help='更新本次未发布暂存包的产品文件，保留已验证runtime并重写校验和ZIP')
    args=parser.parse_args()
    try:
        build(args)
    except BaseException:
        if getattr(args,'managed_stage',None):
            build_state(args.managed_stage,'failed','portable');cleanup_builds(args)
        raise
    else:
        build_state(args.managed_stage,'succeeded','portable');cleanup_builds(args)
