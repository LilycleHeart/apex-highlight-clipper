# 第三方资源

应用代码不改变第三方作品的许可。发布包保留依赖各自的 LICENSE / NOTICE / dist-info 信息。

`assets/legends/hud/` 中的运行模板仅保留游戏内技能符号的去背景单色掩码，不包含录像帧、玩家名称或其他个人信息；图形版权属于 EA / Respawn，对应英雄页面及文件校验值见该目录的 `sources.json`。官网技能插画与游戏内 HUD 图案可能不同，识别时分别处理。

| 资源 | 来源及许可信息 |
| --- | --- |
| Python 3.11.9 嵌入式 x64 | [Python 官方下载](https://www.python.org/downloads/release/python-3119/)，包内 `runtime/*/LICENSE.txt`，PSF License |
| Electron、Chromium | [Electron](https://github.com/electron/electron)，Windows包 `app/LICENSE`、`LICENSES.chromium.html` |
| GenSen Rounded 源泉圆体 | [ButTaiwan/gensen-font](https://github.com/ButTaiwan/gensen-font)，SIL OFL 1.1，完整 TC Medium / Bold 字库；`electron-ui/public/fonts/GenSen-OFL.txt` |
| Cal Sans | [Google Fonts](https://github.com/google/fonts/tree/main/ofl/calsans)，SIL OFL 1.1，`electron-ui/public/fonts/CalSans-OFL.txt` |
| ONNX Runtime / DirectML | [Microsoft ONNX Runtime](https://github.com/microsoft/onnxruntime)，MIT；各运行环境包含版权声明，DirectML保留原分发条款 |
| RapidOCR / OCR模型 | [RapidOCR](https://github.com/RapidAI/RapidOCR)、[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)，Apache 2.0；武器模型为 PP-OCRv5 mobile，难读姓名复核使用 PP-OCRv5 server、英文 mobile 和日文 PP-OCRv4；固定 SHA256 位于 `weapon_reader.py`、`target_name_reader.py`、`japanese_name_reader.py` |
| PyAV / 内存索引解码 | [PyAV](https://github.com/PyAV-Org/PyAV)，BSD 3-Clause；轮子附带的 FFmpeg 库保留原许可，依赖许可随 av dist-info 保存 |
| FFmpeg命令行工具 | 便携 ZIP 首次启动从 [Gyan 官方 9.0.2](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2) 下载并核对固定 SHA256；EXE 安装包已包含相同供应包的 ffmpeg/ffprobe。该构建为 GPLv3，工具目录保存供应方 LICENSE / README，源码链接见供应方发布页 |
| Apex武器、战绩、段位图形 | [Apex Wiki](https://apexlegends.fandom.com/)。社区镜像的游戏素材，权利属于 EA / Respawn 及对应权利人，并非 EA 官方 SVG 包；逐项来源与字节哈希在 `electron-ui/public/apex-icons/sources.json` 和 `assets/ranks/sources.json`。击倒使用护盾图形，击杀映射保留原有头骨轮廓 |
| 英雄筛选头像、定位与弹药图标 | Apex Wiki 镜像的 EA / Respawn 游戏原生 PNG / SVG，原字节保留；39 项来源与 SHA256 在 `electron-ui/public/apex-icons/picker-sources.json`。定位依据 [EA 当前英雄名单](https://www.ea.com/games/apex-legends/apex-legends/game-objects/characters-hub)，筛选面板按游戏选人界面的定位分栏与英雄发布顺序排列 |
| 英雄技能识别模板 | [EA 官方英雄页面](https://www.ea.com/games/apex-legends/apex-legends/characters-hub) 的战术与终极技能图形；权利属于 EA / Respawn。28 位英雄的原图地址与 SHA256 记录在 `assets/legends/sources.json`，用于本人 HUD 图形比对，不代表官方合作 |
| 本人英雄头像比对资源 | EA / Respawn 游戏内固定头像的局部图像，已去除玩家名称和场景。标签由独立技能图形证据或固定英雄字幕核对；逐项来源说明与 SHA256 在 `assets/legends/portraits/sources.json`。这些资源不是玩家昵称答案表 |
| Blanca两套角色、开关音效 | 用户提供的平涂/线稿 PNG 与“消失”“复原”WAV，保留原素材；轮廓SVG由alpha边缘派生，不改变原图与音频。项目不对这些第三方素材另行授予授权 |

OpenCV、NumPy、Pillow、Send2Trash及其余 Python 依赖的许可证随各包元数据保存。图标、模型、字体、角色和音频不因项目公开而自动成为公有领域。

本工具为非官方社区项目，与 EA / Respawn 无隶属关系。

`electron-ui/public/apex-icons/ranks/unranked.svg` 是依据用户已确认的游戏内匹配徽章绘制的 UI 矢量版本，用于避免录像裁片缩放时的模糊与杂色边缘；不代表 EA 官方提供的 SVG。原始 `assets/ranks/unranked.png` 识别模板保留。
