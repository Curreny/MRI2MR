from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
ARTERY_THRESHOLDS = (700.0, 800.0, 900.0)
VEIN_TOLERANCES = (0.83, 0.85, 0.88)
VEIN_MIN_SIZES = (800, 1000, 1500)
TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}
MAX_JOB_WAIT_SECONDS = 55


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def validate_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"{label} must match {ID_RE.pattern}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_fingerprint(root: Path, files: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: str(item).lower()):
        stat = path.stat()
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()


@dataclass(frozen=True)
class Settings:
    project_root: Path
    case_root: Path
    input_roots: tuple[Path, ...]
    python_exe: Path
    vascular_script: Path
    runner_script: Path
    dcm2niix_exe: Path
    dcmdjpeg_exe: Path
    max_glb_bytes: int = 80 * 1024 * 1024
    max_vertices: int = 1_000_000
    max_faces: int = 1_500_000

    @classmethod
    def discover(
        cls,
        server_file: Path,
        case_root: Path | None = None,
        input_roots: Iterable[Path] = (),
    ) -> "Settings":
        project_root = server_file.resolve().parents[3]
        resolved_case_root = (case_root or project_root / "workspace" / "vessel-pilot").resolve()
        roots = tuple(path.resolve() for path in input_roots) or (
            (project_root / "workspace").resolve(),
        )
        return cls(
            project_root=project_root,
            case_root=resolved_case_root,
            input_roots=roots,
            python_exe=project_root / "runtime" / "python" / "BrainAAL" / "python.exe",
            vascular_script=project_root / "scripts" / "Vascular_cmd.py",
            runner_script=server_file.resolve().with_name("job_runner.py"),
            dcm2niix_exe=project_root / "dcm2niix_win" / "dcm2niix.exe",
            dcmdjpeg_exe=(
                project_root
                / "dcmtk-3.7.0-win64-dynamic"
                / "dcmtk-3.7.0-win64-dynamic"
                / "bin"
                / "dcmdjpeg.exe"
            ),
        )


