param(
    [string]$OutputDir = "F:\Desktop\MRI2MR-core",
    [string]$CondaEnvPath = "D:\anaconda\envs\BrainAAL",
    [string]$CondaPackArchive = "",
    [string]$CondaCommand = "conda",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutputPath = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir
} else {
    Join-Path $ProjectRoot $OutputDir
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
if ($OutputPath.TrimEnd("\") -ieq $ProjectRoot.TrimEnd("\")) {
    throw "OutputDir must not be the project root."
}

$BuildDir = Join-Path $ProjectRoot "dist\_build"
$PythonTarget = Join-Path $OutputPath "runtime\python\BrainAAL"

function Write-Utf8NoBom {
    param([string]$Path, [string[]]$Lines)
    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $Lines, $Encoding)
}

function Copy-Tree {
    param([string]$Name)
    $Source = Join-Path $ProjectRoot $Name
    $Target = Join-Path $OutputPath $Name
    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }
    $RobocopyArgs = @(
        $Source,
        $Target,
        "/E",
        "/R:2",
        "/W:1",
        "/XD",
        "__pycache__",
        ".pytest_cache",
        "/XF",
        "*.pyc*",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NC",
        "/NS",
        "/NP"
    )
    & robocopy @RobocopyArgs | Out-Null
    $RobocopyExit = $LASTEXITCODE
    if ($RobocopyExit -ge 8) {
        throw "robocopy failed for $Name with exit code $RobocopyExit."
    }
    $global:LASTEXITCODE = 0
}

function Remove-GeneratedFiles {
    param([string]$Root, [string]$SkipRoot)
    $ResolvedSkipRoot = $null
    if (Test-Path -LiteralPath $SkipRoot) {
        $ResolvedSkipRoot = (Resolve-Path -LiteralPath $SkipRoot).Path
    }

    Get-ChildItem -LiteralPath $Root -Recurse -Force -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -in @("__pycache__", ".pytest_cache") -and
            (-not $ResolvedSkipRoot -or -not $_.FullName.StartsWith($ResolvedSkipRoot, [System.StringComparison]::OrdinalIgnoreCase))
        } |
        ForEach-Object {
            try {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
            } catch {
                Write-Warning "Could not remove generated directory: $($_.FullName)"
            }
        }

    Get-ChildItem -LiteralPath $Root -Recurse -Force -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like "*.pyc*" -and
            (-not $ResolvedSkipRoot -or -not $_.FullName.StartsWith($ResolvedSkipRoot, [System.StringComparison]::OrdinalIgnoreCase))
        } |
        ForEach-Object {
            try {
                Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
            } catch {
                Write-Warning "Could not remove generated file: $($_.FullName)"
            }
        }
}

