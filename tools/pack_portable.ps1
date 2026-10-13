param(
    [string]$OutputDir = "dist\MRI2MR_Portable",
    [string]$CondaEnvPath = "D:\anaconda\envs\BrainAAL",
    [string]$CondaPackArchive = "",
    [string]$CondaCommand = "conda",
    [string]$MatlabRuntimeSource = "",
    [string]$MatlabRuntimeInstaller = "",
    [string]$SpmCompiledExe = "",
    [switch]$IncludeMatlabRuntime,
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

function Copy-Tree {
    param([string]$Name)
    $Source = Join-Path $ProjectRoot $Name
    $Target = Join-Path $OutputPath $Name
    if (Test-Path -LiteralPath $Source) {
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
}

function Test-IsUnderPath {
    param([string]$Path, [string[]]$Roots)
    foreach ($Item in $Roots) {
        if ($Item -and $Path.StartsWith($Item, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Remove-GeneratedFiles {
    param([string]$Root, [string[]]$SkipRoots = @())
    $ResolvedSkipRoots = @()
    foreach ($SkipRoot in $SkipRoots) {
        if (Test-Path -LiteralPath $SkipRoot) {
            $ResolvedSkipRoots += (Resolve-Path -LiteralPath $SkipRoot).Path
        }
    }
    Get-ChildItem -LiteralPath $Root -Recurse -Force -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("__pycache__", ".pytest_cache") -and -not (Test-IsUnderPath $_.FullName $ResolvedSkipRoots) } |
        ForEach-Object {
            $GeneratedDir = $_.FullName
            try {
                Remove-Item -LiteralPath $GeneratedDir -Recurse -Force -ErrorAction Stop
            } catch {
                Write-Warning "Could not remove generated directory: $GeneratedDir"
            }
        }
    Get-ChildItem -LiteralPath $Root -Recurse -Force -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "*.pyc*" -and -not (Test-IsUnderPath $_.FullName $ResolvedSkipRoots) } |
        ForEach-Object {
            $GeneratedFile = $_.FullName
            try {
                Remove-Item -LiteralPath $GeneratedFile -Force -ErrorAction Stop
            } catch {
                Write-Warning "Could not remove generated file: $GeneratedFile"
            }
        }
}

function Get-FolderSizeBytes {
    param([string]$Root)
    if (-not (Test-Path -LiteralPath $Root)) { return 0 }
    return (Get-ChildItem -LiteralPath $Root -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
}

function Write-Utf8NoBom {
    param([string]$Path, [string[]]$Lines)
    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $Lines, $Encoding)
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
    "start_portable.bat",
    "start_portable_debug.bat",
    "README_USER_GUIDE.md"
)) {
    $Source = Join-Path $ProjectRoot $File
    if (Test-Path -LiteralPath $Source) {
        Copy-Item -LiteralPath $Source -Destination (Join-Path $OutputPath $File) -Force
    }
}

New-Item -ItemType Directory -Force -Path (Join-Path $OutputPath "workspace") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutputPath "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutputPath "runtime") | Out-Null

if ($SpmCompiledExe) {
    $CompiledTargetDir = Join-Path $OutputPath "runtime\spm_compiled"
    New-Item -ItemType Directory -Force -Path $CompiledTargetDir | Out-Null
    Copy-Item -LiteralPath $SpmCompiledExe -Destination (Join-Path $CompiledTargetDir "run_spm_segmentation.exe") -Force
}

$SourceCompiledDir = Join-Path $ProjectRoot "runtime\spm_compiled"
if (Test-Path -LiteralPath $SourceCompiledDir) {
    New-Item -ItemType Directory -Force -Path (Join-Path $OutputPath "runtime") | Out-Null
    Copy-Item -LiteralPath $SourceCompiledDir -Destination (Join-Path $OutputPath "runtime") -Recurse -Force
}

$SourceStandaloneDir = Join-Path $ProjectRoot "runtime\spm_standalone"
if (Test-Path -LiteralPath $SourceStandaloneDir) {
    Copy-Item -LiteralPath $SourceStandaloneDir -Destination (Join-Path $OutputPath "runtime") -Recurse -Force
}

if ($IncludeMatlabRuntime) {
    $RuntimeSource = $MatlabRuntimeSource
    if (-not $RuntimeSource) {
        throw "Use -MatlabRuntimeSource to point to an installed MATLAB Runtime folder. Do not package the full MATLAB installation."
    }
    if (Test-Path -LiteralPath $RuntimeSource) {
        $RuntimeTarget = Join-Path $OutputPath "runtime\matlab_runtime\R2025b"
        New-Item -ItemType Directory -Force -Path (Split-Path $RuntimeTarget -Parent) | Out-Null
        Copy-Item -LiteralPath $RuntimeSource -Destination $RuntimeTarget -Recurse -Force
    }
}

if ($MatlabRuntimeInstaller) {
    if (-not (Test-Path -LiteralPath $MatlabRuntimeInstaller)) {
        throw "MATLAB Runtime installer not found: $MatlabRuntimeInstaller"
    }
    $InstallerTargetDir = Join-Path $OutputPath "runtime\matlab_runtime_installer"
    if (Test-Path -LiteralPath $InstallerTargetDir) {
        Remove-Item -LiteralPath $InstallerTargetDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $InstallerTargetDir | Out-Null
    $InstallerItem = Get-Item -LiteralPath $MatlabRuntimeInstaller
    if ($InstallerItem.PSIsContainer) {
        robocopy $InstallerItem.FullName $InstallerTargetDir /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
        $RobocopyExit = $LASTEXITCODE
        if ($RobocopyExit -ge 8) {
            throw "robocopy failed for MATLAB Runtime installer with exit code $RobocopyExit."
        }
        $global:LASTEXITCODE = 0
    } else {
        Copy-Item -LiteralPath $InstallerItem.FullName -Destination (Join-Path $InstallerTargetDir "MATLAB_Runtime_R2025b_win64.exe") -Force
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $PythonTarget "python.exe"))) {
    New-Item -ItemType Directory -Force -Path $PythonTarget | Out-Null
    $Archive = $CondaPackArchive
    if (-not $Archive) {
        $Archive = Join-Path $BuildDir "BrainAAL.tar.gz"
        if (-not (Test-Path -LiteralPath $Archive)) {
            & $CondaCommand pack -p $CondaEnvPath -o $Archive --force --ignore-missing-files
        }
    }
    if (Test-Path -LiteralPath $Archive) {
        Expand-CondaPackArchive $Archive $PythonTarget
    }
}

$PortableConfig = [ordered]@{
    schema_version = 2
    MRI2MR_ROOT = "."
    MAIN_SCRIPT = "scripts\Main_cmd.py"
    SPM_SCRIPT = "scripts\run_spm_segmentation.m"
    DCM2NIIX_EXE = "dcm2niix_win\dcm2niix.exe"
    DCMTK_DCMDJPEG_EXE = "dcmtk-3.7.0-win64-dynamic\dcmtk-3.7.0-win64-dynamic\bin\dcmdjpeg.exe"
    SPM_DIR = "spm"
    SPM_BACKEND = "auto"
    MCR_HOME = "runtime\matlab_runtime\R2025b"
    SPM_STANDALONE_DIR = "runtime\spm_standalone"
    SPM_STANDALONE_EXE = "runtime\spm_standalone\spm12.exe"
    SPM_COMPILED_EXE = "runtime\spm_compiled\run_spm_segmentation.exe"
    SYNTHSEG_DOCKER_IMAGE = "pwesp/synthseg:py38"
    PYTHON_EXE = "runtime\python\BrainAAL\python.exe"
    workspace_root = "workspace"
    template_dir = "template"
    default_roi_file = "template\ROI_ED_Filter.nii.gz"
    docker_exe = "docker"
    host = "127.0.0.1"
    port = 8000
    log_retention_days = 30
    allow_overwrite = $false
    max_concurrent_jobs = 1
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
$PortableConfigJson = $PortableConfig | ConvertTo-Json -Depth 6
Write-Utf8NoBom (Join-Path $OutputPath "config\app_settings.json") @($PortableConfigJson)

Remove-GeneratedFiles $OutputPath @($PythonTarget)

$PortableReadme = @(
    "# MRI2MR Portable V4",
    "",
    "Double-click start_portable.bat to launch the WebUI.",
    "",
    "Bundled runtime checks:",
    "- Python: runtime\python\BrainAAL\python.exe",
    "- SPM compiled backend: runtime\spm_compiled\run_spm_segmentation.exe",
    "- MATLAB Runtime: runtime\matlab_runtime\R2025b",
    "- MATLAB Runtime installer: runtime\matlab_runtime_installer\setup.exe",
    "- DICOM tools: dcm2niix_win and dcmtk-3.7.0-win64-dynamic",
    "- Three.js viewer assets: app\static\vendor\three",
    "",
    "Notes:",
    "- start_webui.bat is intentionally not copied into the portable package because it may fall back to a system Python.",
    "- If runtime\matlab_runtime\R2025b is missing, start_portable.bat installs the bundled MATLAB Runtime into that folder on first launch.",
    "- SynthSeg still uses Docker image pwesp/synthseg:py38 unless that backend is replaced in a future package.",
    "- Review MATLAB Runtime, SPM, DCMTK, dcm2niix, Python, and package licenses before external redistribution."
)
Write-Utf8NoBom (Join-Path $OutputPath "README_PORTABLE_V4.md") $PortableReadme

$ReportPath = Join-Path $OutputPath "PACKING_REPORT.txt"
$Checks = [ordered]@{
    "Portable root" = $OutputPath
    "Python exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "runtime\python\BrainAAL\python.exe"))
    "dcm2niix exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "dcm2niix_win\dcm2niix.exe"))
    "dcmdjpeg exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "dcmtk-3.7.0-win64-dynamic\dcmtk-3.7.0-win64-dynamic\bin\dcmdjpeg.exe"))
    "SPM dir exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "spm"))
    "MCR_HOME exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "runtime\matlab_runtime\R2025b"))
    "MCR installer exists" = ((Test-Path -LiteralPath (Join-Path $OutputPath "runtime\matlab_runtime_installer\setup.exe")) -or (Test-Path -LiteralPath (Join-Path $OutputPath "runtime\matlab_runtime_installer\MATLAB_Runtime_R2025b_win64.exe")))
    "SPM standalone exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "runtime\spm_standalone\spm12.exe"))
    "SPM compiled exists" = (Test-Path -LiteralPath (Join-Path $OutputPath "runtime\spm_compiled\run_spm_segmentation.exe"))
    "Three.js local assets exist" = (Test-Path -LiteralPath (Join-Path $OutputPath "app\static\vendor\three\build\three.module.js"))
    "Validation tools exist" = (Test-Path -LiteralPath (Join-Path $OutputPath "tools\validate_webui_v3_config.py"))
    "Folder size bytes" = (Get-FolderSizeBytes $OutputPath)
}

$Lines = @(
    "MRI2MR portable packing report",
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    ""
)
foreach ($Item in $Checks.GetEnumerator()) {
    $Lines += ("{0}: {1}" -f $Item.Key, $Item.Value)
}
$Lines += ""
$Lines += "Notes:"
$Lines += "- workspace runtime results are not copied by default."
$Lines += "- SynthSeg still requires Docker unless a future package replaces that backend."
$Lines += "- MATLAB Runtime redistribution and SPM licensing must be reviewed before external distribution."
Write-Utf8NoBom $ReportPath $Lines

Write-Host "Portable package created at: $OutputPath"
Write-Host "Report: $ReportPath"
