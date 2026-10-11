# MRI2MR WebUI 第三版优化说明

本文档基于当前 `F:\Desktop\MRI2MR` 代码和第二版 WebUI 结构编写。第三版不推翻第二版的病例管理、参数配置、输出筛选和预览逻辑，而是在 DICOM 转换和输入文件选择体验上继续增强。

已核对的主程序和配置包括：

- `scripts\Main_cmd.py`
- `app\backend\main.py`
- `app\backend\jobs.py`
- `app\backend\command_builder.py`
- `app\backend\preview.py`
- `app\backend\outputs.py`
- `app\backend\patients.py`
- `app\static\app.js`
- `app\static\index.html`
- `app\static\style.css`
- `config\app_settings.json`
- `config\modes.json`

Python 环境仍使用：

```text
D:\anaconda\envs\BrainAAL\python.exe
```

## 1. 第三版优化目标

第三版重点解决四个问题：

- DICOM 转换时，同一个关键词可能匹配到多个 T1、MRA、MRV、DTI 序列，程序必须默认只导出每个模态的一个最佳文件，并清楚显示自动选中了哪个文件。
- 自动选择结果必须允许用户手动覆盖，用户可以通过文件管理器窗口选择 DICOM 原始文件夹、单模态原始序列文件夹或已转换的 NIfTI 文件。
- 所有文件/文件夹参数输入框旁边都要提供“选择”按钮，尤其是 DICOM 输入文件夹。
- 选中或生成单模态影像后，要在输入框下方显示影像基本信息；DTI 还要显示 bval、bvec、b 值和梯度方向信息，并在运行日志中输出。

## 2. 当前代码现状

当前 `scripts\Main_cmd.py` 已经有 DICOM 转换流程：

```text
_process_dicom_convert
_collect_dcm2niix_candidates
_select_anatomical_candidate
_select_dti_candidate
_export_dicom_candidate
```

当前逻辑是：

- 先用 `dcm2niix` 把 DICOM 输入目录转换到 `temp\dicom2niix_output`。
- 收集 `.nii`、`.nii.gz` 及同名 `.json`、`.bval`、`.bvec`。
- T1/MRA/MRV 根据关键词匹配，排除带 bval/bvec 的候选，并按文件大小选一个。
- DTI 优先选择同时有 bval/bvec 且匹配 DTI 关键词的候选，再按 bval 数量选一个。
- 日志会输出 `Selected T1/MRA/MRV/DTI` 和导出路径。

当前 WebUI 现状：

- `config\modes.json` 的 DICOM 模式只有 `dicom_dir`、DCMTK、只处理 DTI、关键词等字段。
- `app\static\app.js` 的 `createField()` 对 file/directory 字段仍渲染为普通文本输入框。
- 后端没有本机文件管理器选择接口。
- `app\backend\preview.py` 的 `nifti_volume_info()` 只返回 shape、轴信息和 segmentation 标记，还没有体素大小、4D 方向数、affine、dtype 等完整元信息。

## 3. 真实 RawData 多候选问题

在示例目录：

```text
F:\Desktop\BrainVRReadingRoom\BrainVRReadingRoom\Data_Zhu\RawData
```

可以看到多个会被关键词命中的序列。

T1 相关：

```text
t1_gre_fsp3d_dr_sag_iso0.7_151645_201
t1_gre_fsp3d_dr_sag_iso0.7_MPR_C_151645_203
t1_gre_fsp3d_dr_sag_iso0.7_MPR_S_151645_202
t1_gre_fsp3d_dr_sag_iso0.7_MPR_T_151645_204
```

MRA 相关：

```text
tof3d_tra_152034_301
tof3d_tra_Crop_MIP_152034_304
tof3d_tra_Crop_SagBatchMIP_152034_302
tof3d_tra_Crop_TraBatchMIP_152034_303
```

MRV 相关：

```text
pc3d_sag_veins_CD_152512_401
pc3d_sag_veins_CD_MIP_152512_404
pc3d_sag_veins_CD_SagBatchMIP_152512_402
pc3d_sag_veins_CD_TraBatchMIP_152512_403
```

DTI/NODDI 相关：

```text
epi_dti_tra_iso2.0mm_dir24_SaveB_153219_501
noddi_b0_iso2mm_AP_SaveBySlc_154530_801
noddi_dir100_iso2mm_Ref_153913_701
noddi_dir100_iso2mm_SaveBySlc_154109_702
```

第三版默认自动选择时，应优先选择原始三维/四维序列，避免 MIP、BatchMIP、MPR、Scout、Motion Curve 等派生序列误入标准输出。

## 4. DICOM 自动选择规则

