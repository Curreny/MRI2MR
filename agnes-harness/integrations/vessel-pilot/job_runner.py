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
from parameters import MODALITIES, normalize_parameters, parameter_names, target_vessels


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


def conversion_result(case_dir: Path, conversion_mode: str = "vessel") -> dict[str, Any]:
    if conversion_mode == "nifti":
        outputs = sorted((case_dir / "patient_input" / "nifti").glob("*.nii"))
        if not outputs:
            raise PipelineFailure("NO_NIFTI_OUTPUT", "No NIfTI series were produced")
        artifacts: dict[str, Any] = {}
        validation: dict[str, Any] = {}
        for path in outputs:
            try:
                image = nib.load(str(path))
                shape = [int(value) for value in image.shape]
                zooms = [float(value) for value in image.header.get_zooms()]
                if len(shape) < 2 or any(value < 1 for value in shape):
                    raise ValueError(f"invalid image shape: {shape}")
                if not np.isfinite(image.affine).all() or any(
                    not np.isfinite(value) or value <= 0 for value in zooms
                ):
                    raise ValueError("invalid affine or voxel sizes")
                # Force a payload read so a truncated file is not reported as a successful conversion.
                np.asanyarray(image.dataobj)
                validation[path.name] = {"shape": shape, "voxel_size": zooms}
                artifacts[path.name] = {"path": str(path), "size": path.stat().st_size, "sha256": hash_file(path)}
            except Exception as exc:
                raise PipelineFailure("INVALID_CONVERTED_NIFTI", str(exc), {"path": str(path)}) from exc
        return {
            "conversion_mode": "nifti",
            "outputs": {path.name: str(path) for path in outputs},
            "artifacts": artifacts,
            "validation": validation,
        }
    if conversion_mode not in MODALITIES:
        raise ValueError("Unsupported conversion mode")
    outputs = {
        name: case_dir / "patient_input" / f"{name.upper()}.nii"
        for name in MODALITIES[conversion_mode]
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
            "Conversion is missing required modalities: " + ", ".join(missing),
            {
                "required_modalities": list(outputs),
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


def candidate_commands(spec: dict[str, Any]) -> list[tuple[str, list[str], Path]]:
    """Build only the requested stages; paths always come from the controlled case directory."""
    case_dir = Path(spec["case_dir"])
    payload = spec["payload"]
    target = payload.get("target", "both")
    parameters = normalize_parameters(target, payload["parameters"])
    candidate_dir = case_dir / "candidates" / payload["candidate_id"]
    commands = []
    for vessel in target_vessels(target):
        output = candidate_dir / f"{vessel}.glb"
        # A vein-only task uses MRV as its spatial reference, so it does not need MRA or T1.
        reference = case_dir / "patient_input" / ("MRV.nii" if target == "vein" else "MRA.nii")
        command = [spec["python_exe"], spec["vascular_script"], "--mode", vessel,
                   "--base-data-dir", str(case_dir), "--reference-file", str(reference),
                   f"--{vessel}-output-file", str(output)]
        for name, value in parameters.items():
            if name in parameter_names(vessel):
                command.extend(["--" + name.replace("_", "-"), str(value)])
        if vessel == "vein":
            mrv = case_dir / "patient_input" / "MRV.nii"
            signature = {"source": hash_file(mrv), **{key: value for key, value in parameters.items() if key.startswith("mrv_frangi_sigmas_")}}
            cache_key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20]
            cache = case_dir / "temp" / f"frangi_{cache_key}.nii"
            command.extend(["--mrv-frangi-cache-file", str(cache)])
        commands.append((f"{vessel}_reconstruction", command, output))
    return commands


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
            conversion_mode = payload.get("conversion_mode", "vessel")
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
                *(["ALL"] if conversion_mode == "nifti" else [name.upper() for name in MODALITIES[conversion_mode]]),
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
            result = conversion_result(case_dir, conversion_mode)
            case_manifest = json.loads(case_manifest_path.read_text(encoding="utf-8"))
            case_manifest["conversion_status"] = "succeeded"
            case_manifest["converted_at"] = now()
            case_manifest["conversion_outputs"] = result["artifacts"]
            case_manifest["nifti_outputs"] = result["outputs"]
            case_manifest.pop("conversion_error", None)
            atomic_json(case_manifest_path, case_manifest)
        elif spec["kind"] == "candidate":
            result = {"candidate_id": payload["candidate_id"], "target": payload.get("target", "both")}
            for phase, command, output in candidate_commands(spec):
                set_phase(phase)
                run_command(command, log_path)
                if not output.is_file() or output.stat().st_size == 0:
                    raise RuntimeError(f"Candidate did not produce a non-empty GLB: {output.name}")
                result[f"{output.stem}_glb"] = str(output)
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
