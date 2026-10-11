# MRI2MR WebUI 开发事项清单

本文档用于规划 `F:\Desktop\MRI2MR` 中 MRI2MR WebUI 的最终实现。目标是把现有命令行程序封装成一个本地 WebUI，用户通过浏览器选择输入数据、选择处理模式、填写对应参数、运行任务，并自动查看结果预览。

## 1. 最终目标

WebUI 需要完成以下能力：

- 支持输入 DICOM 文件夹或 NIfTI 文件。
- 用户通过下拉框选择处理模式。
- 每个模式显示独立参数输入区，只显示该模式相关参数。
- 程序文件路径固定在 `F:\Desktop\MRI2MR` 内，不暴露给普通用户填写。
- 每次运行生成独立病例工作区，避免覆盖其他病例结果。
- 任务运行时显示实时日志、状态、耗时和错误信息。
- 任务完成后自动出现结果预览。
- 用户可以选择查看中间结果，但不需要手动打开文件。
- 支持取消正在运行的任务。

## 2. 固定程序路径

WebUI 后端应固定使用以下路径，不要求用户输入：

```text
MRI2MR_ROOT = F:\Desktop\MRI2MR

MAIN_SCRIPT = F:\Desktop\MRI2MR\scripts\Main_cmd.py
SPM_SCRIPT = F:\Desktop\MRI2MR\scripts\run_spm_segmentation.m
DCM2NIIX_EXE = F:\Desktop\MRI2MR\dcm2niix_win\dcm2niix.exe
DCMTK_DCMDJPEG_EXE = F:\Desktop\MRI2MR\dcmtk-3.7.0-win64-dynamic\dcmtk-3.7.0-win64-dynamic\bin\dcmdjpeg.exe
SPM_DIR = F:\Desktop\MRI2MR\spm
SYNTHSEG_DOCKER_IMAGE = pwesp/synthseg:py38
PYTHON_EXE = D:\anaconda\envs\BrainAAL\python.exe
```

建议新增配置文件：

```text
F:\Desktop\MRI2MR\config\app_settings.json
```

配置内容包括：

- 程序路径
- 默认输出根目录
- 默认 Python 解释器
- Docker 镜像名
- 日志保留天数
- 是否允许覆盖已有病例
- 最大并发任务数，第一版建议为 1

## 3. 推荐目录结构

建议在 `F:\Desktop\MRI2MR` 内新增：

```text
F:\Desktop\MRI2MR
  app
    backend
      main.py
      config.py
      modes.py
      jobs.py
      command_builder.py
      preview.py
      outputs.py
    static
      index.html
      app.js
      style.css
  config
    app_settings.json
  workspace
    <case_id>
      patient_input
      SynthSeg_result
      model_output
      temp
      logs
      previews
      job.json
  scripts
    Main_cmd.py
    run_spm_segmentation.m
  dcm2niix_win
  dcmtk-3.7.0-win64-dynamic
  spm
  SynthSeg-master
```

每个病例使用独立 `case_id`，例如：

```text
F:\Desktop\MRI2MR\workspace\20260624_153012_patient001
```

WebUI 调用 `Main_cmd.py` 时，应显式传入：

```text
--base-data-dir <case_workspace>
--patient-data-dir <case_workspace>\patient_input
--synthseg-data-dir <case_workspace>\SynthSeg_result
--output-dir <case_workspace>\model_output
```

## 4. 后端任务

### 4.1 建立 FastAPI 后端

需要实现：

- 启动 Web 服务
- 加载固定配置
- 返回模式列表
- 接收任务表单
- 运行 `Main_cmd.py`
- 实时推送日志
- 管理任务状态
- 生成预览资源
- 返回输出文件列表

建议接口：

```text
GET  /api/config
GET  /api/modes
POST /api/jobs
GET  /api/jobs
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/logs
POST /api/jobs/{job_id}/cancel
GET  /api/jobs/{job_id}/outputs
GET  /api/jobs/{job_id}/previews
```

### 4.2 任务状态模型

每个任务保存 `job.json`：

```json
{
  "job_id": "20260624_153012_patient001",
  "case_name": "patient001",
  "mode": "synthseg_segmentation",
  "status": "running",
  "created_at": "2026-06-24T15:30:12",
  "started_at": "2026-06-24T15:30:15",
  "finished_at": null,
  "command": [],
  "workspace": "",
  "log_file": "",
  "outputs": [],
  "previews": [],
  "error": null
}
```

状态枚举：

```text
pending
running
success
failed
cancelled
```

### 4.3 命令构建器

必须用 `subprocess.Popen(list_args, shell=False)`，不要拼接 shell 字符串。

示例：

```text
D:\anaconda\envs\BrainAAL\python.exe
F:\Desktop\MRI2MR\scripts\Main_cmd.py
--mode synthseg_segmentation
--base-data-dir <case_workspace>
--patient-data-dir <case_workspace>\patient_input
--synthseg-data-dir <case_workspace>\SynthSeg_result
--output-dir <case_workspace>\model_output
--t1-file <selected_t1_file>
--dk-file <case_workspace>\SynthSeg_result\T1_synthseg.nii
--synthseg-threads 4
```

