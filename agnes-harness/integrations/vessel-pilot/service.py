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
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from parameters import MODALITIES, normalize_parameters, target_vessels


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}
MAX_JOB_WAIT_SECONDS = 55
DICOM_SUFFIXES = {".dcm", ".dicom", ".ima"}
VISUAL_LABELS = {
    "artery": {"good", "too_dense", "too_sparse", "uncertain"},
    "vein": {"good", "too_dense", "too_sparse", "scalp_dominant", "intracranial_sparse", "uncertain"},
}


class VesselPilotInputError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


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


def has_dicom_preamble(path: Path) -> bool:
    try:
        if path.stat().st_size < 132:
            return False
        with path.open("rb") as stream:
            stream.seek(128)
            return stream.read(4) == b"DICM"
    except OSError:
        return False


def dicom_input_preflight(files: list[Path]) -> dict[str, Any]:
    non_empty = [path for path in files if path.stat().st_size > 0]
    preamble_files = {path for path in non_empty if has_dicom_preamble(path)}
    suffix_files = {path for path in non_empty if path.suffix.lower() in DICOM_SUFFIXES}
    likely_dicom = preamble_files | suffix_files
    non_dicom = [path for path in files if path not in likely_dicom]
    warnings: list[str] = []
    if non_dicom and likely_dicom:
        warnings.append("mixed_non_dicom_files_ignored_by_converter")
    if suffix_files - preamble_files:
        warnings.append("dicom_suffix_without_standard_preamble")
    return {
        "likely_dicom_file_count": len(likely_dicom),
        "standard_preamble_file_count": len(preamble_files),
        "non_dicom_file_count": len(non_dicom),
        "empty_file_count": len(files) - len(non_empty),
        "warnings": warnings,
    }


