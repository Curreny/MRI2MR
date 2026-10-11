# MRI2MR Core — 用户使用指南

> 本指南帮助你了解 MRI2MR Core 是什么、如何启动、如何使用，并覆盖所有内置处理模式。
> 本文件为自动生成，不包含对任何已有文件的新修改（仅为新增 README）。

---

## 一、项目概述

**MRI2MR Core** 是一个面向脑 MRI 影像分析的桌面 Web 工具，核心功能：

1. **DICOM → NIfTI 转换**：将原始 DICOM 序列（T1、MRA、MRV、DTI）自动识别并转为 NIfTI 格式。
2. **组织分割**：支持 SPM（MATLAB）和 SynthSeg（Docker）两种分割后端，生成灰质/白质/DK 脑区标签图。
3. **3D 模型生成**：基于分割结果，导出 GLB 格式的三维模型（脑区、脑叶、脑半球、脑室、动脉、静脉、纤维束等）。
4. **纤维追踪**：基于 DTI / DKI 数据，利用 DIPY 进行确定性纤维追踪，导出纤维束模型。

整个流程由 Web UI 驱动，后台通过 FastAPI + 子进程调用 Python 主脚本 `scripts/Main_cmd.py` 完成实际处理。

---

## 二、目录结构速览

```
MRI2MR-core/
├── app/
│   ├── backend/          # FastAPI 后端（API 路由、任务管理、病人管理）
│   │   ├── main.py       # 主入口，定义所有 REST API
│   │   ├── jobs.py       # 任务（Job）生命周期管理
│   │   ├── patients.py   # 病人工作区管理
│   │   ├── command_builder.py  # 命令行构建（将 JSON 配置转为 CLI 参数）
│   │   ├── config.py     # 加载 app_settings.json
│   │   ├── modes.py      # 加载 modes.json（各处理模式定义）
│   │   ├── inspectors.py # DICOM 序列检测、路径检查
│   │   └── preview.py    # NIfTI 切片预览渲染
│   └── static/           # Web UI（HTML/CSS/JS + Three.js）
│       ├── index.html    # 主界面
│       ├── app.js        # 前端逻辑
│       └── vendor/       # 依赖库（three.js 等）
├── config/
│   ├── app_settings.json # 全局路径和后端配置
│   └── modes.json       # 所有处理模式的字段定义（CLI 参数映射）
├── scripts/
│   ├── Main_cmd.py       # 核心处理脚本（DICOM 转换、分割、建模、纤维追踪）
│   ├── Utils/            # 工具函数（仿射矩阵、路径处理等）
│   └── run_spm_segmentation.m  # SPM 分割 MATLAB 脚本
├── spm/                  # SPM 源码目录（需与 MATLAB 配合使用）
├── template/             # 模板文件（DK_Regions.txt、DK_Lobes.txt、ROI_ED_Filter.nii.gz）
├── dcm2niix_win/         # dcm2niix 可执行文件（DICOM 转 NIfTI）
├── dcmtk-3.7.0-win64-dynamic/  # DCMTK 工具（DICOM 解压）
├── runtime/python/       # 可移植 Python 环境（BrainAAL conda 环境）
├── workspace/            # 病人工作区根目录（每次运行生成子目录）
├── logs/                 # 运行日志
├── start_core.bat        # 一键启动脚本
└── requirements-webui.txt  # Web 后端依赖
```

---

## 三、系统要求

| 组件 | 说明 |
|------|------|
| **Windows 10/11** | 主操作系统 |
| **MATLAB（含 SPM12）** | 用于 SPM 分割；路径可在 `config/app_settings.json` 中配置 |
| **Docker Desktop** | 用于运行 SynthSeg 容器（`pwesp/synthseg:py38`） |
| **可移植 Python 环境** | 已内置于 `runtime/python/BrainAAL/`，无需额外安装 |
| **DICOM 文件** | 包含 T1、MRA、MRV、DTI 等序列的 DICOM 文件夹 |

### 可配置路径（`config/app_settings.json`）

- `MATLAB_EXE`：matlab.exe 完整路径（不在 PATH 时必须填写）
- `SPM_DIR`：SPM 源码目录（默认 `spm/`）
- `SPM_BACKEND`：`matlab_cli`（调用 MATLAB 命令行）
- `SYNTHSEG_DOCKER_IMAGE`：SynthSeg Docker 镜像名
- `DCM2NIIX_EXE`：dcm2niix 可执行文件路径
- `PYTHON_EXE`：主脚本使用的 Python 解释器路径

---

## 四、启动方法

### 方法一：一键启动（推荐）

1. 启动 **Docker Desktop**（SynthSeg 模式需要）。
2. 双击 `start_core.bat`。
3. 等待命令行窗口输出 `Uvicorn running on http://127.0.0.1:8000`。
4. 浏览器自动打开 `http://127.0.0.1:8000/`。

