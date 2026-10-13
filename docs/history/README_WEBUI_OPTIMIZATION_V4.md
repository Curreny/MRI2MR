# MRI2MR WebUI 第四版优化方案：便携运行包与无完整 MATLAB 依赖

本文档作为第四版优化方案，目标是让 `F:\Desktop\MRI2MR` 可以打包成一个尽量自包含的 Windows 文件夹，使另一台电脑在不安装 Anaconda、不安装完整 MATLAB 的情况下运行 WebUI 和主要处理流程。

第四版不替代第三版已经完成的 DICOM 自动检测、序列路径可手动修改、影像信息备注等能力，而是在“运行环境可迁移”这个层面继续优化。

## 1. 当前问题

当前项目依赖两类外部环境：

- Python 环境：当前配置使用 `D:\anaconda\envs\BrainAAL\python.exe`。
- SPM/MATLAB 环境：当前 SPM 分割代码通过 MATLAB Engine for Python 启动完整 MATLAB。

当前 SPM 调用位于：

```text
scripts\Main_cmd.py
_process_spm_segmentation()
```

现有逻辑是：

```python
import matlab.engine
eng = matlab.engine.start_matlab()
eng.run_spm_segmentation(t1_file, spm_dir, nargout=0)
```

这意味着目标电脑必须安装完整 MATLAB，并且 Python 环境中必须安装 MATLAB Engine for Python。仅把 MATLAB Runtime 复制到项目文件夹里，无法运行这段代码。

## 2. 第四版目标

第四版目标分成三个层次：

1. Python 便携化  
   将当前 `BrainAAL` Python 环境打包到项目目录内，WebUI 启动时使用内置 Python，不再依赖目标电脑的 Anaconda。

2. SPM 无完整 MATLAB 化  
   将 SPM 分割从 `matlab.engine` 改为可在 MATLAB Runtime 下运行的方式。推荐优先支持 SPM standalone 或已编译的 SPM 分割 exe。

3. 配置相对路径化  
   所有关键路径从 `F:\Desktop\MRI2MR`、`D:\anaconda\envs\BrainAAL` 这类绝对路径，改为基于项目根目录解析的相对路径。这样整个文件夹移动到另一台电脑或另一个盘符后仍可运行。

## 3. 关键技术边界

### 3.1 MATLAB Runtime 不是完整 MATLAB

MATLAB Runtime 可以运行由 MATLAB Compiler 编译出的程序，也可以运行 SPM standalone 这类已经编译好的应用。它不能替代完整 MATLAB 来执行 `matlab.engine.start_matlab()`。

因此第四版必须修改代码：

```text
当前：Python -> matlab.engine -> 完整 MATLAB -> run_spm_segmentation.m
目标：Python -> subprocess -> SPM standalone/compiled exe -> MATLAB Runtime
```

### 3.2 不能把完整 MATLAB 当作依赖直接打包

完整 MATLAB 受 MathWorks 授权约束，不适合作为项目目录的一部分分发给用户。第四版应使用 MATLAB Runtime 或让用户使用官方安装包安装 Runtime。

### 3.3 Python 可以打包，但需要修复路径

Python 环境可以用 `conda-pack` 打包。但当前 `config\app_settings.json` 写死了：

```json
"PYTHON_EXE": "D:\\anaconda\\envs\\BrainAAL\\python.exe"
```

第四版需要改为相对路径，例如：

```json
"PYTHON_EXE": "runtime\\python\\BrainAAL\\python.exe"
```

并让后端配置加载器把相对路径解析为项目根目录下的绝对路径。

## 4. 推荐总体方案

推荐采用“便携文件夹”方案，而不是一开始就做安装包。

目标目录结构：

```text
MRI2MR_Portable\
  app\
  config\
  scripts\
  template\
  dcm2niix_win\
  dcmtk-3.7.0-win64-dynamic\
  runtime\
    python\
      BrainAAL\
        python.exe
        Scripts\
        Lib\
        ...
    matlab_runtime\
      R202x\
        ...
    spm_standalone\
      ...
  workspace\
  logs\
  start_portable.bat
  start_portable_debug.bat
  pack_portable.ps1
  README_WEBUI_OPTIMIZATION_V4.md
```

如果 MATLAB Runtime 体积过大，也可以采用半便携方案：

```text
runtime\matlab_runtime_installer\
  MATLAB_Runtime_R202x_win64.exe
```

