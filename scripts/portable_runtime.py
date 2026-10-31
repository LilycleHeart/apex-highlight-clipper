"""按完整包目录的内容哈希共享依赖，保留每种模式的冲突包。"""
from pathlib import Path
import hashlib
import json
import shutil

# 仅接受已审计的依赖；元数据与许可证随完整目录保留。
MODULES = set('adodbapi av av.libs colorama cv2 flatbuffers google isapi mpmath '
              'numpy numpy.libs onnxruntime packaging PIL pyclipper pythonwin '
              'pywin32_system32 rapidocr_onnxruntime send2trash shapely shapely.libs '
              'sympy tqdm win32 win32com win32comext yaml _yaml bin'.split())
MODULE_FILES = {'pythoncom.py', 'PyWin32.chm', 'pywin32.pth', 'pywin32.version.txt',
                'six.py', 'isympy.py'}
DISTRIBUTIONS = set('av colorama flatbuffers mpmath numpy onnxruntime '
                    'onnxruntime_directml opencv_python packaging pillow protobuf '
                    'pyclipper pywin32 pyyaml rapidocr_onnxruntime send2trash shapely '
                    'six sympy tqdm'.split())


def dependency_files(source):
    source = Path(source)
    files = {}
    for top in sorted(source.iterdir()):
        if top.is_symlink():
            raise RuntimeError(f'依赖含符号链接：{top}')
        if top.name == '__pycache__' or top.name in {'pip', 'setuptools', 'pkg_resources', '_distutils_hack'}:
            continue
        if top.name.startswith(('pip-', 'setuptools-')) or top.name == 'distutils-precedence.pth':
            continue
        metadata = top.name.endswith('.dist-info') and top.name[:-10].rsplit('-', 1)[0].lower() in DISTRIBUTIONS
        if top.name not in MODULES | MODULE_FILES and not metadata:
            raise RuntimeError(f'依赖白名单外的内容：{top.name}；请审计后明确加入')
        for file in ([top] if top.is_file() else sorted(top.rglob('*'))):
            if file.is_symlink():
                raise RuntimeError(f'依赖含符号链接：{file}')
            relative = file.relative_to(source)
            if {'__pycache__', 'tests'} & set(relative.parts) or file.suffix == '.pyc':
                continue
            if file.is_file():
                files[relative.as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return files


def assemble_runtime(target, sources, python_archive, bootstrap):
    """不修改输入环境；任何差异都让整个顶层包保持私有。"""
    import zipfile
    target = Path(target)
    manifests = {mode: dependency_files(source) for mode, source in sources.items()}
    units = {}
    for mode, manifest in manifests.items():
        units[mode] = {}
        for name, digest in manifest.items():
            units[mode].setdefault(name.split('/')[0], {})[name] = digest
    shared = sorted(name for name, files in units['cpu'].items()
                    if name != 'onnxruntime' and files == units['dml'].get(name))
    # 轮子的加载器按相邻目录查找DLL，整组共享或整组保持私有。
    for family in [ {'av', 'av.libs'}, {'numpy', 'numpy.libs'},
                    {'shapely', 'shapely.libs'}, {'yaml', '_yaml'},
                    {'pythoncom.py', 'pywin32.pth', 'pywin32_system32', 'win32',
                     'pythonwin', 'win32com', 'win32comext', 'adodbapi', 'isapi'} ]:
        if not family.issubset(shared):
            shared = [name for name in shared if name not in family]
    common = target / 'runtime/shared/Lib/site-packages'
    common.mkdir(parents=True)
    saved = 0
    for unit in shared:
        for name in units['cpu'][unit]:
            source = Path(sources['cpu']) / name
            destination = common / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            saved += source.stat().st_size
    required, dll_dirs = {}, {}
    private_units = {}
    for mode, manifest in manifests.items():
        runtime = target / 'runtime' / mode
        runtime.mkdir(parents=True)
        with zipfile.ZipFile(python_archive) as archive:
            archive.extractall(runtime)
        private = runtime / 'Lib/site-packages'
        private.mkdir(parents=True)
        private_units[mode] = sorted(set(units[mode]) - set(shared))
        for name in manifest:
            if name.split('/')[0] in shared:
                continue
            destination = private / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(sources[mode]) / name, destination)
        # 固定sys.path，不读取开发环境、PYTHONPATH或另一模式的site-packages。
        (runtime / 'python311._pth').write_text('\n'.join([
            'python311.zip', '.', '..\\..\\', 'Lib/site-packages',
            '..\\shared\\Lib\\site-packages', 'import site', '']), 'utf-8')
        shutil.copy2(bootstrap, runtime / 'sitecustomize.py')
        active = [p for root in [runtime, common] for p in root.rglob('*')
                  if p.is_file() and p.suffix.lower() in {'.dll', '.pyd'}]
        # AddDllDirectory间的顺序未定义；禁止激活不同内容的同名原生库。
        names = {}
        for file in active:
            if file.suffix.lower() != '.dll':
                continue  # Python按完整模块路径加载pyd；audio/video可合法同名。
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            key = file.name.lower()
            if key in names and names[key] != digest:
                raise RuntimeError(f'{mode}模式有同名不同内容的原生库：{file.name}')
            names[key] = digest
        dll_dirs[mode] = sorted({p.parent.relative_to(target).as_posix() for p in active})
        required[mode] = sorted({p.relative_to(target).as_posix() for p in active} | {
            ('runtime/shared' if p.split('/')[0] in shared else f'runtime/{mode}') + '/Lib/site-packages/' + p for p in [
                'numpy/__init__.py', 'cv2/__init__.py', 'av/__init__.py',
                'rapidocr_onnxruntime/__init__.py', 'pywin32.pth']
        } | {'models/numeric_rec_en_v4.onnx', 'models/weapon_rec_v5.onnx', 'assets/counters/hud_digits_v1.onnx', 'models/ppocrv6_rec_small.onnx'} |
            {p.relative_to(target).as_posix() for root in [common, private] for p in root.rglob('*.onnx')})
    layout = {'version': 1, 'shared_units': shared, 'private_units': private_units,
              'shared_bytes_saved': saved, 'required': required, 'dll_dirs': dll_dirs}
    (target / 'runtime/runtime-layout.json').write_text(
        json.dumps(layout, ensure_ascii=False, indent=2, sort_keys=True), 'utf-8')
    return layout