> 若 MATLAB 不在 PATH 中，脚本会自动搜索常见安装位置（`C:\Program Files\MATLAB\R*\`、`D:\Matlab\`），找到后自动设置。

### 方法二：手动启动

```powershell
# 在 MRI2MR-core 目录下
& "C:\Users\admin\anaconda3\envs\BrainAAL\python.exe" -B -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

---

## 五、Web UI 使用说明

打开浏览器访问 `http://127.0.0.1:8000/`，界面分为三大区域：

### 1. 病例管理面板（左上）

- **新建病人**：点击"新建病人"按钮，填写姓名、ID、性别、年龄、检查日期、备注。
- **选择已有病人**：从下拉列表中选择，自动加载其工作区。
- **保存病人**：将当前填写信息保存到工作区元数据。
- **刷新病人**：重新扫描 `workspace/` 目录，更新病人列表。

每个病人对应 `workspace/<病人ID或文件夹名>/` 目录，内部结构：

```
workspace/<病人>/
├── patient_input/      # 输入文件（T1.nii、MRA.nii、MRV.nii、DTI 等）
├── SynthSeg_result/    # SynthSeg 分割输出
├── model_output/       # 模型输出（GLB 文件）
├── temp/              # 临时文件（DICOM 转换中间结果、缓存等）
├── logs/              # 该病人任务的日志
└── previews/          # 预览图
```

### 2. 模式选择与参数面板（中上）

根据选中的病人，显示当前可用的处理模式。每个模式有独立的参数表单，由 `config/modes.json` 驱动。

### 3. 处理进度与结果（右/下）

- 点击 **运行** 按钮提交任务。
- 任务状态：`pending` → `running` → `success` / `failed` / `cancelled`。
- 运行完成后，可在结果区域查看：
  - NIfTI 文件切片预览（可切换轴：X/Y/Z）
  - GLB 模型 3D 预览（基于 Three.js）
  - 日志输出

---

## 六、处理模式说明

所有模式均在 `config/modes.json` 中定义，通过 Web UI 选择并填写参数后运行。

### 模式 1：DICOM 转换（dicom_convert）

| 项目 | 说明 |
|------|------|
| 输入 | DICOM 文件夹（含 T1、MRA、MRV、DTI 序列） |
| 输出 | `patient_input/T1.nii`、`MRA.nii`、`MRV.nii`、`DTI.nii.gz`、`DTI.bval`、`DTI.bvec` |
| 关键参数 | `dicom_dir`（DICOM 输入文件夹） |
| 可选参数 | `dicom_decompress_dcmtk`（5T DTI 或压缩 DICOM 建议启用）、`dti_only`（只处理 DTI） |

**自动识别逻辑**：根据序列名称/协议名中的关键词匹配（T1：`t1/mprage/bravo`；MRA：`mra/tof/angio`；MRV：`mrv/venography`；DTI：`dti/dwi/diffusion`）。关键词可在高级选项中自定义。

---

### 模式 2：SynthSeg 分割（synthseg_segmentation）

| 项目 | 说明 |
|------|------|
| 输入 | T1 NIfTI 文件（默认 `patient_input/T1.nii`） |
| 输出 | `SynthSeg_result/T1_synthseg.nii` |
| 依赖 | Docker 容器 `pwesp/synthseg:py38` |
| 参数 | `t1_file`、`synthseg_threads`（CPU 线程数，默认 4） |

> SynthSeg 模式需要 **Docker Desktop 已启动**。

---

### 模式 3：SPM 分割（spm_segmentation）

| 项目 | 说明 |
|------|------|
| 输入 | T1 NIfTI 文件 |
| 输出 | `patient_input/c1T1.nii`（灰质）、`c2T1.nii`（白质） |
| 依赖 | MATLAB + SPM12 源码目录 |
| 参数 | `t1_file` |

SPM 使用 `matlab_cli` 后端，调用 `scripts/run_spm_segmentation.m` 脚本执行组织分割。

---

### 模式 4：DK 脑区模型（individual_regions）

| 项目 | 说明 |
|------|------|
| 输入 | T1 参考图 + SynthSeg DK 标签图 |
| 输出 | `model_output/individual_regions/*.glb`（每个 DK 脑区一个 GLB） |
| 参数 | `dk_file`（默认 `SynthSeg_result/T1_synthseg.nii`）、`dk_name_file`（DK 名称映射表） |

基于 SynthSeg 输出的 DK 分区标签，通过 Marching Cubes 提取每个脑区表面网格，导出为 GLB。

---

### 模式 5：灰白质模型（gm_wm）

