# MRI2MR · VesselPilot

MRI2MR 当前提供一个面向脑血管 MRI 的本地工作流：通过 [Agnes Harness](agnes-harness/README.zh-CN.md) 的网页对话，检查已脱敏的 DICOM 目录，将序列转换为 NIfTI，并从 MRA、MRV 重建动脉、静脉的 GLB 三维模型。影像处理由 [`scripts/Vascular_cmd.py`](scripts/Vascular_cmd.py) 执行，Agnes 的 VesselPilot 集成负责选择输入、管理任务、展示预览和保存结果。

> 当前入口面向 Windows 本地使用。重建结果及自动质控仅供研究和技术检查，不能代替临床判读。请仅使用已脱敏、获准处理的数据；DICOM 可能包含可识别的患者信息。

## 功能与输入输出

| 任务          | 输入                                     | 主要输出                                            |
| ------------- | ---------------------------------------- | --------------------------------------------------- |
| DICOM 预检    | 一个已脱敏的本地 DICOM 目录              | 文件统计、序列抽样预览、病例 ID；不会启动转换或重建 |
| DICOM → NIfTI | 含可转换 DICOM 序列的目录                | `patient_input/nifti/*.nii` 及各文件的实际路径      |
| 动脉重建      | 含可用三维 MRA 序列的 DICOM 目录         | `MRA.nii`、候选 `artery.glb`、预览和质控报告        |
| 静脉重建      | 含可用三维 MRV 序列的 DICOM 目录         | `MRV.nii`、候选 `vein.glb`、预览和质控报告          |
| 动静脉重建    | 同一病例中分别可用的三维 MRA 与 MRV 序列 | 两侧 GLB、预览和质控报告                            |

重建请求默认会在有限候选数内尝试调参、比较结果。可明确要求“只运行一次”或固定参数。当前对话工作流可调整的参数只有动脉阈值 `vessel_threshold`、静脉弱生长容差 `mrv_weak_grow_tolerance` 和静脉最小区域大小 `mrv_post_process_min_size`；其他重建参数使用默认值。单独转换 NIfTI 不会启动重建。

## 环境依赖

