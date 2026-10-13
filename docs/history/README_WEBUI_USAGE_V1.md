# MRI2MR WebUI 第一版使用说明书

本文档适用于当前目录 `F:\Desktop\MRI2MR` 中已经实现的 MRI2MR WebUI 第一版。

WebUI 用来把原来的命令行程序 `scripts\Main_cmd.py` 封装成本地网页工具。用户可以在浏览器里填写病例名、输入路径、处理模式和参数，然后运行 DICOM 转换、SynthSeg 分割、SPM 分割、脑模型生成、血管模型生成和纤维束追踪等任务。

## 1. 启动方式

### 方式一：双击启动

在 `F:\Desktop\MRI2MR` 下双击：

```text
start_webui.bat
```

启动后浏览器会打开：

```text
http://127.0.0.1:8000
```

如果浏览器没有自动打开，可以手动复制上面的地址访问。

### 方式二：命令行启动

```bat
cd /d F:\Desktop\MRI2MR
D:\anaconda\envs\BrainAAL\python.exe -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

## 2. 页面区域说明

页面分为四个主要区域：

- 顶部：病例名、输入类型、输入路径、运行、取消。
- 左侧：处理模式和该模式对应的参数表单。
- 中间：结果预览区，用于显示 NIfTI 切片预览或 GLB 模型。
- 右侧：任务状态、耗时、输出文件列表。
- 底部：实时运行日志。

## 3. 基本使用流程

1. 打开 `http://127.0.0.1:8000`。
2. 填写病例名，例如 `patient001`。
3. 选择输入类型：`NIfTI 文件` 或 `DICOM 文件夹`。
4. 在“输入路径”中填写本机绝对路径，例如：

```text
F:\Data\patient001\T1.nii
F:\Data\patient001\DICOM
```

5. 在左侧选择处理模式。
6. 根据模式补充必填参数。
7. 点击“运行”。
8. 在底部查看实时日志。
9. 任务结束后，在右侧输出文件列表中点击结果文件查看预览。

每次运行都会创建独立工作区：

```text
F:\Desktop\MRI2MR\workspace\<任务ID>
```

## 4. 输入路径填写规则

当前第一版使用“路径输入”，不做浏览器上传。

### DICOM 输入

选择 `DICOM 文件夹`，输入路径填写 DICOM 所在文件夹：

```text
F:\Data\patient001\DICOM
```

### NIfTI 输入

选择 `NIfTI 文件`，输入路径填写 `.nii` 或 `.nii.gz` 文件：

```text
F:\Data\patient001\T1.nii
F:\Data\patient001\DTI.nii.gz
```

## 5. 主要模式说明

### DICOM 转换

用途：把 DICOM 文件夹转换为标准命名的 NIfTI 文件。

常见输出：

```text
patient_input\T1.nii
patient_input\MRA.nii
patient_input\MRV.nii
patient_input\DTI.nii.gz
patient_input\DTI.bval
patient_input\DTI.bvec
```

可选项：

- 启用 DCMTK 解压：适合压缩 DICOM 或 5T DTI 数据。
- 只处理 DTI：只导出 DTI、bval、bvec，不导出 T1/MRA/MRV。

### SynthSeg 分割

用途：从 T1 NIfTI 生成 SynthSeg 标签图。

输入：

```text
T1.nii 或 T1.nii.gz
```

输出：

```text
SynthSeg_result\T1_synthseg.nii
```

系统会自动使用 Docker 镜像：

```text
pwesp/synthseg:py38
```

### SPM 分割

用途：从 T1 NIfTI 生成灰质、白质等组织分割结果。

常见输出：

```text
patient_input\c1T1.nii
patient_input\c2T1.nii
```

其中 `c2T1.nii` 通常作为纤维束追踪的白质 mask。

### DK 脑区模型

用途：根据 T1 和 SynthSeg 标签图生成多个 DK 脑区 `.glb` 模型。

常用输入：

```text
T1.nii
T1_synthseg.nii
```

输出位置：

```text
model_output\individual_regions
```

### 动脉模型

用途：从 MRA 图像生成动脉血管模型。

输入：

```text
MRA.nii
```

常用参数：

- 血管阈值
- 最小连通区域大小
- 血管减面比例

输出：

```text
model_output\vessel\vessel.glb
```

