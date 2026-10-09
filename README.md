# Apex Highlight Clipper

本地运行的 Apex Legends 自动交战剪辑工具，采用 Electron + React + TypeScript 界面与 Python 分析内核。

批量导入录像，定位交战，确认本人击倒、助攻或消灭提示，按交战分别无损导出。原始视频与音轨使用 FFmpeg stream copy，不重新编码。

## 功能

- 拖入录像、多选文件、导入文件夹与批量队列。
- 智能局部识别，保留长 TTK 拉扯、倒地后的有效队友续战。
- 本人击倒／助攻／消灭至少出现一种才保留；只有伤害的候选跳过，无法可靠判断的候选标为待复核。
- 独立 MP4 输出，中文日期时间、击杀、枪械与伤害命名。
- GPU 负载档位、细查频率、交战合并间隔、前后保留时长可调。
- 分阶段断点、继续原批次、已完成输出不重复导出。
- Material 动态配色，跟随系统主题与强调色；颜文字助手、阶段播报与真实采样缩略图。
- 可选逐包无损校验。完整模式支持校验后移入回收站；智能模式保留原片。

## 当前适配范围

这是 Windows x64 的本地应用。当前主要校准于 **2560×1080、繁体中文 Apex HUD**。其他宽高比、语言、HUD 缩放或布局需要额外校准，不能保证直接识别。

GPU OCR 使用 DirectML；硬件视频解码路径当前按 NVIDIA CUDA 验证。其他显卡建议先使用 CPU 模式。低占用档控制工作节奏，不是固定的 GPU 利用率上限。

无损切割依赖关键帧，实际边界可能略向外扩展。记录中的击杀、伤害来自本人 HUD 识别，模糊或矛盾的计数仍可能需要人工复核。

## 本机安装

需要 Python 3.11、Node.js 22.12 或更新版本，以及包含 `ffmpeg` 和 `ffprobe` 的 FFmpeg 安装。项目在 Python 3.11 / Node.js 24 上验证。

在仓库根目录创建 CPU 环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_weapon_model.py
```

GPU 环境与 CPU 环境分开，避免 ONNX Runtime 包互相覆盖：

```powershell
.\setup_gpu.ps1 -Python python
.\.gpu-venv\Scripts\python.exe setup_weapon_model.py
```

FFmpeg 可放在 `tools/ffmpeg.exe` 和 `tools/ffprobe.exe`，或放入 PATH。也可设置 `APEX_FFMPEG_DIR`，或创建本机专用、不会提交的 `ffmpeg.local.json`：

```json
{"directory": "D:/Tools/ffmpeg/bin"}
```

模型由安装脚本下载并校验。仓库不包含录像、模型权重、虚拟环境、node_modules 或成品运行包。

构建界面：

```powershell
cd electron-ui
npm ci
npm run build
npm start
```

构建 Windows 应用目录：

```powershell
npm run package
```

生成 `electron-ui/release/Apex Highlight Clipper-win32-x64/`。双击根目录的 `启动Electron界面.cmd`，优先打开该运行包；`预览Electron界面.cmd` 可查看明确标记的模拟阶段。

**目前运行包仍需本项目的 Python、模型与 FFmpeg，请保留整个项目目录。它不是可任意复制到其他电脑的独立安装包。**

## 使用

1. 导入录像并选择输出文件夹。
2. 默认智能模式、2帧/秒和低GPU负载即可开始。
3. 每场有效交战独立导出。结果中区分保留、跳过和待复核。
4. 中断时选择停止并保存进度；继续任务时沿用原队列与剪辑参数。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| 细查频率 | 2帧/秒 | 算法采样精度，新任务范围1–5；不改变成片帧率 |
| 合并间隔 | 35秒 | 相邻交战信号可合并的间隔 |
| 前置 / 收尾 | 10 / 15秒 | 交战前后额外保留的内容 |
| GPU负载 | 低占用 | 低占用、均衡、全速；不保证每份录像的总耗时按档位严格递减 |

更旧的任务沿用原业务规则，旧成片不会自动重筛或删除。已处理和已有缓存的录像保留原断点；符合相同业务规则的未开始录像可以使用新版规划。

高级命令行工具 `apex_clipper.py` 用于底层诊断；完整桌面流程由 `app_worker.py` 执行，包括最新战果筛选与任务续接。

## 验证与开发

```powershell
.\.venv\Scripts\python.exe -m unittest discover -p "test_*.py"
cd electron-ui
npm run build
npm test
```

实拍验证素材与内部运行记录不进入公开仓库。不能把模拟测试或缓存续接耗时当成冷启动性能。

- [模块与事件协议](docs/architecture.md)
- [性能记录与边界](docs/performance.md)
- [开发约定](docs/development.md)

![颜文字助手的关键姿态](docs/assets/kaomoji-mascot-reference.svg)
