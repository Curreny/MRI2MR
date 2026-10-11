from __future__ import annotations

from collections import Counter
from math import isfinite
from pathlib import Path
from typing import Any
import warnings

import numpy as np


NIFTI_SUFFIXES = (".nii", ".nii.gz")
BVAL_SUFFIX = ".bval"
BVEC_SUFFIX = ".bvec"
B0_THRESHOLD = 50.0
MAX_DICOM_HEADERS = 96
MAX_DICOM_CANDIDATES = 1000
DICOM_FIELDS = (
    "SeriesDescription",
    "ProtocolName",
    "SeriesNumber",
    "Modality",
    "Rows",
    "Columns",
    "PixelSpacing",
    "SliceThickness",
    "SpacingBetweenSlices",
)
DIFFUSION_BVALUE_KEYWORDS = ("DiffusionBValue",)
DIFFUSION_ORIENTATION_KEYWORDS = ("DiffusionGradientOrientation",)
DICOM_MODALITY_KEYWORDS = {
    "T1": ("t1", "mprage", "bravo", "spgr", "tfl", "3dt1"),
    "MRA": ("mra", "tof", "angio", "artery"),
    "MRV": ("mrv", "venography", "venogram", "vein", "venous"),
    "DTI": ("dti", "dwi", "diff", "diffusion", "noddi", "dir"),
}
DICOM_MODALITY_FIELDS = {
    "T1": "dicom_t1_source",
    "MRA": "dicom_mra_source",
    "MRV": "dicom_mrv_source",
    "DTI": "dicom_dti_source",
}
DICOM_DERIVED_KEYWORDS = (
    "mip",
    "batchmip",
    "mpr",
    "crop",
    "scout",
    "motion",
    "curve",
    "localizer",
    "survey",
    "ref",
)
DTI_DERIVED_KEYWORDS = ("b0", "ref", "mip", "batchmip", "adc", "trace", "fa", "colfa")
MAX_DICOM_SERIES_DIRS = 300


def inspect_path_payload(payload: dict[str, Any]) -> dict[str, Any]:
    path_text = _clean_path_text(payload.get("path"))
    field = str(payload.get("field") or "")
    related = payload.get("related") if isinstance(payload.get("related"), dict) else {}

    if not path_text:
        return _result(False, "No path selected.", {"path": "", "exists": False})

    path = Path(path_text)
    try:
        exists = path.exists()
    except OSError as exc:
        return _result(False, f"Could not access path: {exc}", {"path": path_text, "exists": False})

    if not exists:
        return _result(False, "Path does not exist.", {"path": path_text, "exists": False, "field": field})

    try:
        if path.is_dir():
            return inspect_dicom_directory(path, field=field)

        if not path.is_file():
            return _result(
                False,
                "Path is neither a file nor a directory.",
                {"path": str(path), "exists": True, "field": field},
            )

        name = path.name.lower()
        if _is_nifti(path):
            return inspect_nifti(path, related=related, field=field)
        if name.endswith((BVAL_SUFFIX, BVEC_SUFFIX)):
            return inspect_gradient_file(path, related=related, field=field)

        dicom_result = try_inspect_dicom_file(path, field=field)
        if dicom_result is not None:
            return dicom_result

        return _result(
            False,
            "Unsupported path type. Supported files: .nii, .nii.gz, .bval, .bvec; supported folders: DICOM.",
            {"path": str(path), "exists": True, "field": field, "type": "unsupported"},
        )
    except Exception as exc:
        return _result(
            False,
            f"Could not inspect path: {exc}",
            {"path": str(path), "exists": True, "field": field},
        )


