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
        raise RuntimeError(f"Vascular command failed with exit code {completed.returncode}")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
            run_command(command, log_path)
            outputs = {
                "mra": case_dir / "patient_input" / "MRA.nii",
                "mrv": case_dir / "patient_input" / "MRV.nii",
            }
            missing = [name for name, path in outputs.items() if not path.is_file()]
            if missing:
                raise RuntimeError(f"Conversion did not produce: {', '.join(missing)}")
            case_manifest_path = case_dir / "case.json"
            case_manifest = json.loads(case_manifest_path.read_text(encoding="utf-8"))
            case_manifest["conversion_status"] = "succeeded"
            case_manifest["converted_at"] = now()
            atomic_json(case_manifest_path, case_manifest)
            result = {"outputs": {name: str(path) for name, path in outputs.items()}}
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
                atomic_json(case_manifest_path, case_manifest)
            except Exception:
                pass
        state.update(
            {
                "status": "failed",
                "phase": "failed",
                "finished_at": now(),
                "error": {"code": "PIPELINE_FAILED", "message": str(exc)},
            }
        )
        atomic_json(state_path, state)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
