# MRI2MR WebUI 用户使用说明

本文档描述 MRI2MR WebUI 的预期使用方式。WebUI 用来控制 MRI2MR 的 DICOM 转换、SynthSeg 分割、SPM 分割和模型生成流程。

## 1. 软件入口

WebUI 安装在：

```text
F:\Desktop\MRI2MR
```

启动方式：

1. 双击 `start_webui.bat`。
2. 等待命令行窗口显示服务已启动。
3. 浏览器自动打开，或手动访问：

```text
http://127.0.0.1:8000
```

如果浏览器没有自动打开，可复制上面的地址到浏览器地址栏。

## 2. 用户需要准备的数据

WebUI 支持两类输入：

### 2.1 DICOM 数据

适用于：

- 原始 3T DICOM 数据
- 原始 5T DICOM 数据
- 5T DTI 纤维束数据

用户需要选择 DICOM 文件夹。

### 2.2 NIfTI 数据

适用于已经转换好的文件：

```text
.nii
.nii.gz
```

常见输入包括：

- T1.nii
- MRA.nii
- MRV.nii
- DTI.nii.gz
- SynthSeg 标签图
- SPM 灰质或白质分割结果

## 3. 用户不需要填写的内容

以下程序路径由系统固定管理，普通用户不需要填写：

```text
dcm2niix.exe
dcmdjpeg.exe
Main_cmd.py
SPM 路径
SynthSeg Docker 镜像
Python 环境
```

如果这些路径有变化，应由管理员修改配置文件，不在普通使用界面中修改。

## 4. 主界面说明

WebUI 主界面分为几个区域：

```text
左侧：输入数据和模式选择
中间：结果预览窗口
右侧：输出文件和中间结果
底部：运行日志
顶部：运行、取消、任务状态
```

## 5. 基本使用流程

通用流程如下：

1. 输入病例名。
2. 选择输入类型：DICOM 或 NIfTI。
3. 选择输入文件或文件夹。
4. 从下拉框选择处理模式。
5. 填写该模式需要的参数。
6. 点击“运行”。
7. 查看底部实时日志。
8. 等待任务完成。
9. 中间预览窗口自动显示结果。
10. 需要时在右侧选择查看中间结果。

## 6. 处理模式说明

### 6.1 DICOM 转换

用于把原始 DICOM 转成 NIfTI。

输入：

- DICOM 文件夹

可选项：

- 5T DTI 数据需要勾选“启用 DCMTK 解压”。

输出：

```text
T1.nii
MRA.nii
MRV.nii
DTI.nii.gz
DTI.bval
DTI.bvec
```

任务完成后，WebUI 会自动预览转换出的 NIfTI 图像。

### 6.2 SynthSeg 分割

用于生成脑结构分割标签图。

输入：

- T1 NIfTI 文件

系统会自动使用：

```text
--parc
--robust
--cpu
```

输出：

```text
T1_synthseg.nii
```

任务完成后，WebUI 会自动显示标签图预览。若有原始 T1，预览中可以显示叠加效果。

### 6.3 SPM 分割

用于生成灰质、白质等组织分割结果。

输入：

- T1 NIfTI 文件

输出通常包括：

```text
c1T1.nii
c2T1.nii
```

其中 `c2T1.nii` 常用于纤维束追踪的白质 mask。

### 6.4 DK 脑区模型

用于根据 SynthSeg 标签图生成 DK 脑区模型。

输入：

- T1 NIfTI 文件
- SynthSeg 标签图

输出：

```text
多个 .glb 模型文件
```

完成后，模型会自动出现在预览窗口。

### 6.5 脑叶模型

用于根据 DK 脑区合成脑叶模型。

输入：

- T1 NIfTI 文件
- SynthSeg 标签图

输出：

```text
frontal.glb
temporal.glb
parietal.glb
occipital.glb
其他脑叶模型
```

### 6.6 脑半球模型

用于生成左、右脑半球模型。

输入：

- T1 NIfTI 文件
- SynthSeg 标签图

输出：

```text
left.glb
right.glb
```

### 6.7 脑室模型

用于生成脑室模型。

输入：

- T1 NIfTI 文件
- robust SynthSeg 标签图

输出：

```text
ventricle.glb
```

### 6.8 其他组织模型

用于生成 SynthSeg 分割中的其他组织结构。

输入：

- robust SynthSeg 标签图

输出：

```text
多个 .glb 模型文件
```

### 6.9 动脉模型

用于从 MRA 图像生成动脉模型。

输入：

- MRA NIfTI 文件

常用参数：

- 血管阈值
- 最小连通区域大小
- 减面比例

输出：

```text
vessel.glb
```

### 6.10 静脉模型

用于从 MRV 图像生成静脉模型。

输入：

- MRV NIfTI 文件

常用参数：

- 强种子百分位
- 弱种子百分位
- 生长容差
- 后处理最小大小

输出：

```text
vessel_vein.glb
```

### 6.11 普通纤维束

用于生成 DTI 纤维束模型。

输入：

- DTI.nii.gz
- DTI.bval
- DTI.bvec
- 白质 mask，例如 c2T1.nii