def detect_dicom_series_payload(payload: dict[str, Any]) -> dict[str, Any]:
    path_text = _clean_path_text(payload.get("path"))
    if not path_text:
        return _result(False, "No DICOM root folder selected.", {"path": "", "exists": False})

    root = Path(path_text)
    if not root.exists():
        return _result(False, "DICOM root folder does not exist.", {"path": path_text, "exists": False})
    if not root.is_dir():
        return _result(False, "DICOM root path must be a folder.", {"path": str(root), "exists": True})

    keywords = _keywords_from_payload(payload)
    series_dirs = _candidate_series_directories(root)
    if not series_dirs:
        return _result(
            False,
            "No candidate DICOM series folders were found.",
            {"path": str(root), "exists": True, "type": "dicom_series_detection", "selections": {}},
        )

    directory_infos = [_series_directory_info(path) for path in series_dirs]
    selections: dict[str, dict[str, Any] | None] = {}
    candidates_by_modality: dict[str, list[dict[str, Any]]] = {}

    for modality in ("T1", "MRA", "MRV", "DTI"):
        ranked = [_score_series_directory(info, modality, keywords[modality]) for info in directory_infos]
        ranked.sort(key=lambda item: item["score"], reverse=True)
        candidates_by_modality[modality] = ranked[:30]
        best = ranked[0] if ranked and ranked[0]["eligible"] else None
        selections[DICOM_MODALITY_FIELDS[modality]] = best

    details = {
        "path": str(root),
        "exists": True,
        "type": "dicom_series_detection",
        "series_dir_count": len(series_dirs),
        "series_dir_limit": MAX_DICOM_SERIES_DIRS,
        "dicom_header_reader": _dicom_header_reader_status(directory_infos),
        "selections": selections,
        "candidates": candidates_by_modality,
    }
    return _result(True, _format_dicom_detection_summary(selections), details)


def inspect_nifti(path: Path, related: dict[str, Any] | None = None, field: str = "") -> dict[str, Any]:
    try:
        import nibabel as nib
    except ImportError:
        return _result(
            False,
            "nibabel is not installed; NIfTI headers cannot be read.",
            {"path": str(path), "exists": True, "field": field, "type": "nifti"},
        )

    img = nib.load(str(path))
    header = img.header
    shape = [int(dim) for dim in img.shape]
    ndim = len(shape)
    zooms = [float(value) for value in header.get_zooms()]
    spatial_dims = min(3, ndim, len(zooms))
    voxel_size = [_round_float(zooms[index], 4) for index in range(spatial_dims)]
    fov = [_round_float(shape[index] * voxel_size[index], 4) for index in range(spatial_dims)]
    affine = _matrix_to_json(img.affine)
    try:
        orientation = [axis or "?" for axis in nib.aff2axcodes(img.affine)]
    except Exception:
        orientation = []
    volume_count = int(np.prod(shape[3:])) if ndim > 3 else 1

    details: dict[str, Any] = {
        "path": str(path),
        "exists": True,
        "field": field,
        "type": "nifti",
        "shape": shape,
        "ndim": ndim,
        "volume_count": volume_count,
        "voxel_size_mm": voxel_size,
        "fov_mm": fov,
        "dtype": str(header.get_data_dtype()),
        "orientation": orientation,
        "affine": affine,
        "file_size": int(path.stat().st_size),
    }

    gradient_paths, gradient_requested = _gradient_paths_for_nifti(path, related or {})
    if gradient_requested or any(item is not None and item.exists() for item in gradient_paths.values()):
        gradient = summarize_gradient_pair(
            gradient_paths.get("bval"),
            gradient_paths.get("bvec"),
            expected_volume_count=volume_count,
        )
        details["gradients"] = gradient["details"]
        details["gradient_summary"] = gradient["summary"]
        if gradient["details"].get("warnings"):
            details["warnings"] = gradient["details"]["warnings"]

    return _result(True, _format_nifti_summary(details), details)


def inspect_gradient_file(path: Path, related: dict[str, Any] | None = None, field: str = "") -> dict[str, Any]:
    paths = _gradient_paths_for_file(path, related or {})
    summary = summarize_gradient_pair(paths.get("bval"), paths.get("bvec"))
    details = summary["details"]
    details["path"] = str(path)
    details["exists"] = True
    details["field"] = field
    details["selected_type"] = "bval" if path.name.lower().endswith(BVAL_SUFFIX) else "bvec"
    return _result(summary["ok"], summary["summary"], details)