第一次运行时提示用户安装 Runtime，安装后在配置里保存 `MCR_HOME`。但从用户体验上看，完全便携更好。

## 5. SPM 处理模块改造方案

第四版核心是重构 `_process_spm_segmentation()`。

### 5.1 新增 SPM 后端类型

建议新增配置项：

```json
{
  "SPM_BACKEND": "auto",
  "SPM_DIR": "spm",
  "SPM_SCRIPT": "scripts\\run_spm_segmentation.m",
  "SPM_STANDALONE_DIR": "runtime\\spm_standalone",
  "SPM_STANDALONE_EXE": "runtime\\spm_standalone\\spm12.exe",
  "SPM_COMPILED_EXE": "runtime\\spm_compiled\\run_spm_segmentation.exe",
  "MCR_HOME": "runtime\\matlab_runtime\\R202x"
}
```

`SPM_BACKEND` 可选值：

```text
auto
matlab_engine
spm_standalone
compiled_exe
```

推荐顺序：

```text
compiled_exe -> spm_standalone -> matlab_engine
```

解释：

- `compiled_exe`：最适合固定流程发布。把 `run_spm_segmentation.m` 编译成 exe，目标电脑只需要 MATLAB Runtime。
- `spm_standalone`：适合直接使用官方 SPM standalone，Python 生成 batch，再调用 standalone SPM 执行。
- `matlab_engine`：保留给开发机和兼容旧环境，不作为便携版默认方式。

### 5.2 推荐优先方案：compiled_exe

如果开发机有 MATLAB Compiler 许可证，推荐把 SPM 分割包装为独立 exe。

目标调用方式：

```text
runtime\spm_compiled\run_spm_segmentation.exe <t1_file> <spm_dir>
```

Python 端使用：

```python
subprocess.run(
    [compiled_exe, str(t1_file), str(spm_dir)],
    check=True,
)
```

优点：

- Python 不需要 MATLAB Engine。
- 用户不需要安装完整 MATLAB。
- 入口参数最简单。
- 更容易在日志里捕获 stdout/stderr。

注意：

- 编译工作必须在有 MATLAB Compiler 的机器上完成。
- 编译产物要和 MATLAB Runtime 版本匹配。
- `spm` 目录、`TPM.nii`、MEX 文件等资源必须随包保留，或编译时明确包含。

### 5.3 备选方案：SPM standalone

如果没有 MATLAB Compiler，可以使用 SPM standalone。

目标流程：

1. Python 根据当前 T1 路径生成一个临时 batch 文件，例如：

```text
workspace\<case>\temp\spm_batch\spm_segment_job.m
```

2. Python 调用 SPM standalone，并传入 MATLAB Runtime 路径和 batch。

3. SPM 输出：

```text
patient_input\c1T1.nii
patient_input\c2T1.nii
```

需要注意：

- 当前项目中的 `spm\bin\spm-mcr` 是 bash 脚本，不是 Windows exe。
- Windows 便携版需要实际的 Windows SPM standalone 可执行文件。
- 需要实测 standalone 的命令行参数格式，并把它固化在代码和 README 中。

### 5.4 旧方案保留：matlab_engine

为了不破坏开发机现有流程，可以保留旧实现：

```text
SPM_BACKEND=matlab_engine
```

但便携版默认不应使用它。

## 6. Python 环境打包方案

推荐使用 `conda-pack`。

### 6.1 在开发机安装 conda-pack

```bat
conda activate BrainAAL
conda install -c conda-forge conda-pack
```

或：

```bat
pip install conda-pack
```

### 6.2 打包当前环境

建议输出到项目外临时目录：

```bat
conda pack -n BrainAAL -o F:\Desktop\MRI2MR_build\BrainAAL.tar.gz
```

### 6.3 解压到便携目录

```bat
mkdir F:\Desktop\MRI2MR_Portable\runtime\python\BrainAAL
tar -xzf F:\Desktop\MRI2MR_build\BrainAAL.tar.gz -C F:\Desktop\MRI2MR_Portable\runtime\python\BrainAAL
```

第一次运行前执行：

```bat
runtime\python\BrainAAL\Scripts\conda-unpack.exe
```

如果目标电脑没有 `tar`，可以用 7-Zip 或在 `pack_portable.ps1` 中调用 PowerShell 解压逻辑。

### 6.4 Python 环境必须包含的包

不能只看 `requirements-webui.txt`，因为主程序还依赖医学影像和建模包。需要以当前 `BrainAAL` 环境为准，至少检查：

