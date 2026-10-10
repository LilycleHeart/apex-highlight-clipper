# 开发约定

主要运行环境为 Windows x64，Python3.11与Node.js24。先读README安装依赖，FFmpeg与模型单独安装。

源码分为项目根目录的Python内核、`electron-ui/`界面与`desktop/`历史WinForms入口。界面构建不把Python环境打进ASAR。发布包额外使用官方Python3.11.9嵌入式x64环境，CPU/DirectML依赖隔离，保留许可。

## V5界面与发布

surfaceGeometry.ts保留底边连接导航与凹角，并提供V5的320ms双沿及菜单曲线；surfaceMotion.ts统一零初速度重定向、可见性暂停和按压。FluidLayout.tsx实测卡片布局，插值真实宽度与位置，边界路径独立，媒体与文字不缩放。DOM数据顺序不改，右卡展开时只调整CSS视觉顺序。

tests/v5-ui-validation.cjs与tests/v5-theme-validation.cjs使用隔离目录中的合成媒体及元数据，验证自动历史库、真实比例/旋转、事件seek、统计展开、320ms双沿中断、四主题、减少动效和最小窗口。合成数据不进入生产库或发布包。真实性截图使用已导出录像，不以Figma图片替代。

在electron-ui设置APEX_PACKAGE_OUT=release-v5构建独立目录，避免覆盖正在运行的旧程序；回仓库运行scripts/build-portable.py。目标存在时拒绝覆盖。CPU/DML环境必须都是Python3.11 x64，发布前运行包内两种provider并检查无外部项目依赖。

发布ZIP不含FFmpeg命令行可执行程序；Start.cmd首次通过scripts/setup-ffmpeg.ps1获取固定官方供应版本并校验SHA256，或由用户提供工具。模型在发布包内，源码仓库记录下载校验逻辑。

发布前检查回归、真实播放、快速反向、减少动效、可见性暂停及760×620/1120×820尺寸；push后确认远端commit和Windows CI，最后发布运行包与SHA256SUMS并核对资产。

## 测试

Python单元测试使用临时目录和模拟调用，公开仓库不依赖开发者的私有录像路径。GUI纯逻辑测试在 `npm run build` 后执行 `npm test`。需要真实录像的性能、OCR与界面联调另行准备本机素材；这些运行记录不提交。

调整识别规则时检查伤害/击杀、切枪、零击杀助攻、本人倒地后队友续战、字幕被击倒负例和模糊提示。调整时间网格时核对绝对PTS，不能通过改文件编号伪装成更密集采样。

## 数据与发布

录像、分析缓存、模型、虚拟环境、构建包、本机配置和内部交接记录均在 `.gitignore` 中排除。不要提交鉴权信息或个人路径。小型HUD字形模板用于当前校准配置。

保留原任务版本与断点，升级不能静默改写历史成片。改名时保持旧的本机用户数据路径兼容。测试回收逻辑只使用专门生成的副本，不回收用户原始录像。

主题固定使用官方MCU0.4.0的SchemeVibrant、contrast0、spec2021、platformphone。任意seed经HCT/调色板生成语义色，同帧合并、缓存64种组合。库索引保存在用户数据目录library.json，仅发现已知输出根，不遍历用户磁盘，不改写任务与成片。