class VesselPilotService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.case_root.mkdir(parents=True, exist_ok=True)

    def startup_check(self) -> dict[str, Any]:
        required = {
            "python": self.settings.python_exe,
            "vascular_script": self.settings.vascular_script,
            "job_runner": self.settings.runner_script,
            "dcm2niix": self.settings.dcm2niix_exe,
            "dcmdjpeg": self.settings.dcmdjpeg_exe,
        }
        missing = [name for name, path in required.items() if not path.is_file()]
        if missing:
            raise RuntimeError(f"Missing VesselPilot runtime files: {', '.join(missing)}")
        return {
            "case_root": str(self.settings.case_root),
            "input_roots": [str(path) for path in self.settings.input_roots],
            "runtime": {name: str(path) for name, path in required.items()},
        }

    def choose_dicom_folder(self) -> dict[str, Any]:
        """Open a local folder picker and return a validated input directory."""
        if os.name != "nt":
            return {"status": "unavailable", "message": "The folder picker is only available on Windows."}
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = 'Select a deidentified DICOM folder'; "
            "$dialog.ShowNewFolderButton = $false; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Write-Output $dialog.SelectedPath }"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        selected = completed.stdout.strip()
        if completed.returncode != 0:
            raise RuntimeError("The DICOM folder picker could not be opened")
        if not selected:
            return {"status": "cancelled"}
        source = Path(selected).resolve(strict=True)
        if not source.is_dir():
            raise ValueError("Selected path is not a directory")
        if not any(is_within(source, root) for root in self.settings.input_roots):
            return {
                "status": "outside_input_roots",
                "selected_path": str(source),
                "allowed_input_roots": [str(root) for root in self.settings.input_roots],
                "message": "Select a folder below an allowed input root or update the MCP input-root configuration.",
            }
        return {"status": "selected", "input_path": str(source)}

    def _case_dir(self, case_id: str) -> Path:
        return self.settings.case_root / validate_id(case_id, "case_id")

    def _load_case(self, case_id: str) -> tuple[Path, dict[str, Any]]:
        case_dir = self._case_dir(case_id)
        manifest = case_dir / "case.json"
        if not manifest.is_file():
            raise ValueError(f"Unknown case_id: {case_id}")
        return case_dir, read_json(manifest)

    def inspect_dicom_case(
        self, input_path: str, confirm_deidentified: bool, case_id: str | None = None
    ) -> dict[str, Any]:
        if confirm_deidentified is not True:
            raise ValueError("confirm_deidentified must be true before local DICOM processing")
        source = Path(input_path).expanduser().resolve(strict=True)
        if not source.is_dir():
            raise ValueError("input_path must be a DICOM directory")
        if not any(is_within(source, root) for root in self.settings.input_roots):
            raise ValueError("input_path is outside configured input roots")
        files = [path for path in source.rglob("*") if path.is_file()]
        if not files:
            raise ValueError("input_path contains no files")
        if len(files) > 200_000:
            raise ValueError("input_path exceeds the 200000-file safety limit")
        total_bytes = sum(path.stat().st_size for path in files)
        chosen_id = case_id or f"case-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        validate_id(chosen_id, "case_id")
        case_dir = self._case_dir(chosen_id)
        manifest_path = case_dir / "case.json"
        if manifest_path.exists():
            previous = read_json(manifest_path)
            if previous.get("source_path") != str(source):
                raise ValueError(f"case_id already exists: {chosen_id}")
            return self.case_status(chosen_id)
        case_dir.mkdir(parents=True, exist_ok=False)
        fingerprint = input_fingerprint(source, files)
        manifest = {
            "schema_version": 1,
            "case_id": chosen_id,
            "created_at": utc_now(),
            "source_path": str(source),
            "input_fingerprint": fingerprint,
            "input_file_count": len(files),
            "input_total_bytes": total_bytes,
            "deidentification": "user_confirmed_not_verified",
            "conversion_status": "not_started",
        }
        atomic_json(manifest_path, manifest)
        return self.case_status(chosen_id)

    def case_status(self, case_id: str) -> dict[str, Any]:
        case_dir, manifest = self._load_case(case_id)
        candidates_dir = case_dir / "candidates"
        candidates = []
        if candidates_dir.is_dir():
            for path in sorted(candidates_dir.iterdir()):
                if path.is_dir():
                    candidates.append(path.name)
        return {
            "case_id": manifest["case_id"],
            "input_fingerprint": manifest["input_fingerprint"],
            "input_file_count": manifest["input_file_count"],
            "input_total_bytes": manifest["input_total_bytes"],
            "deidentification": manifest["deidentification"],
            "conversion_status": manifest.get("conversion_status", "unknown"),
            "has_mra": (case_dir / "patient_input" / "MRA.nii").is_file(),
            "has_mrv": (case_dir / "patient_input" / "MRV.nii").is_file(),
            "candidates": candidates,
        }

    def _create_job(self, case_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        case_dir, _ = self._load_case(case_id)
        job_id = f"job-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        job_dir = case_dir / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        spec_path = job_dir / "spec.json"
        state_path = job_dir / "state.json"
        spec = {
            "schema_version": 1,
            "job_id": job_id,
            "case_id": case_id,
            "kind": kind,
            "case_dir": str(case_dir),
            "python_exe": str(self.settings.python_exe),
            "vascular_script": str(self.settings.vascular_script),
            "dcm2niix_exe": str(self.settings.dcm2niix_exe),
            "dcmdjpeg_exe": str(self.settings.dcmdjpeg_exe),
            "payload": payload,
        }
        atomic_json(spec_path, spec)
        atomic_json(
            state_path,
            {
                "schema_version": 1,
                "job_id": job_id,
                "case_id": case_id,
                "kind": kind,
                "status": "queued",
                "created_at": utc_now(),
            },
        )
        log_path = job_dir / "runner.log"
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                [str(self.settings.python_exe), str(self.settings.runner_script), "--spec", str(spec_path)],
                cwd=str(self.settings.project_root),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                creationflags=creationflags,
            )
        state = read_json(state_path)
        state["pid"] = process.pid
        atomic_json(state_path, state)
        state = self._job_snapshot(job_id, case_id)
        state["user_notice"] = (
            "The job has started. Vessel reconstruction normally takes about 20 minutes; "
            "progress checks wait server-side and report authoritative elapsed time."
            if kind == "candidate"
            else "DICOM conversion has started; progress checks wait server-side."
        )
        return state

    def start_conversion(self, case_id: str, decompress_with_dcmtk: bool = True) -> dict[str, Any]:
        case_dir, manifest = self._load_case(case_id)
        if (case_dir / "patient_input" / "MRA.nii").is_file() and (
            case_dir / "patient_input" / "MRV.nii"
        ).is_file():
            return {"case_id": case_id, "status": "already_succeeded"}
        manifest["conversion_status"] = "queued"
        atomic_json(case_dir / "case.json", manifest)
        return self._create_job(
            case_id,
            "conversion",
            {"source_path": manifest["source_path"], "decompress_with_dcmtk": decompress_with_dcmtk},
        )

    def start_candidate(
        self,
        case_id: str,
        candidate_id: str,
        vessel_threshold: float,
        mrv_weak_grow_tolerance: float,
        mrv_post_process_min_size: int,
    ) -> dict[str, Any]:
        candidate_id = validate_id(candidate_id, "candidate_id")
        if float(vessel_threshold) not in ARTERY_THRESHOLDS:
            raise ValueError(f"vessel_threshold must be one of {ARTERY_THRESHOLDS}")
        if float(mrv_weak_grow_tolerance) not in VEIN_TOLERANCES:
            raise ValueError(f"mrv_weak_grow_tolerance must be one of {VEIN_TOLERANCES}")
        if int(mrv_post_process_min_size) not in VEIN_MIN_SIZES:
            raise ValueError(f"mrv_post_process_min_size must be one of {VEIN_MIN_SIZES}")
        case_dir, _ = self._load_case(case_id)
        if not (case_dir / "patient_input" / "MRA.nii").is_file() or not (
            case_dir / "patient_input" / "MRV.nii"
        ).is_file():
            raise ValueError("DICOM conversion must succeed before candidate generation")
        candidate_dir = case_dir / "candidates" / candidate_id
        if candidate_dir.exists():
            raise ValueError(f"candidate_id already exists and is immutable: {candidate_id}")
        candidate_dir.mkdir(parents=True, exist_ok=False)
        parameters = {
            "vessel_threshold": float(vessel_threshold),
            "mrv_weak_grow_tolerance": float(mrv_weak_grow_tolerance),
            "mrv_post_process_min_size": int(mrv_post_process_min_size),
        }
        atomic_json(candidate_dir / "parameters.json", parameters)
        return self._create_job(
            case_id,
            "candidate",
            {"candidate_id": candidate_id, "parameters": parameters},
        )

    def _find_job_dir(self, job_id: str, case_id: str) -> Path:
        validate_id(job_id, "job_id")
        case_dir, _ = self._load_case(case_id)
        job_dir = case_dir / "jobs" / job_id
        if not (job_dir / "state.json").is_file():
            raise ValueError(f"Unknown job_id for case: {job_id}")
        return job_dir

    @staticmethod
    def _job_observation_token(state: dict[str, Any]) -> str:
        visible = {
            "status": state.get("status"),
            "phase": state.get("phase"),
            "finished_at": state.get("finished_at"),
            "result": state.get("result"),
            "error": state.get("error"),
        }
        return hashlib.sha256(
            json.dumps(visible, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

    def _job_snapshot(self, job_id: str, case_id: str) -> dict[str, Any]:
        job_dir = self._find_job_dir(job_id, case_id)
        state = read_json(job_dir / "state.json")
        now = datetime.now(timezone.utc)
        started = parse_utc(state.get("started_at")) or parse_utc(state.get("created_at"))
        finished = parse_utc(state.get("finished_at"))
        elapsed_seconds = max(0.0, ((finished or now) - started).total_seconds()) if started else 0.0
        compact = {
            key: state[key]
            for key in (
                "schema_version",
                "job_id",
                "case_id",
                "kind",
                "status",
                "phase",
                "created_at",
                "started_at",
                "finished_at",
                "result",
                "error",
                "message",
            )
            if key in state
        }
        compact["server_time"] = now.isoformat()
        compact["elapsed_seconds"] = round(elapsed_seconds, 3)
        compact["elapsed_minutes"] = round(elapsed_seconds / 60.0, 2)
        compact["observation_token"] = self._job_observation_token(state)
        if state.get("status") in TERMINAL_JOB_STATES:
            compact["recommended_poll_after_seconds"] = 0
            compact["recommended_status_update_after_seconds"] = 0
        else:
            is_candidate = state.get("kind") == "candidate"
            compact["recommended_poll_after_seconds"] = 55
            compact["recommended_status_update_after_seconds"] = 180
            if is_candidate:
                compact["typical_duration_minutes"] = 20
        return compact

    def get_job(self, job_id: str, case_id: str, wait_seconds: int = 55) -> dict[str, Any]:
        """Long-poll a job; non-terminal calls wait for change or the requested interval."""
        if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, int):
            raise ValueError("wait_seconds must be an integer")
        if wait_seconds < 1 or wait_seconds > MAX_JOB_WAIT_SECONDS:
            raise ValueError(f"wait_seconds must be between 1 and {MAX_JOB_WAIT_SECONDS}")
        initial = self._job_snapshot(job_id, case_id)
        if initial.get("status") in TERMINAL_JOB_STATES:
            return initial
        initial_token = initial["observation_token"]
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
            current = self._job_snapshot(job_id, case_id)
            if current.get("status") in TERMINAL_JOB_STATES:
                return current
            if current["observation_token"] != initial_token:
                return current
        result = self._job_snapshot(job_id, case_id)
        result["waited_seconds"] = wait_seconds
        result["unchanged"] = result["observation_token"] == initial_token
        return result

    def cancel_job(self, job_id: str, case_id: str) -> dict[str, Any]:
        job_dir = self._find_job_dir(job_id, case_id)
        state_path = job_dir / "state.json"
        state = read_json(state_path)
        if state.get("status") in TERMINAL_JOB_STATES:
            return self._job_snapshot(job_id, case_id)
        pid = state.get("pid")
        if isinstance(pid, int) and pid > 0:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
        state.update({"status": "cancelled", "finished_at": utc_now(), "message": "Cancelled by user"})
        atomic_json(state_path, state)
        return self._job_snapshot(job_id, case_id)

    def list_candidates(self, case_id: str) -> dict[str, Any]:
        case_dir, _ = self._load_case(case_id)
        results = []
        root = case_dir / "candidates"
        if root.is_dir():
            for path in sorted(root.iterdir()):
                if not path.is_dir():
                    continue
                report = path / "report.json"
                results.append(
                    {
                        "candidate_id": path.name,
                        "has_artery": (path / "artery.glb").is_file(),
                        "has_vein": (path / "vein.glb").is_file(),
                        "parameters": read_json(path / "parameters.json")
                        if (path / "parameters.json").is_file()
                        else None,
                        "report": read_json(report) if report.is_file() else None,
                    }
                )
        return {"case_id": case_id, "candidates": results}

    def _mesh_metrics(self, path: Path, preview_dir: Path, color: tuple[int, int, int]) -> dict[str, Any]:
        import numpy as np
        import trimesh

        loaded = trimesh.load(str(path), force="scene")
        if isinstance(loaded, trimesh.Scene):
            meshes = [item for item in loaded.geometry.values() if isinstance(item, trimesh.Trimesh)]
            if not meshes:
                raise ValueError(f"No mesh geometry in {path.name}")
            mesh = trimesh.util.concatenate(meshes)
        else:
            mesh = loaded
        vertices = np.asarray(mesh.vertices)
        faces = np.asarray(mesh.faces)
        if len(vertices) == 0 or len(faces) == 0:
            raise ValueError(f"Empty mesh in {path.name}")
        if not np.isfinite(vertices).all():
            raise ValueError(f"Non-finite coordinates in {path.name}")
        components = mesh.split(only_watertight=False)
        face_counts = sorted((len(component.faces) for component in components), reverse=True)
        largest_ratio = face_counts[0] / len(faces) if face_counts else 0.0
        self._render_previews(mesh, preview_dir, color)
        return {
            "file_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "vertices": int(len(vertices)),
            "faces": int(len(faces)),
            "components": int(len(components)),
            "largest_component_face_ratio": round(float(largest_ratio), 6),
            "bounds": np.asarray(mesh.bounds).round(4).tolist(),
            "extents": np.asarray(mesh.extents).round(4).tolist(),
            "duplicate_faces": int(len(faces) - len(mesh.unique_faces())),
        }

    @staticmethod
    def _render_previews(mesh: Any, output: Path, color: tuple[int, int, int]) -> None:
        from PIL import Image, ImageDraw
        import numpy as np

        output.mkdir(parents=True, exist_ok=True)
        vertices = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces, dtype=int)
        if len(faces) > 50_000:
            step = max(1, math.ceil(len(faces) / 50_000))
            faces = faces[::step]
        views = {
            "front": (0, 2, False, False),
            "back": (0, 2, True, False),
            "left": (1, 2, False, False),
            "right": (1, 2, True, False),
            "top": (0, 1, False, True),
            "bottom": (0, 1, False, False),
        }
        for name, (axis_x, axis_y, flip_x, flip_y) in views.items():
            points = vertices[:, [axis_x, axis_y]].copy()
            if flip_x:
                points[:, 0] *= -1
            if flip_y:
                points[:, 1] *= -1
            low = points.min(axis=0)
            span = np.maximum(points.max(axis=0) - low, 1e-9)
            scale = min(900.0 / span[0], 900.0 / span[1])
            xy = (points - low) * scale
            xy[:, 0] += (1024 - span[0] * scale) / 2
            xy[:, 1] += (1024 - span[1] * scale) / 2
            xy[:, 1] = 1024 - xy[:, 1]
            image = Image.new("RGB", (1024, 1024), (245, 247, 250))
            draw = ImageDraw.Draw(image, "RGBA")
            line_color = (*color, 90)
            for face in faces:
                polygon = [tuple(xy[index]) for index in face]
                draw.line(polygon + [polygon[0]], fill=line_color, width=1)
            draw.text((16, 16), name, fill=(25, 25, 25, 255))
            image.save(output / f"{name}.png", optimize=True)

        montage = Image.new("RGB", (1440, 960), (232, 235, 240))
        for index, name in enumerate(views):
            preview = Image.open(output / f"{name}.png").convert("RGB")
            preview.thumbnail((468, 468))
            x = (index % 3) * 480 + (480 - preview.width) // 2
            y = (index // 3) * 480 + (480 - preview.height) // 2
            montage.paste(preview, (x, y))
        montage.quantize(colors=128).save(output / "montage.png", optimize=True)

    def evaluate_candidate(self, case_id: str, candidate_id: str) -> dict[str, Any]:
        candidate_id = validate_id(candidate_id, "candidate_id")
        case_dir, manifest = self._load_case(case_id)
        candidate_dir = case_dir / "candidates" / candidate_id
        artery = candidate_dir / "artery.glb"
        vein = candidate_dir / "vein.glb"
        if not artery.is_file() or not vein.is_file():
            raise ValueError("Candidate must contain both artery.glb and vein.glb")
        errors: list[str] = []
        metrics: dict[str, Any] = {}
        for name, path, color in (
            ("artery", artery, (205, 40, 40)),
            ("vein", vein, (40, 85, 205)),
        ):
            try:
                metrics[name] = self._mesh_metrics(path, candidate_dir / "previews" / name, color)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        limits = {
            "max_glb_bytes": self.settings.max_glb_bytes,
            "max_vertices": self.settings.max_vertices,
            "max_faces": self.settings.max_faces,
        }
        violations = list(errors)
        for name, item in metrics.items():
            if item["file_bytes"] > limits["max_glb_bytes"]:
                violations.append(f"{name}: file size exceeds limit")
            if item["vertices"] > limits["max_vertices"]:
                violations.append(f"{name}: vertex count exceeds limit")
            if item["faces"] > limits["max_faces"]:
                violations.append(f"{name}: face count exceeds limit")
        conclusion = "fail" if violations else "pass"
        report = {
            "schema_version": 1,
            "case_id": case_id,
            "candidate_id": candidate_id,
            "created_at": utc_now(),
            "input_fingerprint": manifest["input_fingerprint"],
            "parameters": read_json(candidate_dir / "parameters.json"),
            "quality_scope": "technical_mesh_qc_v1",
            "clinical_quality_review_required": True,
            "limits": limits,
            "metrics": metrics,
            "violations": violations,
            "conclusion": conclusion,
            "preview_root": str(candidate_dir / "previews"),
            "preview_montages": {
                "artery": str(candidate_dir / "previews" / "artery" / "montage.png"),
                "vein": str(candidate_dir / "previews" / "vein" / "montage.png"),
            },
        }
        atomic_json(candidate_dir / "report.json", report)
        return report

    def suggest_parameters(
        self,
        case_id: str,
        based_on_candidate_id: str,
        artery_assessment: str,
        vein_assessment: str,
    ) -> dict[str, Any]:
        """Turn a visual assessment into one safe, untried, one-parameter change."""
        based_on_candidate_id = validate_id(based_on_candidate_id, "based_on_candidate_id")
        allowed = {"good", "too_dense", "too_sparse", "uncertain"}
        if artery_assessment not in allowed or vein_assessment not in allowed:
            raise ValueError(f"assessments must be one of {sorted(allowed)}")
        case_dir, _ = self._load_case(case_id)
        candidate_dir = case_dir / "candidates" / based_on_candidate_id
        parameters_path = candidate_dir / "parameters.json"
        report_path = candidate_dir / "report.json"
        if not parameters_path.is_file() or not report_path.is_file():
            raise ValueError("The base candidate must be reconstructed and evaluated first")
        base = read_json(parameters_path)
        tried: set[tuple[float, float, int]] = set()
        candidates_root = case_dir / "candidates"
        for path in candidates_root.iterdir() if candidates_root.is_dir() else ():
            item = path / "parameters.json"
            if not item.is_file():
                continue
            value = read_json(item)
            tried.add(
                (
                    float(value["vessel_threshold"]),
                    float(value["mrv_weak_grow_tolerance"]),
                    int(value["mrv_post_process_min_size"]),
                )
            )

        base_tuple = (
            float(base["vessel_threshold"]),
            float(base["mrv_weak_grow_tolerance"]),
            int(base["mrv_post_process_min_size"]),
        )
        proposals: list[tuple[tuple[float, float, int], str]] = []

        def directional(values: tuple[Any, ...], current: Any, direction: int) -> list[Any]:
            index = values.index(current)
            indices = range(index + direction, len(values), direction) if direction > 0 else range(index - 1, -1, -1)
            return [values[position] for position in indices]

        if artery_assessment in {"too_dense", "too_sparse"}:
            direction = 1 if artery_assessment == "too_dense" else -1
            reason = "reduce artery density/noise" if direction > 0 else "recover missing artery branches"
            for value in directional(ARTERY_THRESHOLDS, base_tuple[0], direction):
                proposals.append(((value, base_tuple[1], base_tuple[2]), reason))
        if vein_assessment in {"too_dense", "too_sparse"}:
            direction = 1 if vein_assessment == "too_dense" else -1
            reason = "reduce vein density/noise" if direction > 0 else "recover missing vein branches"
            for value in directional(VEIN_TOLERANCES, base_tuple[1], direction):
                proposals.append(((base_tuple[0], value, base_tuple[2]), reason))
            for value in directional(VEIN_MIN_SIZES, base_tuple[2], direction):
                proposals.append(((base_tuple[0], base_tuple[1], value), reason))

        for proposal, reason in proposals:
            if proposal not in tried:
                parameters = {
                    "vessel_threshold": proposal[0],
                    "mrv_weak_grow_tolerance": proposal[1],
                    "mrv_post_process_min_size": proposal[2],
                }
                return {
                    "status": "recommended",
                    "based_on_candidate_id": based_on_candidate_id,
                    "parameters": parameters,
                    "reason": reason,
                    "changed_parameter_count": sum(a != b for a, b in zip(base_tuple, proposal)),
                    "candidate_id_suggestion": (
                        f"auto-a{int(proposal[0])}-t{str(proposal[1]).replace('.', '')}-s{proposal[2]}"
                    ),
                }
        if artery_assessment == "good" and vein_assessment == "good":
            return {"status": "no_change", "reason": "Both vessel previews were assessed as good."}
        return {
            "status": "needs_human_review",
            "reason": "No safe untried one-parameter change remains, or the visual assessment is uncertain.",
        }

    def finalize_case(self, case_id: str, candidate_id: str) -> dict[str, Any]:
        candidate_id = validate_id(candidate_id, "candidate_id")
        case_dir, manifest = self._load_case(case_id)
        candidate_dir = case_dir / "candidates" / candidate_id
        report_path = candidate_dir / "report.json"
        if not report_path.is_file():
            raise ValueError("Candidate must be evaluated before finalization")
        report = read_json(report_path)
        if report.get("conclusion") != "pass":
            raise ValueError("Only a candidate with conclusion=pass can be finalized")
        final_dir = case_dir / "final" / candidate_id
        if not final_dir.exists():
            final_dir.mkdir(parents=True, exist_ok=False)
            for name in ("artery.glb", "vein.glb", "parameters.json", "report.json"):
                shutil.copy2(candidate_dir / name, final_dir / name)
            if (candidate_dir / "previews").is_dir():
                shutil.copytree(candidate_dir / "previews", final_dir / "previews")
        final_manifest = {
            "schema_version": 1,
            "case_id": case_id,
            "candidate_id": candidate_id,
            "created_at": utc_now(),
            "input_fingerprint": manifest["input_fingerprint"],
            "parameters": report["parameters"],
            "quality_scope": report["quality_scope"],
            "clinical_quality_review_required": True,
            "artifacts": {
                "artery_glb": str(final_dir / "artery.glb"),
                "vein_glb": str(final_dir / "vein.glb"),
                "report": str(final_dir / "report.json"),
                "previews": str(final_dir / "previews"),
            },
            "checksums": {
                "artery_glb": sha256_file(final_dir / "artery.glb"),
                "vein_glb": sha256_file(final_dir / "vein.glb"),
            },
        }
        atomic_json(case_dir / "final" / "manifest.json", final_manifest)
        return final_manifest
