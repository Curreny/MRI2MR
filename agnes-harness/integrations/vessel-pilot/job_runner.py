from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np


class PipelineFailure(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_command(command: list[str], log_path: Path) -> None:
    with log_path.open("ab") as log:
        log.write(("\n$ " + subprocess.list2cmdline(command) + "\n").encode("utf-8"))
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
    if completed.returncode != 0:
        raise PipelineFailure(
            "EXTERNAL_COMMAND_FAILED",
            f"Vascular command failed with exit code {completed.returncode}",
            {"exit_code": completed.returncode},
        )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clear_conversion_outputs(case_dir: Path) -> None:
    patient_input = case_dir / "patient_input"
    patient_input.mkdir(parents=True, exist_ok=True)
    for stale_name in ("MRA.nii", "MRV.nii", "dicom_selection.json"):
        (patient_input / stale_name).unlink(missing_ok=True)


def conversion_result(case_dir: Path) -> dict[str, Any]:
    outputs = {
        "mra": case_dir / "patient_input" / "MRA.nii",
        "mrv": case_dir / "patient_input" / "MRV.nii",
    }
    available = [
        name for name, path in outputs.items() if path.is_file() and path.stat().st_size > 0
    ]
    missing = [name for name in outputs if name not in available]
    selection_path = case_dir / "patient_input" / "dicom_selection.json"
    selection: dict[str, Any] | None = None
    if selection_path.is_file():
        try:
            loaded = json.loads(selection_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                selection = loaded
        except (OSError, ValueError):
            selection = None
    if missing:
        raise PipelineFailure(
            "MISSING_REQUIRED_MODALITY",
            "Conversion requires both MRA and MRV; missing: " + ", ".join(missing),
            {
                "required_modalities": ["mra", "mrv"],
                "available_modalities": available,
                "missing_modalities": missing,
                "selection_report": str(selection_path) if selection_path.is_file() else None,
                "selection": selection,
            },
        )
    validation: dict[str, Any] = {}
    for name, path in outputs.items():
        try:
            image = nib.load(str(path))
            shape = [int(value) for value in image.shape]
            affine = np.asarray(image.affine, dtype=float)
            zooms = [float(value) for value in image.header.get_zooms()[:3]]
            if len(shape) != 3 or any(value <= 1 for value in shape):
                raise ValueError(f"expected non-degenerate 3D volume, got {shape}")
            if affine.shape != (4, 4) or not np.isfinite(affine).all():
                raise ValueError("affine contains non-finite values")
            if len(zooms) != 3 or any(not np.isfinite(value) or value <= 0 for value in zooms):
                raise ValueError(f"invalid voxel sizes: {zooms}")
            validation[name] = {"shape": shape, "voxel_size": zooms}
        except Exception as exc:
            raise PipelineFailure(
                "INVALID_CONVERTED_NIFTI",
                f"Converted {name.upper()} is not a usable 3D NIfTI: {exc}",
                {"modality": name, "path": str(path)},
            ) from exc
    if selection:
        selected_sources: dict[str, str] = {}
        for record in selection.get("records", []):
            if not isinstance(record, dict):
                continue
            modality = str(record.get("modality", "")).lower()
            selected = record.get("selected_candidate")
            if (
                modality in outputs
                and isinstance(selected, dict)
                and isinstance(selected.get("path"), str)
            ):
                selected_sources[modality] = selected["path"]
        if (
            "mra" in selected_sources
            and "mrv" in selected_sources
            and os.path.normcase(os.path.abspath(selected_sources["mra"]))
            == os.path.normcase(os.path.abspath(selected_sources["mrv"]))
        ):
            raise PipelineFailure(
                "AMBIGUOUS_MODALITY_SELECTION",
                "MRA and MRV resolved to the same converted series",
                {"selected_sources": selected_sources, "selection_report": str(selection_path)},
            )
    return {
        "outputs": {name: str(path) for name, path in outputs.items()},
        "artifacts": {
            name: {"sha256": hash_file(path), "size": path.stat().st_size}
            for name, path in outputs.items()
        },
        "validation": validation,
        "selection_report": str(selection_path) if selection_path.is_file() else None,
        "selection": selection,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    spec_path = Path(args.spec).resolve(strict=True)
    job_dir = spec_path.parent
    state_path = job_dir / "state.json"
    log_path = job_dir / "commands.log"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({"status": "running", "phase": "starting", "started_at": now(), "pid": os.getpid()})
    atomic_json(state_path, state)

    def set_phase(phase: str) -> None:
        state["phase"] = phase
        atomic_json(state_path, state)

    try:
        python = spec["python_exe"]
        script = spec["vascular_script"]
        case_dir = Path(spec["case_dir"])
        payload = spec["payload"]
        if spec["kind"] == "conversion":
            set_phase("dicom_conversion")
            clear_conversion_outputs(case_dir)
            case_manifest_path = case_dir / "case.json"
            case_manifest = json.loads(case_manifest_path.read_text(encoding="utf-8"))
            case_manifest["conversion_status"] = "running"
            case_manifest.pop("conversion_error", None)
            atomic_json(case_manifest_path, case_manifest)
            command = [
                python,
                script,
                "--mode",
                "dicom_convert",
                "--dicom-dir",
                payload["source_path"],
                "--dicom-modalities",
                "MRA",
                "MRV",
                "--base-data-dir",
                str(case_dir),
                "--dcm2niix-exe",
                spec["dcm2niix_exe"],
            ]
            if payload.get("decompress_with_dcmtk", True):
                command.extend(
                    ["--dicom-decompress-dcmtk", "--dcmtk-dcmdjpeg-exe", spec["dcmdjpeg_exe"]]
                )
            try:
                run_command(command, log_path)
            except PipelineFailure as exc:
                raise PipelineFailure(
                    "DICOM_CONVERSION_FAILED",
                    str(exc),
                    {**exc.details, "command_log": str(log_path)},
                ) from exc
            result = conversion_result(case_dir)
            case_manifest = json.loads(case_manifest_path.read_text(encoding="utf-8"))
            case_manifest["conversion_status"] = "succeeded"
            case_manifest["converted_at"] = now()
            case_manifest["conversion_outputs"] = result["artifacts"]
            case_manifest.pop("conversion_error", None)
            atomic_json(case_manifest_path, case_manifest)
        elif spec["kind"] == "candidate":
            candidate_id = payload["candidate_id"]
            parameters = payload["parameters"]
            candidate_dir = case_dir / "candidates" / candidate_id
            artery = candidate_dir / "artery.glb"
            vein = candidate_dir / "vein.glb"
            mrv = case_dir / "patient_input" / "MRV.nii"
            cache_key = hash_file(mrv)[:16]
            cache = case_dir / "temp" / f"frangi_{cache_key}.nii"
            set_phase("artery_reconstruction")
            run_command(
                [
                    python,
                    script,
                    "--mode",
                    "artery",
                    "--base-data-dir",
                    str(case_dir),
                    "--reference-modality",
                    "auto",
                    "--vessel-threshold",
                    str(parameters["vessel_threshold"]),
                    "--artery-output-file",
                    str(artery),
                ],
                log_path,
            )
            set_phase("vein_reconstruction")
            run_command(
                [
                    python,
                    script,
                    "--mode",
                    "vein",
                    "--base-data-dir",
                    str(case_dir),
                    "--reference-modality",
                    "auto",
                    "--mrv-frangi-cache-file",
                    str(cache),
                    "--mrv-weak-grow-tolerance",
                    str(parameters["mrv_weak_grow_tolerance"]),
                    "--mrv-post-process-min-size",
                    str(parameters["mrv_post_process_min_size"]),
                    "--vein-output-file",
                    str(vein),
                ],
                log_path,
            )
            missing = [path.name for path in (artery, vein) if not path.is_file() or path.stat().st_size == 0]
            if missing:
                raise RuntimeError(f"Candidate did not produce valid GLB files: {', '.join(missing)}")
            result = {"candidate_id": candidate_id, "artery_glb": str(artery), "vein_glb": str(vein)}
        else:
            raise ValueError(f"Unsupported job kind: {spec['kind']}")
        state.update({"status": "succeeded", "phase": "complete", "finished_at": now(), "result": result})
        atomic_json(state_path, state)
        return 0
    except Exception as exc:
        if spec.get("kind") == "conversion":
            try:
                case_manifest_path = Path(spec["case_dir"]) / "case.json"
                case_manifest = json.loads(case_manifest_path.read_text(encoding="utf-8"))
                case_manifest["conversion_status"] = "failed"
                case_manifest["conversion_error"] = {
                    "code": exc.code if isinstance(exc, PipelineFailure) else "PIPELINE_FAILED",
                    "message": str(exc),
                    "details": exc.details if isinstance(exc, PipelineFailure) else {},
                }
                atomic_json(case_manifest_path, case_manifest)
            except Exception:
                pass
        state.update(
            {
                "status": "failed",
                "phase": "failed",
                "finished_at": now(),
                "error": {
                    "code": exc.code if isinstance(exc, PipelineFailure) else "PIPELINE_FAILED",
                    "message": str(exc),
                    "details": exc.details if isinstance(exc, PipelineFailure) else {},
                },
            }
        )
        atomic_json(state_path, state)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