常用参数：

- GFA 阈值
- 停止阈值
- 生长步长
- 最大角度
- 种子密度

输出：

```text
fiber.glb
```

### 6.12 脑区间纤维连接

用于生成脑区之间的纤维束连接。

输入：

- DTI.nii.gz
- DTI.bval
- DTI.bvec
- GWI atlas
- 白质 mask

输出：

```text
多个脑区连接 .glb 模型文件
```

### 6.13 DKI 纤维束

用于多 b 值 DKI 数据的纤维追踪。

输入：

- DKI NIfTI 文件
- bval
- bvec
- 白质 mask

输出：

```text
DKI 纤维束 .glb 模型
```

## 7. 参数填写规则

每个模式只显示该模式需要的参数。

参数分为：

- 必填参数
- 常用参数
- 高级参数

普通用户建议只修改常用参数。高级参数用于精细调试，例如：

- 平滑迭代次数
- marching cubes 阈值
- 模型减面比例
- 纤维束最大角度
- 纤维束停止阈值

## 8. 自动预览说明

WebUI 会自动预览两类结果。

### 8.1 图像预览

适用于：

- T1
- MRA
- MRV
- DTI b0
- SynthSeg 标签图
- SPM 分割结果
- GWI atlas

预览会显示：

- 轴位
- 冠状位
- 矢状位

对于标签图，WebUI 可以显示彩色叠加预览。

### 8.2 模型预览

适用于：

```text
.glb
```

用户可以：

- 旋转模型
- 缩放模型
- 平移模型
- 切换不同模型
- 显示或隐藏部分模型
- 重置视角

任务完成后，最新结果会自动加载到中间预览窗口。

## 9. 中间结果查看

右侧会显示中间结果列表。

用户可以查看：

- DICOM 转换出的 NIfTI
- SynthSeg 标签图
- SPM 灰质和白质图
- 血管分割中间图
- GWI atlas
- 已生成的 GLB 模型
- 日志文件

点击任意中间结果后，预览窗口自动切换，不需要用户手动打开文件。

## 10. 输出位置

每个病例会自动创建独立工作区：

```text
F:\Desktop\MRI2MR\workspace\<病例ID>
```

其中包含：

```text
patient_input
SynthSeg_result
model_output
temp
logs
previews
job.json
```

最终模型通常位于：

```text
F:\Desktop\MRI2MR\workspace\<病例ID>\model_output
```

日志通常位于：

```text
F:\Desktop\MRI2MR\workspace\<病例ID>\logs
```

## 11. 任务状态

任务状态包括：

```text
等待中
运行中
成功
失败
已取消
```

如果任务失败，底部日志会显示失败原因。常见原因包括：

- 输入文件不存在
- DICOM 文件夹选择错误
- bval 或 bvec 缺失
- Docker 未启动
- MATLAB 或 SPM 不可用
- 输出目录无权限
- 参数设置不合适导致没有生成模型

## 12. 取消任务

任务运行中可以点击“取消”。

取消后：

- 当前进程会停止。
- 已生成的中间文件会保留。
- 任务状态变为“已取消”。
- 日志仍可查看。

## 13. 推荐工作流

### 13.1 从原始 DICOM 到脑区模型

1. 选择 DICOM 转换。
2. 输入 DICOM 文件夹。
3. 运行并确认生成 T1。
4. 选择 SynthSeg 分割。
5. 输入 T1。
6. 运行并确认生成 `T1_synthseg.nii`。
7. 选择 DK 脑区模型。
8. 运行并查看 GLB 预览。

### 13.2 从 5T DTI 到纤维束模型

1. 选择 DICOM 转换。
2. 输入 5T DTI DICOM 文件夹。
3. 勾选“启用 DCMTK 解压”。
4. 运行并确认生成 `DTI.nii.gz`、`DTI.bval`、`DTI.bvec`。
5. 准备或生成白质 mask。
6. 选择普通纤维束。
7. 填写 DTI、bval、bvec、mask。
8. 运行并查看 GLB 预览。

### 13.3 从 NIfTI 直接生成血管模型

1. 选择 NIfTI 输入。
2. 选择 MRA 或 MRV 文件。
3. 选择动脉模型或静脉模型。
4. 调整阈值参数。
5. 运行并查看模型预览。

## 14. 使用建议

- 每个病例使用清晰病例名。
- 初次处理新设备数据时先用默认参数。
- 血管模型需要根据图像强度微调阈值。
- 纤维束模型参数变化会明显影响模型大小和密度。
- 运行大型 DTI 或 DKI 数据时不要同时启动多个任务。
- SynthSeg 运行前确认 Docker Desktop 已启动。
- SPM 运行前确认 MATLAB 可正常启动。

## 15. 管理员维护

管理员负责：

- 检查固定程序路径。
- 检查 Conda 环境。
- 检查 Docker 镜像。
- 检查 SPM 路径。
- 清理旧病例工作区。
- 备份重要输出模型。

普通用户只需要使用 WebUI 页面，不需要打开命令行。

