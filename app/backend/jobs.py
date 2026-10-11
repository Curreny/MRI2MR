from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .command_builder import CommandBuildError, build_command, sanitize_job_name
from .config import AppSettings
from .modes import get_mode, load_modes
from .patients import (
    ensure_patient_workspace,
    get_patient,
    list_patients,
    resolve_patient_file,
    save_patient,
    scan_patient_outputs,
    update_patient,
)
from .preview import generate_previews


FINAL_STATUSES = {"success", "failed", "cancelled"}

MODE_ESTIMATES: dict[str, tuple[str, int]] = {
    "dicom_convert": ("Running DICOM conversion", 20 * 60),
    "synthseg_segmentation": ("Running SynthSeg", 40 * 60),
    "spm_segmentation": ("Running SPM segmentation", 30 * 60),
    "gm_wm": ("Generating brain tissue model", 30 * 60),
    "individual_regions": ("Generating brain region models", 30 * 60),
    "lobes": ("Generating lobe models", 30 * 60),
    "hemispheres": ("Generating hemisphere models", 30 * 60),
    "ventricle": ("Generating ventricle model", 30 * 60),
    "multiroi": ("Generating ROI models", 30 * 60),
    "tissue": ("Generating tissue models", 30 * 60),
    "vessel": ("Generating vessel model", 10 * 60),
    "mrv": ("Generating venous model", 10 * 60),
    "fiber_tracking": ("Running fiber tracking", 60 * 60),
    "fiber_tracking_region": ("Running fiber tracking", 60 * 60),
    "fiber_tracking_dki": ("Running fiber tracking", 60 * 60),
}

DEFAULT_STAGE = "Running processing pipeline"
DEFAULT_ESTIMATE_SECONDS = 30 * 60


def utc_now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def make_job_id(patient_folder: str) -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{sanitize_job_name(patient_folder)}"