| 项目 | 说明 |
|------|------|
| 输入 | SPM 输出的 `c2T1.nii`（白质）或 `c1T1.nii`（灰质） |
| 输出 | `model_output/gm_wm/w*.glb` |
| 参数 | `mask_file`（默认 `c2T1.nii`） |

---

### 模式 6：动脉模型（vessel）

| 项目 | 说明 |
|------|------|
| 输入 | MRA NIfTI 文件（`MRA.nii`） |
| 输出 | `model_output/vessel/vessel.glb` |
| 参数 | `vessel_threshold`（默认 400，越高血管越少）、`vessel_min_object_size`（默认 1000）、`vessel_decimation_fraction`（默认 0.5） |

---

### 模式 7：静脉模型（mrv）

| 项目 | 说明 |
|------|------|
| 输入 | MRV NIfTI 文件（`MRV.nii`） |
| 输出 | `model_output/mrv/vessel_vein.glb` |
| 参数 | `mrv_strong_seed_percentile`（默认 99.9）、`mrv_weak_seed_percentile`（默认 99.8）、`mrv_frangi_sigmas_start/end/step`（Frangi 滤波参数） |

静脉提取使用 Frangi 多尺度滤波 + 区域生长算法。

---

### 模式 8：脑叶模型（lobes）

| 项目 | 说明 |
|------|------|
| 输入 | T1 + DK 标签图 |
| 输出 | `model_output/lobes/*.glb`（额叶、颞叶、顶叶、枕叶等） |
| 参数 | `lobe_map_file`（DK → 脑叶映射表，默认 `template/DK_Lobes.txt`） |

---

### 模式 9：脑半球模型（hemispheres）

| 项目 | 说明 |
|------|------|
| 输入 | T1 + DK 标签图 |
| 输出 | `model_output/hemispheres/left.glb`、`right.glb` |

---

### 模式 10：脑室模型（ventricle）

| 项目 | 说明 |
|------|------|
| 输入 | robust SynthSeg 标签图 |
| 输出 | `model_output/ventricle/ventricle.glb` |

---

### 模式 11：多层 ROI 模型（multiroi）

| 项目 | 说明 |
|------|------|
| 输入 | 多层 ROI NIfTI 分割文件 |
| 输出 | `model_output/multiroi/ROI*.glb` |

---

### 模式 12：普通 ROI 模型（roi）

| 项目 | 说明 |
|------|------|
| 输入 | 单个 ROI mask NIfTI 文件 |
| 输出 | `model_output/roi/ROI.glb` |

---

### 模式 13：纤维追踪（fiber_tracking）

| 项目 | 说明 |
|------|------|
| 输入 | DTI（`DTI.nii.gz` + `DTI.bval` + `DTI.bvec`）+ 白质 mask（`c2T1.nii`） |
| 输出 | `model_output/fiber_tracking/Fiber_*.glb` |
| 参数 | `fiber_gfa_threshold`（默认 0.25）、`fiber_stop_threshold`（默认 0.2）、`fiber_step_size`（默认 0.5）、`fiber_max_angle`（默认 45°） |

基于 DIPY 确定性 LocalTracking 算法，在白质 mask 内追踪纤维束。

---

### 模式 14：脑区间纤维连接（fiber_tracking_region）

| 项目 | 说明 |
|------|------|
| 输入 | DTI + GWI atlas（灰白质交界图）+ 白质 mask |
| 输出 | `model_output/fiber_tracking_region/*.glb` |
| 参数 | `gwi_atlas_file`、`fiber_region_min_streamlines`（默认 10，少于该数量不导出） |

GWI atlas 可由 DK 标签图和白质 mask 自动生成（`gwi_dilation_iterations` 控制膨胀次数）。

---

### 模式 15：DKI 纤维追踪（fiber_tracking_dki）

| 项目 | 说明 |
|------|------|
| 输入 | 多 b 值 DKI 数据（`dki_4d.nii.gz` + `bvals.bval` + `bvecs.bvec`）+ 白质 mask |
| 输出 | `model_output/fiber_tracking_dki/DKI_MultiShell_Fiber_*.glb`、`dki_parameters/*.nii.gz` |

适用于多 b 值 DKI 数据，使用 CS-DECONV 模型进行纤维追踪并导出参数图。

---

## 七、常用参数速查

### 模型生成公共参数（所有 GLB 模式均支持）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `smoothing_iterations` | 20 | 网格平滑迭代次数 |
| `smoothing_lambda` | 0.7 | Humphrey 平滑强度 |
| `marching_cubes_level` | 0.7 | 体素→网格等值面阈值 |
| `min_object_size` | 14500 | 最小连通区域体素数（过滤噪声） |
| `mesh_decimation_fraction` | 0.08 | GLB 导出前减面比例 |
| `num_processes` | 8 | 并行进程数 |