```text
fastapi
uvicorn
numpy
nibabel
matplotlib
Pillow
dipy
nilearn
scipy
skimage / scikit-image
trimesh
pydicom
requests
```

实际依赖应通过一次完整流程验证，而不是手动猜包。

## 7. 配置相对路径化

当前 `config\app_settings.json` 中大量路径是绝对路径：

```json
"MRI2MR_ROOT": "F:\\Desktop\\MRI2MR",
"MAIN_SCRIPT": "F:\\Desktop\\MRI2MR\\scripts\\Main_cmd.py",
"PYTHON_EXE": "D:\\anaconda\\envs\\BrainAAL\\python.exe"
```

第四版建议改为：

```json
{
  "schema_version": 2,
  "MRI2MR_ROOT": ".",
  "MAIN_SCRIPT": "scripts\\Main_cmd.py",
  "SPM_SCRIPT": "scripts\\run_spm_segmentation.m",
  "DCM2NIIX_EXE": "dcm2niix_win\\dcm2niix.exe",
  "DCMTK_DCMDJPEG_EXE": "dcmtk-3.7.0-win64-dynamic\\dcmtk-3.7.0-win64-dynamic\\bin\\dcmdjpeg.exe",
  "SPM_DIR": "spm",
  "PYTHON_EXE": "runtime\\python\\BrainAAL\\python.exe",
  "WORKSPACE_ROOT": "workspace",
  "TEMPLATE_DIR": "template",
  "SPM_BACKEND": "auto",
  "MCR_HOME": "runtime\\matlab_runtime\\R202x",
  "SPM_STANDALONE_DIR": "runtime\\spm_standalone",
  "SPM_STANDALONE_EXE": "runtime\\spm_standalone\\spm12.exe",
  "SPM_COMPILED_EXE": "runtime\\spm_compiled\\run_spm_segmentation.exe"
}
```

需要修改：

```text
app\backend\config.py
```

建议新增路径解析规则：

- 绝对路径原样使用。
- 相对路径基于 `MRI2MR_ROOT`。
- `MRI2MR_ROOT` 为 `.` 时，解析为当前项目根目录。
- WebUI 启动时将工作目录固定为项目根目录。

## 8. 启动脚本设计

新增：

```text
start_portable.bat
```

建议内容：

```bat
@echo off
setlocal

cd /d "%~dp0"

set PYTHONDONTWRITEBYTECODE=1
set MRI2MR_PORTABLE_ROOT=%~dp0
set MCR_HOME=%~dp0runtime\matlab_runtime\R202x
set SPM_HOME=%~dp0runtime\spm_standalone

set PYTHON_EXE=%~dp0runtime\python\BrainAAL\python.exe

if not exist "%PYTHON_EXE%" (
  echo Portable Python not found: %PYTHON_EXE%
  pause
  exit /b 1
)

if exist "%~dp0runtime\python\BrainAAL\Scripts\conda-unpack.exe" (
  "%~dp0runtime\python\BrainAAL\Scripts\conda-unpack.exe"
)

start "" http://127.0.0.1:8000/
"%PYTHON_EXE%" -B -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000

pause
```

也建议新增：

```text
start_portable_debug.bat
```

区别是不自动打开浏览器，并保留完整控制台日志，便于排查目标电脑问题。

## 9. 打包脚本设计

新增：

```text
tools\pack_portable.ps1
```

职责：

1. 创建输出目录：

```text
dist\MRI2MR_Portable
```

2. 复制项目必要文件：

```text
app
config
scripts
template
dcm2niix_win
dcmtk-3.7.0-win64-dynamic
spm 或 runtime\spm_standalone
requirements-webui.txt
README*.md
start_portable.bat
```

3. 排除大型运行结果和缓存：

```text
workspace\*
__pycache__
.pytest_cache
*.pyc
temp 输出
jobs 输出
previews 输出
model_output 输出
```

4. 解包 Python 环境到：

```text
runtime\python\BrainAAL
```

5. 写入便携版配置：

```text
config\app_settings.json
```

6. 生成打包报告：

```text
dist\MRI2MR_Portable\PACKING_REPORT.txt
```

报告内容包括：

- Python 路径是否存在。
- dcm2niix 是否存在。
- dcmdjpeg 是否存在。
- SPM backend 类型。
- MCR_HOME 是否存在。
- SPM standalone/compiled exe 是否存在。
- 总体文件夹大小。

## 10. 后端代码改造清单

### 10.1 `app\backend\config.py`

