from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .command_builder import CommandBuildError
from .config import APP_ROOT, AppSettings
from .jobs import JobManager
from .modes import load_modes
from .outputs import is_nifti
from .inspectors import detect_dicom_series_payload, inspect_path_payload
from .preview import nifti_volume_info, render_nifti_slice_png


settings = AppSettings.load()
job_manager = JobManager(settings)

app = FastAPI(title="MRI2MR WebUI", version="0.1.0")
static_dir = APP_ROOT / "app" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.middleware("http")
async def no_cache_for_webui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    response = FileResponse(static_dir / "index.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/api/config")
def api_config() -> dict[str, Any]:
    return settings.public_dict()


@app.get("/api/runtime-status")
def api_runtime_status() -> dict[str, Any]:
    return settings.runtime_status()


@app.get("/api/modes")
def api_modes() -> dict[str, Any]:
    return {"modes": load_modes()}


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    return payload


def _dialog_filetypes(patterns: Any) -> list[tuple[str, str]] | None:
    if not isinstance(patterns, list):
        return None
    filetypes: list[tuple[str, str]] = []
    for item in patterns:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        label = str(item[0] or "Files")
        pattern_value = item[1]
        if isinstance(pattern_value, (list, tuple)):
            pattern = " ".join(str(part) for part in pattern_value if part)
        else:
            pattern = str(pattern_value or "*")
        filetypes.append((label, pattern))
    return filetypes or None


def _dialog_initial_dir(value: Any) -> str | None:
    text = str(value or "").strip().strip('"').strip("'").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_file():
        path = path.parent
    if path.is_dir():
        return str(path)
    return None


def _open_native_path_dialog(payload: dict[str, Any]) -> str:
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in {"file", "directory"}:
        raise ValueError("kind must be 'file' or 'directory'.")

    try:
        import tkinter as tk
        from tkinter import TclError, filedialog
    except Exception as exc:
        raise RuntimeError("Tkinter is not available; native file dialogs cannot be opened.") from exc

    title = str(payload.get("title") or ("Select file" if kind == "file" else "Select directory"))
    options: dict[str, Any] = {"title": title}
    initial_dir = _dialog_initial_dir(payload.get("initial_dir"))
    if initial_dir:
        options["initialdir"] = initial_dir
    if kind == "file":
        filetypes = _dialog_filetypes(payload.get("patterns"))
        if filetypes:
            options["filetypes"] = filetypes

    root: Any | None = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        if kind == "file":
            selected = filedialog.askopenfilename(parent=root, **options)
        else:
            selected = filedialog.askdirectory(parent=root, **options)
        root.update()
        return str(selected or "")
    except TclError as exc:
        raise RuntimeError(
            "Could not open native file dialog. The server may be running without a desktop session."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Could not open native file dialog: {exc}") from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


@app.post("/api/select-path")
async def select_path(request: Request) -> dict[str, str]:
    payload = await _json_object(request)
    try:
        return {"path": _open_native_path_dialog(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/inspect-path")
async def inspect_path(request: Request) -> dict[str, Any]:
    payload = await _json_object(request)
    return inspect_path_payload(payload)


@app.post("/api/detect-dicom-series")
async def detect_dicom_series(request: Request) -> dict[str, Any]:
    payload = await _json_object(request)
    return detect_dicom_series_payload(payload)


@app.post("/api/jobs")
async def create_job(request: Request) -> dict[str, Any]:
    payload = await request.json()
    try:
        job = job_manager.create_job(payload)
        return {"job": job}
    except CommandBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": job_manager.list_jobs()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job}


@app.get("/api/jobs/{job_id}/logs")
def get_logs(job_id: str) -> dict[str, Any]:
    try:
        return job_manager.read_logs(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    try:
        return {"job": job_manager.cancel_job(job_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@app.get("/api/jobs/{job_id}/outputs")
def get_outputs(job_id: str) -> dict[str, Any]:
    try:
        return {"outputs": job_manager.outputs(job_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@app.get("/api/jobs/{job_id}/previews")
def get_previews(job_id: str) -> dict[str, Any]:
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"previews": job.get("previews", [])}


@app.get("/api/jobs/{job_id}/file")
def get_job_file(job_id: str, path: str) -> FileResponse:
    try:
        target = job_manager.resolve_job_file(job_id, path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(target)


@app.get("/api/jobs/{job_id}/nifti-info")
def get_job_nifti_info(job_id: str, path: str) -> dict[str, Any]:
    try:
        target = job_manager.resolve_job_file(job_id, path)
        if not is_nifti(target):
            raise ValueError("File is not a NIfTI volume.")
        return nifti_volume_info(target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/nifti-slice")
def get_job_nifti_slice(
    job_id: str,
    path: str,
    axis: str = Query("z"),
    index: int = Query(0, ge=0),
) -> StreamingResponse:
    try:
        target = job_manager.resolve_job_file(job_id, path)
        if not is_nifti(target):
            raise ValueError("File is not a NIfTI volume.")
        stream, meta = render_nifti_slice_png(target, axis, index)
        return StreamingResponse(
            stream,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "X-Nifti-Axis": str(meta["axis"]),
                "X-Nifti-Index": str(meta["index"]),
                "X-Nifti-Size": str(meta["size"]),
            },
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/patients")
def list_patients() -> dict[str, Any]:
    return {"patients": job_manager.list_patients()}


@app.post("/api/patients")
async def create_patient(request: Request) -> dict[str, Any]:
    payload = await request.json()
    try:
        return {"patient": job_manager.save_patient(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/patients/{patient_id_or_folder}")
async def update_patient(patient_id_or_folder: str, request: Request) -> dict[str, Any]:
    payload = await request.json()
    try:
        return {"patient": job_manager.update_patient(patient_id_or_folder, payload)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/patients/{patient_id_or_folder}/outputs")
def get_patient_outputs(patient_id_or_folder: str) -> dict[str, Any]:
    try:
        return {"outputs": job_manager.patient_outputs(patient_id_or_folder)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc


@app.get("/api/patients/{patient_id_or_folder}/file")
def get_patient_file(patient_id_or_folder: str, path: str) -> FileResponse:
    try:
        target = job_manager.resolve_patient_file(patient_id_or_folder, path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(target)


@app.get("/api/patients/{patient_id_or_folder}/nifti-info")
def get_patient_nifti_info(patient_id_or_folder: str, path: str) -> dict[str, Any]:
    try:
        target = job_manager.resolve_patient_file(patient_id_or_folder, path)
        if not is_nifti(target):
            raise ValueError("File is not a NIfTI volume.")
        return nifti_volume_info(target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/patients/{patient_id_or_folder}/nifti-slice")
def get_patient_nifti_slice(
    patient_id_or_folder: str,
    path: str,
    axis: str = Query("z"),
    index: int = Query(0, ge=0),
) -> StreamingResponse:
    try:
        target = job_manager.resolve_patient_file(patient_id_or_folder, path)
        if not is_nifti(target):
            raise ValueError("File is not a NIfTI volume.")
        stream, meta = render_nifti_slice_png(target, axis, index)
        return StreamingResponse(
            stream,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "X-Nifti-Axis": str(meta["axis"]),
                "X-Nifti-Index": str(meta["index"]),
                "X-Nifti-Size": str(meta["size"]),
            },
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/patients/{patient_id_or_folder}")
def get_patient(patient_id_or_folder: str) -> dict[str, Any]:
    try:
        return {"patient": job_manager.get_patient(patient_id_or_folder)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
