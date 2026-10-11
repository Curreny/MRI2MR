from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote


NIFTI_SUFFIXES = (".nii", ".nii.gz")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")
MODEL_SUFFIXES = (".glb",)
TEXT_SUFFIXES = (".log", ".txt")
VECTOR_SUFFIXES = (".bval", ".bvec")

MODEL_GROUP_LABELS = {
    "dk_regions": "DK 脑区",
    "lobes": "脑叶",
    "hemispheres": "脑半球",
    "tissue": "组织",
    "vessel": "动脉",
    "mrv": "静脉",
    "vascular": "血管",
    "fiber_tracking": "纤维束",
    "fiber_tracking_region": "脑区连接",
    "fiber_tracking_dki": "DKI 纤维束",
    "gm_wm": "灰白质",
    "ventricle": "脑室",
    "multiroi": "多层 ROI",
    "roi": "ROI",
    "models": "模型",
}

CATEGORY_ORDER = {
    "input": 0,
    "segmentation": 1,
    "final_model": 2,
    "important_intermediate": 3,
    "preview": 4,
    "log": 5,
    "metadata": 6,
}

IGNORED_TEMP_DIRS = {
    "dicom2niix_output",
    "dicom_dcmtk_decompressed",
}

IMPORTANT_TEMP_NAMES = {
    "gfa.nii",
    "gfa.nii.gz",
    "out_figma12_1000.nii",
    "out_figma12_1000.nii.gz",
    "interface_atlas.nii",
    "interface_atlas.nii.gz",
}

IMPORTANT_TEMP_KEYWORDS = (
    "atlas",
    "gfa",
    "figma",
    "frangi",
    "interface_atlas",
    "mask",
    "seg",
    "synthseg",
    "vessel",
    "vessel_mask",
)


def is_nifti(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(NIFTI_SUFFIXES)


def is_segmentation_nifti(path: Path) -> bool:
    if not is_nifti(path):
        return False
    name = path.name.lower()
    try:
        parts = [part.lower() for part in path.parts]
    except TypeError:
        parts = []
    return (
        name == "t1_synthseg.nii"
        or name == "t1_synthseg.nii.gz"
        or "synthseg" in name
        or "seg" in name
        or "synthseg_result" in parts
    )


def file_type(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(NIFTI_SUFFIXES):
        return "nifti"
    if name.endswith(MODEL_SUFFIXES):
        return "glb"
    if name.endswith(IMAGE_SUFFIXES):
        return "image"
    if name.endswith(TEXT_SUFFIXES):
        return "text"
    if name.endswith(".json"):
        return "json"
    return path.suffix.lower().lstrip(".") or "file"


def category_for(path: Path, workspace: Path) -> str:
    try:
        rel_parts = path.resolve().relative_to(workspace.resolve()).parts
    except ValueError:
        return "important_intermediate"
    rel_parts_lower = tuple(part.lower() for part in rel_parts)
    first = rel_parts_lower[0] if rel_parts_lower else ""
    name = path.name.lower()
    if name in {"patient.json", "job.json"}:
        return "metadata"
    if name.endswith(".log"):
        return "log"
    if first == "previews":
        return "preview"
    if first == "model_output" and name.endswith(MODEL_SUFFIXES):
        return "final_model"
    if first == "synthseg_result" or is_segmentation_nifti(path):
        return "segmentation"
    if first == "patient_input":
        return "input"
    if first == "temp":
        return "important_intermediate"
    if first == "jobs" and rel_parts_lower[-1] == "job.json":
        return "metadata"
    return "important_intermediate"


def model_group_for(path: Path, workspace: Path) -> str | None:
    if not path.name.lower().endswith(MODEL_SUFFIXES):
        return None
    parts = _relative_parts(path, workspace)
    if len(parts) < 2 or parts[0] != "model_output":
        return "models"

    group = parts[1]
    if group == "individual_regions":
        return "dk_regions"
    if group in MODEL_GROUP_LABELS:
        return group
    return "models"


def _preview_stem(path: Path) -> str:
    safe = path.name.replace(".nii.gz", "").replace(".nii", "")
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in safe)


def preview_name_for(path: Path) -> str:
    safe = _preview_stem(path)
    if is_segmentation_nifti(path):
        return f"{safe}_segmentation_slices.png"
    return f"{safe}_slices.png"


def segmentation_preview_name_for(path: Path, view: str) -> str:
    safe = _preview_stem(path)
    return f"{safe}_segmentation_{view}.png"


def _relative_parts(path: Path, workspace: Path) -> tuple[str, ...]:
    try:
        return tuple(part.lower() for part in path.resolve().relative_to(workspace.resolve()).parts)
    except ValueError:
        return ()


def _is_under_ignored_temp_dir(path: Path, workspace: Path) -> bool:
    parts = _relative_parts(path, workspace)
    return len(parts) >= 2 and parts[0] == "temp" and parts[1] in IGNORED_TEMP_DIRS


def _is_important_temp_file(path: Path) -> bool:
    name = path.name.lower()
    if not is_nifti(path):
        return False
    if name in IMPORTANT_TEMP_NAMES:
        return True
    return any(keyword in name for keyword in IMPORTANT_TEMP_KEYWORDS)


def _is_legacy_segmentation_grayscale_preview(path: Path) -> bool:
    name = path.name.lower()
    return (
        name.endswith("_slices.png")
        and not name.endswith("_segmentation_slices.png")
        and ("synthseg" in name or "seg" in name)
    )


def is_output_file(path: Path, workspace: Path) -> bool:
    parts = _relative_parts(path, workspace)
    if not parts or _is_under_ignored_temp_dir(path, workspace):
        return False

    first = parts[0]
    name = path.name.lower()
    if len(parts) == 1 and name in {"patient.json", "job.json"}:
        return True
    if first == "patient_input":
        return is_nifti(path) or name.endswith(VECTOR_SUFFIXES)
    if first == "synthseg_result":
        return is_nifti(path)
    if first == "model_output":
        return name.endswith(MODEL_SUFFIXES)
    if first == "previews":
        return name.endswith(IMAGE_SUFFIXES) and not _is_legacy_segmentation_grayscale_preview(path)
    if first == "logs":
        return name == "run.log" or name.endswith(".log")
    if first == "jobs":
        return len(parts) >= 3 and name in {"job.json", "run.log"}
    if first == "temp":
        return _is_important_temp_file(path)
    return False


def _iter_files(root: Path, workspace: Path) -> Iterable[Path]:
    if not root.exists():
        return
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda child: child.name.lower())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if not _is_under_ignored_temp_dir(child, workspace):
                    stack.append(child)
            elif child.is_file():
                yield child