### 4.4 任务取消

Windows 下需要终止子进程树，建议使用 `psutil`：

- 查找主进程
- 递归终止子进程
- 等待退出
- 超时后强制 kill
- 更新任务状态为 `cancelled`

## 5. 前端任务

### 5.1 页面布局

第一版页面建议：

```text
顶部：病例名、输入类型、运行按钮、取消按钮
左侧：模式下拉框、参数表单
中间：预览窗口
右侧：任务状态、输出文件、中间结果列表
底部：实时日志
```

### 5.2 输入区

支持两类输入：

- DICOM 文件夹
- NIfTI 文件，例如 `.nii`、`.nii.gz`

第一版可先支持路径输入。后续可增加：

- 拖拽上传文件
- 选择本地文件夹
- 最近使用路径
- 病例模板

### 5.3 模式下拉框

模式名称建议显示中文，后端仍使用 `Main_cmd.py` 的英文 mode：

```text
DICOM 转换 -> dicom_convert
SynthSeg 分割 -> synthseg_segmentation
SPM 分割 -> spm_segmentation
DK 脑区模型 -> individual_regions
灰白质模型 -> gm_wm
动脉模型 -> vessel
静脉模型 -> mrv
脑叶模型 -> lobes
脑半球模型 -> hemispheres
脑室模型 -> ventricle
多层 ROI 模型 -> multiroi
普通纤维束 -> fiber_tracking
脑区间纤维连接 -> fiber_tracking_region
其他组织 -> tissue
DKI 纤维束 -> fiber_tracking_dki
```

### 5.4 参数表单

每个模式建立独立参数 schema。字段包括：

- 字段名
- 中文标签
- 类型
- 默认值
- 是否必填
- 帮助文本
- 是否高级参数
- 参数对应的命令行名称

示例：

```json
{
  "mode": "synthseg_segmentation",
  "fields": [
    {
      "name": "t1_file",
      "label": "结构像 NIfTI 文件",
      "type": "file",
      "cli": "--t1-file",
      "required": true
    },
    {
      "name": "synthseg_threads",
      "label": "CPU 线程数",
      "type": "number",
      "cli": "--synthseg-threads",
      "default": 4
    }
  ]
}
```

## 6. 模式参数清单

### 6.1 DICOM 转换

必填：

- DICOM 输入文件夹
- 病例名

可选：

- 是否启用 DCMTK 解压
- 是否只处理 DTI
- T1 关键词
- MRA 关键词
- MRV 关键词
- DTI 关键词

固定参数：

- `--dcm2niix-exe`
- `--dcmtk-dcmdjpeg-exe`
- `--dicom-temp-dir`
- `--dicom-decompress-dir`

输出：

- `patient_input\T1.nii`
- `patient_input\MRA.nii`
- `patient_input\MRV.nii`
- `patient_input\DTI.nii.gz`
- `patient_input\DTI.bval`
- `patient_input\DTI.bvec`

### 6.2 SynthSeg 分割

必填：

- T1 NIfTI 文件

可选：

- CPU 线程数

固定参数：

- Docker 镜像 `pwesp/synthseg:py38`
- `--parc`
- `--robust`
- `--cpu`

输出：

- `SynthSeg_result\T1_synthseg.nii`

### 6.3 SPM 分割

必填：

- T1 NIfTI 文件

固定参数：

- `--spm-dir F:\Desktop\MRI2MR\spm`

输出：

- `patient_input\c1T1.nii`
- `patient_input\c2T1.nii`
- 其他 SPM 生成文件

### 6.4 模型生成类模式

这些模式一般使用已经生成的中间数据：

- DK 脑区模型：需要 T1 和 SynthSeg 标签图
- 脑叶模型：需要 T1、SynthSeg 标签图、DK_Lobes.txt
- 脑半球模型：需要 T1 和 SynthSeg 标签图
- 脑室模型：需要 T1 和 robust SynthSeg 标签图
- 其他组织：需要 robust SynthSeg 标签图
- 动脉模型：需要 MRA
- 静脉模型：需要 MRV
- 灰白质模型：需要 SPM 的 c2 白质图
- 纤维束：需要 DTI、bval、bvec、白质 mask
- 脑区间纤维连接：需要 DTI、bval、bvec、GWI atlas、白质 mask
- DKI 纤维束：需要 DKI、bval、bvec、白质 mask

输出：

- `.glb` 模型文件
- 日志
- 预览截图

## 7. 预览功能任务

### 7.1 NIfTI 预览

需要后端生成 PNG 预览：

- 轴位 axial
- 冠状 coronal
- 矢状 sagittal
- 可选标签图 overlay

适用文件：