新增字段：

```python
spm_backend: str
mcr_home: Path | None
spm_standalone_dir: Path | None
spm_standalone_exe: Path | None
spm_compiled_exe: Path | None
```

新增路径解析 helper：

```python
def _resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else root / path
```

`public_dict()` 中增加：

```text
mcr_home
spm_standalone_exe
spm_compiled_exe
spm_backend
```

方便 WebUI 首页或诊断接口展示当前运行状态。

### 10.2 `app\backend\command_builder.py`

构建命令时追加：

```text
--spm-backend
--mcr-home
--spm-standalone-exe
--spm-compiled-exe
```

保持兼容：

- 如果配置中没有这些字段，仍按旧方式传参。
- 便携版配置中存在这些字段时使用新方式。

### 10.3 `scripts\Main_cmd.py`

新增 CLI 参数：

```python
parser.add_argument("--spm-backend", type=str, default="auto")
parser.add_argument("--mcr-home", type=str, default=None)
parser.add_argument("--spm-standalone-exe", type=str, default=None)
parser.add_argument("--spm-compiled-exe", type=str, default=None)
```

`Config.__init__()` 中保存：

```python
self.SPM_BACKEND = spm_backend
self.MCR_HOME = Path(mcr_home) if mcr_home else None
self.SPM_STANDALONE_EXE = Path(spm_standalone_exe) if spm_standalone_exe else None
self.SPM_COMPILED_EXE = Path(spm_compiled_exe) if spm_compiled_exe else None
```

重构：

```python
def _process_spm_segmentation(self):
    backend = self._resolve_spm_backend()
    if backend == "compiled_exe":
        return self._process_spm_segmentation_compiled()
    if backend == "spm_standalone":
        return self._process_spm_segmentation_standalone()
    if backend == "matlab_engine":
        return self._process_spm_segmentation_matlab_engine()
    raise RuntimeError(...)
```

新增：

```python
def _process_spm_segmentation_compiled(self)
def _process_spm_segmentation_standalone(self)
def _process_spm_segmentation_matlab_engine(self)
def _resolve_spm_backend(self)
def _validate_spm_outputs(self)
```

`_validate_spm_outputs()` 必须确认：

```text
patient_input\c1T1.nii
patient_input\c2T1.nii
```

存在，否则给出清晰错误。

## 11. SPM batch 生成方案

当前 `scripts\run_spm_segmentation.m` 接收：

```text
t1_file
spm_dir
```

如果使用 standalone，建议新增模板：

```text
scripts\spm_segment_batch_template.m
```

模板中使用占位符：

```text
{{T1_FILE}}
{{SPM_DIR}}
{{TPM_FILE}}
```

运行前生成实际 batch：

```text
workspace\<case>\temp\spm_batch\spm_segment_job.m
```

这样每个病例的 batch 可保存到日志目录，便于追溯。

## 12. WebUI 配置界面增强

第四版建议在 WebUI 增加一个“运行环境诊断”区域或 API：

```text
GET /api/runtime-status
```

返回：

```json
{
  "python": {
    "configured": "...",
    "effective": "...",
    "exists": true
  },
  "spm": {
    "backend": "compiled_exe",
    "mcr_home": "...",
    "compiled_exe": "...",
    "standalone_exe": "...",
    "ready": true
  },
  "tools": {
    "dcm2niix": true,
    "dcmtk_dcmdjpeg": true,
    "docker": false
  }
}
```

这样用户在另一台电脑上第一次打开 WebUI 时，可以直接看到缺什么。

## 13. 验证清单

在开发机上验证：

```bat
runtime\python\BrainAAL\python.exe -B tools\validate_webui_v2_config.py
runtime\python\BrainAAL\python.exe -B tools\validate_webui_v3_config.py
runtime\python\BrainAAL\python.exe -B -c "import nibabel, dipy, nilearn, pydicom; print('OK')"
```

在干净 Windows 电脑上验证：

1. 电脑没有安装 Anaconda。
2. 电脑没有安装完整 MATLAB。
3. 双击：

```text
start_portable.bat
```

4. 打开：

```text
http://127.0.0.1:8000/
```

5. WebUI 配置路径检查全部通过。
6. DICOM 转换模式成功输出：

```text
T1.nii
MRA.nii
MRV.nii
DTI.nii.gz
DTI.bval
DTI.bvec
```

7. SPM 分割模式成功输出：

```text
c1T1.nii
c2T1.nii
```

