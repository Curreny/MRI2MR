from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AppSettings
from .outputs import scan_outputs


PATIENT_FIELDS = ("patient_name", "patient_id", "sex", "age", "study_date", "notes")
PATIENT_SUBDIRS = ("patient_input", "SynthSeg_result", "model_output", "temp", "logs", "previews", "jobs")
TEMP_SKIP_DIRS = {"dicom2niix_output", "dicom_dcmtk_decompressed"}
IMPORTANT_TEMP_MARKERS = (
    "atlas",
    "figma",
    "frangi",
    "gfa",
    "interface",
    "mask",
    "vessel",
)
INTERNAL_PATIENT_PREFIXES = (".", "_")

INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


@dataclass(frozen=True)
class PatientRecord:
    folder: str
    workspace: Path
    patient: dict[str, Any]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _folder_part(value: Any) -> str:
    clean = INVALID_WINDOWS_CHARS.sub("_", _clean_text(value))
    clean = re.sub(r"\s+", "_", clean).strip(" ._-")
    return clean


def sanitize_patient_folder(value: str) -> str:
    return _folder_part(value) or "unknown"


def patient_folder_from_info(patient: dict[str, Any]) -> str:
    name = _folder_part(patient.get("patient_name"))
    patient_id = _folder_part(patient.get("patient_id"))
    if name and patient_id:
        return f"{name}_{patient_id}"
    return name or patient_id or "unknown"


def patient_from_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    raw_patient = payload.get("patient") if isinstance(payload.get("patient"), dict) else {}
    patient = {field: _clean_text(raw_patient.get(field)) for field in PATIENT_FIELDS}

    for field in PATIENT_FIELDS:
        if not patient[field] and field in payload:
            patient[field] = _clean_text(payload.get(field))

    requested_folder = _clean_text(
        payload.get("patient_folder")
        or raw_patient.get("patient_folder")
        or raw_patient.get("folder")
        or raw_patient.get("existing_patient_id")
        or payload.get("existing_patient_id")
    )
    return patient, requested_folder


def _safe_workspace(root: Path, folder: str) -> Path:
    root = root.resolve()
    workspace = (root / sanitize_patient_folder(folder)).resolve()
    if root != workspace and root not in workspace.parents:
        raise ValueError("Invalid patient workspace path.")
    return workspace


def _patient_file(workspace: Path) -> Path:
    return workspace / "patient.json"


