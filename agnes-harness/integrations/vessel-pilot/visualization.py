"""Small, anonymous previews carried by MCP and persisted as session artifacts."""
from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps


MAX_PREVIEW_BYTES = 1024 * 1024
# Harness production MCP policy accepts at most two image blocks per tool result.
MAX_IMAGES = 2
MAX_NIFTI_VOLUMES = 3


def gray_image(array: Any, invert: bool = False) -> Image.Image:
    values = np.asarray(array, dtype=float)
    if values.ndim != 2 or not np.isfinite(values).any():
        raise ValueError("No readable grayscale pixels")
    finite = values[np.isfinite(values)]
    low, high = np.percentile(finite, [1, 99])
    if high <= low:
        low, high = float(finite.min()), float(finite.max())
    pixels = np.clip((np.nan_to_num(values, nan=low) - low) / max(high - low, 1e-9), 0, 1)
    image = Image.fromarray((pixels * 255).astype(np.uint8), "L").convert("RGB")
    return ImageOps.invert(image) if invert else image


def montage(tiles: list[tuple[str, Image.Image]], columns: int = 3) -> Image.Image:
    width, height = 300, 320
    canvas = Image.new("RGB", (columns * width, ((len(tiles) + columns - 1) // columns) * height), (15, 23, 35))
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(tiles):
        tile = image.copy()
        tile.thumbnail((width - 16, height - 36))
        x, y = (index % columns) * width, (index // columns) * height
        canvas.paste(tile, (x + (width - tile.width) // 2, y + 28 + (height - 36 - tile.height) // 2))
        draw.text((x + 12, y + 9), label, fill=(216, 226, 240))
    return canvas


def nifti_preview(path: Path) -> Image.Image:
    import nibabel as nib

    image = nib.load(str(path))
    if len(image.shape) > 3:
        image = image.slicer[(slice(None),) * 3 + (0,) * (len(image.shape) - 3)]
    image = nib.as_closest_canonical(image)
    # Read only three planes of the first frame, never a whole 4D diffusion volume.
    shape = image.shape
    if len(shape) < 2:
        raise ValueError("NIfTI has fewer than two dimensions")
    tail = (0,) * max(0, len(shape) - 3)
    if len(shape) == 2:
        return montage([("Image plane", gray_image(image.dataobj[:, :]))], columns=1)
    spacing = image.header.get_zooms()[:3]
    tiles = []
    for axis, label, plane_axes in ((0, "Sagittal / X", (1, 2)), (1, "Coronal / Y", (0, 2)), (2, "Axial / Z", (0, 1))):
        selection = [slice(None)] * 3
        selection[axis] = shape[axis] // 2
        tile = gray_image(np.rot90(np.asarray(image.dataobj[tuple(selection) + tail])))
        physical = (tile.width * spacing[plane_axes[0]], tile.height * spacing[plane_axes[1]])
        scale = 280 / max(physical)
        tile = tile.resize((max(1, round(physical[0] * scale)), max(1, round(physical[1] * scale))))
        tiles.append((label, tile))
    return montage(tiles)


def dicom_preview(source: Path) -> tuple[Image.Image | None, list[str]]:
    import pydicom

    series: dict[str, list[tuple[float, Path]]] = {}
    scanned = 0
    # Sampling is bounded and confined to the already registered input root.
    for path in source.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        scanned += 1
        if scanned > 2048:
            break
        try:
            header = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
            if not getattr(header, "Rows", 0) or not getattr(header, "Columns", 0):
                continue
            uid = str(getattr(header, "SeriesInstanceUID", path.parent))
            series.setdefault(uid, []).append((float(getattr(header, "InstanceNumber", 0)), path))
        except Exception:
            continue
    tiles = []
    unavailable = 0
    for series_index, entries in enumerate(list(series.values())[:3]):
        entries.sort(key=lambda item: (item[0], str(item[1])))
        indices = sorted({round((len(entries) - 1) * fraction) for fraction in (0.25, 0.5, 0.75)})
        for index in indices:
            try:
                dataset = pydicom.dcmread(str(entries[index][1]), force=True)
                if int(dataset.Rows) * int(dataset.Columns) * int(getattr(dataset, "NumberOfFrames", 1)) > 32_000_000:
                    raise ValueError("DICOM sample exceeds preview pixel budget")
                if getattr(dataset, "SamplesPerPixel", 1) != 1:
                    raise ValueError("Only grayscale DICOM samples are supported")
                pixels = dataset.pixel_array
                if pixels.ndim == 3:
                    pixels = pixels[pixels.shape[0] // 2]
                pixels = pixels.astype(float) * float(getattr(dataset, "RescaleSlope", 1)) + float(getattr(dataset, "RescaleIntercept", 0))
                tile = gray_image(pixels, str(getattr(dataset, "PhotometricInterpretation", "")) == "MONOCHROME1")
                spacing = getattr(dataset, "PixelSpacing", [1, 1])
                physical = (tile.width * float(spacing[1]), tile.height * float(spacing[0]))
                scale = 280 / max(physical)
                tile = tile.resize((max(1, round(physical[0] * scale)), max(1, round(physical[1] * scale))))
                tiles.append((f"Series {series_index + 1} / sample {index + 1}", tile))
            except Exception:
                unavailable += 1
    warnings = ["DICOM 仅抽样前 2048 个文件、最多三个序列；切片编号不代表解剖方位。"]
    if unavailable or not tiles:
        warnings.append("部分 DICOM 像素无法解码（可能为压缩格式）；可在转换完成后查看 NIfTI 预览。")
    return (montage(tiles) if tiles else None), warnings


def image_content(image: Image.Image, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    stream = BytesIO()
    image.convert("RGB").quantize(colors=128).save(stream, format="PNG", optimize=True)
    raw = stream.getvalue()
    if len(raw) > MAX_PREVIEW_BYTES:
        raise ValueError("Preview exceeds the one MiB artifact read budget")
    descriptor = {"label": label, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "mime": "image/png"}
    block = {"type": "image", "data": base64.b64encode(raw).decode("ascii"), "mimeType": "image/png"}
    return descriptor, block


def tool_visualization(service: Any, name: str, arguments: dict[str, Any], data: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Enrich results without changing processing, job state, or tool authorization."""
    case_id = arguments.get("case_id") or data.get("case_id")
    if not case_id:
        return None, []
    stage = ""
    title = ""
    images: list[tuple[str, Image.Image]] = []
    warnings: list[str] = []
    candidate_id = arguments.get("candidate_id") or arguments.get("based_on_candidate_id")
    parameters = data.get("parameters", {})
    metrics = data.get("metrics", {})
    conclusion = data.get("conclusion")
    result = data.get("result") or {}
    if name == "inspect_dicom_case":
        stage, title = "dicom", "原始 DICOM · 抽样切片"
        case_dir, manifest = service._load_case(case_id)
        try:
            cached = case_dir / "previews" / "dicom.png"
            if cached.is_file():
                with Image.open(cached) as image:
                    images.append(("DICOM 原始像素抽样", image.copy()))
                warnings.append("DICOM 抽样预览；不叠加患者信息，切片编号不代表解剖方位。")
            else:
                image, notes = dicom_preview(Path(manifest["source_path"]))
                warnings.extend(notes)
                if image:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    image.save(cached)
                    images.append(("DICOM 原始像素抽样", image))
        except Exception:
            warnings.append("DICOM 原始切片预览不可用；转换和重建仍可继续。")
    elif (name == "get_vessel_job" and data.get("kind") == "conversion" and data.get("status") == "succeeded") or (name == "start_dicom_conversion" and data.get("status") == "already_succeeded"):
        stage, title = "nifti", "转换完成 · NIfTI 三向切片"
        outputs = result.get("outputs", data.get("outputs", {}))
        case_dir, _ = service._load_case(case_id)
        for label, value in list(outputs.items())[:MAX_NIFTI_VOLUMES]:
            try:
                path = Path(value).resolve(strict=True)
                path.relative_to(case_dir.resolve())
                images.append((str(label), nifti_preview(path)))
            except Exception:
                warnings.append(f"{label} 切片预览不可用；转换文件路径仍保留在工具结果中。")
        if len(outputs) > MAX_NIFTI_VOLUMES:
            warnings.append(f"共 {len(outputs)} 个 NIfTI 输出，此处展示前 {MAX_NIFTI_VOLUMES} 个。")
        if len(images) > 1:
            # One strip per volume: three volumes fit in 900x960, below the media pixel budget.
            canvas = Image.new("RGB", (900, 320 * len(images)), (15, 23, 35))
            labels = []
            for index, (label, image) in enumerate(images):
                tile = image.copy()
                tile.thumbnail((900, 296))
                canvas.paste(tile, ((900 - tile.width) // 2, index * 320 + 24))
                ImageDraw.Draw(canvas).text((12, index * 320 + 6), f"Volume {index + 1}", fill=(216, 226, 240))
                labels.append(f"{index + 1}: {label}")
            images = [("NIfTI · " + " / ".join(labels), canvas)]
    elif name in {"evaluate_vessel_candidate", "finalize_vessel_case", "suggest_vessel_parameters"}:
        stage = {"evaluate_vessel_candidate": "candidate", "finalize_vessel_case": "final", "suggest_vessel_parameters": "tuning"}[name]
        if name == "evaluate_vessel_candidate" and arguments.get("assessments") is not None:
            stage = "visual_qc"
        title = {"candidate": "候选评估 · GLB 六视图", "visual_qc": "视觉质控 · 判断与依据", "final": "最终模型 · 定稿摘要", "tuning": "Agent 参数寻优 · 本轮判断与下一步"}[stage]
        case_dir, _ = service._load_case(case_id)
        report = data if stage in {"candidate", "visual_qc"} else json.loads((case_dir / "candidates" / candidate_id / "report.json").read_text(encoding="utf-8"))
        parameters, metrics, conclusion = report.get("parameters", {}), report.get("metrics", {}), report.get("conclusion")
        # A candidate's montage is immutable and is already shown by the first
        # evaluation. Later QC, tuning and finalization cards only add decisions;
        # attaching the same pixels again duplicates the image in chat history.
        if stage == "candidate":
            for vessel, value in report.get("preview_montages", {}).items():
                path = Path(value).resolve(strict=True)
                path.relative_to(case_dir.resolve())
                with Image.open(path) as image:
                    images.append((f"{'动脉' if vessel == 'artery' else '静脉'} GLB · 前 / 后 / 左 / 右 / 上 / 下", image.copy()))
    else:
        return None, []
    descriptors, blocks = [], []
    for label, image in images[:MAX_IMAGES]:
        try:
            descriptor, block = image_content(image, label)
            descriptors.append(descriptor)
            blocks.append(block)
        except Exception:
            warnings.append(f"{label} 预览生成失败。")
    visualization = {"version": 1, "stage": stage, "title": title, "case_id": case_id,
                     "candidate_id": candidate_id, "parameters": parameters, "metrics": metrics,
                     "conclusion": conclusion, "images": descriptors, "warnings": warnings}
    if stage == "visual_qc":
        visualization["visual_assessment"] = report.get("visual_assessment")
    if stage == "tuning":
        visualization["decision"] = {"status": data.get("status"), "reason": data.get("reason"),
                                     "next_parameters": data.get("parameters"),
                                     "artery_assessment": arguments.get("artery_assessment"),
                                     "vein_assessment": arguments.get("vein_assessment")}
    return visualization, blocks