第三版仍然只导出标准文件：

```text
patient_input\T1.nii
patient_input\MRA.nii
patient_input\MRV.nii
patient_input\DTI.nii.gz
patient_input\DTI.bval
patient_input\DTI.bvec
```

每个模态只导出一个文件。自动选择需要记录并展示：

```text
模态
选中的源文件名
选中的源路径
输出路径
匹配关键词
选择理由
候选数量
被排除候选摘要
```

建议生成两个记录文件：

```text
temp\dicom_candidates.json
patient_input\dicom_selection.json
```

### 4.1 T1/MRA/MRV 排序建议

对 T1/MRA/MRV 候选，建议新增候选评分，不再只按文件大小排序。

优先级建议：

1. 匹配对应模态关键词。
2. 排除 DTI 候选，即排除同名 bval/bvec。
3. 降权派生序列：`mip`、`batchmip`、`mpr`、`scout`、`motion`、`curve`、`localizer`、`survey`、`ref`。
4. 优先原始采集序列，例如示例中的 `201`、`301`、`401`。
5. 同分时再按体积维度、文件大小或 Instance 数量排序。

示例期望：

```text
T1  -> t1_gre_fsp3d_dr_sag_iso0.7_151645_201
MRA -> tof3d_tra_152034_301
MRV -> pc3d_sag_veins_CD_152512_401
```

### 4.2 DTI 排序建议

DTI 候选优先级：

1. 必须有 `.bval` 和 `.bvec`。
2. 匹配 DTI 关键词：`dti`、`dwi`、`diff`、`diffusion`、`noddi`、`dir`。
3. 优先 4D NIfTI，且第 4 维数量和 bval 数量一致。
4. 优先 bval 数量最多的候选。
5. 降权 `b0`、`ref`、`MIP`、派生图。

日志至少输出：

```text
[DICOM] Selected DTI: <filename>
        bval count: <N>
        bvec shape: 3 x <N>
        unique b-values: 0(8), 1000(30), 2000(60)
        gradient directions: <non-zero bvec count>
```

## 5. 手动指定单模态来源

DICOM 转换模式新增四个可选字段：

```text
dicom_t1_source
dicom_mra_source
dicom_mrv_source
dicom_dti_source
```

建议命令行参数：

```text
--dicom-t1-source
--dicom-mra-source
--dicom-mrv-source
--dicom-dti-source
```

这些字段为空时使用自动识别。填写后覆盖对应模态的自动选择。

路径允许两类：

- 已转换的 `.nii` 或 `.nii.gz` 文件。
- 原始 DICOM 单序列文件夹。

如果用户指定 `.nii/.nii.gz`：

- T1/MRA/MRV 直接复制或按目标压缩格式保存到标准输出名。
- DTI 需要检查同名 `.bval` 和 `.bvec`，若缺失则给出明确错误。

如果用户指定 DICOM 单序列文件夹：

- 对该文件夹单独运行 `dcm2niix` 到专用临时目录。
- 从该临时目录选择唯一候选。
- 再导出为标准文件名。

手动指定的选择记录也要写入 `dicom_selection.json`，`selection_mode` 标记为：

```text
auto
manual_nifti
manual_dicom_series
```

## 6. 文件管理器选择窗口

第三版需要为所有 `file`、`directory`、`folder` 字段增加选择按钮。

浏览器自身的 `<input type="file">` 无法稳定提供真实本机绝对路径，因此本项目应使用本机后端弹窗。

建议新增后端接口：

```text
POST /api/select-path
```

请求：

```json
{
  "kind": "file",
  "title": "选择 T1 NIfTI 文件",
  "initial_dir": "F:\\Desktop",
  "patterns": [["NIfTI", "*.nii *.nii.gz"], ["All files", "*"]]
}
```

或：

```json
{
  "kind": "directory",
  "title": "选择 DICOM 输入文件夹",
  "initial_dir": "F:\\Desktop"
}
```

返回：

```json
{
  "path": "F:\\Desktop\\BrainVRReadingRoom\\BrainVRReadingRoom\\Data_Zhu\\RawData"
}
```

实现建议：

- 后端使用 `tkinter.filedialog.askopenfilename()` 和 `askdirectory()`。
- 创建并隐藏 Tk 根窗口，选择结束后销毁。
- 只返回路径，不复制文件。
- 如果服务器运行在无桌面环境，返回清晰错误并允许用户继续手动输入路径。

前端调整：

- `createField()` 渲染文件/目录字段时，输入框右侧加“选择”按钮。
- 点击按钮调用 `/api/select-path`。
- 返回路径后写入输入框，并触发 `change` 事件刷新备注。
- 保留手动输入能力。

