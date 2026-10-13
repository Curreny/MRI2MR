# MRI2MR WebUI 第二版优化说明

本文档用于记录当前 WebUI 第一版基础上的第二版优化目标。第二版重点优化页面信息结构、病例管理、进度展示、预览逻辑和输出文件筛选规则。

## 1. 第二版优化目标

当前第一版 WebUI 已经可以启动、选择模式、填写参数、运行任务、查看日志和输出文件。

第二版需要解决以下问题：

- 页面中存在两个输入路径位置：顶部输入路径和参数配置中的文件路径，容易让用户困惑。
- 顶部区域应该承担病例管理和进度展示，而不是再放一份文件输入。
- 病例文件夹必须按“病人”管理，而不是按“单次任务”管理；同一个病人多次运行不同模块时，所有数据都应进入同一个病人主文件夹。
- 病例文件夹应尽量根据病人的基本信息命名，主要依据病人姓名。
- 选中已有病人后，右侧输出栏应显示该病人已经处理完成的所有结果，并支持预览。
- 选中已有病人后，当前模式中能自动推断的文件路径应自动填好，同时保留手动修改能力。
- 任务运行时需要用进度条和预估时间展示处理进度。
- SynthSeg 预览时应重点查看 segmentation 标签结果，而不是把它当普通 volume 灰度图查看。
- 输出文件列表不应显示普通临时文件，只保留最终结果和重要中间结果。
- 模型文件需要支持多模型组合展示，不能只支持单个 GLB 逐个查看。

## 2. 页面布局调整

### 2.1 顶部区域

顶部区域不再放文件输入框。

顶部区域保留两类功能：

```text
左侧：病例管理
右侧：处理进度
```

### 2.2 左侧参数区域

所有输入文件、输入文件夹和模式参数，都统一放在左侧“参数配置”区域中。

也就是说：

- DICOM 文件夹输入只出现在 DICOM 转换模式的参数表单中。
- T1 文件输入只出现在 SynthSeg、SPM、DK 脑区模型等需要 T1 的参数表单中。
- MRA 文件输入只出现在动脉模型参数表单中。
- MRV 文件输入只出现在静脉模型参数表单中。
- DTI、bval、bvec、mask 只出现在纤维束相关模式参数表单中。

页面顶部不再出现通用“输入路径”。

## 3. 病例管理

### 3.1 病例基本信息

顶部新增病例管理区，用于填写病人的基本信息。

这些信息全部为非必填。

建议字段：

```text
病人姓名
病人 ID
性别
年龄
检查日期
备注
```

其中“病人姓名”是命名病例主文件夹的主要依据。

### 3.2 病人主文件夹命名规则

第二版必须修复第一版中“每运行一个模块就创建一个新的病人主文件夹”的问题。

当前第一版实际会出现类似结构：

```text
workspace\20260626_094748_patient001
workspace\20260626_095055_patient001
workspace\20260626_095953_patient001
workspace\20260626_100021_patient001
```

这会导致同一个病人的 DICOM 转换结果、SynthSeg 结果、SPM 结果和模型结果分散在多个主文件夹中，是错误的。

第二版应改为：

```text
workspace\<patient_folder>
```

一个病人只有一个主文件夹。这个病人后续运行任意模块，都复用这个主文件夹。

推荐格式：

```text
workspace\<病人姓名>_<病人ID>
```

示例：

```text
workspace\张三_001
workspace\patient001
workspace\unknown
```

命名规则：

- 如果填写了病人姓名，优先使用病人姓名。
- 如果填写了病人 ID，追加病人 ID。
- 如果姓名和 ID 都没有填写，使用 `unknown`。
- 文件夹名必须去除 Windows 不允许的字符。
- 同一个病人再次运行模块时，复用已有主文件夹。
- 只有在新建病人且同名冲突但确认不是同一病人时，才追加编号，例如 `_02`。

### 3.3 病人主文件夹结构

一个病人的所有数据应统一放在一个主文件夹下：

```text
workspace\<patient_folder>
  patient.json
  patient_input
  SynthSeg_result
  model_output
  temp
  previews
  logs
  jobs
    <job_id>
      job.json
      run.log
```

其中：