def read_patient_json(workspace: Path) -> dict[str, Any]:
    patient_file = _patient_file(workspace)
    if not patient_file.exists():
        return {}
    try:
        data = json.loads(patient_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_patient_json(workspace: Path, patient: dict[str, Any]) -> None:
    _patient_file(workspace).write_text(json.dumps(patient, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_patient(existing: dict[str, Any], incoming: dict[str, Any], folder: str) -> dict[str, Any]:
    merged = {field: _clean_text(existing.get(field)) for field in PATIENT_FIELDS}
    for field in PATIENT_FIELDS:
        if incoming.get(field) not in (None, ""):
            merged[field] = _clean_text(incoming.get(field))

    now = _now_iso()
    merged["patient_folder"] = folder
    merged["created_at"] = _clean_text(existing.get("created_at")) or now
    merged["updated_at"] = now
    return merged


def _iter_patient_workspaces(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [
        path
        for path in root.iterdir()
        if path.is_dir() and _patient_file(path).exists() and not _is_test_patient_workspace(path)
    ]


def _record_from_workspace(workspace: Path) -> PatientRecord:
    patient = read_patient_json(workspace)
    folder = workspace.name
    if not patient.get("patient_folder"):
        patient["patient_folder"] = folder
    return PatientRecord(folder=folder, workspace=workspace.resolve(), patient=patient)


def _find_by_patient_id(root: Path, patient_id: str) -> PatientRecord | None:
    if not patient_id:
        return None
    for workspace in _iter_patient_workspaces(root):
        record = _record_from_workspace(workspace)
        if _clean_text(record.patient.get("patient_id")) == patient_id:
            return record
    return None


def _is_test_patient_workspace(workspace: Path) -> bool:
    return workspace.name.startswith(INTERNAL_PATIENT_PREFIXES)


def _find_requested_patient(root: Path, identifier: str) -> PatientRecord | None:
    clean = _clean_text(identifier)
    if not clean:
        return None

    folder_workspace = _safe_workspace(root, clean)
    if folder_workspace.is_dir() and _patient_file(folder_workspace).exists() and not _is_test_patient_workspace(folder_workspace):
        return _record_from_workspace(folder_workspace)

    by_id = _find_by_patient_id(root, clean)
    if by_id is not None:
        return by_id

    for workspace in _iter_patient_workspaces(root):
        record = _record_from_workspace(workspace)
        if record.folder == clean:
            return record
    return None


def _identity_conflicts(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    existing_id = _clean_text(existing.get("patient_id"))
    incoming_id = _clean_text(incoming.get("patient_id"))
    return bool(existing_id and incoming_id and existing_id != incoming_id)


def _dedupe_workspace(root: Path, base_folder: str, incoming: dict[str, Any]) -> Path:
    base_folder = sanitize_patient_folder(base_folder)
    for index in range(1, 1000):
        folder = base_folder if index == 1 else f"{base_folder}_{index:02d}"
        workspace = _safe_workspace(root, folder)
        if not workspace.exists():
            return workspace
        if not _identity_conflicts(read_patient_json(workspace), incoming):
            return workspace
    raise RuntimeError(f"Unable to allocate patient workspace for: {base_folder}")


def ensure_patient_workspace(settings: AppSettings, payload: dict[str, Any]) -> PatientRecord:
    root = settings.workspace_root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    patient, requested_folder = patient_from_payload(payload)
    explicit_folder = bool(requested_folder)

    if explicit_folder:
        existing_requested = _find_requested_patient(root, requested_folder)
        workspace = existing_requested.workspace if existing_requested is not None else _safe_workspace(root, requested_folder)
    else:
        existing = _find_by_patient_id(root, patient.get("patient_id", ""))
        if existing is not None:
            workspace = existing.workspace
        else:
            workspace = _dedupe_workspace(root, patient_folder_from_info(patient), patient)

    workspace.mkdir(parents=True, exist_ok=True)
    for subdir in PATIENT_SUBDIRS:
        (workspace / subdir).mkdir(parents=True, exist_ok=True)

    stored = _merge_patient(read_patient_json(workspace), patient, workspace.name)
    _write_patient_json(workspace, stored)
    return PatientRecord(folder=workspace.name, workspace=workspace, patient=stored)


def save_patient(settings: AppSettings, payload: dict[str, Any]) -> dict[str, Any]:
    record = ensure_patient_workspace(settings, payload)
    return _public_patient(record)


def update_patient(settings: AppSettings, patient_id_or_folder: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = resolve_patient(settings, patient_id_or_folder)
    incoming, _ = patient_from_payload(payload)

    for subdir in PATIENT_SUBDIRS:
        (record.workspace / subdir).mkdir(parents=True, exist_ok=True)

    stored = _merge_patient(read_patient_json(record.workspace), incoming, record.folder)
    _write_patient_json(record.workspace, stored)
    return _public_patient(_record_from_workspace(record.workspace))


def _public_patient(record: PatientRecord) -> dict[str, Any]:
    jobs = []
    for job_file in (record.workspace / "jobs").glob("*/job.json"):
        try:
            job = json.loads(job_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(job, dict):
            jobs.append(job)
    jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)

    data = dict(record.patient)
    data["patient_folder"] = record.folder
    data["patient_workspace"] = str(record.workspace)
    data["job_count"] = len(jobs)
    if jobs:
        latest = jobs[0]
        data["latest_job"] = {
            "job_id": latest.get("job_id"),
            "mode": latest.get("mode"),
            "status": latest.get("status"),
            "created_at": latest.get("created_at"),
            "finished_at": latest.get("finished_at"),
        }
    else:
        data["latest_job"] = None
    return data


def list_patients(settings: AppSettings) -> list[dict[str, Any]]:
    root = settings.workspace_root.resolve()
    patients = [_public_patient(_record_from_workspace(path)) for path in _iter_patient_workspaces(root)]
    patients.sort(key=lambda item: (item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return patients


def resolve_patient(settings: AppSettings, patient_id_or_folder: str) -> PatientRecord:
    root = settings.workspace_root.resolve()
    identifier = _clean_text(patient_id_or_folder)
    if not identifier:
        raise KeyError(patient_id_or_folder)

    record = _find_requested_patient(root, identifier)
    if record is not None:
        return record
    raise KeyError(patient_id_or_folder)


def get_patient(settings: AppSettings, patient_id_or_folder: str) -> dict[str, Any]:
    return _public_patient(resolve_patient(settings, patient_id_or_folder))


def resolve_patient_file(settings: AppSettings, patient_id_or_folder: str, relative_path: str) -> Path:
    record = resolve_patient(settings, patient_id_or_folder)
    workspace = record.workspace.resolve()
    target = (workspace / relative_path).resolve()
    if workspace != target and workspace not in target.parents:
        raise ValueError("File path is outside this patient workspace.")
    if not target.is_file():
        raise FileNotFoundError(str(target))
    return target


def scan_patient_outputs(
    workspace: Path,
    *,
    job_id: str | None = None,
    patient_folder: str | None = None,
) -> list[dict[str, Any]]:
    return scan_outputs(workspace, job_id=job_id, patient_folder=patient_folder)
