# 模块与事件协议

Electron 主进程负责文件选择、系统配色、Python 子进程与受限文件读取；React 负责交互和显示。预加载脚本只公开类型明确的 IPC，渲染进程关闭 Node 集成。

## 分析流程

`app_worker.py` 读取请求 JSON，创建持久 `task.json`，经 stdout JSONL 向界面报告状态。日志和状态流按完整行处理，支持跨块 UTF-8。

| 模块 | 职责 |
| --- | --- |
| app_task / app_cancel | 批次版本、锁、冻结参数和协作停止 |
| smart_scan / planning_evidence | 关键帧粗查、计分变化、局部细查规划 |
| early_round_end | 提前确认结束或换局证据，保护未知队友续战 |
| adaptive_evidence | 证据范围与输出保留范围分离，解码调度 |
| resume_media / resume_io | 分块采样、逐片导出、提交日志和恢复 |
| evidence_completion | 计分审计失败时只补缺失画面和识别行 |
| combat_outcome_reader | 本人中下方击倒、助攻、消灭提示及字幕排除 |
| weapon_reader / outcome_reader | 枪械名称、全灭与队友交战尾部 |
| verify_export | 视频及全部音轨的压缩包、时间戳检查 |

最终输出是 stream copy。检测采样帧率与成片帧率分离。

## Worker 请求

新任务字段为 `files`、`output`、`backend`（cpu/dml）、`scan_mode`（smart/complete）、`gpu_load`（low/balanced/fast）、`fps`、`gap`、`pre`、`post`、`verify`、`delete_source`、`pipeline`。

停止标记必须位于项目 `validation/app-requests/`，使用唯一 `.stop` 文件名，并在启动前确定。创建该文件请求协作停止；收到 `stopped` 才表示进度已保存。正常停止退出码是75。

续接用 `resume_task` 指向原 `task.json`，使用新的停止标记。只有设备、负载档位等运行参数可覆盖，剪辑参数与业务规则保持冻结。

## JSONL 事件

- `run`：任务目录、记录路径、筛选规则与旧参数说明。
- `file`：当前源文件、批次位置。
- `stage` / `progress` / `log`：稳定阶段ID、说明与工作进度。
- `preview`：已提交画面路径和实际检查时间点，界面低频刷新。
- `result`：独立输出、校验状态、原片处置和保留/排除/待复核统计。
- `done`：整批汇总；有失败时不能显示全部成功。
- `stopped` / `error` / `fatal`：协作停止、单文件错误、批次致命错误。

`result_filter_summary` 包含 `kept`、`rejected`、`review`、`rule`。零击杀不等于无战果，助攻片段可以被保留。输出资格由内核决定，前端不按文件名或伤害猜测。

## 缓存与兼容

缓存以源指纹、HUD配置、采样率及算法版本区分；提交图像带 SHA256。已完成片段先验证文件身份再跳过，原片已合法回收时仍可恢复已完成任务。

战果模板与数字OCR配置分开；本机校准样例可放在忽略的 `combat-outcome-fixtures.local.json`。发布的配置只包含运行所需参数和小型字形模板。