- `patient_input` 保存 DICOM 转换得到的 T1、MRA、MRV、DTI、bval、bvec，也可以保存用户手动指定或复制进来的输入。
- `SynthSeg_result` 保存 SynthSeg 标签图。
- `model_output` 保存所有最终 GLB 模型。
- `temp` 保存该病人的中间文件。
- `previews` 保存该病人的预览图。
- `logs` 可保存汇总日志。
- `jobs\<job_id>` 保存每一次运行模块的任务记录和该任务日志。

任务仍然可以有独立 `job_id`，但 `job_id` 不再作为病人主文件夹名。

正确关系是：

```text
病人主文件夹：workspace\<patient_folder>
单次任务记录：workspace\<patient_folder>\jobs\<job_id>
```

### 3.4 病人选择和复用

顶部病例管理区需要支持：

- 新建病人。
- 选择已有病人。
- 查看当前选中的病人主文件夹。
- 保存或更新病人基本信息。

选中已有病人后：

- 后续运行所有模块都使用该病人的主文件夹。
- 右侧输出栏显示该病人已经处理完成的结果。
- 参数表单中的默认路径自动切换到该病人主文件夹下的文件。

例如选中：

```text
workspace\张三_001
```

则默认路径应自动变为：

```text
workspace\张三_001\patient_input\T1.nii
workspace\张三_001\SynthSeg_result\T1_synthseg.nii
workspace\张三_001\patient_input\MRA.nii
workspace\张三_001\patient_input\DTI.nii.gz
workspace\张三_001\patient_input\DTI.bval
workspace\张三_001\patient_input\DTI.bvec
workspace\张三_001\patient_input\c2T1.nii
```

这些自动填充路径必须允许用户手动修改。

### 3.5 病例信息保存

病例信息应保存到病人主文件夹：

```text
workspace\<patient_folder>\patient.json
```

建议结构：

```json
{
  "patient_name": "",
  "patient_id": "",
  "sex": "",
  "age": "",
  "study_date": "",
  "notes": ""
}
```

任务信息保存到：

```text
workspace\<patient_folder>\jobs\<job_id>\job.json
```

## 4. 参数配置区文件输入规则

第二版只保留参数配置区中的文件输入。

### 4.1 表单字段来源

每个模式根据 `config\modes.json` 显示自己的参数字段。

文件字段由模式 schema 决定，不再受顶部通用输入路径影响。

例如：

```text
DICOM 转换：dicom_dir
SynthSeg 分割：t1_file
SPM 分割：t1_file
DK 脑区模型：t1_file、dk_file
动脉模型：t1_file、mra_file
普通纤维束：t1_file、dti_file、dti_bvals_file、dti_bvecs_file、mask_file
```

### 4.2 默认路径

表单可以继续提供默认路径，但默认路径必须基于当前选中的病人主文件夹，而不是新建任务文件夹。

```text
{patient_workspace}\patient_input\T1.nii
{patient_workspace}\SynthSeg_result\T1_synthseg.nii
{patient_workspace}\patient_input\DTI.nii.gz
```

用户可以手动修改这些路径。

### 4.4 自动填充规则

选中病人或切换处理模式时，参数表单应根据该病人的已有文件自动填充。

建议映射：

```text
t1_file -> patient_input\T1.nii
dk_file -> SynthSeg_result\T1_synthseg.nii
synthseg_robust_file -> SynthSeg_result\T1_synthseg.nii
mra_file -> patient_input\MRA.nii
mrv_file -> patient_input\MRV.nii
dti_file -> patient_input\DTI.nii.gz
dti_bvals_file -> patient_input\DTI.bval
dti_bvecs_file -> patient_input\DTI.bvec
mask_file -> patient_input\c2T1.nii
gwi_atlas_file -> temp\interface_atlas.nii.gz
fiber_gfa_cache_file -> temp\gfa.nii
mrv_frangi_cache_file -> temp\out_figma12_1000.nii
```

自动填充不等于锁定路径。用户仍然可以手动改成其它文件。

### 4.3 必填校验

点击“运行”时，只校验当前模式的必填字段。

如果缺少必填文件或文件夹，页面应直接提示：

```text
请填写 T1 NIfTI 文件
请填写 DICOM 输入文件夹
请填写 bval 文件
```