### 普通纤维束

用途：根据 DTI 数据生成纤维束模型。

输入：

```text
DTI.nii.gz
DTI.bval
DTI.bvec
c2T1.nii
```

常用参数：

- GFA 阈值
- 停止阈值
- 生长步长
- 最大角度
- 种子密度

## 6. 输出和预览

任务输出保存在病例工作区中：

```text
workspace\<任务ID>
  patient_input
  SynthSeg_result
  model_output
  temp
  logs
  previews
  job.json
```

WebUI 会扫描以下结果：

- `.nii`
- `.nii.gz`
- `.png`
- `.jpg`
- `.glb`
- `.log`
- `.json`

NIfTI 文件会生成三视图 PNG 预览：

- axial
- coronal
- sagittal

GLB 模型会在中间预览区加载显示。模型预览依赖浏览器访问 Three.js CDN；如果网络不可用，文件仍会出现在右侧列表中，可以直接打开或保存。

## 7. 日志和任务状态

任务状态包括：

```text
等待中
运行中
成功
失败
已取消
```

底部日志会实时显示 `Main_cmd.py` 的输出。如果任务失败，优先查看底部日志和右侧错误信息。

日志文件保存在：

```text
workspace\<任务ID>\logs\run.log
```

## 8. 取消任务

任务运行中可以点击顶部“取消”。

取消后：

- 当前任务进程会被终止。
- 已经生成的中间文件会保留。
- 状态变为“已取消”。
- 日志仍可查看。

## 9. 固定程序和资源路径

普通用户不需要填写这些路径，系统会从配置文件读取：

```text
config\app_settings.json
```

当前固定路径包括：

```text
Main_cmd.py
dcm2niix.exe
dcmdjpeg.exe
SPM 路径
SynthSeg Docker 镜像
Python 环境
template\DK_Regions.txt
template\DK_Lobes.txt
template\ROI_ED_Filter.nii.gz
```

其中模板资源来自原始项目：

```text
F:\Desktop\BrainVRReadingRoom\BrainVRReadingRoom
```

## 10. 推荐工作流

### 从 DICOM 到 DK 脑区模型

1. 运行 `DICOM 转换`，生成 `T1.nii`。
2. 运行 `SynthSeg 分割`，生成 `T1_synthseg.nii`。
3. 运行 `DK 脑区模型`，生成多个 `.glb` 模型。
4. 在右侧点击 `.glb` 文件查看模型。

### 从 MRA 到动脉模型

1. 输入 MRA NIfTI 文件路径。
2. 选择 `动脉模型`。
3. 调整血管阈值。
4. 运行后查看 `vessel.glb`。

### 从 DTI 到纤维束模型

1. 准备 `DTI.nii.gz`、`DTI.bval`、`DTI.bvec`。
2. 准备白质 mask，例如 `c2T1.nii`。
3. 选择 `普通纤维束`。
4. 填写 DTI、bval、bvec、mask 路径。
5. 运行后查看纤维束 `.glb`。

## 11. 常见问题

### 页面打不开

确认 WebUI 服务已启动，并访问：

```text
http://127.0.0.1:8000
```

也可以检查：

```text
http://127.0.0.1:8000/health
```

正常应返回：

```json
{"status":"ok"}
```

### 任务提交失败

常见原因：

- 病例名为空。
- 必填路径为空。
- 输入路径不存在。
- 当前已有任务正在运行。

### SynthSeg 失败

检查：

- Docker Desktop 是否启动。
- 是否能访问镜像 `pwesp/synthseg:py38`。
- T1 文件路径是否正确。

### SPM 失败

检查：

- MATLAB 是否可用。
- MATLAB Engine for Python 是否安装在 `BrainAAL` 环境。
- `F:\Desktop\MRI2MR\spm` 是否存在。
- `scripts\run_spm_segmentation.m` 是否存在。

### GLB 不能预览

可能是浏览器不能访问 Three.js CDN。模型文件本身仍在右侧输出列表和 `workspace` 目录中。

## 12. 当前第一版限制

- 当前使用路径输入，不支持浏览器上传文件。
- 同一时间默认只运行一个任务。
- GLB 在线预览依赖 Three.js CDN。
- 尚未实现一键流水线，需要按模式逐步运行。
- 尚未实现病例历史管理和参数预设。