def summarize_gradient_pair(
    bval_path: Path | None,
    bvec_path: Path | None,
    expected_volume_count: int | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    bval_details: dict[str, Any] | None = None
    bvec_details: dict[str, Any] | None = None

    if bval_path is not None:
        if bval_path.exists():
            bval_details = _read_bval(bval_path)
        else:
            warnings.append(f"bval file does not exist: {bval_path}")

    if bvec_path is not None:
        if bvec_path.exists():
            bvec_details = _read_bvec(bvec_path)
        else:
            warnings.append(f"bvec file does not exist: {bvec_path}")

    if bval_details is None and bvec_details is None:
        return {
            "ok": False,
            "summary": "No readable bval/bvec file found.",
            "details": {
                "type": "gradient_table",
                "bval_path": str(bval_path) if bval_path else None,
                "bvec_path": str(bvec_path) if bvec_path else None,
                "warnings": warnings,
            },
        }

    bval_count = bval_details.get("count") if bval_details else None
    bvec_count = bvec_details.get("count") if bvec_details else None
    if bval_count is not None and bvec_count is not None and bval_count != bvec_count:
        warnings.append(f"bval count ({bval_count}) does not match bvec count ({bvec_count}).")

    if expected_volume_count is not None:
        if bval_count is not None and bval_count != expected_volume_count:
            warnings.append(f"bval count ({bval_count}) does not match NIfTI volumes ({expected_volume_count}).")
        if bvec_count is not None and bvec_count != expected_volume_count:
            warnings.append(f"bvec count ({bvec_count}) does not match NIfTI volumes ({expected_volume_count}).")

    unique_b_values = bval_details.get("unique_b_values") if bval_details else []
    b0_count = bval_details.get("b0_count") if bval_details else None
    if bval_details is not None:
        gradient_direction_count = bval_details.get("gradient_direction_count")
    elif bvec_details is not None:
        gradient_direction_count = bvec_details.get("gradient_direction_count")
    else:
        gradient_direction_count = None

    count = bval_count if bval_count is not None else bvec_count
    details: dict[str, Any] = {
        "type": "gradient_table",
        "bval_path": str(bval_path) if bval_path else None,
        "bvec_path": str(bvec_path) if bvec_path else None,
        "count": count,
        "shape": bval_details.get("shape") if bval_details else bvec_details.get("shape"),
        "unique_b_values": unique_b_values,
        "b0_count": b0_count,
        "gradient_direction_count": gradient_direction_count,
        "bval": bval_details,
        "bvec": bvec_details,
        "expected_volume_count": expected_volume_count,
        "count_matches_expected": (
            None
            if expected_volume_count is None or count is None
            else count == expected_volume_count
        ),
        "warnings": warnings,
    }
    return {"ok": True, "summary": _format_gradient_summary(details), "details": details}


def inspect_dicom_directory(path: Path, field: str = "") -> dict[str, Any]:
    try:
        import pydicom
    except ImportError:
        return _result(
            False,
            "pydicom is not installed; DICOM headers cannot be read.",
            {"path": str(path), "exists": True, "field": field, "type": "dicom_directory"},
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        headers, scan_details = _sample_dicom_headers(path, pydicom)
        series = _summarize_dicom_series(headers) if headers else []
        has_b_value = any(_dataset_has_keyword(ds, DIFFUSION_BVALUE_KEYWORDS) for _, ds in headers)
        has_gradient_orientation = any(_dataset_has_keyword(ds, DIFFUSION_ORIENTATION_KEYWORDS) for _, ds in headers)
    if not headers:
        return _result(
            False,
            "No DICOM headers were found in this folder.",
            {
                "path": str(path),
                "exists": True,
                "field": field,
                "type": "dicom_directory",
                **scan_details,
            },
        )

    series_uid_count = len(series)
    details = {
        "path": str(path),
        "exists": True,
        "field": field,
        "type": "dicom_directory",
        "sampled_header_count": len(headers),
        "series_instance_uid_count": series_uid_count,
        "series": series,
        "has_diffusion_b_value": has_b_value,
        "has_diffusion_gradient_orientation": has_gradient_orientation,
        **scan_details,
    }
    return _result(True, _format_dicom_summary(details), details)


def try_inspect_dicom_file(path: Path, field: str = "") -> dict[str, Any] | None:
    if path.suffix.lower() != ".dcm":
        return None
    try:
        import pydicom
    except ImportError:
        return _result(
            False,
            "pydicom is not installed; DICOM headers cannot be read.",
            {"path": str(path), "exists": True, "field": field, "type": "dicom_file"},
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception as exc:
        return _result(
            False,
            f"Could not read DICOM header: {exc}",
            {"path": str(path), "exists": True, "field": field, "type": "dicom_file"},
        )
    if not _looks_like_dicom(ds):
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        series = _summarize_dicom_series([(path, ds)])
        has_b_value = _dataset_has_keyword(ds, DIFFUSION_BVALUE_KEYWORDS)
        has_gradient_orientation = _dataset_has_keyword(ds, DIFFUSION_ORIENTATION_KEYWORDS)
    details = {
        "path": str(path),
        "exists": True,
        "field": field,
        "type": "dicom_file",
        "sampled_header_count": 1,
        "series_instance_uid_count": len(series),
        "series": series,
        "has_diffusion_b_value": has_b_value,
        "has_diffusion_gradient_orientation": has_gradient_orientation,
    }
    return _result(True, _format_dicom_summary(details), details)


def _sample_dicom_headers(root: Path, pydicom: Any) -> tuple[list[tuple[Path, Any]], dict[str, Any]]:
    headers: list[tuple[Path, Any]] = []
    candidates_scanned = 0
    read_errors = 0
    candidate_limit_reached = False
    header_limit_reached = False

    for candidate in _iter_dicom_candidates(root):
        if candidates_scanned >= MAX_DICOM_CANDIDATES:
            candidate_limit_reached = True
            break
        candidates_scanned += 1
        try:
            ds = pydicom.dcmread(str(candidate), stop_before_pixels=True, force=True)
        except Exception:
            read_errors += 1
            continue
        if not _looks_like_dicom(ds):
            continue
        headers.append((candidate, ds))
        if len(headers) >= MAX_DICOM_HEADERS:
            header_limit_reached = True
            break

    return headers, {
        "candidate_files_scanned": candidates_scanned,
        "read_errors": read_errors,
        "candidate_scan_limit": MAX_DICOM_CANDIDATES,
        "header_sample_limit": MAX_DICOM_HEADERS,
        "candidate_scan_limit_reached": candidate_limit_reached,
        "header_sample_limit_reached": header_limit_reached,
    }


def _summarize_dicom_series(headers: list[tuple[Path, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[tuple[Path, Any]]] = {}
    for file_path, ds in headers:
        uid = str(getattr(ds, "SeriesInstanceUID", "") or "<missing>")
        groups.setdefault(uid, []).append((file_path, ds))

    series: list[dict[str, Any]] = []
    for uid, items in groups.items():
        datasets = [ds for _, ds in items]
        fields = {name: _most_common_dicom_value(datasets, name) for name in DICOM_FIELDS}
        sop_uids = {str(getattr(ds, "SOPInstanceUID", "") or index) for index, ds in enumerate(datasets)}
        series.append(
            {
                "SeriesInstanceUID": uid,
                "instance_count": len(items),
                "unique_sop_instance_count": len(sop_uids),
                "sample_files": [str(file_path) for file_path, _ in items[:5]],
                "fields": fields,
                "has_diffusion_b_value": any(_dataset_has_keyword(ds, DIFFUSION_BVALUE_KEYWORDS) for ds in datasets),
                "has_diffusion_gradient_orientation": any(
                    _dataset_has_keyword(ds, DIFFUSION_ORIENTATION_KEYWORDS) for ds in datasets
                ),
            }
        )

    series.sort(key=lambda item: int(item["instance_count"]), reverse=True)
    return series


def _read_bval(path: Path) -> dict[str, Any]:
    array = _load_numeric_text(path)
    values = np.atleast_1d(array).astype(float).reshape(-1)
    b0_count = int(np.count_nonzero(values <= B0_THRESHOLD))
    gradient_direction_count = int(np.count_nonzero(values > B0_THRESHOLD))
    return {
        "path": str(path),
        "shape": _shape_of(array),
        "count": int(values.size),
        "unique_b_values": _unique_b_values(values),
        "b0_count": b0_count,
        "gradient_direction_count": gradient_direction_count,
    }


def _read_bvec(path: Path) -> dict[str, Any]:
    array = _load_numeric_text(path)
    vectors = _normalize_bvec_array(array)
    if vectors is not None:
        norms = np.linalg.norm(vectors, axis=0)
        count = int(vectors.shape[1])
        gradient_direction_count = int(np.count_nonzero(norms > 1e-6))
    else:
        count = int(np.atleast_1d(array).size)
        gradient_direction_count = None
    return {
        "path": str(path),
        "shape": _shape_of(array),
        "count": count,
        "gradient_direction_count": gradient_direction_count,
    }


def _load_numeric_text(path: Path) -> np.ndarray:
    try:
        array = np.loadtxt(str(path), dtype=float)
    except ValueError as exc:
        raise ValueError(f"Could not parse numeric text file {path}: {exc}") from exc
    return np.asarray(array, dtype=float)


def _normalize_bvec_array(array: np.ndarray) -> np.ndarray | None:
    array = np.asarray(array, dtype=float)
    if array.ndim == 0:
        return None
    if array.ndim == 1:
        if array.size == 3:
            return array.reshape(3, 1)
        if array.size > 3 and array.size % 3 == 0:
            return array.reshape(3, array.size // 3)
        return None
    if array.ndim != 2:
        return None
    if array.shape[0] == 3:
        return array
    if array.shape[1] == 3:
        return array.T
    return None


def _gradient_paths_for_nifti(path: Path, related: dict[str, Any]) -> tuple[dict[str, Path | None], bool]:
    base = _nifti_base(path)
    requested = False
    bval = _related_path(related, "bval")
    bvec = _related_path(related, "bvec")
    if bval is not None:
        requested = True
    else:
        inferred_bval = path.with_name(f"{base}{BVAL_SUFFIX}")
        bval = inferred_bval if inferred_bval.exists() else None
    if bvec is not None:
        requested = True
    else:
        inferred_bvec = path.with_name(f"{base}{BVEC_SUFFIX}")
        bvec = inferred_bvec if inferred_bvec.exists() else None
    return {"bval": bval, "bvec": bvec}, requested


def _gradient_paths_for_file(path: Path, related: dict[str, Any]) -> dict[str, Path | None]:
    name = path.name.lower()
    bval = _related_path(related, "bval")
    bvec = _related_path(related, "bvec")
    if name.endswith(BVAL_SUFFIX):
        bval = bval or path
        bvec = bvec or path.with_suffix(BVEC_SUFFIX)
    elif name.endswith(BVEC_SUFFIX):
        bvec = bvec or path
        bval = bval or path.with_suffix(BVAL_SUFFIX)
    return {"bval": bval, "bvec": bvec}


def _iter_dicom_candidates(root: Path):
    ignored_suffixes = {
        ".bval",
        ".bvec",
        ".gz",
        ".glb",
        ".jpeg",
        ".jpg",
        ".json",
        ".log",
        ".m",
        ".mat",
        ".nii",
        ".png",
        ".txt",
        ".xml",
    }
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.name.startswith("."):
            continue
        if candidate.suffix.lower() in ignored_suffixes:
            continue
        yield candidate


def _candidate_series_directories(root: Path) -> list[Path]:
    try:
        children = [child for child in sorted(root.iterdir(), key=lambda item: item.name.lower()) if child.is_dir()]
    except OSError:
        return []
    if not children:
        return [root]
    return children[:MAX_DICOM_SERIES_DIRS]


def _series_directory_info(path: Path) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    instance_count: int | None = None
    series_uid_count: int | None = None
    has_b_value = False
    has_gradient_orientation = False

    try:
        import pydicom
    except ImportError:
        pydicom = None
    header_reader = "pydicom" if pydicom is not None else "filename_only"

    if pydicom is not None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                headers, _ = _sample_dicom_headers(path, pydicom)
                if headers:
                    series = _summarize_dicom_series(headers)
                    series_uid_count = len(series)
                    if series:
                        fields = series[0].get("fields") or {}
                        instance_count = int(series[0].get("instance_count") or 0)
                    has_b_value = any(_dataset_has_keyword(ds, DIFFUSION_BVALUE_KEYWORDS) for _, ds in headers)
                    has_gradient_orientation = any(
                        _dataset_has_keyword(ds, DIFFUSION_ORIENTATION_KEYWORDS) for _, ds in headers
                    )
        except Exception:
            headers = []

    text_parts = [
        path.name,
        str(fields.get("SeriesDescription") or ""),
        str(fields.get("ProtocolName") or ""),
        str(fields.get("SeriesNumber") or ""),
        str(fields.get("Modality") or ""),
    ]
    text = " ".join(text_parts).lower()
    return {
        "path": str(path),
        "name": path.name,
        "text": text,
        "fields": fields,
        "instance_count": instance_count,
        "series_uid_count": series_uid_count,
        "has_diffusion_b_value": has_b_value,
        "has_diffusion_gradient_orientation": has_gradient_orientation,
        "header_reader": header_reader,
    }


def _keywords_from_payload(payload: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    raw = payload.get("keywords") if isinstance(payload.get("keywords"), dict) else {}
    result: dict[str, tuple[str, ...]] = {}
    aliases = {
        "T1": ("t1", "dicom_t1_keywords"),
        "MRA": ("mra", "dicom_mra_keywords"),
        "MRV": ("mrv", "dicom_mrv_keywords"),
        "DTI": ("dti", "dicom_dti_keywords"),
    }
    for modality, keys in aliases.items():
        values: list[str] = []
        for key in keys:
            values.extend(_string_list(raw.get(key)))
        result[modality] = tuple(values) or DICOM_MODALITY_KEYWORDS[modality]
    return result


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    return [part.lower() for part in str(value).replace(";", ",").replace(" ", ",").split(",") if part.strip()]


def _score_series_directory(info: dict[str, Any], modality: str, keywords: tuple[str, ...]) -> dict[str, Any]:
    text = str(info.get("text") or "").lower()
    tokens = _text_tokens(text)
    compact = "".join(ch for ch in text if ch.isalnum())
    matched = _matched_modality_keywords(text, tokens, compact, keywords)

    derived = _matched_series_keywords(text, tokens, compact, DICOM_DERIVED_KEYWORDS)
    dti_derived = _matched_series_keywords(text, tokens, compact, DTI_DERIVED_KEYWORDS)

    eligible = bool(matched)
    score = 100.0 * len(matched)
    reason = "matched keywords" if matched else "no modality keyword match"

    if modality in {"T1", "MRA", "MRV"}:
        if derived:
            score -= 160.0 + 35.0 * len(derived)
            reason += "; downranked derived/reformatted series"
            eligible = False
        else:
            score += 40.0
    else:
        direction_count = _direction_count_from_text(text)
        if direction_count:
            score += min(float(direction_count), 150.0)
        if info.get("has_diffusion_b_value") or info.get("has_diffusion_gradient_orientation"):
            score += 40.0
        if dti_derived:
            score -= 180.0 + 35.0 * len(dti_derived)
            reason += "; downranked derived/reference diffusion series"
            eligible = False
        if "savebyslc" in compact or "saveb" in compact:
            score += 15.0

    fields = info.get("fields") or {}
    series_number = fields.get("SeriesNumber")
    try:
        score += min(float(series_number or 0), 1000.0) / 10000.0
    except (TypeError, ValueError):
        pass

    return {
        "modality": modality,
        "field": DICOM_MODALITY_FIELDS[modality],
        "path": info["path"],
        "name": info["name"],
        "score": round(score, 4),
        "eligible": eligible,
        "reason": reason,
        "matched_keywords": matched,
        "derived_keywords": dti_derived if modality == "DTI" else derived,
        "series_description": fields.get("SeriesDescription"),
        "protocol_name": fields.get("ProtocolName"),
        "series_number": fields.get("SeriesNumber"),
        "instance_count": info.get("instance_count"),
        "series_uid_count": info.get("series_uid_count"),
        "has_diffusion_b_value": info.get("has_diffusion_b_value"),
        "has_diffusion_gradient_orientation": info.get("has_diffusion_gradient_orientation"),
        "header_reader": info.get("header_reader"),
    }


def _dicom_header_reader_status(directory_infos: list[dict[str, Any]]) -> str:
    statuses = {str(info.get("header_reader") or "") for info in directory_infos}
    if "pydicom" in statuses:
        return "pydicom"
    return "filename_only"


def _matched_modality_keywords(
    text: str,
    tokens: set[str],
    compact: str,
    keywords: tuple[str, ...],
) -> list[str]:
    matched: list[str] = []
    for raw_keyword in keywords:
        keyword = raw_keyword.strip().lower()
        if not keyword:
            continue
        compact_keyword = "".join(ch for ch in keyword if ch.isalnum())
        if keyword == "dir":
            hit = "dir" in tokens or _direction_count_from_text(text) > 0
        elif keyword in {"t1", "mra", "mrv", "dti", "dwi", "tof"}:
            hit = keyword in tokens or any(token.startswith(keyword) for token in tokens)
        elif keyword in {"diff", "3dt1"}:
            hit = keyword in tokens or any(token.startswith(keyword) for token in tokens) or compact_keyword in compact
        else:
            hit = keyword in tokens or keyword in text
        if hit:
            matched.append(keyword)
    return matched


def _matched_series_keywords(
    text: str,
    tokens: set[str],
    compact: str,
    keywords: tuple[str, ...],
) -> list[str]:
    matched: list[str] = []
    for keyword in keywords:
        if keyword == "batchmip":
            hit = "batchmip" in compact
        elif keyword in {"mip", "mpr", "ref", "b0", "fa"}:
            hit = keyword in tokens
        else:
            hit = keyword in tokens or keyword in text
        if hit:
            matched.append(keyword)
    return matched


def _text_tokens(text: str) -> set[str]:
    import re

    return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}


def _direction_count_from_text(text: str) -> int:
    import re

    matches = [int(value) for value in re.findall(r"dir(?:ection)?[_-]?(\d+)", text.lower())]
    return max(matches) if matches else 0


def _format_dicom_detection_summary(selections: dict[str, dict[str, Any] | None]) -> str:
    parts = []
    for label, field in (("T1", "dicom_t1_source"), ("MRA", "dicom_mra_source"), ("MRV", "dicom_mrv_source"), ("DTI", "dicom_dti_source")):
        selected = selections.get(field)
        parts.append(f"{label}: {selected['name'] if selected else '未检测到'}")
    return "DICOM 自动检测：" + "；".join(parts)


def _looks_like_dicom(ds: Any) -> bool:
    return any(
        hasattr(ds, key)
        for key in (
            "SOPInstanceUID",
            "SeriesInstanceUID",
            "StudyInstanceUID",
            "Modality",
            "Rows",
            "Columns",
        )
    )


def _dataset_has_keyword(ds: Any, keywords: tuple[str, ...]) -> bool:
    try:
        for element in ds.iterall():
            if getattr(element, "keyword", "") in keywords:
                return True
    except Exception:
        for keyword in keywords:
            if getattr(ds, keyword, None) is not None:
                return True
    return False


def _most_common_dicom_value(datasets: list[Any], field: str) -> Any:
    values = [_json_ready(getattr(ds, field, None)) for ds in datasets]
    values = [value for value in values if value not in (None, "", [])]
    if not values:
        return None
    keys = [_counter_key(value) for value in values]
    winner_key, _ = Counter(keys).most_common(1)[0]
    return values[keys.index(winner_key)]


def _format_nifti_summary(details: dict[str, Any]) -> str:
    shape = "x".join(str(dim) for dim in details["shape"])
    voxel = _format_number_list(details.get("voxel_size_mm", []), decimals=2)
    orientation = "".join(details.get("orientation") or [])
    dtype = details.get("dtype") or ""
    if details.get("volume_count", 1) > 1:
        return f"NIfTI: {shape}, voxel {voxel} mm, volumes {details['volume_count']}, {orientation}, {dtype}"
    fov = _format_number_list(details.get("fov_mm", []), decimals=1)
    return f"NIfTI: {shape}, voxel {voxel} mm, FOV {fov} mm, {orientation}, {dtype}"


def _format_gradient_summary(details: dict[str, Any]) -> str:
    parts: list[str] = []
    if details.get("count") is not None:
        parts.append(f"count {details['count']}")
    bval = details.get("bval")
    if bval:
        parts.append(f"b-values {_format_unique_b_values(bval.get('unique_b_values') or [])}")
        parts.append(f"b0 {bval.get('b0_count')}")
    bvec = details.get("bvec")
    if bvec:
        parts.append(f"bvec shape {_format_shape(bvec.get('shape') or [])}")
    if details.get("gradient_direction_count") is not None:
        parts.append(f"gradients {details['gradient_direction_count']}")
    if details.get("warnings"):
        parts.append("warnings: " + " ".join(details["warnings"]))
    return "Gradient table: " + ", ".join(parts)


def _format_dicom_summary(details: dict[str, Any]) -> str:
    series_count = int(details.get("series_instance_uid_count") or 0)
    sampled_count = int(details.get("sampled_header_count") or 0)
    series = details.get("series") or []
    if series_count > 1:
        return (
            f"DICOM: {series_count} SeriesInstanceUID values detected in {sampled_count} sampled instances; "
            "choose a single-series folder or use auto detection."
    )
    if not series:
        return "DICOM: no readable series information."
    fields = series[0].get("fields") or {}
    description = fields.get("SeriesDescription") or fields.get("ProtocolName")
    if not description:
        description = Path(str(details.get("path") or "")).name or "unnamed series"
    shape = _format_dicom_compact_shape(fields, series[0])
    voxel = _format_dicom_compact_voxel(fields)
    return f"{description}\n{shape}, {voxel}"


def _format_dicom_compact_shape(fields: dict[str, Any], selected_series: dict[str, Any]) -> str:
    rows = _format_integer_like(fields.get("Rows"))
    columns = _format_integer_like(fields.get("Columns"))
    instances = _format_integer_like(selected_series.get("instance_count"))
    if rows and columns and instances:
        return f"({rows},{columns},{instances})"
    if rows and columns:
        return f"({rows},{columns})"
    return "(unknown)"


def _format_dicom_compact_voxel(fields: dict[str, Any]) -> str:
    spacing = _numeric_values(fields.get("PixelSpacing"))
    slice_spacing = _first_numeric(fields.get("SpacingBetweenSlices"))
    if slice_spacing is None:
        slice_spacing = _first_numeric(fields.get("SliceThickness"))
    if len(spacing) >= 2 and slice_spacing is not None:
        values = [spacing[0], spacing[1], slice_spacing]
    elif len(spacing) >= 2:
        values = [spacing[0], spacing[1]]
    else:
        values = []
    if not values:
        return "unknown voxel"
    return "*".join(_format_compact_number(value) for value in values) + "mm"


def _numeric_values(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = [value]
    result: list[float] = []
    for item in values:
        try:
            numeric = float(item)
        except (TypeError, ValueError):
            continue
        if isfinite(numeric):
            result.append(numeric)
    return result


def _first_numeric(value: Any) -> float | None:
    values = _numeric_values(value)
    return values[0] if values else None


def _format_integer_like(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else ""
    if not isfinite(numeric):
        return ""
    rounded = round(numeric)
    if abs(numeric - rounded) < 1e-6:
        return str(int(rounded))
    return _format_compact_number(numeric)


def _format_compact_number(value: Any, digits: int = 4) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not isfinite(numeric):
        return "nan"
    text = f"{numeric:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def _unique_b_values(values: np.ndarray) -> list[dict[str, Any]]:
    counter: Counter[Any] = Counter(_b_value_bucket(float(value)) for value in values)
    return [{"value": value, "count": int(count)} for value, count in sorted(counter.items(), key=lambda item: item[0])]


def _b_value_bucket(value: float) -> int | float:
    rounded = round(value)
    if abs(value - rounded) < 0.01:
        return int(rounded)
    return _round_float(value, 2)


def _format_unique_b_values(values: list[dict[str, Any]]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{item['value']}({item['count']})" for item in values)


def _format_number_list(values: list[Any], decimals: int) -> str:
    if not values:
        return "unknown"
    return "x".join(_format_number(value, decimals=decimals) for value in values)


def _format_number(value: Any, decimals: int = 2) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not isfinite(numeric):
        return "nan"
    return f"{numeric:.{decimals}f}"


def _format_shape(shape: list[Any]) -> str:
    return "x".join(str(part) for part in shape) if shape else "unknown"


def _format_dicom_value(value: Any) -> str:
    if isinstance(value, list):
        return "x".join(_format_number(item, decimals=3) for item in value)
    return str(value)


def _matrix_to_json(matrix: Any) -> list[list[Any]]:
    array = np.asarray(matrix, dtype=float)
    return [[_round_float(float(value), 8) for value in row] for row in array]


def _round_float(value: float, digits: int = 4) -> float | None:
    if not isfinite(value):
        return None
    rounded = round(float(value), digits)
    if rounded == -0.0:
        return 0.0
    return rounded


def _json_ready(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return _round_float(value, 6)
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
        try:
            return [_json_ready(item) for item in value]
        except TypeError:
            pass
    return str(value)


def _counter_key(value: Any) -> str:
    return repr(value)


def _shape_of(array: np.ndarray) -> list[int]:
    if array.ndim == 0:
        return [1]
    return [int(dim) for dim in array.shape]


def _clean_path_text(value: Any) -> str:
    return str(value or "").strip().strip('"').strip("'").strip()


def _related_path(related: dict[str, Any], key: str) -> Path | None:
    value = _clean_path_text(related.get(key))
    return Path(value) if value else None


def _nifti_base(path: Path) -> str:
    name = path.name
    lower = name.lower()
    if lower.endswith(".nii.gz"):
        return name[:-7]
    if lower.endswith(".nii"):
        return name[:-4]
    return path.stem


def _is_nifti(path: Path) -> bool:
    return path.name.lower().endswith(NIFTI_SUFFIXES)


def _result(ok: bool, summary: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"ok": bool(ok), "summary": summary, "details": details}