必须覆盖：

```text
DICOM 输入文件夹 dicom_dir
T1/MRA/MRV/DTI NIfTI 文件
bval/bvec 文件
mask 文件
DK/SynthSeg/ROI 文件
第三版新增的 dicom_t1_source/dicom_mra_source/dicom_mrv_source/dicom_dti_source
```

## 7. 输入框下方影像备注

第三版中，文件或文件夹输入框下方要显示动态备注。备注不是帮助文本的替代，而是当前路径对应数据的真实信息。

### 7.1 NIfTI 信息

对 `.nii`、`.nii.gz` 路径，后端应返回：

```json
{
  "path": "",
  "exists": true,
  "type": "nifti",
  "shape": [256, 256, 192],
  "ndim": 3,
  "volume_count": 1,
  "voxel_size_mm": [0.7, 0.7, 0.7],
  "fov_mm": [179.2, 179.2, 134.4],
  "dtype": "float32",
  "orientation": ["R", "A", "S"],
  "affine": [[...]],
  "file_size": 123456789
}
```

前端备注显示为短文本，例如：

```text
已读取：256×256×192，体素 0.70×0.70×0.70 mm，FOV 179.2×179.2×134.4 mm，RAS，float32
```

4D DTI 显示：

```text
已读取：128×128×72×101，体素 2.00×2.00×2.00 mm，方向数 101
```

### 7.2 bval/bvec 信息

对 `.bval`、`.bvec` 文件，以及 DTI NIfTI 旁边可找到同名 bval/bvec 时，后端应返回：

```json
{
  "bval_count": 101,
  "bvec_shape": [3, 101],
  "b0_count": 8,
  "unique_bvals": [
    {"b": 0, "count": 8},
    {"b": 1000, "count": 30},
    {"b": 2000, "count": 63}
  ],
  "gradient_direction_count": 93,
  "matches_volume_count": true
}
```

前端备注显示：

```text
bval 101 个；bvec 3×101；b=0:8，b=1000:30，b=2000:63；非零梯度 93；与 DTI 4D 数量一致
```

如果数量不一致，备注必须显示警告。

### 7.3 DICOM 原始文件夹信息

对 DICOM 文件夹，后端可优先读取少量 DICOM 文件头，不需要加载像素数据。

建议使用 `pydicom.dcmread(path, stop_before_pixels=True, force=True)`。

可展示：

```text
SeriesDescription
ProtocolName
SeriesNumber
Modality
Rows × Columns
PixelSpacing
SliceThickness
SpacingBetweenSlices
Instance 数量
是否包含 DiffusionBValue / DiffusionGradientOrientation
```

如果一个文件夹下包含多个序列，备注显示：

```text
检测到多个 SeriesInstanceUID，建议选择更具体的单序列文件夹，或使用自动识别。
```

## 8. 后端信息接口

建议新增通用检查接口：

```text
POST /api/inspect-path
```

请求：

```json
{
  "path": "F:\\Data\\patient001\\DTI.nii.gz",
  "field": "dti_file",
  "related": {
    "bval": "F:\\Data\\patient001\\DTI.bval",
    "bvec": "F:\\Data\\patient001\\DTI.bvec"
  }
}
```

返回：

```json
{
  "ok": true,
  "summary": "128×128×72×101，体素 2.00×2.00×2.00 mm，方向数 101",
  "details": {}
}
```

这个接口可以复用并增强 `app\backend\preview.py` 中的 NIfTI 读取逻辑，也可以拆成新文件：

```text
app\backend\inspectors.py
```

注意：

- 只读取文件头和 bval/bvec 文本，不读取完整影像数据。
- 路径必须存在才返回元信息。
- 对工作区外路径允许只读检查，因为用户需要选择原始数据路径。
- 不要把检查失败作为表单错误，除非用户点击运行。

## 9. DTI 日志增强

在 `Main_cmd.py` 中建议新增工具函数：

```text
_summarize_nifti(path)
_summarize_bvals_bvecs(bval_path, bvec_path, expected_volume_count=None)
_print_dti_gradient_summary(dti_path, bval_path, bvec_path)
```

在以下位置调用：

- DICOM 转换导出 DTI 后。
- 用户手动指定 DTI source 后。
- 普通纤维束和脑区间纤维追踪读取 bval/bvec 后。
- DKI 纤维束读取 bval/bvec 后。

DICOM 转换日志示例：

