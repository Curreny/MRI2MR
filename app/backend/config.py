from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = APP_ROOT / "config"


def _get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return default


def _resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (root / path).resolve()


def _path(root: Path, data: dict[str, Any], *keys: str, default: str | Path) -> Path:
    return _resolve_path(root, _get(data, *keys, default=str(default)))


def _optional_path(root: Path, data: dict[str, Any], *keys: str, default: str | Path | None = None) -> Path | None:
    value = _get(data, *keys, default=default)
    if value in (None, ""):
        return None
    return _resolve_path(root, value)


def _matlab_exe_exists(value: str) -> bool:
    configured = value.strip() or "matlab"
    configured_path = Path(configured)
    if configured_path.is_absolute() or "\\" in configured or "/" in configured:
        return configured_path.exists()
    if shutil.which(configured):
        return True
    if Path("D:/Matlab/bin/matlab.exe").exists():
        return True
    matlab_root = Path("C:/Program Files/MATLAB")
    return matlab_root.exists() and any(matlab_root.glob("R*/bin/matlab.exe"))


@dataclass(frozen=True)
class AppSettings:
    mri2mr_root: Path
    main_script: Path
    spm_script: Path
    dcm2niix_exe: Path
    dcmtk_dcmdjpeg_exe: Path
    spm_dir: Path
    python_exe: Path
    workspace_root: Path
    spm_backend: str
    matlab_exe: str
    mcr_home: Path | None
    spm_standalone_dir: Path | None
    spm_standalone_exe: Path | None
    spm_compiled_exe: Path | None
    synthseg_docker_image: str
    docker_exe: str
    log_retention_days: int
    allow_overwrite: bool
    max_concurrent_jobs: int
    template_dir: Path | None = None

    @classmethod
    def load(cls) -> "AppSettings":
        config_file = CONFIG_DIR / "app_settings.json"
        data: dict[str, Any] = {}
        if config_file.exists():
            with config_file.open("r", encoding="utf-8-sig") as f:
                data = json.load(f)

        root = _resolve_path(APP_ROOT, _get(data, "MRI2MR_ROOT", "mri2mr_root", default=APP_ROOT))
        template_dir_raw = _get(data, "TEMPLATE_DIR", "template_dir", default=None)
        template_dir = _resolve_path(root, template_dir_raw) if template_dir_raw else root / "template"

        return cls(
            mri2mr_root=root,
            main_script=_path(root, data, "MAIN_SCRIPT", "main_script", default=root / "scripts" / "Main_cmd.py"),
            spm_script=_path(root, data, "SPM_SCRIPT", "spm_script", default=root / "scripts" / "run_spm_segmentation.m"),
            dcm2niix_exe=_path(
                root,
                data,
                "DCM2NIIX_EXE",
                "dcm2niix_exe",
                default=root / "dcm2niix_win" / "dcm2niix.exe",
            ),
            dcmtk_dcmdjpeg_exe=_path(
                root,
                data,
                "DCMTK_DCMDJPEG_EXE",
                "dcmtk_dcmdjpeg_exe",
                default=root
                / "dcmtk-3.7.0-win64-dynamic"
                / "dcmtk-3.7.0-win64-dynamic"
                / "bin"
                / "dcmdjpeg.exe",
            ),
            spm_dir=_path(root, data, "SPM_DIR", "spm_dir", default=root / "spm"),
            python_exe=_path(root, data, "PYTHON_EXE", "python_exe", default=sys.executable),
            workspace_root=_path(root, data, "WORKSPACE_ROOT", "workspace_root", default=root / "workspace"),
            spm_backend=str(_get(data, "SPM_BACKEND", "spm_backend", default="auto")).strip().lower() or "auto",
            matlab_exe=str(_get(data, "MATLAB_EXE", "matlab_exe", default="matlab")).strip() or "matlab",
            mcr_home=_optional_path(root, data, "MCR_HOME", "mcr_home", default=root / "runtime" / "matlab_runtime" / "R2025b"),
            spm_standalone_dir=_optional_path(
                root,
                data,
                "SPM_STANDALONE_DIR",
                "spm_standalone_dir",
                default=root / "runtime" / "spm_standalone",
            ),
            spm_standalone_exe=_optional_path(
                root,
                data,
                "SPM_STANDALONE_EXE",
                "spm_standalone_exe",
                default=root / "runtime" / "spm_standalone" / "spm12.exe",
            ),
            spm_compiled_exe=_optional_path(
                root,
                data,
                "SPM_COMPILED_EXE",
                "spm_compiled_exe",
                default=root / "runtime" / "spm_compiled" / "run_spm_segmentation.exe",
            ),
            synthseg_docker_image=str(
                _get(data, "SYNTHSEG_DOCKER_IMAGE", "synthseg_docker_image", default="pwesp/synthseg:py38")
            ),
            docker_exe=str(_get(data, "DOCKER_EXE", "docker_exe", default="docker")),
            log_retention_days=int(_get(data, "LOG_RETENTION_DAYS", "log_retention_days", default=30)),
            allow_overwrite=bool(_get(data, "ALLOW_OVERWRITE", "allow_overwrite", default=False)),
            max_concurrent_jobs=int(_get(data, "MAX_CONCURRENT_JOBS", "max_concurrent_jobs", default=1)),
            template_dir=template_dir,
        )

    def resolved_python(self) -> Path:
        return self.python_exe if self.python_exe.exists() else Path(sys.executable)

    def public_dict(self) -> dict[str, Any]:
        paths = {
            "mri2mr_root": self.mri2mr_root,
            "main_script": self.main_script,
            "spm_script": self.spm_script,
            "dcm2niix_exe": self.dcm2niix_exe,
            "dcmtk_dcmdjpeg_exe": self.dcmtk_dcmdjpeg_exe,
            "spm_dir": self.spm_dir,
            "python_exe": self.python_exe,
            "workspace_root": self.workspace_root,
            "template_dir": self.template_dir,
            "mcr_home": self.mcr_home,
            "spm_standalone_dir": self.spm_standalone_dir,
            "spm_standalone_exe": self.spm_standalone_exe,
            "spm_compiled_exe": self.spm_compiled_exe,
        }
        return {
            "paths": {key: str(value) for key, value in paths.items() if value is not None},
            "path_status": {key: value.exists() for key, value in paths.items() if value is not None},
            "effective_python_exe": str(self.resolved_python()),
            "spm_backend": self.spm_backend,
            "matlab_exe": self.matlab_exe,
            "synthseg_docker_image": self.synthseg_docker_image,
            "log_retention_days": self.log_retention_days,
            "allow_overwrite": self.allow_overwrite,
            "max_concurrent_jobs": self.max_concurrent_jobs,
        }

    def runtime_status(self) -> dict[str, Any]:
        effective_python = self.resolved_python()
        compiled_ready = bool(self.spm_compiled_exe and self.spm_compiled_exe.exists())
        standalone_ready = bool(self.spm_standalone_exe and self.spm_standalone_exe.exists())
        mcr_ready = bool(self.mcr_home and self.mcr_home.exists())
        runtime_installer = self.mri2mr_root / "runtime" / "matlab_runtime_installer" / "setup.exe"
        runtime_installer_ready = runtime_installer.exists()
        if self.spm_backend == "auto":
            selected_backend = "compiled_exe" if compiled_ready else "spm_standalone" if standalone_ready else "matlab_engine"
        else:
            selected_backend = self.spm_backend
        if selected_backend in {"compiled_exe", "spm_standalone"}:
            spm_ready = (compiled_ready if selected_backend == "compiled_exe" else standalone_ready) and mcr_ready
        elif selected_backend == "matlab_cli":
            spm_ready = _matlab_exe_exists(self.matlab_exe)
        else:
            spm_ready = selected_backend == "matlab_engine"

        spm_reason = ""
        if selected_backend == "compiled_exe":
            if not compiled_ready:
                spm_reason = "SPM compiled executable not found."
            elif runtime_installer_ready and not mcr_ready:
                spm_reason = "MATLAB Runtime will be installed from the bundled installer on first launch."
            elif not mcr_ready:
                spm_reason = "MATLAB Runtime directory not found."
        elif selected_backend == "spm_standalone":
            if not standalone_ready:
                spm_reason = "SPM standalone executable not found."
            elif runtime_installer_ready and not mcr_ready:
                spm_reason = "MATLAB Runtime will be installed from the bundled installer on first launch."
            elif not mcr_ready:
                spm_reason = "MATLAB Runtime directory not found."
        elif selected_backend == "matlab_engine":
            spm_reason = "Development fallback: requires full MATLAB and MATLAB Engine for Python."
        elif selected_backend == "matlab_cli":
            if not spm_ready:
                spm_reason = "MATLAB executable not found. Set MATLAB_EXE or put matlab on PATH."
        else:
            spm_reason = f"Unsupported SPM backend: {selected_backend}."

        docker_path = Path(self.docker_exe)
        docker_exists = docker_path.exists() if docker_path.is_absolute() else bool(shutil.which(self.docker_exe))

        return {
            "python": {
                "configured": str(self.python_exe),
                "effective": str(effective_python),
                "exists": self.python_exe.exists(),
                "using_fallback": effective_python != self.python_exe,
            },
            "spm": {
                "backend": self.spm_backend,
                "selected_backend": selected_backend,
                "matlab_exe": self.matlab_exe,
                "mcr_home": str(self.mcr_home) if self.mcr_home else "",
                "mcr_exists": mcr_ready,
                "runtime_installer": str(runtime_installer),
                "runtime_installer_exists": runtime_installer_ready,
                "standalone_dir": str(self.spm_standalone_dir) if self.spm_standalone_dir else "",
                "standalone_dir_exists": bool(self.spm_standalone_dir and self.spm_standalone_dir.exists()),
                "standalone_exe": str(self.spm_standalone_exe) if self.spm_standalone_exe else "",
                "standalone_exists": standalone_ready,
                "compiled_exe": str(self.spm_compiled_exe) if self.spm_compiled_exe else "",
                "compiled_exists": compiled_ready,
                "spm_dir": str(self.spm_dir),
                "spm_dir_exists": self.spm_dir.exists(),
                "ready": spm_ready,
                "reason": spm_reason,
            },
            "tools": {
                "dcm2niix": self.dcm2niix_exe.exists(),
                "dcmtk_dcmdjpeg": self.dcmtk_dcmdjpeg_exe.exists(),
                "docker": docker_exists,
            },
        }