不应再提示顶部输入路径缺失。

## 5. 处理进度展示

顶部新增处理进度展示区。

建议包含：

```text
当前任务状态
当前阶段
进度条
已用时间
预估剩余时间
```

### 5.1 状态

状态仍然使用：

```text
pending
running
success
failed
cancelled
```

页面显示为：

```text
等待中
运行中
成功
失败
已取消
```

### 5.2 阶段

不同模式可以显示不同阶段。

示例：

#### DICOM 转换

```text
准备工作区
检查 DICOM 文件夹
必要时执行 DCMTK 解压
运行 dcm2niix
识别 T1/MRA/MRV/DTI
导出标准命名文件
生成预览
完成
```

#### SynthSeg 分割

```text
检查 T1 文件
检查 Docker
运行 SynthSeg
等待标签图输出
生成 segmentation 预览
完成
```

#### 模型生成

```text
读取 NIfTI
生成 mask
Marching Cubes
平滑和减面
导出 GLB
生成输出列表
完成
```

#### 纤维束追踪

```text
读取 DTI/bval/bvec/mask
估计响应函数
计算 GFA
执行纤维追踪
生成 GLB
保存重要中间结果
完成
```

### 5.3 进度条实现建议

第一阶段可以使用“阶段权重”估算进度，不要求从算法内部获得精确百分比。

示例：

```json
{
  "stage": "运行 SynthSeg",
  "progress": 45,
  "elapsed_seconds": 120,
  "estimated_remaining_seconds": 180
}
```

### 5.4 预估时间

预估时间可以按以下优先级计算：

1. 同模式历史任务平均耗时。
2. 当前模式预设耗时。
3. 如果无历史数据，则显示“估算中”。

建议预设：

```text
DICOM 转换：5-20 分钟
SynthSeg 分割：10-40 分钟
SPM 分割：5-30 分钟
DK 脑区模型：5-30 分钟
动脉模型：1-10 分钟
普通纤维束：10-60 分钟
```

预估时间只作为提示，不作为任务超时判断。

## 6. SynthSeg 预览优化

当前第一版会把 `.nii` 文件统一生成灰度 volume 三视图预览。

第二版中，SynthSeg 结果应按 segmentation 标签图进行预览。

### 6.1 识别规则

以下文件应被识别为 segmentation：

```text
T1_synthseg.nii
*synthseg*.nii
*seg*.nii
标签图字段 dk_file
synthseg_robust_file
```

### 6.2 显示方式

Segmentation 预览不应使用普通灰度窗宽窗位。

建议显示：

- 标签图彩色预览。
- 三视图：axial、coronal、sagittal。
- 如有对应 T1，可叠加显示 segmentation overlay。
- 不同标签使用稳定颜色映射。

### 6.3 输出文件

建议生成：

```text
previews\T1_synthseg_segmentation_axial.png
previews\T1_synthseg_segmentation_coronal.png
previews\T1_synthseg_segmentation_sagittal.png
previews\T1_synthseg_overlay_axial.png
```

第一版可以先生成彩色 segmentation 三视图，overlay 可作为后续增强。

## 7. 输出文件筛选规则

第二版右侧输出文件列表不再显示所有临时文件。

右侧输出文件列表显示的是“当前选中病人”的结果，而不只是“当前任务”的结果。

选中病人后，即使还没有运行新的任务，也应能看到该病人已经完成的部分，例如：

```text
T1.nii
T1_synthseg.nii
c2T1.nii
vessel.glb
DK 脑区 glb
fiber.glb
run.log
```

### 7.1 应显示的文件

输出列表应显示：

#### 最终结果

```text
.glb
T1_synthseg.nii
c1T1.nii
c2T1.nii
T1.nii
MRA.nii
MRV.nii
DTI.nii.gz
DTI.bval
DTI.bvec
```

#### 重要中间结果

```text
Frangi 滤波结果
纤维束 GFA 文件
GWI atlas
vessel mask
segmentation preview
模型 preview
日志文件
job.json
patient.json
```

典型文件示例：

```text
temp\out_figma12_1000.nii
temp\gfa.nii
temp\interface_atlas.nii.gz
previews\*.png
logs\run.log
```

### 7.2 不应显示的文件

普通临时文件不显示在输出列表中。