```text
[DICOM] Exported DTI: F:\...\patient_input\DTI.nii.gz
[DICOM] Exported DTI bval: F:\...\patient_input\DTI.bval
[DICOM] Exported DTI bvec: F:\...\patient_input\DTI.bvec
[DTI] image shape: 128 x 128 x 72 x 101
[DTI] voxel size: 2.00 x 2.00 x 2.00 mm
[DTI] bval count: 101
[DTI] bvec shape: 3 x 101
[DTI] b-values: 0(8), 1000(30), 2000(63)
[DTI] gradient directions: 93
[DTI] bval/bvec count matches DTI volumes: yes
```

## 10. 前端展示要求

第三版参数表单中，路径字段结构建议为：

```text
字段标题 *
[路径输入框                         ][选择]
当前数据备注
帮助文本
```

备注样式建议：

```css
.field-note
.field-note.warning
.field-note.error
```

备注状态：

- 空路径：不显示或显示“未选择”。
- 路径不存在：显示浅色警告，不阻塞编辑。
- NIfTI 可读：显示 shape、体素、方向数等。
- bval/bvec 可读：显示 b 值和梯度方向。
- DICOM 文件夹可读：显示序列摘要。
- 检查失败：显示失败原因。

## 11. 需要修改的文件

建议改动位置：

```text
scripts\Main_cmd.py
```

- 增加手动 source 参数。
- 增强 DICOM 候选评分。
- 输出 `dicom_candidates.json` 和 `dicom_selection.json`。
- 增强 DTI bval/bvec 日志。

```text
config\modes.json
```

- DICOM 模式增加 `dicom_t1_source`、`dicom_mra_source`、`dicom_mrv_source`、`dicom_dti_source`。
- 为 file/directory 字段补充 `accept` 或 `dialog` 配置。

```text
app\backend\main.py
```

- 增加 `/api/select-path`。
- 增加 `/api/inspect-path`。

```text
app\backend\preview.py
app\backend\inspectors.py
```

- 增强 NIfTI 元信息读取。
- 增加 bval/bvec 摘要。
- 增加 DICOM 文件头摘要。

```text
app\static\app.js
```

- 文件/目录字段改为路径输入组。
- 增加选择按钮调用。
- 增加路径变更后的元信息检查和备注刷新。
- DICOM 任务完成后读取并显示选择摘要。

```text
app\static\style.css
```

- 增加路径输入组和备注样式。

```text
tools\validate_webui_v3_config.py
```

- 增加第三版配置和接口检查。

## 12. 验收标准

### 12.1 DICOM 自动选择

使用：

```text
F:\Desktop\BrainVRReadingRoom\BrainVRReadingRoom\Data_Zhu\RawData
```

运行 DICOM 转换后：

- 只生成一个 `T1.nii`。
- 只生成一个 `MRA.nii`。
- 只生成一个 `MRV.nii`。
- 只生成一个 `DTI.nii.gz`。
- 只生成一组 `DTI.bval`、`DTI.bvec`。
- 日志显示每个模态选中了哪个源文件。
- `patient_input\dicom_selection.json` 中记录完整选择结果。

### 12.2 手动覆盖

- 用户能点击 DICOM 输入文件夹旁的“选择”按钮打开文件管理器。
- 用户能给 T1/MRA/MRV/DTI 单独指定源路径。
- 指定源路径后，对应模态使用手动路径，不再使用自动候选。
- 手动指定路径会写入 `dicom_selection.json`。

### 12.3 输入备注

- 选择 T1/MRA/MRV NIfTI 后，输入框下方显示 shape、体素大小、FOV。
- 选择 DTI NIfTI 后，显示 4D shape、体素大小、方向数。
- 选择 bval/bvec 后，显示 b 值分布和梯度方向数量。
- 选择 DICOM 文件夹后，显示 DICOM 序列摘要。
- bval/bvec 数量和 DTI 4D 方向数不一致时显示警告。

### 12.4 日志

DICOM 转换导出 DTI 后，运行日志必须包含：

```text
bval count
bvec shape
unique b-values
gradient directions
count matches DTI volumes
```

### 12.5 兼容性

- 第二版病例主文件夹结构保持不变。
- 当前病人输出列表和 NIfTI/GLB 预览保持可用。
- 手动输入路径仍可运行。
- 无法打开文件管理器时，不影响手动输入路径。

## 13. 推荐开发顺序

1. 先实现 `/api/select-path`，让所有路径字段都能从文件管理器填入。
2. 实现 `/api/inspect-path`，让 NIfTI、DICOM、bval/bvec 备注可显示。
3. 在前端 `createField()` 中加入路径输入组、选择按钮和备注区。
4. 扩展 DICOM 模式的手动 source 字段和 CLI 参数。
5. 增强 `Main_cmd.py` 的候选评分、选择记录和 DTI 日志。
6. 用 `Data_Zhu\RawData` 做端到端验收。