def iter_output_files(workspace: Path) -> list[Path]:
    workspace = workspace.resolve()
    scan_roots = [
        workspace / "patient_input",
        workspace / "SynthSeg_result",
        workspace / "model_output",
        workspace / "temp",
        workspace / "logs",
        workspace / "previews",
        workspace / "jobs",
    ]
    candidates: list[Path] = [workspace / "patient.json", workspace / "job.json"]
    for root in scan_roots:
        candidates.extend(_iter_files(root, workspace))

    seen: set[Path] = set()
    outputs: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        if is_output_file(path, workspace):
            outputs.append(path)
    outputs.sort(
        key=lambda item: (
            CATEGORY_ORDER.get(category_for(item, workspace), 99),
            item.relative_to(workspace).as_posix().lower(),
        )
    )
    return outputs


def _file_url(relative_path: str, job_id: str | None, patient_folder: str | None) -> str:
    rel = quote(relative_path, safe="/")
    if job_id:
        return f"/api/jobs/{quote(job_id, safe='')}/file?path={rel}"
    if patient_folder:
        return f"/api/patients/{quote(patient_folder, safe='')}/file?path={rel}"
    return f"/api/file?path={rel}"


def scan_outputs(workspace: Path, job_id: str | None = None, patient_folder: str | None = None) -> list[dict[str, Any]]:
    workspace = workspace.resolve()
    preview_dir = workspace / "previews"
    patient_folder = patient_folder or workspace.name
    entries: list[dict[str, Any]] = []

    for path in iter_output_files(workspace):
        rel = path.resolve().relative_to(workspace).as_posix()
        info = path.stat()
        entry = {
            "name": path.name,
            "relative_path": rel,
            "type": file_type(path),
            "category": category_for(path, workspace),
            "size": info.st_size,
            "modified_at": info.st_mtime,
            "url": _file_url(rel, job_id, patient_folder),
            "previewable": False,
            "preview_url": None,
        }
        model_group = model_group_for(path, workspace)
        if model_group:
            entry["model_group"] = model_group
            entry["model_group_label"] = MODEL_GROUP_LABELS.get(model_group, model_group)

        if entry["type"] in {"image", "glb"}:
            entry["previewable"] = True
            entry["preview_url"] = entry["url"]
        elif is_nifti(path):
            preview = preview_dir / preview_name_for(path)
            if preview.exists():
                preview_rel = preview.resolve().relative_to(workspace).as_posix()
                entry["previewable"] = True
                entry["preview_url"] = _file_url(preview_rel, job_id, patient_folder)
        entries.append(entry)

    return entries