function Get-FolderSizeBytes {
    param([string]$Root)
    if (-not (Test-Path -LiteralPath $Root)) {
        return 0
    }
    return (Get-ChildItem -LiteralPath $Root -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
}

function Expand-CondaPackArchive {
    param([string]$Archive, [string]$Destination)
    if ($Archive.ToLowerInvariant().EndsWith(".zip")) {
        Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
        return
    }

    $ExtractorPython = Join-Path $CondaEnvPath "python.exe"
    if (-not (Test-Path -LiteralPath $ExtractorPython)) {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($PythonCommand) {
            $ExtractorPython = $PythonCommand.Source
        }
    }

    if (Test-Path -LiteralPath $ExtractorPython) {
        $ExtractorScript = Join-Path $BuildDir "extract_conda_pack.py"
        if (-not (Test-Path -LiteralPath $ExtractorScript)) {
            $ExtractorCode = @'
import os
import shutil
import sys
import tarfile

archive = sys.argv[1]
destination = os.path.abspath(sys.argv[2])
os.makedirs(destination, exist_ok=True)

with tarfile.open(archive, "r:*") as tf:
    for member in tf:
        target = os.path.abspath(os.path.join(destination, member.name))
        if not (target == destination or target.startswith(destination + os.sep)):
            print(f"warning: skipped unsafe path {member.name}", file=sys.stderr)
            continue
        try:
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            if member.issym() or member.islnk():
                link_target = os.path.abspath(os.path.join(destination, member.linkname))
                if os.path.exists(target):
                    continue
                if os.path.exists(link_target):
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    try:
                        os.link(link_target, target)
                    except OSError:
                        shutil.copy2(link_target, target)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tf.extract(member, destination)
        except (FileExistsError, PermissionError):
            if not os.path.exists(target):
                raise
            print(f"warning: kept existing {member.name}", file=sys.stderr)

python_exe = os.path.join(destination, "python.exe")
if not os.path.exists(python_exe):
    raise SystemExit(f"python.exe was not extracted to {python_exe}")
'@
            Write-Utf8NoBom $ExtractorScript @($ExtractorCode)
        }
        & $ExtractorPython -B $ExtractorScript $Archive $Destination
        if ($LASTEXITCODE -ne 0) {
            throw "Could not extract Python environment archive with Python tarfile: $Archive"
        }
        return
    }

    tar -xzf $Archive -C $Destination
    if ($LASTEXITCODE -ne 0 -and -not (Test-Path -LiteralPath (Join-Path $Destination "python.exe"))) {
        throw "Could not extract Python environment archive: $Archive"
    }
}

if ($Clean -and (Test-Path -LiteralPath $OutputPath)) {
    Remove-Item -LiteralPath $OutputPath -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

foreach ($Name in @(
    "app",
    "config",
    "scripts",
    "template",
    "tools",
    "dcm2niix_win",
    "dcmtk-3.7.0-win64-dynamic",
    "spm"
)) {
    Copy-Tree $Name
}

foreach ($File in @(
    "requirements-webui.txt",
    "README_USER_GUIDE.md",
    "README_WEBUI_USAGE_V1.md",
    "README_WEBUI_TASKS.md",
    "README_WEBUI_OPTIMIZATION_V2.md",
    "README_WEBUI_OPTIMIZATION_V3.md",
    "README_WEBUI_OPTIMIZATION_V4.md"
)) {
    $Source = Join-Path $ProjectRoot $File
    if (Test-Path -LiteralPath $Source) {
        Copy-Item -LiteralPath $Source -Destination (Join-Path $OutputPath $File) -Force
    }
}

New-Item -ItemType Directory -Force -Path (Join-Path $OutputPath "workspace") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutputPath "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutputPath "runtime") | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $PythonTarget "python.exe"))) {
    New-Item -ItemType Directory -Force -Path $PythonTarget | Out-Null
    $Archive = $CondaPackArchive
    if (-not $Archive) {
        $Archive = Join-Path $BuildDir "BrainAAL.tar.gz"
        if (-not (Test-Path -LiteralPath $Archive)) {
            & $CondaCommand pack -p $CondaEnvPath -o $Archive --force --ignore-missing-files
        }
    }
    if (-not (Test-Path -LiteralPath $Archive)) {
        throw "Python environment archive not found: $Archive"
    }
    Expand-CondaPackArchive $Archive $PythonTarget
}

$CoreConfig = [ordered]@{
    schema_version = 2
    MRI2MR_ROOT = "."
    MAIN_SCRIPT = "scripts\Main_cmd.py"
    SPM_SCRIPT = "scripts\run_spm_segmentation.m"
    DCM2NIIX_EXE = "dcm2niix_win\dcm2niix.exe"
    DCMTK_DCMDJPEG_EXE = "dcmtk-3.7.0-win64-dynamic\dcmtk-3.7.0-win64-dynamic\bin\dcmdjpeg.exe"
    SPM_DIR = "spm"
    SPM_BACKEND = "matlab_cli"
    MATLAB_EXE = "matlab"
    MCR_HOME = ""
    SPM_STANDALONE_DIR = ""
    SPM_STANDALONE_EXE = ""
    SPM_COMPILED_EXE = ""
    SYNTHSEG_DOCKER_IMAGE = "pwesp/synthseg:py38"
    PYTHON_EXE = "runtime\python\BrainAAL\python.exe"
    workspace_root = "workspace"
    template_dir = "template"
    default_roi_file = "template\ROI_ED_Filter.nii.gz"
    resource_source_root = "."
    resource_sources = [ordered]@{
        "DK_Regions.txt" = "template\DK_Regions.txt"
        "DK_Lobes.txt" = "template\DK_Lobes.txt"
        "ROI_ED_Filter.nii.gz" = "template\ROI_ED_Filter.nii.gz"
    }
    docker_exe = "docker"
    conda_activate_bat = ""
    conda_env_name = "BrainAAL"
    host = "127.0.0.1"
    port = 8000
    log_retention_days = 30
    allow_overwrite = $false
    max_concurrent_jobs = 1
    case_id_datetime_format = "%Y%m%d_%H%M%S"
    patient_workspace_subdirs = @("patient_input", "SynthSeg_result", "model_output", "temp", "logs", "previews")
    default_command_dirs = [ordered]@{
        base_data_dir = "{patient_workspace}"
        patient_data_dir = "{patient_workspace}\patient_input"
        synthseg_data_dir = "{patient_workspace}\SynthSeg_result"
        output_dir = "{patient_workspace}\model_output"
        dicom_temp_dir = "{patient_workspace}\temp\dicom2niix_output"
        dicom_decompress_dir = "{patient_workspace}\temp\dicom_dcmtk_decompressed"
        template_dir = "template"
    }
    status_values = @("pending", "running", "success", "failed", "cancelled")
    preview_extensions = @(".nii", ".nii.gz", ".png", ".jpg", ".jpeg", ".glb")
}
Write-Utf8NoBom (Join-Path $OutputPath "config\app_settings.json") @($CoreConfig | ConvertTo-Json -Depth 8)

$StartScript = @'
@echo off
setlocal

cd /d "%~dp0"

set PYTHONDONTWRITEBYTECODE=1
set PYTHONNOUSERSITE=1
set MRI2MR_CORE_ROOT=%~dp0
set PYTHON_EXE=%~dp0runtime\python\BrainAAL\python.exe
set WEBUI_URL=http://127.0.0.1:8000/

if not exist "%PYTHON_EXE%" (
  echo Portable Python not found:
  echo   %PYTHON_EXE%
  pause
  exit /b 1
)

if "%MATLAB_EXE%"=="" (
  for %%M in (matlab.exe) do set MATLAB_EXE=%%~$PATH:M
)
if "%MATLAB_EXE%"=="" if exist "D:\Matlab\bin\matlab.exe" set MATLAB_EXE=D:\Matlab\bin\matlab.exe
if "%MATLAB_EXE%"=="" (
  for /d %%D in ("C:\Program Files\MATLAB\R*") do if exist "%%~fD\bin\matlab.exe" set MATLAB_EXE=%%~fD\bin\matlab.exe
)

if "%MATLAB_EXE%"=="" (
  echo MATLAB was not found on PATH or in common install locations.
  echo Edit config\app_settings.json and set MATLAB_EXE to your matlab.exe path.
  pause
  exit /b 1
)

docker version >nul 2>nul
if errorlevel 1 (
  echo Docker is not available. Please start Docker Desktop before running SynthSeg modes.
)

if exist "%~dp0runtime\python\BrainAAL\Scripts\conda-unpack.exe" (
  "%~dp0runtime\python\BrainAAL\Scripts\conda-unpack.exe"
)

start "" "%WEBUI_URL%"
"%PYTHON_EXE%" -B -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000

pause
'@
Write-Utf8NoBom (Join-Path $OutputPath "start_core.bat") @($StartScript)

$Readme = @(
    "# MRI2MR Core",
    "",
    "This package is for users who already have MATLAB and Docker, but do not have the MRI2MR Python environment.",
    "",
    "Start:",
    "1. Start Docker Desktop.",
    "2. Double-click start_core.bat.",
    "",
    "Bundled:",
    "- Portable Python: runtime\python\BrainAAL\python.exe",
    "- MRI2MR WebUI and processing scripts",
    "- SPM source folder: spm",
    "- DICOM tools: dcm2niix_win and dcmtk-3.7.0-win64-dynamic",
    "",
    "Not bundled:",
    "- MATLAB Runtime",
    "- MATLAB Runtime installer",
    "- SPM compiled executable",
    "",
    "SPM uses full MATLAB through config\app_settings.json:",
    "- SPM_BACKEND = matlab_cli",
    "- MATLAB_EXE = matlab",
    "",
    "If MATLAB is not on PATH, edit MATLAB_EXE in config\app_settings.json or set the MATLAB_EXE environment variable before launching.",
    "SynthSeg still uses Docker image pwesp/synthseg:py38."
)
Write-Utf8NoBom (Join-Path $OutputPath "README_CORE.md") $Readme

Remove-GeneratedFiles $OutputPath $PythonTarget

$ReportPath = Join-Path $OutputPath "PACKING_REPORT_CORE.txt"
$Checks = [ordered]@{
    "Core root" = $OutputPath
    "Python exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "runtime\python\BrainAAL\python.exe"))
    "dcm2niix exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "dcm2niix_win\dcm2niix.exe"))
    "dcmdjpeg exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "dcmtk-3.7.0-win64-dynamic\dcmtk-3.7.0-win64-dynamic\bin\dcmdjpeg.exe"))
    "SPM dir exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "spm"))
    "MATLAB Runtime excluded" = (-not (Test-Path -LiteralPath (Join-Path $OutputPath "runtime\matlab_runtime")))
    "MATLAB Runtime installer excluded" = (-not (Test-Path -LiteralPath (Join-Path $OutputPath "runtime\matlab_runtime_installer")))
    "SPM compiled excluded" = (-not (Test-Path -LiteralPath (Join-Path $OutputPath "runtime\spm_compiled")))
    "Three.js local assets exist" = (Test-Path -LiteralPath (Join-Path $OutputPath "app\static\vendor\three\build\three.module.js"))
    "Folder size bytes" = (Get-FolderSizeBytes $OutputPath)
}

$Lines = @(
    "MRI2MR core packing report",
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    ""
)
foreach ($Item in $Checks.GetEnumerator()) {
    $Lines += ("{0}: {1}" -f $Item.Key, $Item.Value)
}
$Lines += ""
$Lines += "Notes:"
$Lines += "- This core package intentionally excludes MATLAB Runtime and SPM compiled runtime files."
$Lines += "- SPM segmentation is configured for full MATLAB through --spm-backend=matlab_cli."
$Lines += "- Docker is required for SynthSeg modes."
Write-Utf8NoBom $ReportPath $Lines

Write-Host "MRI2MR core package created at: $OutputPath"
Write-Host "Report: $ReportPath"
