# 开发约定

主要运行环境为 Windows x64，Python3.11与Node.js24。先读README安装依赖，FFmpeg与模型单独安装。

源码分为项目根目录的Python内核、`electron-ui/`界面与`desktop/`历史WinForms入口。界面构建不把Python环境打进ASAR。便携包使用官方Python3.11.9嵌入式x64环境；共享候选按完整目录内容哈希合并相同基础依赖，CPU/DirectML的ONNX Runtime与差异依赖继续隔离，保留许可。

## v1.0.1 界面与发布

窗口按钮由 DOM 绘制并进入同一个根视图快照；关闭 native titleBarOverlay 后，通过受限窗口 IPC 处理最小化、最大化/还原和 close。close 仍调用 win.close，沿用现有断点保存与设置写入保护；最大化状态由主进程事件同步。按钮位于独立 portal，设置面板打开时仍可操作。

surfaceGeometry.ts保留底边连接导航与凹角；surfaceMotion.ts从实际屏幕几何重定向，并处理可见性暂停。FluidLayout.tsx在DOM更新前采集真实位置：首次入场、视图切换或尺寸变化使用短淡入，尺寸不变的重排只过渡位置。动画期间保持最终布局宽高，不缩放卡片或文字，卡片边缘维持规整圆角；减少动效时直接到终态。常规与全屏视频均使用 contain，媒体容器跟随实际显示比例；只有列表封面使用 cover。常规与全屏控件以透明底覆盖在画面底部，不额外增加播放器高度；文字和图标添加阴影，本局战绩随控件隐藏。结果标记位置仍使用结果发生时间，回看位置通过已有开枪/正伤害时间线按连续过程计算；同目标延迟击杀关联此前击倒，缺失旧时间线时回退到结果前6秒，不额外做OCR。滚轮监听仅绑定展开的播放器：常规模式只拦截音量控件，视频画面保留页面滚动；全屏模式额外允许画面滚轮调音量，卸载时移除监听。VirtualClips只挂载视口附近的卡片，选中卡片保留DOM和唯一video。

tests/v5-ui-validation.cjs与tests/v5-theme-validation.cjs使用隔离目录中的合成媒体及元数据，验证自动历史库、真实比例/旋转、事件seek、统计展开、320ms双沿中断、四主题、减少动效和最小窗口。合成数据不进入生产库或发布包。真实性截图使用已导出录像，不以Figma图片替代。

在electron-ui设置APEX_PACKAGE_OUT=release-v5构建独立目录，避免覆盖正在运行的旧程序；回仓库运行scripts/build-portable.py。默认暂存目录是publish/v5-shared，目标存在时拒绝覆盖。CPU/DML输入必须都是Python3.11 x64。可通过--runtime-source指定既有双环境便携包，逐文件核对FILES.sha256.json后复用依赖，不需要重新下载。输入、产品模块和依赖采用白名单；相邻原生库组成完整共享组，任一成员不同就整组隔离。ZIP按固定时间戳和文件顺序生成，便于用相同输入重复构建。

`--shared-runtime-source`复用已有独立推理报告且逐文件内容不变的运行库，资源和加载器也必须一致。内核代码不变时复用对应检查；内核代码变化时补一个便携worker冒烟，不重复已通过的CPU/DirectML库推理测试。

EXE 安装包由 `scripts/build-installer.py --bundle publish/<构建目录>/Apex-Clipper-<版本>-Windows-x64 --iscc <ISCC.exe路径>` 生成，使用 Inno Setup 7。编译器采用可解压的工具包，使用前核对其 Authenticode 发布者为 Pyrsys B.V.。脚本校验便携包的既有报告和逐文件清单，只打包清单内文件，并加入固定 SHA256 的 FFmpeg 9.0.2 官方供应包及许可。FFmpeg ZIP 放在 `publish/downloads/ffmpeg-9.0.2-essentials_build.zip`。所有依赖、EXE、校验报告与临时文件均留在被 Git 忽略的 publish 内。

安装包默认安装到当前用户的 LocalAppData/Programs，不要求管理员权限；开始菜单入口直接运行应用，桌面快捷方式可选。`/PORTABLE=1 /DIR=<隔离目录> /VERYSILENT /NORESTART` 可用于一次最小解包与启动检查，不写卸载登记或快捷方式。安装包已附视频工具，可离线运行。只检查安装文件完整性及启动，复用内核已有验证；测试目录在检查后清除。