8. 后续灰白质、血管、纤维束、GLB 生成流程可读取这些输出。

## 14. 风险与注意事项

### 14.1 MATLAB Runtime 版本匹配

编译 exe 或 SPM standalone 需要匹配对应的 MATLAB Runtime 版本。版本不匹配时，目标电脑可能启动失败或出现 MCR 初始化错误。

### 14.2 SPM standalone Windows 产物缺失

当前项目中的 `spm` 目录包含 SPM 源码和 `spm\bin\spm-mcr`，但这是 bash 脚本，不是 Windows standalone exe。第四版需要补齐 Windows 可运行的 SPM standalone 或自行编译 exe。

### 14.3 SynthSeg 仍依赖 Docker

当前配置中：

```json
"SYNTHSEG_DOCKER_IMAGE": "pwesp/synthseg:py38"
```

如果目标电脑也要运行 SynthSeg，那么 Docker Desktop 和镜像仍是额外依赖。第四版主要解决 Python 和 SPM/MATLAB 便携化；是否进一步打包 SynthSeg 镜像，需要单独作为第五版或第四版扩展项处理。

可选方向：

- 保留 Docker 依赖，启动前检查 Docker 是否可用。
- 导出 Docker 镜像为 `.tar`，在目标电脑导入。
- 改用非 Docker 的 SynthSeg/FastSurfer/SynthSeg 本地环境，但这会显著增加 Python 环境复杂度。

### 14.4 包体积会很大

预估：

```text
Python conda 环境：数 GB
MATLAB Runtime：数 GB
SPM：数百 MB 到数 GB
项目资源和模板：数百 MB
```

最终便携包可能达到 5-10 GB 或更大。

### 14.5 授权

需要分别确认：

- MATLAB Runtime 再分发条款。
- MATLAB Compiler 编译产物分发条款。
- SPM 许可证。
- dcm2niix、DCMTK 许可证。
- Python/Conda 包许可证。

本文档是工程实施方案，不替代法律授权审核。

## 15. 实施步骤建议

### 阶段 1：路径相对化

目标：

- `config\app_settings.json` 可以使用相对路径。
- `app\backend\config.py` 正确解析相对路径。
- 现有 WebUI 功能不回退。

验收：

```text
把 MRI2MR 文件夹复制到另一个路径，修改最少配置后仍能启动 WebUI。
```

### 阶段 2：Python 便携化

目标：

- 使用 `conda-pack` 打包 `BrainAAL`。
- WebUI 使用 `runtime\python\BrainAAL\python.exe`。

验收：

```text
在没有 Anaconda 的电脑上启动 WebUI。
```

### 阶段 3：SPM 后端抽象

目标：

- `_process_spm_segmentation()` 支持 `matlab_engine`、`compiled_exe`、`spm_standalone`。
- 默认便携版不使用 `matlab.engine`。

验收：

```text
SPM 分割可在不安装完整 MATLAB 的环境中输出 c1T1.nii 和 c2T1.nii。
```

### 阶段 4：打包脚本

目标：

- 一条命令生成 `dist\MRI2MR_Portable`。
- 自动排除 workspace 运行结果和缓存。
- 自动生成打包报告。

验收：

```text
dist\MRI2MR_Portable 可以复制到另一台电脑运行。
```

### 阶段 5：干净机器验收

目标：

- 在没有 Anaconda、没有完整 MATLAB 的 Windows 电脑上跑通关键流程。

验收病例：

```text
DICOM 转换 -> SPM 分割 -> 灰白质模型生成
```

## 16. 第四版完成标准

第四版完成时，应满足：

- 用户无需安装 Anaconda。
- 用户无需安装完整 MATLAB。
- 双击 `start_portable.bat` 可启动 WebUI。
- WebUI 能显示 Python、SPM、MCR、dcm2niix、DCMTK 的就绪状态。
- DICOM 转换功能保持第三版能力。
- SPM 分割能稳定输出 `c1T1.nii`、`c2T1.nii`。
- 所有关键路径可以随项目文件夹移动。
- README 中明确说明包体积、授权和 Docker/SynthSeg 的额外依赖边界。

## 17. 官方参考

- MATLAB Runtime: https://www.mathworks.com/products/compiler/matlab-runtime.html
- MATLAB Compiler: https://www.mathworks.com/products/compiler.html
- SPM12: https://www.fil.ion.ucl.ac.uk/spm/software/spm12/
- conda-pack: https://conda.github.io/conda-pack/