- T1
- MRA
- MRV
- DTI b0
- SynthSeg 标签图
- SPM c1/c2
- GWI atlas
- vessel mask

建议输出：

```text
previews
  T1_axial.png
  T1_coronal.png
  T1_sagittal.png
  synthseg_overlay_axial.png
```

### 7.2 GLB 模型预览

前端使用 Three.js 加载 `.glb`：

- 自动加载最新输出模型
- 支持旋转、缩放、平移
- 支持切换模型文件
- 支持显示/隐藏单个模型
- 支持重置视角

### 7.3 自动预览触发

任务结束后后端执行：

1. 扫描输出目录。
2. 识别 NIfTI、PNG、GLB。
3. 生成或更新预览资源。
4. 更新 `job.json`。
5. 前端自动刷新预览窗口。

### 7.4 中间结果查看

右侧中间结果列表中显示：

- 原始输入
- DICOM 转换结果
- SynthSeg 标签图
- SPM 灰质和白质
- GWI atlas
- 血管分割中间结果
- 纤维束相关中间结果

用户点击列表项后，中间预览窗口自动切换，不需要手动打开文件。

## 8. 输出管理

每个任务输出应记录：

- 文件名
- 文件类型
- 文件路径
- 文件大小
- 更新时间
- 是否为最终结果
- 是否可预览

输出文件分类：

```text
input
intermediate
final_model
preview
log
```

## 9. 错误处理

需要明确提示：

- 输入文件不存在
- DICOM 文件夹为空
- `dcm2niix.exe` 不存在
- `dcmdjpeg.exe` 不存在
- Docker 未启动
- SynthSeg 镜像不存在
- MATLAB 或 SPM 不可用
- bval/bvec 缺失
- 输出文件没有生成
- 用户取消任务

错误信息要显示在 UI 中，同时写入日志。

## 10. 安全和稳定性

必须做到：

- 命令执行使用 list 参数，不使用 shell 拼接。
- 固定程序路径从配置读取，不让普通用户修改。
- 每个病例独立工作区。
- 默认不覆盖已有病例。
- 删除临时文件前检查路径是否位于 `F:\Desktop\MRI2MR\workspace` 内。
- 任务运行中禁止修改该任务参数。
- 任务失败后保留日志和已生成中间文件。

## 11. 启动脚本

建议新增：

```text
F:\Desktop\MRI2MR\start_webui.bat
```

内容目标：

```bat
@echo off
call D:\anaconda\Scripts\activate.bat BrainAAL
cd /d F:\Desktop\MRI2MR
python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
pause
```

浏览器访问：

```text
http://127.0.0.1:8000
```

## 12. 测试清单

### 12.1 基础测试

- WebUI 能启动。
- 首页能打开。
- 固定程序路径能正确读取。
- 模式下拉框显示完整。
- 切换模式后参数表单正确变化。
- 参数校验生效。

### 12.2 命令生成测试

- 每个模式生成的命令行参数正确。
- 路径带空格时能正常运行。
- 未填写必填项时不启动任务。
- 固定程序路径不会出现在普通用户输入框中。

### 12.3 DICOM 测试

- 3T DICOM 转换成功。
- 5T DTI 勾选 DCMTK 解压后转换成功。
- 输出 `DTI.nii.gz`、`DTI.bval`、`DTI.bvec`。
- 转换完成后自动生成 NIfTI 预览。

### 12.4 SynthSeg 测试

- Docker 可用性检测正确。
- SynthSeg 使用 CPU 运行。
- 自动带 `--parc`、`--robust`、`--cpu`。
- 输出 `T1_synthseg.nii`。
- 完成后自动显示标签图预览。

### 12.5 模型测试

- DK 脑区模型生成 `.glb`。
- 脑叶模型生成 `.glb`。
- 动脉模型生成 `.glb`。
- 纤维束模型生成 `.glb`。
- GLB 自动出现在预览窗口。

### 12.6 日志和取消测试

- 日志实时滚动。
- 任务失败时显示错误。
- 用户取消任务后进程退出。
- 取消后状态显示为 `cancelled`。

## 13. 第一版交付标准

第一版完成即可认为可用：

- 可以启动本地 WebUI。
- 可以选择 DICOM 或 NIfTI 输入。
- 可以选择至少以下模式运行：
  - DICOM 转换
  - SynthSeg 分割
  - DK 脑区模型
  - 动脉模型
  - 普通纤维束
- 可以实时查看日志。
- 可以自动预览 NIfTI 中间结果。
- 可以自动预览 GLB 最终模型。
- 输出文件按病例保存。
- 程序路径不需要用户填写。

## 14. 第二版扩展

第二版可以增加：

- 一键流水线，例如 DICOM -> SynthSeg -> SPM -> 模型生成。
- 病例历史管理。
- 参数预设。
- 多模型同时预览。
- 标签图透明度调节。
- NIfTI 切片位置滑块。
- 模型截图导出。
- 运行报告导出。
- 简单权限控制。

