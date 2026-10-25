<p align="center">
  <a href="https://count.getloli.com/">
    <img src="https://count.getloli.com/get/@LilycleHeart-AHC?theme=moebooru" alt="AHC 访问计数 · Moe Counter" />
  </a>
</p>

# AHC · Apex Highlight Clipper

> **「打了一晚上 Apex，几十个 G 的录像懒得翻？把视频丢进去，你去喝杯水，高光片段就已经全切好了。」**
> 
> 本地自动识别交战、0 重编码秒切、原画质与多音轨完整保留。专为 Apex 玩家与切片创作者打造的开箱即用工具。

[ 立即下载 Windows 版 (免配置安装) ](https://github.com/LilycleHeart/apex-highlight-clipper/releases/latest) · [ 详细使用手册 ](docs/user-guide.md) · [ 开发者说明 ](docs/development.md) · [ 第三方资源 ](docs/third-party.md)

![Windows 10 / 11](https://img.shields.io/badge/Windows-10%20%2F%2011-1274ff) ![Release](https://img.shields.io/github/v/release/LilycleHeart/apex-highlight-clipper) ![Validate](https://github.com/LilycleHeart/apex-highlight-clipper/actions/workflows/validate.yml/badge.svg)

---

![整理片段 · 真实运行截图](docs/assets/clips-detail.png)

<table>
<tr>
  <td><img src="docs/assets/start.png" alt="开始：导入录像与队列"></td>
  <td><img src="docs/assets/statistics.png" alt="全局片段库统计"></td>
</tr>
<tr>
  <td><img src="docs/assets/clips-grid.png" alt="紧凑网格"></td>
  <td><img src="docs/assets/clips-list.png" alt="列表视图"></td>
</tr>
</table>

*(界面均为真实运行截图，素材管理像相册一样好找)*

---

## 为什么需要 AHC？

- **痛点 1：几十个 G 的录像堆在硬盘，翻时间轴翻到头皮发麻**  
  打完几小时游戏想剪集锦，却要在漫长的搜物资、跑毒录像里肉眼找高光？  
  → **AHC 会自己“看”录像**：基于本地视觉与 HUD 识别，自动定位每一场交火，把你打出击倒、助攻、灭队的高光时刻精准挑出来。
- **痛点 2：剪映/PR 导出一堆切片还要压制半天，画质还变糊**  
  重新编码又慢又吃 CPU，好不容易录的高码率 2K/4K 画面被二压成马赛克？  
  → **极速无损直出**：底层采用 FFmpeg 流复制技术，**0 重新编码**，几秒钟切完一段。画面 100% 原始画质，而且**所有独立音轨（游戏声、麦克风、开黑语音）原封不动保留**，剪辑师狂喜。
- **痛点 3：配置环境劝退，担心隐私泄露**  
  想要用开源工具，却要配 Python、装 CUDA、输各种黑框框命令？  
  → **下载双击即用，纯本地运行**：内置所需环境与轻量识别模型，不联网上传视频，数据 100% 留在你的电脑里，断网也能正常用。

---

## 三步快速上手

1. **下载启动**：下载安装包（或解压便携 ZIP），双击运行 `Apex Highlight Clipper.exe`（普通权限即可，无需管理员）。
2. **拖入录像**：把你的 OBS 录像文件（或整个文件夹）直接拖进窗口，选好导出目录。
3. **一键开剪**：点击「开始整理」。软件会自动扫描并切片，想玩游戏随时暂停，支持断点续剪。

> 说明：自带开箱即用的轻量运行环境与模型；本地已有 FFmpeg 的用户也可以直接复用。

---

## 核心亮点

- **懂 Apex 的交战逻辑**：不仅能识别快速秒杀，更懂拉扯慢、TTK 长的多队混战；哪怕你中途倒地、队友反打收割的完整对局也能连贯切出。
- **只留你的高光战果**：默认只保留包含你有效击倒、消灭或助攻的片段，过滤掉纯粹的人体描边或无效对枪；拿不准的对局会保留给你人工复核。
- **通吃主流分辨率与 HUD**：自动适配普通 16:9、16:10、带鱼屏，职业哥偏爱的 **4:3 拉伸画面**，以及游戏的「精简」界面配置。遇到异常画面会明确提示，绝不假装成功却漏切片段。
- **随心挑选的高光素材库**：剪完的片段自动汇入片段库。支持详细卡片、紧凑网格、列表 3 种视图，内置播放器可直接全屏预览；支持按武器类别、使用英雄、对局模式/段位、击杀/伤害快速筛选。
- **群友问你怎么灭队的？一键发 QQ**：在片段库选中高光视频，右键即可直接呼起 QQ 分享窗口，秒发给群友。
- **安全防误删机制**：删除片段需双击二次确认，且仅移入系统回收站，绝不误删你的原录像文件。

---

## 常用选项调节

在首页「整理选项」中，你可以按自己的打法风格微调：

| 调节项 | 推荐场景 | 说明 |
| :--- | :--- | :--- |
| **合并间隔** (默认 10秒) | 喜欢多队混战剪在一起 → 调大<br>喜欢单次击杀利落切片 → 调小 | 相隔小于该时间的战斗会合并为同一段 |
| **前后保留** (默认 各6秒) | 喜欢看完整架枪身法 → 调大<br>想要短平快短视频节奏 → 调小 | 交火开始前和结束后的缓冲时长 |
| **战绩过滤** (默认 关闭) | 只要单局 3 杀以上 / 500 伤以上 | 开启后可设门槛，自动剔除小摩擦 |
| **原录像回收** (默认 关闭) | 硬盘空间告急时使用 | 仅在切片完整导出后，才将原片移入系统回收站 |

---

## 常见问题 (FAQ)

<details>
<summary><b>Q: 为什么有些片段的战绩显示「≥2」或者「—」？</b></summary>
视觉识别严格遵循客观证据原则：当画面被技能特效、烟雾遮挡或结算文字未完整截到时，AHC 宁愿保守显示已确认的下限（如至少 2 杀），也绝不胡乱捏造虚假战绩。
</details>

<details>
<summary><b>Q: 对录像格式有什么要求？</b></summary>
推荐使用 OBS 录制的标准 H.264/H.265(HEVC)/AV1 MP4 或 MOV 格式。无损切片依赖视频关键帧索引，如果是无法拖动时间轴的破损流，建议先用 remux 重新封装后再导入。
</details>

<details>
<summary><b>Q: 会偷跑我的流量或泄露我的对局吗？</b></summary>
完全不会。核心识别与切片 100% 在本地显卡/CPU 完成。仅在检查更新或缺失工具时产生必要连接，无任何用户录像上传逻辑。
</details>

---

## 开发者与源码构建

如果你想参与贡献或从源码运行：

```powershell
# 1. 环境准备 (需 Python 3.11 + Node.js 24)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
python setup_weapon_model.py           # 下载并校验 OCR 模型
.\scripts\setup-ffmpeg.ps1             # 准备固定版本工具

# 2. 启动前端界面
cd electron-ui
npm ci
npm run build
npm start
```

- 开启 GPU 加速调试请运行 `.\setup_gpu.ps1` 搭建独立的 `.gpu-venv`。
- NVIDIA 显卡可运行 `.\setup_cuda.ps1` 安装独立的 `.cuda-venv`，重开界面后在「性能设置 → 识别设备」选择「GPU · CUDA」。安装会下载 CUDA/cuDNN 运行库；「自动」仍沿用 DirectML/CPU，已有便携包不包含这套可选环境。
- 「GPU · DirectML」只负责识别推理，画面解码使用显卡的 DirectX 硬解（AMD/Intel 同样适用）；本机不支持时自动退回 CPU 解码，任务不会因此中断。
- 更多内核架构、测试用例与打包说明，请查阅 [开发说明文档](docs/development.md)。

---

## 许可与免责声明

本项目为开源非官方社区工具，与 Electronic Arts 或 Respawn Entertainment 无任何隶属关系。相关游戏图形与角色素材版权归原权利人所有，详见 [第三方资源引用说明](docs/third-party.md)。
