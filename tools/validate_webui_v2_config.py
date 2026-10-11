from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def walk_json(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}", key, child
            yield from walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield f"{path}[{index}]", str(index), child
            yield from walk_json(child, f"{path}[{index}]")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def command_value(command: list[str], flag: str) -> str:
    index = command.index(flag)
    return command[index + 1]


def check_backend_syntax() -> None:
    for path in sorted((ROOT / "app" / "backend").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print("OK backend Python syntax: app/backend/*.py")


def check_api_routes() -> None:
    tree = ast.parse((ROOT / "app" / "backend" / "main.py").read_text(encoding="utf-8"))
    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                route = decorator.args[0].value
                if isinstance(route, str):
                    routes.add((method, route))

    required = {
        ("GET", "/api/config"),
        ("GET", "/api/modes"),
        ("POST", "/api/jobs"),
        ("GET", "/api/jobs"),
        ("GET", "/api/jobs/{job_id}"),
        ("POST", "/api/jobs/{job_id}/cancel"),
        ("GET", "/api/patients"),
        ("POST", "/api/patients"),
        ("GET", "/api/patients/{patient_id_or_folder}"),
        ("PATCH", "/api/patients/{patient_id_or_folder}"),
        ("GET", "/api/patients/{patient_id_or_folder}/outputs"),
        ("GET", "/health"),
    }
    missing = sorted(required - routes)
    require(not missing, f"Missing API routes: {missing}")
    print(f"OK backend API route declarations: {len(routes)} routes")


def check_json_and_placeholders() -> None:
    app_settings = read_json(ROOT / "config" / "app_settings.json")
    modes = read_json(ROOT / "config" / "modes.json")

    require("global_fields" not in modes, "Top-level global_fields must not be used for V2 file input.")

    for path in [ROOT / "config" / "app_settings.json", ROOT / "config" / "modes.json"]:
        text = path.read_text(encoding="utf-8")
        require("{case_workspace}" not in text, f"Stale {{case_workspace}} in {path}")

    for path in [ROOT / "app" / "static" / "index.html", ROOT / "app" / "static" / "app.js"]:
        text = path.read_text(encoding="utf-8")
        require("input_path" not in text, f"Stale input_path reference in {path}")

    command_builder_text = (ROOT / "app" / "backend" / "command_builder.py").read_text(encoding="utf-8")
    require("input_path" not in command_builder_text, "Command builder must not accept top-level input_path.")

    fallback_modes_text = (ROOT / "app" / "backend" / "modes.py").read_text(encoding="utf-8")
    require("use_input_path" not in fallback_modes_text, "Fallback mode schema must not use V1 use_input_path.")

    stale_value_from = [
        path
        for path, key, child in walk_json(modes)
        if key == "value_from" and isinstance(child, str) and child.startswith("case_")
    ]
    require(not stale_value_from, f"Stale case_* value_from entries: {stale_value_from}")

    default_dirs = app_settings.get("default_command_dirs", {})
    require(default_dirs.get("base_data_dir") == "{patient_workspace}", "base_data_dir must use patient_workspace")
    require(
        default_dirs.get("patient_data_dir") == "{patient_workspace}\\patient_input",
        "patient_data_dir must use patient_workspace",
    )
    require("patient_workspace_subdirs" in app_settings, "patient_workspace_subdirs is missing")

    for name, source in app_settings.get("resource_sources", {}).items():
        require(Path(source).is_file(), f"Missing resource source for {name}: {source}")

    template_dir = Path(app_settings["template_dir"])
    for filename in ["DK_Regions.txt", "DK_Lobes.txt", "ROI_ED_Filter.nii.gz"]:
        require((template_dir / filename).is_file(), f"Missing template resource: {template_dir / filename}")

    print("OK JSON/config placeholders/resources")


def check_patient_workspace_contract() -> None:
    from app.backend.command_builder import build_command
    from app.backend.config import AppSettings
    from app.backend.modes import get_mode, load_modes
    from app.backend.patients import patient_folder_from_info

    settings = AppSettings.load()
    patient = {
        "patient_name": "Jane Doe",
        "patient_id": "P001",
        "sex": "",
        "age": "",
        "study_date": "",
        "notes": "",
    }
    folder = patient_folder_from_info(patient)
    require(folder == "Jane_Doe_P001", "Patient folder naming mismatch")

    patient_workspace = settings.workspace_root / folder
    job_workspace = patient_workspace / "jobs" / "20260626_000000_Jane_Doe_P001"
    require(job_workspace.parent == patient_workspace / "jobs", "Job workspace must live under patient jobs dir")

    payload = {
        "mode": "synthseg_segmentation",
        "patient": patient,
        "parameters": {},
    }
    modes = load_modes()
    synthseg = get_mode(modes, "synthseg_segmentation")
    require(synthseg is not None, "Missing synthseg_segmentation mode")
    command, warnings = build_command(settings, synthseg, payload, patient_workspace)
    require(command_value(command, "--base-data-dir") == str(patient_workspace), "--base-data-dir mismatch")
    require(
        command_value(command, "--patient-data-dir") == str(patient_workspace / "patient_input"),
        "--patient-data-dir mismatch",
    )
    require(
        command_value(command, "--synthseg-data-dir") == str(patient_workspace / "SynthSeg_result"),
        "--synthseg-data-dir mismatch",
    )
    require(
        command_value(command, "--output-dir") == str(patient_workspace / "model_output"),
        "--output-dir mismatch",
    )
    require(
        command_value(command, "--t1-file") == str(patient_workspace / "patient_input" / "T1.nii"),
        "Default t1_file did not resolve under patient_workspace",
    )
    require(not any("{patient_workspace}" in item or "{case_workspace}" in item for item in command), "Unresolved workspace marker")

    dicom = get_mode(modes, "dicom_convert")
    require(dicom is not None, "Missing dicom_convert mode")
    dicom_command, _ = build_command(
        settings,
        dicom,
        {
            "mode": "dicom_convert",
            "patient_folder": folder,
            "parameters": {"dicom_dir": str(patient_workspace / "raw_dicom")},
        },
        patient_workspace,
    )
    require(
        command_value(dicom_command, "--dicom-temp-dir")
        == str(patient_workspace / "temp" / "dicom2niix_output"),
        "--dicom-temp-dir mismatch",
    )
    require(
        command_value(dicom_command, "--dicom-decompress-dir")
        == str(patient_workspace / "temp" / "dicom_dcmtk_decompressed"),
        "--dicom-decompress-dir mismatch",
    )
    require(isinstance(warnings, list), "Warnings should be a list")

    legacy_command, _ = build_command(
        settings,
        synthseg,
        {**payload, "input_path": "F:\\legacy\\T1.nii"},
        patient_workspace,
    )
    require(
        command_value(legacy_command, "--t1-file") == str(patient_workspace / "patient_input" / "T1.nii"),
        "Top-level input_path must not override mode parameters/defaults",
    )

    print("OK patient_workspace command contract")


def check_jobs_reject_top_level_input_path() -> None:
    from app.backend.command_builder import CommandBuildError
    from app.backend.config import AppSettings
    from app.backend.jobs import JobManager

    manager = JobManager(AppSettings.load())
    try:
        manager.create_job({"mode": "synthseg_segmentation", "input_path": "F:\\legacy\\T1.nii", "parameters": {}})
    except CommandBuildError:
        print("OK top-level input_path rejected by job creation")
        return
    except RuntimeError:
        print("SKIP top-level input_path rejection check: another job is active")
        return
    raise AssertionError("POST /api/jobs payload must reject top-level input_path")


def main() -> int:
    check_json_and_placeholders()
    check_backend_syntax()
    check_api_routes()
    check_patient_workspace_contract()
    check_jobs_reject_top_level_input_path()
    print("OK WebUI V2 config validation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