v1.0.1 保持安装器 AppId `{AF948615-855F-4699-8640-11A9E2F08854}` 与用户数据路径兼容。更新器仅接受本仓库同版本的 EXE、有效大小和 GitHub SHA256；流式校验后通过 Electron relaunch 交接到隐藏的 PowerShell helper，等待旧进程退出，再在当前目录安装并重新启动。便携版使用 /PORTABLE=1，安装版沿用卸载登记；不强杀窗口或后台任务。下载在用户数据 updates 目录，有跨进程锁与清理机制。旧版 0.2.0/本地 1.0.0 不具备安装逻辑，第一次通过原更新入口打开 Release 下载 EXE，之后使用应用内“下载并安装”。

两个runtime/*/python.exe入口保留。python311._pth只包含当前模式、包内源码与runtime/shared/Lib/site-packages，不读取PYTHONPATH或系统Python包。sitecustomize检查必需资源、保留AddDllDirectory句柄，并处理共享pywin32.pth；不会将另一模式的ONNX Runtime加入DLL搜索目录。Windows对多个新增DLL目录不保证顺序，因此构建时拒绝当前模式内不同内容的同名DLL。依据：[Python嵌入式路径](https://docs.python.org/3.11/using/windows.html#finding-modules)、[add_dll_directory](https://docs.python.org/3.11/library/os.html#os.add_dll_directory)、[Windows DLL搜索规则](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order)。

发布ZIP最外层仅有 Apex Highlight Clipper.exe 和 resources/。Electron 放在 resources/desktop，内核、runtime、模型、配置、文档与文件清单集中在 resources。启动器首次通过 resources/scripts/setup-ffmpeg.ps1 准备共用 FFmpeg，升级后继续复用；默认输出在系统视频目录，设置、历史与缓存仍使用既有用户数据目录。启动器由 Windows .NET Framework 自带的 C# 编译器生成，无控制台窗口。

安装器兼容旧的平铺目录：仅清理由旧文件清单列出且哈希仍匹配的程序文件，保留自选输出、断点和用户改动。旧更新脚本固定重启 app/Apex Highlight Clipper.exe，升级期间临时提供兼容启动入口，桌面进程确认内容与根启动器相同后清理。文件清单移至 resources/FILES.sha256.json，清单路径仍相对整个便携目录。

只运行本次改动直接影响的最小检查，复用同一代码状态下已通过的结果；不因发布重复运行全部界面组合。共享运行库改动需要验证包移出项目后两种provider的OCR、模式切换、重启、缺资源错误，以及一个媒体seek场景。发布与push需要当前任务明确授权，确认目标commit、CI和包清单后再操作。

## 测试

Python单元测试使用临时目录和模拟调用，公开仓库不依赖开发者的私有录像路径。GUI纯逻辑测试在 `npm run build` 后执行 `npm test`。需要真实录像的性能、OCR与界面联调另行准备本机素材；这些运行记录不提交。

调整识别规则时检查伤害/击杀、切枪、零击杀助攻、本人倒地后队友续战、字幕被击倒负例和模糊提示。调整时间网格时核对绝对PTS，不能通过改文件编号伪装成更密集采样。

## 数据与发布

新任务使用任务格式 v2。`export_layout=task`（默认）在所选输出位置创建本次整理文件夹，`flat` 直接混放在输出位置；两者均只输出 MP4，短任务与源文件标识防止同名覆盖。JSON / CSV、分析、导出清单与断点统一保存于 `<dataRoot>/tasks/<taskId>/`。桌面端的 dataRoot 默认使用 Electron `app.getPath('userData')`，检测到旧版 `%APPDATA%/Apex交战剪辑/preferences.json` 时沿用旧目录；可用 `APEX_DATA_ROOT` 指定隔离目录。直接运行 Python 的 Windows 默认值为 `%LOCALAPPDATA%/Apex Highlight Clipper`。旧版 v1 任务继续按原目录读取及续接，不静默搬动已有成片。

自动布局由 `hud_layout.py` 按左/右/中心、顶部/底部锚点生成，最多四次直接 seek 比较 HUD 标记，不按文件名或编码宽高猜拉伸。每个任务项冻结实际布局，缓存摘要和未完成任务保护使用该布局。无可靠标记时保留未确认状态；非标准 HUD 缩放仍可能需要后续校准。

交战阶段仅保留定位和战果需要的画面信号，不执行枪械名称、账号、队友、英雄或段位识别。`hud_enrichment.py` 是整理后和片段库补充共用的入口，每个片段先取三张不同画面，未确认时最多补三帧，至少两帧一致才确认名称/武器/英雄/段位；只原子追加 export.json 的 recognition.hud_info。名称行按多个尺寸匹配语音图标，裁掉图标再识别，并过滤战队标签。本人按原录像、队友按同局槽位汇集实际多帧姓名，只用重复且占优势的拼写校正相近误读；不跨局合并不同中文姓名。手动重新识别只使用本次所选片段的证据。IPC 只接受当前片段库注册的导出路径，并与识别和维护互斥。历史战績、视频文件与交战边界不因补充而改变。

旧清单缺少对局标识时，仅从来源身份和片段边界均匹配的 `analysis.json` 恢复对局结束事件分组；分析不匹配时不跨片段套用队友姓名。固定昵称区域允许较长的纯数字 ID，昵称边缘的占位方框可移除，内部缺字仍视为未知。英雄技能模板只在按钮中央搜索，避免把梯形边框识别成技能。

结果提示的动作、姓名与积分分别处理：根据 CTC 字符位置裁出姓名，拉丁姓名复用包内英文模型，彩色和灰度视图一致且至少两帧确认后展示。段位图形还核对饱和颜色，避免黄金和白金的相近轮廓互相干扰。游戏内技能符号与官网技能插画分别存放；未充能的条纹背景采用行背景对比处理，不能通过降低阈值填入英雄。补充字段版本为 `optional-hud-v6`，原始计数与交战边界保持冻结。

常玩信息按 match_key 去重；旧记录回退到源录像。英雄来自本人技能 HUD，使用 assets/legends 中官方 EA 图标与来源清单，遮挡或冷却数字可能导致无法确认。英文中心结果提示需高置信语法及相邻两帧相同目标；语法版本独立于原 OCR 日志，解析修复复用原始文字记录，统计检查同时包含解析版本，避免复用旧计数。

`validation`闲时维护：最多保留最近3次测试目录和3次识别缓存，旧测试目录超过7天也会回收；保留最近3份摘要、用户标注及最后任务入口。清理器读取已登记输出根和任务记录，保护未完成任务、缓存代次和近期缓存引用的采样目录；仅处理选定 dataRoot 下的 validation（未指定时使用开发目录），核对全部子项后回收目录，不跟随目录链接。启动后每日维护一次，批次结束后补充维护，开始识别时停止维护。手动预览：`powershell -File scripts/cleanup-validation.ps1 -DataRoot <软件数据目录>`，加`-Apply`才实际删除。统计保存在任务数据目录，成片保存在用户选定的视频输出目录。

封面缓存限制256MB，60天未使用则回收；Chromium磁盘缓存限制64MB。临时请求随进程结束清除，异常残留超过7天回收。打包器标记自身产物并调用`cleanup-generated.ps1`：便携包保留最新2个成功版本，Electron中间包只保留1个，失败包自动回收，运行目录与本次运行库输入跳过。未标记的目录不会自动按名字删除。

录像、分析缓存、模型、虚拟环境、构建包、本机配置和内部交接记录均在 `.gitignore` 中排除。不要提交鉴权信息或个人路径。小型HUD字形模板用于当前校准配置。

保留原任务版本与断点，升级不能静默改写历史成片。改名时保持旧的本机用户数据路径兼容。测试回收逻辑只使用专门生成的副本，不回收用户原始录像。

主题固定使用官方MCU0.4.0的SchemeVibrant、contrast0、spec2021、platformphone。任意seed经HCT/调色板生成语义色，同帧合并、缓存64种组合。库索引保存在用户数据目录library.json，发现已登记输出根与软件 tasks 目录，不遍历用户磁盘；读取历史库不改写任务与成片。

首页 HUD 与过滤开关紧挨导入按钮，开关启用后仅显示三角按钮，由用户手动展开；关闭时收起，再开启仍保持收起。展开只改变布局高度，不缩放内部文字。新任务默认 gap=10、pre=6、post=6；旧任务仍沿用冻结值，历史偏好中的旧默认组合仅迁移一次。无损校验开关与自动校验阶段已移除；原始流复制导出及独立回收站开关保留。

FFmpeg 启动引导固定使用 `%LOCALAPPDATA%/Apex Highlight Clipper/dependencies/ffmpeg/9.0.2`，以文件哈希验证共享副本。当前包、相邻旧包与已安装版可离线迁移；只有缺少已验证工具和 ZIP 时才下载。Python 工具查找与 Electron 缩略图查找保持相同优先级：显式环境路径、共享目录、包内工具、原有后备路径。安装器用 `-NoDownload` 播种共享副本；卸载单个应用版本不删除共享目录。