例如：

```text
temp\dicom2niix_output\*
temp\dicom_dcmtk_decompressed\*
临时复制的 DICOM
程序运行中间缓存
普通无用户查看价值的临时文件
```

这些文件可以继续保存在磁盘中，便于排错，但不出现在 WebUI 输出列表里。

### 7.3 文件分类

建议后端返回文件时增加分类：

```text
input
segmentation
final_model
important_intermediate
preview
log
metadata
```

前端右侧可按分类显示。

## 8. 多模型组合展示

第一版只能单个 GLB 文件逐个预览，这对脑区模型、脑叶模型、半球模型、纤维连接等场景意义有限。

第二版需要支持多模型组合展示。

### 8.1 组合展示目标

用户应能够在同一个 3D 预览窗口中同时查看多个模型。

典型场景：

```text
多个 DK 脑区模型组合显示
脑叶模型组合显示
左右半球模型组合显示
脑室 + 脑区组合显示
动脉 + 静脉组合显示
纤维束 + 脑区/半球组合显示
```

### 8.2 右侧输出栏交互

右侧输出文件栏需要支持：

- 单选文件：只预览一个模型或一个图像。
- 多选 GLB 文件：组合加载到同一个 3D 场景。
- 按分类一键选择，例如“选择全部 DK 脑区模型”。
- 显示/隐藏单个模型。
- 清空当前组合。
- 重置视角。

### 8.3 多模型显示控制

每个已加载模型应有独立控制项：

```text
显示/隐藏
透明度
颜色
删除
定位/聚焦
```

第一阶段至少实现：

- 多个 GLB 同时加载。
- 每个 GLB 可显示/隐藏。
- 一键清空。
- 一键重置视角。

透明度、颜色和聚焦可以作为后续增强。

### 8.4 模型组合预设

可以根据输出路径自动生成组合预设：

```text
DK 脑区组合：model_output\individual_regions\*.glb
脑叶组合：model_output\lobes\*.glb
半球组合：model_output\hemispheres\*.glb
组织组合：model_output\tissue\*.glb
血管组合：model_output\vessel\*.glb + model_output\mrv\*.glb
纤维束组合：model_output\fiber_tracking\*.glb
```

右侧输出栏可以按这些组合提供快捷入口。

## 9. 后端接口调整建议

### 9.1 创建任务

`POST /api/jobs` 中不再接收顶部 `input_path`。

建议结构：

```json
{
  "patient": {
    "patient_name": "",
    "patient_id": "",
    "sex": "",
    "age": "",
    "study_date": "",
    "notes": ""
  },
  "mode": "synthseg_segmentation",
  "parameters": {
    "t1_file": "F:\\Data\\patient001\\T1.nii",
    "synthseg_threads": 4
  }
}
```

后端应先解析或创建 `patient_workspace`，然后把当前任务挂到该病人主文件夹下：

```text
workspace\<patient_folder>\jobs\<job_id>
```

传给 `Main_cmd.py` 的目录应是病人主文件夹下的共享目录：

```text
--base-data-dir <patient_workspace>
--patient-data-dir <patient_workspace>\patient_input
--synthseg-data-dir <patient_workspace>\SynthSeg_result
--output-dir <patient_workspace>\model_output
--dicom-temp-dir <patient_workspace>\temp\dicom2niix_output
--dicom-decompress-dir <patient_workspace>\temp\dicom_dcmtk_decompressed
```

### 9.2 获取任务进度

`GET /api/jobs/{job_id}` 增加：

```json
{
  "status": "running",
  "stage": "运行 SynthSeg",
  "progress": 45,
  "elapsed_seconds": 120,
  "estimated_remaining_seconds": 180
}
```

### 9.3 获取病人列表

新增：

```text
GET /api/patients
GET /api/patients/{patient_id}
```

用于显示已有病人并选择病人。

### 9.4 获取病人输出文件

新增或调整：

```text
GET /api/patients/{patient_id}/outputs
```

返回当前病人已经处理完成的结果和重要中间结果。

### 9.5 获取输出文件

`GET /api/jobs/{job_id}/outputs` 只返回用户需要看的输出和重要中间结果。

普通临时文件默认不返回。

但更推荐前端右侧输出栏以病人为中心：