- Windows 10/11、PowerShell、Git。
- Node.js **24.10 或更新**，以及通过 Corepack 使用的 **pnpm 10.34.5**（版本由 `agnes-harness/package.json` 固定）。从源码构建 Agnes 的 Windows 原生组件还需要 Visual Studio C++ Build Tools 和 Windows SDK；详见 [Agnes Windows 构建说明](agnes-harness/docs/guide/install.zh-CN.md#windows-构建)。
- Conda（Miniconda 或 Anaconda），用于从 [`environment.yml`](environment.yml) 创建 Python 3.9 的 `BrainAAL` 环境。该环境包含 NumPy、NiBabel、pydicom、SimpleITK、trimesh 等处理依赖。
- 仓库内的 `dcm2niix_win/dcm2niix.exe` 和 `dcmtk-3.7.0-win64-dynamic/`，用于 DICOM 转换与压缩影像解码。不要只复制 Python 脚本而遗漏这两个目录。
- 一个可在 Agnes 中配置的模型账号。若需要自动查看重建预览并评估候选，所选模型应支持图像输入；否则需要人工复核。

本仓库不会提交 `node_modules/`、Conda 环境、患者数据或运行输出。克隆后需自行安装依赖。当前 VesselPilot 流程不依赖旧版 MRI2MR Core 的 FastAPI 页面、SPM 或 Docker 分割流程。

## 安装与启动

以下命令在项目根目录的 **PowerShell** 中执行。

1. 创建并激活 Python 环境：

   ```powershell
   conda env create -f .\environment.yml
   conda activate BrainAAL
   ```

2. 安装并构建 Agnes Harness：

   ```powershell
   cd .\agnes-harness
   corepack pnpm install --frozen-lockfile
   .\.github\scripts\prepare-windows-native.ps1 -CacheRoot "$env:LOCALAPPDATA\node-gyp\Cache"
   corepack pnpm --filter @agnes/cli build:local
   cd ..
   ```

   构建完成后应存在 `agnes-harness/packages/cli/dist/local/agnes.mjs`。若已有与当前源码对应的构建产物，可跳过构建。更新 Agnes 源码后需重新构建并重启服务。

3. 启动本地服务：

   ```powershell
   .\start_agnes.ps1
   ```

   浏览器访问 <http://127.0.0.1:4177>。更换端口可运行 `.\start_agnes.ps1 -Port 4180`；只检查和注册 VesselPilot 可运行 `.\start_agnes.ps1 -SetupOnly`。脚本会寻找已激活的 `BrainAAL` Conda 环境，也支持项目内 `runtime/python/BrainAAL/python.exe` 或 `venv/runtime/python/BrainAAL/python.exe`，并检查所需 Python 包。它使用项目根目录作为 Agnes 工作区，运行状态保存在 `agnes-harness/agh-home/`。

4. 首次打开网页时，按提示配置模型。然后在 **Settings → MCP** 确认 `VesselPilot` 已受信任并启用；在 **Settings → Skills** 刷新工作区来源、确认 `vessel-pilot` 已启用。新建任务时确认工作目录为本项目根目录。配置细节见 [VesselPilot 集成说明](agnes-harness/integrations/vessel-pilot/README.md#start-or-register-in-agnes-harness)。

## 输入数据集格式

输入是**一个病例对应的 `MR` 目录**，路径形式为 `数据集/<病例编号>/Data_vessel_<编号>/<检查日期>/MR/`。`MR` 下按序列建目录，每个序列的原始影像放在其 `dcm/` 子目录。VesselPilot 会递归检查选中的目录；DICOM 文件可使用 `.dcm`、`.dicom`、`.ima` 后缀，或包含标准 DICOM `DICM` 文件头。按本地样例整理后的结构如下（文件名和数量仅作示意）：

```text
数据集\
└── A01\
    └── Data_vessel_01\
        └── 20260208\
            └── MR\                         ← 在对话中选择或提供此目录
                ├── 401_tof3d_tra\          ← 名称含 TOF 的序列
                │   ├── dcm\
                │   │   └── *.dcm
                │   ├── *.nii
                │   ├── *.png
                │   └── *.txt
                └── 501_pc3d_sag_veins_CD\  ← 名称含 veins 的序列
                    ├── dcm\
                    │   └── *.dcm
                    ├── *.nii
                    ├── *.png
                    └── *.txt
```

- 上述样例的两个 `dcm/` 分别包含 276 和 260 个 `.dcm` 文件；同级现有的 `.nii`、`.png`、`.txt` 是伴随文件，提交输入时仍选择共同的 `MR` 目录。序列名称和每组切片数可以因病例而异，不能仅凭目录名判定模态，转换后还需核对选择结果。
- **仅转 NIfTI：**只要有可转换的 DICOM 序列即可，不要求 MRA/MRV 成对出现。
- **动脉：**需要可用的三维 MRA；**静脉：**需要可用的三维 MRV；**双侧：**需要来自不同源序列的 MRA 和 MRV。T1 或其他序列可以同时存在，但不能代替所需模态。
- MIP、MPR、定位像，以及不符合要求的二维、四维或退化体数据不会作为血管重建输入。多个序列都可能匹配时，需要核对序列选择。
- 输入目录必须保持可读，处理过程中不要改动源文件。目录内的符号链接不被接受；单个输入目录最多检查 200,000 个文件。
- 可以将数据放在 `workspace/`，也可以在对话中明确提供或选择工作区外的**本机绝对路径**。文件夹选择器传递本地路径，不会把整套 DICOM 上传给远程浏览器。运行输出始终写入项目内的 `workspace/vessel-pilot/`。

## 使用方式

在 Agnes 新任务中，输入已脱敏 DICOM 病例的 `MR` 文件夹绝对路径，或点击输入框旁的 **Select a DICOM folder** 选择该目录，然后发送明确的任务描述。下方的 `C:\数据集\...` 是示例，请替换为本机实际路径。仅选择文件夹不会自动开始处理。首次处理会要求确认数据已脱敏；有歧义的序列或无法确定的视觉结果也可能要求人工选择。

示例提示词：

```text
使用 vessel-pilot，检查 C:\数据集\A01\Data_vessel_01\20260208\MR 的 DICOM 序列，不启动转换。
使用 vessel-pilot，将 C:\数据集\A01\Data_vessel_01\20260208\MR 的已脱敏 DICOM 全部转换为 NIfTI，返回输出路径。
使用 vessel-pilot，只重建这个病例的动脉，阈值从 850 开始，并比较候选结果。
使用 vessel-pilot，只重建静脉；只运行一次，不自动调参。
使用 vessel-pilot，重建这个病例的动脉和静脉，并给出 GLB 路径与质控结论。
```

任务进度、DICOM/NIfTI 切片预览和 GLB 六视图预览会显示在聊天结果中。静脉重建等长任务可能耗时较久；可在同一会话中查看进度或取消。预览与技术检查通过后，才会将候选定稿；结果仍须由具备相应资质的人员复核。

## 输出目录

每个病例分配独立的 `case_id`，每次重建候选有独立的 `candidate_id`。实际路径以工具返回为准，典型结构如下：

```text
workspace/vessel-pilot/<case_id>/
├── case.json                         # 病例与源数据记录
├── patient_input/
│   ├── nifti/*.nii                   # 仅转换任务的输出
│   ├── MRA.nii                       # 动脉重建输入（如有）
│   ├── MRV.nii                       # 静脉重建输入（如有）
│   └── dicom_selection.json          # 序列选择记录
├── jobs/<job_id>/                    # 任务状态与运行记录
├── candidates/<candidate_id>/
│   ├── artery.glb / vein.glb         # 仅包含请求的侧别
│   ├── parameters.json
│   ├── report.json                   # 技术与视觉检查
│   └── previews/                     # 六视图预览
└── final/<candidate_id>/             # 通过检查后的定稿副本
```

`workspace/` 被 Git 忽略。请不要将原始 DICOM、病例输出、日志或含患者信息的截图提交到公开仓库。实现与故障排查细节见 [VesselPilot 文档](agnes-harness/integrations/vessel-pilot/README.md) 和 [Agnes 文档](agnes-harness/docs/README.zh-CN.md)。