def _mode_stage_and_estimate(mode: str) -> tuple[str, int]:
    return MODE_ESTIMATES.get(mode, (DEFAULT_STAGE, DEFAULT_ESTIMATE_SECONDS))


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class JobManager:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.jobs: dict[str, dict[str, Any]] = {}
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.cancel_requested: set[str] = set()
        self.lock = threading.RLock()
        self.settings.workspace_root.mkdir(parents=True, exist_ok=True)
        self._load_existing_jobs()

    def _load_existing_jobs(self) -> None:
        job_files = list(self.settings.workspace_root.glob("*/jobs/*/job.json"))
        job_files.extend(self.settings.workspace_root.glob("*/job.json"))
        for job_file in job_files:
            try:
                job = json.loads(job_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(job, dict) or not job.get("job_id"):
                continue
            job.setdefault("job_workspace", str(job_file.parent))
            if "patient_workspace" not in job and job_file.parent.parent.name == "jobs":
                job["patient_workspace"] = str(job_file.parent.parent.parent)
                job.setdefault("workspace", job["patient_workspace"])
            if job.get("status") == "running":
                job["status"] = "failed"
                job["error"] = "WebUI was restarted while this job was running."
                job["finished_at"] = utc_now_iso()
                job.update(self._progress_fields(job, status="failed"))
                self._save_job(job)
            self.jobs[str(job.get("job_id"))] = job

    def _workspace_for(self, job_id: str) -> Path:
        workspace = (self.settings.workspace_root / job_id).resolve()
        workspace_root = self.settings.workspace_root.resolve()
        if workspace_root != workspace and workspace_root not in workspace.parents:
            raise ValueError("Invalid workspace path.")
        return workspace

    def _job_workspace_for(self, patient_workspace: Path, job_id: str) -> Path:
        workspace = (patient_workspace / "jobs" / job_id).resolve()
        patient_workspace = patient_workspace.resolve()
        if patient_workspace != workspace and patient_workspace not in workspace.parents:
            raise ValueError("Invalid job workspace path.")
        return workspace

    def _job_file(self, job: dict[str, Any]) -> Path:
        if job.get("job_workspace"):
            return Path(str(job["job_workspace"])) / "job.json"
        return Path(str(job["workspace"])) / "job.json"

    def _save_job(self, job: dict[str, Any]) -> None:
        job_file = self._job_file(job)
        job_file.parent.mkdir(parents=True, exist_ok=True)
        job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    def _progress_fields(
        self,
        job: dict[str, Any],
        *,
        status: str | None = None,
        elapsed_seconds: int | None = None,
    ) -> dict[str, Any]:
        current_status = status or str(job.get("status") or "pending")
        mode = str(job.get("mode") or "")
        running_stage, estimate = _mode_stage_and_estimate(mode)

        if elapsed_seconds is None:
            elapsed_seconds = int(job.get("elapsed_seconds") or 0)
            if current_status == "running":
                started_at = _parse_iso(job.get("started_at"))
                if started_at is not None:
                    elapsed_seconds = max(0, int((datetime.now() - started_at).total_seconds()))

        if current_status == "pending":
            return {
                "stage": "Waiting",
                "progress": 0,
                "elapsed_seconds": elapsed_seconds,
                "estimated_remaining_seconds": estimate,
            }
        if current_status == "running":
            progress = min(95, max(5, int((elapsed_seconds / max(estimate, 1)) * 100)))
            return {
                "stage": running_stage,
                "progress": progress,
                "elapsed_seconds": elapsed_seconds,
                "estimated_remaining_seconds": max(0, estimate - elapsed_seconds),
            }
        if current_status == "success":
            return {
                "stage": "Completed",
                "progress": 100,
                "elapsed_seconds": elapsed_seconds,
                "estimated_remaining_seconds": 0,
            }
        if current_status == "cancelled":
            return {
                "stage": "Cancelled",
                "progress": int(job.get("progress") or 0),
                "elapsed_seconds": elapsed_seconds,
                "estimated_remaining_seconds": 0,
            }
        return {
            "stage": "Failed",
            "progress": int(job.get("progress") or 0),
            "elapsed_seconds": elapsed_seconds,
            "estimated_remaining_seconds": 0,
        }

    def _decorate_job(self, job: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(job)
        decorated.update(self._progress_fields(decorated))
        return decorated

    def _update_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        with self.lock:
            job = self.jobs[job_id]
            job.update(updates)
            self._save_job(job)
            return self._decorate_job(job)

    def _active_count(self) -> int:
        return sum(1 for job in self.jobs.values() if job.get("status") in {"pending", "running"})

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "input_path" in payload:
            raise CommandBuildError("文件输入只能通过当前模式的 parameters 字段提交。")

        modes = load_modes()
        mode_name = str(payload.get("mode") or "").strip()
        mode_schema = get_mode(modes, mode_name)
        if mode_schema is None:
            raise CommandBuildError(f"Unknown mode: {mode_name}")

        with self.lock:
            if self._active_count() >= self.settings.max_concurrent_jobs:
                raise RuntimeError("Another job is already running. Please wait or cancel it first.")

        patient_record = ensure_patient_workspace(self.settings, payload)
        patient_workspace = patient_record.workspace
        patient_display_name = (
            str(patient_record.patient.get("patient_name") or "").strip()
            or str(patient_record.patient.get("patient_id") or "").strip()
            or patient_record.folder
        )

        base_job_id = make_job_id(patient_record.folder)
        job_id = base_job_id
        job_workspace = self._job_workspace_for(patient_workspace, job_id)
        suffix = 2
        while job_workspace.exists() and not self.settings.allow_overwrite:
            job_id = f"{base_job_id}_{suffix:02d}"
            job_workspace = self._job_workspace_for(patient_workspace, job_id)
            suffix += 1

        job_workspace.mkdir(parents=True, exist_ok=True)
        command, warnings = build_command(self.settings, mode_schema, payload, patient_workspace)
        log_file = job_workspace / "run.log"
        initial_progress = self._progress_fields({"mode": mode_name, "status": "pending"})
        job = {
            "job_id": job_id,
            "patient_display_name": patient_display_name,
            "patient": patient_record.patient,
            "patient_folder": patient_record.folder,
            "mode": mode_name,
            "mode_label": mode_schema.get("label", mode_name),
            "status": "pending",
            "created_at": utc_now_iso(),
            "started_at": None,
            "finished_at": None,
            "elapsed_seconds": initial_progress["elapsed_seconds"],
            "stage": initial_progress["stage"],
            "progress": initial_progress["progress"],
            "estimated_remaining_seconds": initial_progress["estimated_remaining_seconds"],
            "command": command,
            "workspace": str(patient_workspace),
            "patient_workspace": str(patient_workspace),
            "job_workspace": str(job_workspace),
            "log_file": str(log_file),
            "outputs": [],
            "previews": [],
            "warnings": warnings,
            "error": None,
        }

        with self.lock:
            self.jobs[job_id] = job
            self._save_job(job)

        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        thread.start()
        return self._decorate_job(job)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.lock:
            jobs = [self._decorate_job(job) for job in self.jobs.values()]
        jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return jobs

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return self._decorate_job(job) if job else None

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.get("status") in FINAL_STATUSES:
                return self._decorate_job(job)
            self.cancel_requested.add(job_id)
            process = self.processes.get(job_id)

        if process is not None:
            self._terminate_process_tree(process)
        current = self.get_job(job_id) or {}
        updates = self._progress_fields(current, status="cancelled")
        return self._update_job(job_id, status="cancelled", finished_at=utc_now_iso(), **updates)

    def read_logs(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        log_path = Path(str(job["log_file"]))
        if not log_path.exists():
            return {"text": "", "size": 0}
        data = log_path.read_text(encoding="utf-8", errors="replace")
        return {"text": data, "size": log_path.stat().st_size}

    def outputs(self, job_id: str) -> list[dict[str, Any]]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        return scan_patient_outputs(Path(str(job["workspace"])), job_id=job_id, patient_folder=job.get("patient_folder"))

    def resolve_job_file(self, job_id: str, relative_path: str) -> Path:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        workspace = Path(str(job.get("patient_workspace") or job["workspace"])).resolve()
        target = (workspace / relative_path).resolve()
        if workspace != target and workspace not in target.parents:
            raise ValueError("File path is outside this workspace.")
        if not target.is_file():
            raise FileNotFoundError(str(target))
        return target

    def list_patients(self) -> list[dict[str, Any]]:
        return list_patients(self.settings)

    def save_patient(self, payload: dict[str, Any]) -> dict[str, Any]:
        return save_patient(self.settings, payload)

    def update_patient(self, patient_id_or_folder: str, payload: dict[str, Any]) -> dict[str, Any]:
        return update_patient(self.settings, patient_id_or_folder, payload)

    def get_patient(self, patient_id_or_folder: str) -> dict[str, Any]:
        return get_patient(self.settings, patient_id_or_folder)

    def patient_outputs(self, patient_id_or_folder: str) -> list[dict[str, Any]]:
        patient = self.get_patient(patient_id_or_folder)
        return scan_patient_outputs(
            Path(str(patient["patient_workspace"])),
            patient_folder=str(patient["patient_folder"]),
        )

    def resolve_patient_file(self, patient_id_or_folder: str, relative_path: str) -> Path:
        return resolve_patient_file(self.settings, patient_id_or_folder, relative_path)

    def _run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        log_path = Path(str(job["log_file"]))
        start_time = time.monotonic()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        running_fields = self._progress_fields(job, status="running")
        self._update_job(job_id, status="running", started_at=utc_now_iso(), **running_fields)

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("w", encoding="utf-8", errors="replace") as log:
                if job.get("warnings"):
                    for warning in job["warnings"]:
                        log.write(f"[WebUI Warning] {warning}\n")
                log.write("[WebUI] Command:\n")
                log.write(subprocess.list2cmdline(job["command"]) + "\n\n")
                log.flush()

                process = subprocess.Popen(
                    job["command"],
                    cwd=str(self.settings.mri2mr_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    env=env,
                )
                with self.lock:
                    self.processes[job_id] = process

                assert process.stdout is not None
                for line in process.stdout:
                    log.write(line)
                    log.flush()

                return_code = process.wait()

            elapsed = int(time.monotonic() - start_time)
            with self.lock:
                cancelled = job_id in self.cancel_requested

            if cancelled:
                self._finish_job(job_id, "cancelled", elapsed, None)
            elif return_code == 0:
                previews, warnings = generate_previews(Path(str(job["workspace"])))
                outputs = scan_patient_outputs(
                    Path(str(job["workspace"])),
                    job_id=job_id,
                    patient_folder=job.get("patient_folder"),
                )
                current = self.get_job(job_id) or job
                all_warnings = list(current.get("warnings") or []) + warnings
                self._finish_job(job_id, "success", elapsed, None, outputs=outputs, previews=previews, warnings=all_warnings)
            else:
                self._finish_job(job_id, "failed", elapsed, f"Process exited with code {return_code}")

        except Exception as exc:
            elapsed = int(time.monotonic() - start_time)
            try:
                with log_path.open("a", encoding="utf-8", errors="replace") as log:
                    log.write(f"\n[WebUI Error] {exc}\n")
            except Exception:
                pass
            self._finish_job(job_id, "failed", elapsed, str(exc))
        finally:
            with self.lock:
                self.processes.pop(job_id, None)
                self.cancel_requested.discard(job_id)

    def _finish_job(
        self,
        job_id: str,
        status: str,
        elapsed: int,
        error: str | None,
        outputs: list[dict[str, Any]] | None = None,
        previews: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        current = self.get_job(job_id) or {}
        progress_fields = self._progress_fields(current, status=status, elapsed_seconds=elapsed)
        updates: dict[str, Any] = {
            "status": status,
            "finished_at": utc_now_iso(),
            "error": error,
            **progress_fields,
        }
        if outputs is not None:
            updates["outputs"] = outputs
        if previews is not None:
            updates["previews"] = previews
        if warnings is not None:
            updates["warnings"] = warnings
        self._update_job(job_id, **updates)

    def _terminate_process_tree(self, process: subprocess.Popen[str]) -> None:
        try:
            import psutil
        except ImportError:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            return

        try:
            parent = psutil.Process(process.pid)
        except psutil.Error:
            return

        children = parent.children(recursive=True)
        for child in children:
            child.terminate()
        parent.terminate()

        gone, alive = psutil.wait_procs(children + [parent], timeout=5)
        for proc in alive:
            try:
                proc.kill()
            except psutil.Error:
                pass