@dataclass(frozen=True)
class Settings:
    project_root: Path
    case_root: Path
    input_roots: tuple[Path, ...]
    allow_any_input: bool
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
        allow_any_input: bool = False,
    ) -> "Settings":
        project_root = server_file.resolve().parents[3]
        resolved_case_root = (case_root or project_root / "workspace" / "vessel-pilot").resolve()
        roots = tuple(path.resolve() for path in input_roots) or (
            (project_root / "workspace").resolve(),
        )
        portable_python = project_root / "runtime" / "python" / "BrainAAL" / "python.exe"
        if not portable_python.is_file():
            portable_python = project_root / "venv" / "runtime" / "python" / "BrainAAL" / "python.exe"
        if not portable_python.is_file():
            # A Conda deployment can launch this server without the bundled runtime.
            # Use that same interpreter for conversion and reconstruction jobs.
            portable_python = Path(sys.executable).resolve()
        return cls(
            project_root=project_root,
            case_root=resolved_case_root,
            input_roots=roots,
            allow_any_input=allow_any_input,
            python_exe=portable_python,
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
        self._conversion_lock = threading.Lock()

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
            "allow_any_input": self.settings.allow_any_input,
            "runtime": {name: str(path) for name, path in required.items()},
        }

    def choose_dicom_folder(self) -> dict[str, Any]:
        """Open a local folder picker and return a validated input directory."""
        if os.name != "nt":
            return {"status": "unavailable", "message": "The folder picker is only available on Windows."}
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
            "public static class VesselPilotNativeWindow { "
            "[DllImport(\"user32.dll\", SetLastError=true)] "
            "public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, "
            "int X, int Y, int cx, int cy, uint uFlags); "
            "[DllImport(\"user32.dll\")] "
            "public static extern bool SetForegroundWindow(IntPtr hWnd); }'; "
            "$owner = New-Object System.Windows.Forms.Form; "
            "$owner.ShowInTaskbar = $false; "
            "$owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedToolWindow; "
            "$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual; "
            "$owner.Location = [System.Drawing.Point]::new(-32000, -32000); "
            "$owner.Size = [System.Drawing.Size]::new(1, 1); "
            "$owner.Opacity = 0; "
            "$owner.TopMost = $true; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = 'Select a deidentified DICOM folder'; "
            "$dialog.ShowNewFolderButton = $false; "
            "$owner.Show(); "
            "[VesselPilotNativeWindow]::SetWindowPos($owner.Handle, [IntPtr](-1), 0, 0, 0, 0, "
            "(0x0001 -bor 0x0002 -bor 0x0040)) | Out-Null; "
            "$owner.BringToFront(); $owner.Activate(); "
            "[VesselPilotNativeWindow]::SetForegroundWindow($owner.Handle) | Out-Null; "
            "try { $choice = $dialog.ShowDialog($owner); "
            "if ($choice -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Write-Output $dialog.SelectedPath } "
            "} finally { $owner.Close(); $owner.Dispose(); $dialog.Dispose() }"
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
        if not self.settings.allow_any_input and not any(
            is_within(source, root) for root in self.settings.input_roots
        ):
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
        try:
            source = Path(input_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise VesselPilotInputError(
                "INPUT_PATH_UNAVAILABLE", "input_path does not exist or cannot be read"
            ) from exc
        if not source.is_dir():
            raise VesselPilotInputError("INPUT_NOT_DIRECTORY", "input_path must be a DICOM directory")
        if not self.settings.allow_any_input and not any(
            is_within(source, root) for root in self.settings.input_roots
        ):
            raise VesselPilotInputError(
                "INPUT_OUTSIDE_ROOT", "input_path is outside configured input roots"
            )
        symlinks = [path for path in source.rglob("*") if path.is_symlink()]
        if symlinks:
            raise VesselPilotInputError(
                "INPUT_SYMLINK_UNSUPPORTED",
                "input_path must not contain symbolic links",
                {"symlink_count": len(symlinks)},
            )
        files = [path for path in source.rglob("*") if path.is_file()]
        if not files:
            raise VesselPilotInputError("INPUT_EMPTY", "input_path contains no files")
        if len(files) > 200_000:
            raise VesselPilotInputError(
                "INPUT_TOO_MANY_FILES", "input_path exceeds the 200000-file safety limit"
            )
        preflight = dicom_input_preflight(files)
        if preflight["likely_dicom_file_count"] == 0:
            raise VesselPilotInputError(
                "INPUT_NO_DICOM_FILES",
                "input_path contains files but no recognizable DICOM files",
                preflight,
            )
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
            "input_preflight": preflight,
            "deidentification": "user_confirmed_not_verified",
            "conversion_status": "not_started",
        }
        atomic_json(manifest_path, manifest)
        return self.case_status(chosen_id)

    def case_status(self, case_id: str) -> dict[str, Any]:
        case_dir, manifest = self._load_case(case_id)
        mra = case_dir / "patient_input" / "MRA.nii"
        mrv = case_dir / "patient_input" / "MRV.nii"
        has_mra = mra.is_file() and mra.stat().st_size > 0
        has_mrv = mrv.is_file() and mrv.stat().st_size > 0
        selection_path = case_dir / "patient_input" / "dicom_selection.json"
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
            "input_preflight": manifest.get("input_preflight"),
            "deidentification": manifest["deidentification"],
            "conversion_status": manifest.get("conversion_status", "unknown"),
            "conversion_error": manifest.get("conversion_error"),
            "conversion_mode": manifest.get("conversion_mode", "vessel"),
            "nifti_outputs": manifest.get("nifti_outputs", {}),
            "has_mra": has_mra,
            "has_mrv": has_mrv,
            "conversion_ready": manifest.get("conversion_status") == "succeeded"
            and manifest.get("conversion_mode", "vessel") in MODALITIES
            and all((case_dir / "patient_input" / f"{name.upper()}.nii").is_file()
                    for name in MODALITIES.get(manifest.get("conversion_mode", "vessel"), ())),
            "available_reconstruction_targets": (
                (["artery"] if has_mra else []) + (["vein"] if has_mrv else [])
                + (["both"] if has_mra and has_mrv else [])
            ) if manifest.get("conversion_status") == "succeeded" else [],
            "dicom_selection": read_json(selection_path) if selection_path.is_file() else None,
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

    def start_conversion(
        self, case_id: str, decompress_with_dcmtk: bool = True, conversion_mode: str = "vessel"
    ) -> dict[str, Any]:
        if conversion_mode not in {"vessel", "nifti", "artery", "vein"}:
            raise ValueError("conversion_mode must be vessel, nifti, artery or vein")
        with self._conversion_lock:
            case_dir, manifest = self._load_case(case_id)
            previous_mode = manifest.get("conversion_mode", "vessel")
            if previous_mode == conversion_mode and manifest.get("conversion_status") == "succeeded":
                outputs = manifest.get("nifti_outputs") or {
                    name: str(case_dir / "patient_input" / f"{name.upper()}.nii")
                    for name in MODALITIES.get(conversion_mode, ())
                }
                if outputs and all(Path(path).is_file() and Path(path).stat().st_size > 0 for path in outputs.values()):
                    return {"case_id": case_id, "status": "already_succeeded", "conversion_mode": conversion_mode, "outputs": outputs}
            active_job_id = manifest.get("conversion_job_id")
            if manifest.get("conversion_status") in {"queued", "running"} and isinstance(
                active_job_id, str
            ):
                try:
                    snapshot = self._job_snapshot(active_job_id, case_id)
                    if snapshot.get("status") not in TERMINAL_JOB_STATES:
                        if previous_mode != conversion_mode:
                            raise VesselPilotInputError("CONVERSION_ALREADY_RUNNING", "Wait for the active conversion before changing mode")
                        snapshot["already_running"] = True
                        return snapshot
                except VesselPilotInputError:
                    raise
                except ValueError:
                    pass
            if (case_dir / "candidates").is_dir() and any((case_dir / "candidates").iterdir()):
                raise ValueError("Conversion inputs are used by existing candidates; register a new case_id to reconvert")
            try:
                source = Path(manifest["source_path"]).resolve(strict=True)
                entries = list(source.rglob("*"))
                files = [path for path in entries if path.is_file()]
            except (OSError, RuntimeError) as exc:
                raise VesselPilotInputError(
                    "INPUT_CHANGED_SINCE_INSPECTION",
                    "input_path changed or became unreadable after inspection",
                ) from exc
            if any(path.is_symlink() for path in entries):
                raise VesselPilotInputError(
                    "INPUT_CHANGED_SINCE_INSPECTION",
                    "input_path changed after inspection; inspect it again before conversion",
                    {"reason": "symbolic_link_added"},
                )
            try:
                current_fingerprint = input_fingerprint(source, files)
            except OSError as exc:
                raise VesselPilotInputError(
                    "INPUT_CHANGED_SINCE_INSPECTION",
                    "input_path changed while conversion was being prepared",
                ) from exc
            if current_fingerprint != manifest["input_fingerprint"]:
                raise VesselPilotInputError(
                    "INPUT_CHANGED_SINCE_INSPECTION",
                    "input_path changed after inspection; inspect it again before conversion",
                )
            manifest["conversion_status"] = "queued"
            manifest["conversion_mode"] = conversion_mode
            manifest.pop("nifti_outputs", None)
            manifest.pop("conversion_outputs", None)
            manifest.pop("conversion_error", None)
            atomic_json(case_dir / "case.json", manifest)
            job = self._create_job(
                case_id,
                "conversion",
                {
                    "source_path": manifest["source_path"],
                    "decompress_with_dcmtk": decompress_with_dcmtk,
                    "conversion_mode": conversion_mode,
                },
            )
            manifest = read_json(case_dir / "case.json")
            manifest["conversion_job_id"] = job["job_id"]
            atomic_json(case_dir / "case.json", manifest)
            return job

    def start_candidate(
        self,
        case_id: str,
        candidate_id: str,
        vessel_threshold: float | None = None,
        mrv_weak_grow_tolerance: float | None = None,
        mrv_post_process_min_size: int | None = None,
        target: str = "both",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate_id = validate_id(candidate_id, "candidate_id")
        vessels = target_vessels(target)
        if parameters is not None and not isinstance(parameters, dict):
            raise ValueError("parameters must be an object")
        supplied = dict(parameters or {})
        for name, value in {"vessel_threshold": vessel_threshold, "mrv_weak_grow_tolerance": mrv_weak_grow_tolerance, "mrv_post_process_min_size": mrv_post_process_min_size}.items():
            if value is not None:
                if name in supplied and supplied[name] != value:
                    raise ValueError(f"Conflicting values for {name}")
                supplied[name] = value
        parameters = normalize_parameters(target, supplied)
        case_dir, manifest = self._load_case(case_id)
        modalities = ["mra" if vessel == "artery" else "mrv" for vessel in vessels]
        inputs = [case_dir / "patient_input" / f"{name.upper()}.nii" for name in modalities]
        if manifest.get("conversion_mode", "vessel") == "nifti":
            raise ValueError("NIfTI-only conversion does not select MRA/MRV; first prepare the requested reconstruction inputs")
        if manifest.get("conversion_status") != "succeeded" or any(
            not path.is_file() or path.stat().st_size == 0 for path in inputs
        ):
            raise ValueError("DICOM conversion must succeed before candidate generation")
        recorded_outputs = manifest.get("conversion_outputs")
        if isinstance(recorded_outputs, dict):
            for name, path in zip(modalities, inputs):
                recorded = recorded_outputs.get(name)
                if (
                    not isinstance(recorded, dict)
                    or recorded.get("size") != path.stat().st_size
                    or recorded.get("sha256") != sha256_file(path)
                ):
                    raise ValueError(
                        "Converted inputs changed after validation; rerun DICOM conversion"
                    )
        candidate_dir = case_dir / "candidates" / candidate_id
        for state_path in (case_dir / "jobs").glob("*/state.json"):
            state = read_json(state_path)
            if state.get("kind") == "candidate" and state.get("status") not in TERMINAL_JOB_STATES:
                raise ValueError("A candidate is already running for this case; wait or cancel it before starting another")
        if candidate_dir.exists():
            raise ValueError(f"candidate_id already exists and is immutable: {candidate_id}")
        candidate_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(candidate_dir / "parameters.json", parameters)
        atomic_json(candidate_dir / "candidate.json", {"target": target, "requested_parameters": supplied})
        return self._create_job(
            case_id,
            "candidate",
            {"candidate_id": candidate_id, "parameters": parameters, "target": target},
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
                        "target": self._candidate_target(path),
                        "has_artery": (path / "artery.glb").is_file(),
                        "has_vein": (path / "vein.glb").is_file(),
                        "parameters": read_json(path / "parameters.json")
                        if (path / "parameters.json").is_file()
                        else None,
                        "report": read_json(report) if report.is_file() else None,
                    }
                )
        return {"case_id": case_id, "candidates": results}

    @staticmethod
    def _candidate_target(candidate_dir: Path) -> str:
        path = candidate_dir / "candidate.json"
        target = read_json(path).get("target", "both") if path.is_file() else "both"
        target_vessels(target)
        return target

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
    def _load_mesh(path: Path) -> Any:
        import trimesh

        loaded = trimesh.load(str(path), force="scene")
        if isinstance(loaded, trimesh.Scene):
            meshes = [item for item in loaded.geometry.values() if isinstance(item, trimesh.Trimesh)]
            if not meshes:
                raise ValueError(f"No mesh geometry in {path.name}")
            return trimesh.util.concatenate(meshes)
        return loaded

    def _vein_distribution_proxy(self, artery_path: Path, vein_path: Path) -> dict[str, Any]:
        """Estimate central vs peripheral venous surface area using the artery envelope.

        This is deliberately a technical proxy, not anatomical segmentation: the artery model
        supplies a case-specific intracranial spatial envelope, expanded by 15 percent on every
        axis.  Vein triangle centroids outside that envelope are treated as scalp/peripheral
        candidates so candidates from the same case can be compared during tuning.
        """
        import numpy as np

        artery_mesh = self._load_mesh(artery_path)
        vein_mesh = self._load_mesh(vein_path)
        bounds = np.asarray(artery_mesh.bounds, dtype=float)
        extents = np.maximum(bounds[1] - bounds[0], 1e-9)
        lower = bounds[0] - extents * 0.15
        upper = bounds[1] + extents * 0.15
        centers = np.asarray(vein_mesh.triangles_center, dtype=float)
        areas = np.asarray(vein_mesh.area_faces, dtype=float)
        if len(centers) == 0 or len(areas) == 0 or not np.isfinite(areas).all():
            raise ValueError("Vein mesh has no finite triangle areas")
        inside = np.logical_and(centers >= lower, centers <= upper).all(axis=1)
        total = float(areas.sum())
        if total <= 0:
            raise ValueError("Vein mesh has zero surface area")
        intracranial = float(areas[inside].sum())
        scalp = max(0.0, total - intracranial)
        return {
            "method": "expanded_artery_aabb_v1",
            "artery_envelope_margin_fraction": 0.15,
            "intracranial_proxy_area_ratio": round(intracranial / total, 6),
            "scalp_peripheral_proxy_area_ratio": round(scalp / total, 6),
            "intracranial_proxy_area": round(intracranial, 6),
            "scalp_peripheral_proxy_area": round(scalp, 6),
            "total_vein_area": round(total, 6),
            "interpretation": (
                "Technical within-case comparison only; not a skull segmentation or clinical anatomical label."
            ),
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

    def evaluate_candidate(
        self, case_id: str, candidate_id: str,
        assessments: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        if assessments is not None:
            return self.record_visual_assessment(case_id, candidate_id, assessments)
        candidate_id = validate_id(candidate_id, "candidate_id")
        case_dir, manifest = self._load_case(case_id)
        candidate_dir = case_dir / "candidates" / candidate_id
        target = self._candidate_target(candidate_dir)
        vessels = target_vessels(target)
        artery = candidate_dir / "artery.glb"
        vein = candidate_dir / "vein.glb"
        if any(not (candidate_dir / f"{name}.glb").is_file() for name in vessels):
            raise ValueError(f"Candidate must contain the requested outputs: {', '.join(vessels)}")
        errors: list[str] = []
        metrics: dict[str, Any] = {}
        for name, path, color in (
            ("artery", artery, (205, 40, 40)),
            ("vein", vein, (40, 85, 205)),
        ):
            if name not in vessels:
                continue
            try:
                metrics[name] = self._mesh_metrics(path, candidate_dir / "previews" / name, color)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        vein_distribution_proxy: dict[str, Any] | None = None
        if not errors and target == "both":
            try:
                vein_distribution_proxy = self._vein_distribution_proxy(artery, vein)
            except Exception as exc:
                errors.append(f"vein_distribution_proxy: {exc}")
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
        technical_conclusion = "fail" if violations else "pass"
        preview_montages = {
            name: str(candidate_dir / "previews" / name / "montage.png") for name in metrics
        }
        mesh_hashes = {name: item["sha256"] for name, item in metrics.items()}
        preview_hashes = {
            name: sha256_file(Path(path)) for name, path in preview_montages.items()
        }
        previous_report_path = candidate_dir / "report.json"
        try:
            previous = read_json(previous_report_path) if previous_report_path.is_file() else {}
        except (OSError, ValueError):
            previous = {}
        previous_visual = previous.get("visual_assessment")
        if not isinstance(previous_visual, dict) or (
            previous_visual.get("mesh_sha256") != mesh_hashes
            or previous_visual.get("preview_sha256") != preview_hashes
        ):
            previous_visual = None
        visual_conclusion = previous_visual.get("conclusion") if previous_visual else "pending"
        conclusion = "fail" if technical_conclusion == "fail" else (
            visual_conclusion if visual_conclusion != "pending" else "review"
        )
        report = {
            "schema_version": 1,
            "case_id": case_id,
            "candidate_id": candidate_id,
            "target": target,
            "created_at": utc_now(),
            "input_fingerprint": manifest["input_fingerprint"],
            "parameters": read_json(candidate_dir / "parameters.json"),
            "quality_scope": "technical_mesh_and_visual_qc_v2",
            "clinical_quality_review_required": True,
            "limits": limits,
            "metrics": metrics,
            "vein_distribution_proxy": vein_distribution_proxy,
            "vein_distribution_proxy_unavailable_reason": None if target == "both" else "Requires both artery and vein meshes; not computed for a single-vessel task",
            "violations": violations,
            "technical_conclusion": technical_conclusion,
            "visual_assessment": previous_visual,
            "visual_conclusion": visual_conclusion,
            "conclusion": conclusion,
            "preview_root": str(candidate_dir / "previews"),
            "preview_montages": preview_montages,
            "preview_sha256": preview_hashes,
        }
        atomic_json(candidate_dir / "report.json", report)
        return report

    def record_visual_assessment(
        self, case_id: str, candidate_id: str, assessments: dict[str, dict[str, str]]
    ) -> dict[str, Any]:
        candidate_id = validate_id(candidate_id, "candidate_id")
        case_dir, _ = self._load_case(case_id)
        candidate_dir = case_dir / "candidates" / candidate_id
        report_path = candidate_dir / "report.json"
        if not report_path.is_file():
            raise ValueError("Evaluate the candidate before recording visual assessment")
        report = read_json(report_path)
        vessels = target_vessels(self._candidate_target(candidate_dir))
        if not isinstance(assessments, dict) or set(assessments) != set(vessels):
            raise ValueError("Visual assessments must cover exactly the candidate's requested vessels")
        validated = {}
        for vessel in vessels:
            item = assessments[vessel]
            if not isinstance(item, dict) or set(item) != {"label", "reason"}:
                raise ValueError(f"{vessel} visual assessment requires label and reason")
            label, reason = item["label"], item["reason"]
            if label not in VISUAL_LABELS[vessel]:
                raise ValueError(f"Invalid {vessel} visual assessment label")
            if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 2000:
                raise ValueError(f"{vessel} visual assessment reason must be 8-2000 characters")
            validated[vessel] = {"label": label, "reason": reason.strip()}
        mesh_hashes = report.get("metrics", {})
        if set(mesh_hashes) != set(vessels):
            raise ValueError("Candidate technical metrics are incomplete; evaluate it again")
        mesh_hashes = {name: mesh_hashes[name]["sha256"] for name in vessels}
        for vessel in vessels:
            if sha256_file(candidate_dir / f"{vessel}.glb") != mesh_hashes[vessel]:
                raise ValueError("Candidate changed after evaluation; evaluate it again")
        preview_hashes = {}
        for vessel in vessels:
            path = Path(report["preview_montages"][vessel])
            if not path.is_file():
                raise ValueError("Candidate preview is missing; evaluate it again")
            preview_hashes[vessel] = sha256_file(path)
            if preview_hashes[vessel] != report.get("preview_sha256", {}).get(vessel):
                raise ValueError("Candidate preview changed after evaluation; evaluate it again")
        labels = {item["label"] for item in validated.values()}
        visual_conclusion = "review" if "uncertain" in labels else (
            "pass" if labels == {"good"} else "fail"
        )
        report["visual_assessment"] = {
            "source": "agent_reported",
            "recorded_at": utc_now(),
            "vessels": validated,
            "mesh_sha256": mesh_hashes,
            "preview_sha256": preview_hashes,
            "conclusion": visual_conclusion,
        }
        report["visual_conclusion"] = visual_conclusion
        report["conclusion"] = (
            "fail" if report.get("technical_conclusion") == "fail" else visual_conclusion
        )
        atomic_json(report_path, report)
        return report

    def suggest_parameters(
        self,
        case_id: str,
        based_on_candidate_id: str,
        artery_assessment: str | None = None,
        vein_assessment: str | None = None,
        search_space: dict[str, list[Any]] | None = None,
        locked_parameters: list[str] | None = None,
        max_candidates: int = 6,
    ) -> dict[str, Any]:
        from tuning import recommend

        based_on_candidate_id = validate_id(based_on_candidate_id, "based_on_candidate_id")
        case_dir, _ = self._load_case(case_id)
        candidate_dir = case_dir / "candidates" / based_on_candidate_id
        if not (candidate_dir / "parameters.json").is_file() or not (candidate_dir / "report.json").is_file():
            raise ValueError("The base candidate must be reconstructed and evaluated first")
        target = self._candidate_target(candidate_dir)
        visual = read_json(candidate_dir / "report.json").get("visual_assessment")
        if isinstance(visual, dict):
            recorded = visual.get("vessels", {})
            submitted = {"artery": artery_assessment, "vein": vein_assessment}
            if any(submitted[name] != recorded.get(name, {}).get("label") for name in target_vessels(target)):
                raise ValueError("Parameter suggestion assessments must match the recorded visual QC")
        base = read_json(candidate_dir / "parameters.json")
        tried = []
        for path in (case_dir / "candidates").iterdir():
            item = path / "parameters.json"
            if item.is_file() and self._candidate_target(path) == target:
                tried.append(normalize_parameters(target, read_json(item)))
        result = recommend(target, base, tried, artery_assessment, vein_assessment,
                           search_space, locked_parameters, max_candidates)
        return {"based_on_candidate_id": based_on_candidate_id, "target": target, **result}

    def finalize_case(self, case_id: str, candidate_id: str) -> dict[str, Any]:
        candidate_id = validate_id(candidate_id, "candidate_id")
        case_dir, manifest = self._load_case(case_id)
        candidate_dir = case_dir / "candidates" / candidate_id
        report_path = candidate_dir / "report.json"
        if not report_path.is_file():
            raise ValueError("Candidate must be evaluated before finalization")
        report = read_json(report_path)
        if report.get("technical_conclusion") != "pass" or report.get("visual_conclusion") != "pass" or report.get("conclusion") != "pass":
            raise ValueError("Only a candidate with passing technical and visual QC can be finalized")
        target = self._candidate_target(candidate_dir)
        vessels = target_vessels(target)
        for name in vessels:
            path = candidate_dir / f"{name}.glb"
            if not path.is_file() or sha256_file(path) != report.get("metrics", {}).get(name, {}).get("sha256"):
                raise ValueError("Candidate changed after evaluation; evaluate it again before finalization")
            preview = Path(report.get("preview_montages", {}).get(name, ""))
            visual = report.get("visual_assessment") or {}
            if not preview.is_file() or sha256_file(preview) != visual.get("preview_sha256", {}).get(name):
                raise ValueError("Candidate preview changed after visual assessment; evaluate it again")
        final_dir = case_dir / "final" / candidate_id
        if not final_dir.exists():
            final_dir.mkdir(parents=True, exist_ok=False)
            for name in (*[f"{vessel}.glb" for vessel in vessels], "parameters.json", "report.json"):
                shutil.copy2(candidate_dir / name, final_dir / name)
            if (candidate_dir / "previews").is_dir():
                shutil.copytree(candidate_dir / "previews", final_dir / "previews")
        final_manifest = {
            "schema_version": 1,
            "case_id": case_id,
            "candidate_id": candidate_id,
            "target": target,
            "created_at": utc_now(),
            "input_fingerprint": manifest["input_fingerprint"],
            "parameters": report["parameters"],
            "quality_scope": report["quality_scope"],
            "technical_conclusion": report["technical_conclusion"],
            "visual_assessment": report["visual_assessment"],
            "visual_conclusion": report["visual_conclusion"],
            "clinical_quality_review_required": True,
            "artifacts": {
                **{f"{vessel}_glb": str(final_dir / f"{vessel}.glb") for vessel in vessels},
                "report": str(final_dir / "report.json"),
                "previews": str(final_dir / "previews"),
            },
            "checksums": {
                f"{vessel}_glb": sha256_file(final_dir / f"{vessel}.glb") for vessel in vessels
            },
        }
        atomic_json(case_dir / "final" / "manifest.json", final_manifest)
        return final_manifest
