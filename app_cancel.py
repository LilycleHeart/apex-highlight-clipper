"""工作进程在已提交边界响应停止；硬退出由断点日志恢复。"""
import os
from pathlib import Path

class TaskStopped(BaseException): pass

def check_cancel():
    marker=os.environ.get('APEX_TASK_STOP_FILE')
    if marker and Path(marker).is_file(): raise TaskStopped()
