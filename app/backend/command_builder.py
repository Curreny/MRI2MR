from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import AppSettings
from .modes import iter_fields


EMPTY_VALUES = (None, "", [], ())


class CommandBuildError(ValueError):
    pass



def sanitize_job_name(value: str) -> str:
    clean = re.sub(r"[^\w.-]+", "_", value.strip(), flags=re.UNICODE).strip("._-")
    return clean or "case"


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y", "\u662f"}
    return False


def _list_value(value: Any) -> list[str]:
    if value in EMPTY_VALUES:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part for part in re.split(r"[\s,;]+", str(value).strip()) if part]


def _resolve_template(value: Any, settings: AppSettings, patient_workspace: Path) -> Any:
    if not isinstance(value, str):
        return value
    replacements = {
        "{patient_workspace}": str(patient_workspace),
        "{patient_patient_input_dir}": str(patient_workspace / "patient_input"),
        "{patient_synthseg_result_dir}": str(patient_workspace / "SynthSeg_result"),
        "{patient_model_output_dir}": str(patient_workspace / "model_output"),
        "{patient_temp_dir}": str(patient_workspace / "temp"),
        "{patient_dicom_temp_dir}": str(patient_workspace / "temp" / "dicom2niix_output"),
        "{patient_dicom_decompress_dir}": str(patient_workspace / "temp" / "dicom_dcmtk_decompressed"),
        "{case_workspace}": str(patient_workspace),
        "{case_patient_input_dir}": str(patient_workspace / "patient_input"),
        "{case_synthseg_result_dir}": str(patient_workspace / "SynthSeg_result"),
        "{case_model_output_dir}": str(patient_workspace / "model_output"),
        "{case_temp_dir}": str(patient_workspace / "temp"),
        "{case_dicom_temp_dir}": str(patient_workspace / "temp" / "dicom2niix_output"),
        "{case_dicom_decompress_dir}": str(patient_workspace / "temp" / "dicom_dcmtk_decompressed"),
        "{mri2mr_root}": str(settings.mri2mr_root),
        "{template_dir}": str(settings.template_dir or settings.mri2mr_root / "template"),
    }
    result = value
    for marker, replacement in replacements.items():
        result = result.replace(marker, replacement)
    return result


def _default_path(settings: AppSettings, patient_workspace: Path, raw: str) -> str:
    raw = str(_resolve_template(raw, settings, patient_workspace))
    normalized = raw.replace("\\", "/")
    raw_path = Path(raw)
    if raw_path.is_absolute():
        return str(raw_path)
    if normalized.startswith("template/") and settings.template_dir:
        return str((settings.template_dir / normalized.removeprefix("template/")).resolve())
    if normalized.startswith("scripts/"):
        return str((settings.mri2mr_root / normalized).resolve())
    return str((patient_workspace / normalized).resolve())


def _field_value(
    field: dict[str, Any],
    payload: dict[str, Any],
    settings: AppSettings,
    patient_workspace: Path,
) -> Any:
    params = payload.get("parameters") or {}
    name = field.get("name")
    value = params.get(name)
    if value in EMPTY_VALUES and field.get("default_path"):
        value = _default_path(settings, patient_workspace, str(field["default_path"]))
    if value in EMPTY_VALUES and "default" in field:
        value = field.get("default")
    value = _resolve_template(value, settings, patient_workspace)
    return value


def build_command(
    settings: AppSettings,
    mode_schema: dict[str, Any],
    payload: dict[str, Any],
    patient_workspace: Path,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    mode = str(mode_schema.get("mode") or payload.get("mode") or "").strip()
    if not mode:
        raise CommandBuildError("Missing processing mode.")

    python_exe = settings.resolved_python()
    if python_exe != settings.python_exe:
        warnings.append(f"Configured Python was not found, using current interpreter: {python_exe}")

    command = [
        str(python_exe),
        str(settings.main_script),
        "--mode",
        mode,
        "--base-data-dir",
        str(patient_workspace),
        "--patient-data-dir",
        str(patient_workspace / "patient_input"),
        "--synthseg-data-dir",
        str(patient_workspace / "SynthSeg_result"),
        "--output-dir",
        str(patient_workspace / "model_output"),
        "--spm-dir",
        str(settings.spm_dir),
        "--dcm2niix-exe",
        str(settings.dcm2niix_exe),
        "--dcmtk-dcmdjpeg-exe",
        str(settings.dcmtk_dcmdjpeg_exe),
        "--dicom-temp-dir",
        str(patient_workspace / "temp" / "dicom2niix_output"),
        "--dicom-decompress-dir",
        str(patient_workspace / "temp" / "dicom_dcmtk_decompressed"),
        "--docker-exe",
        settings.docker_exe,
        "--synthseg-docker-image",
        settings.synthseg_docker_image,
        "--spm-script-dir",
        str(settings.spm_script.parent),
        "--spm-backend",
        settings.spm_backend,
        "--matlab-exe",
        settings.matlab_exe,
    ]

    if settings.mcr_home:
        command.extend(["--mcr-home", str(settings.mcr_home)])
    if settings.spm_standalone_exe:
        command.extend(["--spm-standalone-exe", str(settings.spm_standalone_exe)])
    if settings.spm_compiled_exe:
        command.extend(["--spm-compiled-exe", str(settings.spm_compiled_exe)])

    if settings.template_dir:
        command.extend(["--template-dir", str(settings.template_dir)])

    for field in iter_fields(mode_schema):
        cli = field.get("cli")
        if not cli:
            continue
        value = _field_value(field, payload, settings, patient_workspace)
        field_type = field.get("type", "text")
        if field.get("required") and value in EMPTY_VALUES:
            raise CommandBuildError(f"Missing required field: {field.get('label') or field.get('name')}")

        if field_type == "boolean":
            if _bool_value(value):
                command.append(str(cli))
            continue

        if value in EMPTY_VALUES:
            continue

        if field_type in {"list", "string_list"}:
            values = _list_value(value)
            if values:
                command.append(str(cli))
                command.extend(values)
            continue

        command.extend([str(cli), str(value)])

    return command, warnings
