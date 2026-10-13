# 项目文档

- [当前 MRI2MR 使用说明](../README.md)：功能、配置与启动方式。
- [WebUI 用户指南](../README_USER_GUIDE.md)：面向实际操作的步骤。
- [VesselPilot 项目方案](plans/README_VESSEL_PILOT_HACKATHON.md)：研发目标和验收记录。
- [历史 WebUI 文档](history/)：V1 使用说明、任务清单及 V2–V4 优化方案。保留原文供追溯，不作为当前安装说明。

## 环境与仓库边界

`template/` 的三个资源文件由 `config/app_settings.json` 直接引用；`spm/` 是当前 MATLAB 分割所用的 SPM12 源码。DICOM 转换还依赖仓库内的 `dcm2niix_win/` 和 `dcmtk-3.7.0-win64-dynamic/`。这些目录当前没有可复现的下载脚本和固定版本校验，打包脚本也直接复制它们，因此保留在 Git 中。

`venv/`、`workspace/`、`logs/`、`node_modules/` 和根目录的 `dist/` 是本机环境或生成物，已被忽略。根目录的 `README_CORE.md`、`PACKING_REPORT_CORE.txt` 由 `tools/pack_core.ps1` 在输出目录生成，不再作为源文件跟踪。

根目录原有的 `package.json` 和 `pnpm-lock.yaml` 没有声明依赖或构建步骤。Agnes Harness 的 Node 依赖及构建命令位于 `agnes-harness/package.json` 和 `agnes-harness/pnpm-lock.yaml`；其源码目前属于本仓库的跟踪内容，本地构建产物由它自己的 `.gitignore` 排除。

Agnes Harness 可在其目录中运行 `corepack pnpm install --frozen-lockfile`，再运行 `corepack pnpm --filter @agnes/cli build:local`；根目录的 `start_agnes.ps1` 启动这个构建结果。这只解决 Agnes 的 Node 部分。

`requirements-webui.txt` 只列出 WebUI 的 Python 依赖。`start_core.bat` 仍要求 `runtime/python/BrainAAL/python.exe`，而该运行环境当前不在 Git 跟踪列表中。完整图像处理环境还需要 MATLAB、Docker 和其他 Python 包，因此现阶段不能保证仅凭克隆仓库后一条命令就能重建全部运行环境。迁移到 uv 或 Conda 锁文件，需要先整理并验证完整依赖，再确定 SPM、二进制工具和模板的固定来源及校验值。

## 启动与打包脚本

| 脚本 | 用途 |
| --- | --- |
| `start_core.bat` | 在 Windows 上用便携 Python 启动原有 WebUI，并检查 MATLAB、Docker。 |
| `agnes.config.ps1`、`start_agnes.ps1` | 设置当前 checkout 的 Agnes 数据目录与 profile，启动已构建的 CLI。 |
| `show_agent_logs.ps1` | 按级别、会话、工具等条件查看 Agnes JSONL 日志。 |
| `tools/pack_core.ps1` | 复制源码与运行资源、装入 Python 环境，生成 Core 启动文件和报告。 |
| `tools/pack_portable.ps1` | 生成包含更多独立运行组件的便携包。 |

这些 PowerShell 脚本承担 Windows 启动、文件复制和日志查看任务；uv 只能解决 Python 包与环境的管理，不能直接替代这些步骤。以后若需要跨平台打包，可以逐步换成统一的任务运行器，但需要先确保 MATLAB、SPM、Docker 和二进制工具的安装及版本可复现。