```text
GET /api/patients/{patient_id}/outputs
```

当前任务完成后刷新该病人的输出列表。

## 10. 前端验收标准

第二版完成后，页面应满足：

- 顶部没有通用输入路径。
- 顶部可以填写病人基本信息，且全部非必填。
- 病例主文件夹优先用病人姓名命名。
- 同一个病人多次运行不同模块，不会创建多个病人主文件夹。
- 单次任务只在该病人主文件夹下创建任务记录。
- 文件输入只出现在左侧参数配置区域。
- 选中已有病人后，右侧输出栏显示该病人已有结果。
- 选中已有病人后，参数表单自动填入该病人主文件夹下的默认文件路径。
- 自动填入的路径可以手动修改。
- 运行任务后顶部显示进度条。
- 运行任务后顶部显示已用时间和预估剩余时间。
- SynthSeg 结果以 segmentation 彩色标签图方式预览。
- 输出列表不显示普通临时文件。
- Frangi、GFA、GWI atlas 等重要中间文件仍显示。
- GLB 支持多模型组合展示。
- 日志仍可实时查看。
- 取消任务功能保持可用。

## 11. 测试清单

### 11.1 页面结构测试

- 顶部不存在“输入路径”。
- 顶部存在病例信息输入。
- 顶部存在进度条。
- 切换不同模式时，左侧文件字段正确变化。

### 11.2 病例命名和存储位置测试

- 填写姓名后，workspace 使用姓名参与命名。
- 填写姓名和 ID 后，两者都参与命名。
- 不填写姓名和 ID 时，使用 `unknown`。
- 特殊字符会被过滤。
- 同一个病人运行 DICOM 转换、SynthSeg、DK 模型后，仍然只有一个病人主文件夹。
- 每次运行只新增 `jobs\<job_id>` 任务记录。
- `T1.nii`、`T1_synthseg.nii`、`.glb` 都位于同一个病人主文件夹下。

### 11.3 参数自动填充测试

- 选择已有病人后，SynthSeg 的 `t1_file` 自动填入该病人的 `patient_input\T1.nii`。
- 选择已有病人后，DK 模型的 `dk_file` 自动填入该病人的 `SynthSeg_result\T1_synthseg.nii`。
- 选择已有病人后，纤维束的 DTI/bval/bvec/mask 自动填入该病人目录。
- 手动修改自动填入路径后，运行时使用手动修改后的路径。

### 11.4 参数校验测试

- DICOM 转换缺少 `dicom_dir` 时提示错误。
- SynthSeg 缺少 `t1_file` 时提示错误。
- 纤维束缺少 bval/bvec/mask 时提示错误。

### 11.5 预览测试

- 普通 T1 显示灰度 volume 三视图。
- SynthSeg 显示彩色 segmentation 三视图。
- GLB 模型可以加载或显示可下载文件。
- 多个 GLB 可以组合显示在同一个 3D 预览窗口。
- 多模型组合中可以隐藏/显示单个模型。

### 11.6 输出筛选测试

- `model_output` 下 `.glb` 显示。
- `SynthSeg_result\T1_synthseg.nii` 显示。
- `temp\gfa.nii` 显示。
- `temp\out_figma12_1000.nii` 显示。
- `temp\dicom2niix_output` 内普通转换临时文件不显示。
- `temp\dicom_dcmtk_decompressed` 内临时 DICOM 不显示。
- 切换病人后，右侧输出列表切换为该病人的结果。

## 12. 第二版交付标准

第二版完成即可认为优化达标：

- 页面输入结构清晰，不再有两个文件输入入口。
- 病例管理和任务运行信息集中在顶部。
- 参数表单是唯一文件输入位置。
- 病人 workspace 命名与病人姓名关联。
- 同一病人的所有模块结果都保存在同一个病人主文件夹下。
- 单次任务记录保存在病人主文件夹的 `jobs` 子目录下。
- 选中病人后能看到该病人已完成的结果。
- 选中病人后能自动填好可推断的文件路径，并允许手动修改。
- 进度条和预估时间可用。
- SynthSeg 预览按 segmentation 展示。
- 输出列表只显示最终结果和重要中间结果。
- GLB 模型支持多模型组合展示。