### 血管模型参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `vessel_threshold`（MRA） | 400 | MRA 强度阈值，越高血管越少 |
| `vessel_min_object_size` | 1000 | 过滤小血管 |
| `vessel_decimation_fraction` | 0.5 | 动脉模型减面比例 |

### 纤维追踪参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `fiber_gfa_threshold` | 0.25 | GFA 种子区域阈值 |
| `fiber_stop_threshold` | 0.2 | 停止条件阈值 |
| `fiber_step_size` | 0.5 | 每步空间距离（mm） |
| `fiber_max_angle` | 45.0 | 相邻方向最大转角（°） |
| `fiber_seed_density` | 1 | 种子密度 |
| `fiber_radius` | 0.1 | 导出纤维圆柱半径 |
| `fiber_sections` | 3 | 圆柱截面数 |

---

## 八、典型工作流

### 完整流程（从 DICOM 到 3D 模型）

```
步骤 1: DICOM 转换
  选择 DICOM 文件夹 → 自动识别 T1/MRA/MRV/DTI → 输出 NIfTI

步骤 2: 组织分割（二选一）
  a) SynthSeg（需要 Docker）→ 输出 DK 标签图
  b) SPM（需要 MATLAB）→ 输出灰质/白质 mask

步骤 3: 生成 3D 模型
  - DK 脑区 → individual_regions 模式
  - 灰白质 → gm_wm 模式
  - 动脉 → vessel 模式
  - 静脉 → mrv 模式
  - 脑叶 → lobes 模式
  - 纤维束 → fiber_tracking 模式

步骤 4: 查看结果
  在 Web UI 中预览 NIfTI 切片和 3D GLB 模型
```

> 注意：`gm_wm`、`fiber_tracking`、`fiber_tracking_region` 等模式依赖 SPM 输出的白质 mask（`c2T1.nii`），需先运行 SPM 分割。

---

## 九、常见问题

**Q：启动后 Web UI 打不开？**
A：确认 `start_core.bat` 中显示 `Uvicorn running on http://127.0.0.1:8000`，且端口 8000 未被占用。

**Q：SynthSeg 模式报错？**
A：确认 Docker Desktop 已启动，且 `pwesp/synthseg:py38` 镜像已拉取（首次运行会自动拉取）。

**Q：SPM 模式找不到 MATLAB？**
A：编辑 `config/app_settings.json`，将 `MATLAB_EXE` 设置为 matlab.exe 的完整路径，例如：
```json
"MATLAB_EXE": "C:\\Program Files\\MATLAB\\R2025b\\bin\\matlab.exe"
```

**Q：DICOM 转换后找不到某个序列？**
A：Web UI 提供了序列检测结果预览，可查看被排除的原因。必要时在高级选项中调整关键词匹配规则。

**Q：GLB 模型太大/太小？**
A：调整 `mesh_decimation_fraction`（减面比例，越小越精细）和 `vessel_decimation_fraction`（血管专用）。

---

## 十、配置文件说明

### `config/app_settings.json` 关键字段

```json
{
  "MAIN_SCRIPT": "scripts\\Main_cmd.py",
  "SPM_BACKEND": "matlab_cli",
  "MATLAB_EXE": "C:\\Program Files\\MATLAB\\R2025b\\bin\\matlab.exe",
  "SYNTHSEG_DOCKER_IMAGE": "pwesp/synthseg:py38",
  "PYTHON_EXE": "C:\\Users\\admin\\anaconda3\\envs\\BrainAAL\\python.exe",
  "workspace_root": "workspace",
  "template_dir": "template",
  "docker_exe": "C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe",
  "host": "127.0.0.1",
  "port": 8000,
  "max_concurrent_jobs": 1
}
```

- `max_concurrent_jobs`：最大并发任务数（默认 1，避免资源竞争）。
- `log_retention_days`：日志保留天数（默认 30 天）。

### `config/modes.json`

定义所有处理模式的参数、默认值和 CLI 映射，Web UI 据此动态渲染表单。一般无需手动修改。

---

## 十一、输出文件说明

### GLB 模型文件

- 标准 glTF 二进制格式，可用 Blender、Unity、Three.js 等工具打开。
- 每个模型独立命名，如 `caudalmiddlefrontal_L.glb`、`vessel.glb`、`Fiber_1.glb`。

### NIfTI 输出

- `T1_synthseg.nii`：SynthSeg DK 标签图（整数标签，对应 `template/DK_Regions.txt` 中的脑区名称）。
- `c1T1.nii`：SPM 灰质概率图。
- `c2T1.nii`：SPM 白质概率图。

### 日志

- 每个任务在 `workspace/<病人>/logs/` 下生成日志文件，Web UI 中可实时查看。

---

## 十二、免责声明

- 本工具输出（分割结果、模型、纤维追踪）仅供科研参考，不替代临床诊断。
- 使用前请确认数据符合所在机构伦理审查要求。
