"""嵌入式Python启动检查；仅加载当前模式与包内共享依赖。"""
import json
import os
from pathlib import Path
import site
import sys

_DLL_HANDLES = []


def _configure():
    runtime = Path(sys.executable).resolve().parent
    mode = runtime.name
    bundle = runtime.parent.parent
    layout_file = runtime.parent / 'runtime-layout.json'
    if mode not in {'cpu', 'dml'} or not layout_file.is_file():
        raise RuntimeError('缺少 runtime/runtime-layout.json，请完整解压程序包')
    layout = json.loads(layout_file.read_text('utf-8'))
    if layout.get('version') != 1:
        raise RuntimeError('不支持的运行库布局，请完整解压同一版本程序包')
    for relative in layout['required'][mode]:
        file = (bundle / relative).resolve()
        if not file.is_relative_to(bundle) or not file.is_file():
            raise RuntimeError(f'缺少运行资源：{relative}。请完整解压程序包')
    for relative in layout['dll_dirs'][mode]:
        folder = (bundle / relative).resolve()
        if not folder.is_relative_to(bundle):
            raise RuntimeError('运行库DLL路径超出程序包')
        _DLL_HANDLES.append(os.add_dll_directory(str(folder)))
    site.ENABLE_USER_SITE = False
    site.addsitedir(str(runtime.parent / 'shared/Lib/site-packages'))
    if any(not Path(p).resolve().is_relative_to(bundle) for p in sys.path):
        raise RuntimeError('运行库搜索路径超出程序包，已停止加载')


try:
    _configure()
except Exception as error:
    # site默认忽略普通异常；SystemExit确保不以缺资源的环境继续执行任务。
    raise SystemExit(f'AHC运行库加载失败：{error}') from error
