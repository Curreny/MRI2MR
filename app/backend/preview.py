from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .outputs import (
    is_nifti,
    is_segmentation_nifti,
    iter_output_files,
    preview_name_for,
    segmentation_preview_name_for,
)


SEGMENTATION_VIEWS = ("axial", "coronal", "sagittal")
PREVIEW_RENDERER_MTIME = Path(__file__).stat().st_mtime
NIFTI_AXIS_INDEX = {
    "x": 0,
    "sagittal": 0,
    "y": 1,
    "coronal": 1,
    "z": 2,
    "axial": 2,
}


def _normalize_slice(data: np.ndarray) -> Image.Image:
    data = np.nan_to_num(data.astype(np.float32), copy=False)
    if data.size == 0:
        return Image.new("L", (256, 256), color=0)
    low, high = np.percentile(data, [1, 99])
    if high <= low:
        low, high = float(np.min(data)), float(np.max(data))
    if high <= low:
        scaled = np.zeros_like(data, dtype=np.uint8)
    else:
        scaled = np.clip((data - low) / (high - low), 0, 1)
        scaled = (scaled * 255).astype(np.uint8)
    return Image.fromarray(scaled)


def _tile(image: Image.Image, label: str) -> Image.Image:
    if image.mode == "L":
        image = ImageOps.autocontrast(image)
    else:
        image = image.convert("RGB")
    image = ImageOps.contain(image, (240, 240))
    tile = Image.new("RGB", (260, 286), color=(18, 24, 32))
    x = (260 - image.width) // 2
    tile.paste(image.convert("RGB"), (x, 12))
    draw = ImageDraw.Draw(tile)
    draw.text((14, 262), label, fill=(196, 206, 220))
    return tile


def _slice_triplet(
    data: np.ndarray, zooms: tuple[float, float, float]
) -> list[tuple[str, np.ndarray, tuple[float, float]]]:
    x, y, z = (dim // 2 for dim in data.shape)
    return [
        # np.rot90 swaps the displayed width and height.  Keep the matching
        # physical pixel spacing so the preview uses anatomical proportions.
        ("axial", np.rot90(data[:, :, z]), (zooms[0], zooms[1])),
        ("coronal", np.rot90(data[:, y, :]), (zooms[0], zooms[2])),
        ("sagittal", np.rot90(data[x, :, :]), (zooms[1], zooms[2])),
    ]


def _read_nifti_volume(nifti_path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    import nibabel as nib

    img = nib.load(str(nifti_path))
    data = np.asanyarray(img.dataobj)
    if data.ndim == 4:
        data = data[..., 0]
    if data.ndim != 3:
        raise ValueError(f"Preview expects a 3D or 4D NIfTI: {nifti_path}")
    header_zooms = img.header.get_zooms()
    zooms = tuple(float(abs(header_zooms[index])) for index in range(3))
    if any(value <= 0 for value in zooms):
        zooms = (1.0, 1.0, 1.0)
    return data, zooms


@lru_cache(maxsize=2)
def _cached_nifti_volume(path: str, mtime_ns: int, size: int) -> tuple[np.ndarray, tuple[float, float, float]]:
    return _read_nifti_volume(Path(path))


def _load_nifti_volume(nifti_path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    resolved = nifti_path.resolve()
    info = resolved.stat()
    return _cached_nifti_volume(str(resolved), info.st_mtime_ns, info.st_size)


def _resample_to_physical_aspect(
    image: Image.Image,
    pixel_spacing: tuple[float, float],
    *,
    resample: Image.Resampling,
) -> Image.Image:
    """Return a slice whose pixel aspect reflects its in-plane voxel sizes."""
    spacing_x, spacing_y = pixel_spacing
    if spacing_x <= 0 or spacing_y <= 0:
        return image

    physical_width = image.width * spacing_x
    physical_height = image.height * spacing_y
    if physical_width <= 0 or physical_height <= 0:
        return image

    # Preserve the native resolution along the finest sampled direction while
    # limiting the generated preview to a practical size.
    pixels_per_mm = 1.0 / min(spacing_x, spacing_y)
    max_dimension = 2048
    pixels_per_mm = min(pixels_per_mm, max_dimension / max(physical_width, physical_height))
    target = (
        max(1, int(round(physical_width * pixels_per_mm))),
        max(1, int(round(physical_height * pixels_per_mm))),
    )
    if target == image.size:
        return image
    return image.resize(target, resample=resample)


def _slice_image(array: np.ndarray, pixel_spacing: tuple[float, float], segmentation: bool) -> Image.Image:
    if segmentation:
        image = _colorize_label_slice(array)
        return _resample_to_physical_aspect(image, pixel_spacing, resample=Image.Resampling.NEAREST)
    image = ImageOps.autocontrast(_normalize_slice(array)).convert("RGB")
    # Thick-slice directions contain fewer acquired samples.  Interpolating
    # them with bilinear filtering makes the preview look falsely blurred;
    # nearest-neighbour expansion keeps the measured voxel values crisp.
    anisotropy = max(pixel_spacing) / min(pixel_spacing)
    resample = Image.Resampling.NEAREST if anisotropy > 1.5 else Image.Resampling.BILINEAR
    return _resample_to_physical_aspect(image, pixel_spacing, resample=resample)


def _preview_is_current(preview_path: Path, source_mtime: float) -> bool:
    """Invalidate cached PNGs whenever their source or renderer changes."""
    return preview_path.exists() and preview_path.stat().st_mtime >= max(source_mtime, PREVIEW_RENDERER_MTIME)


def _axis_index(axis: str) -> int:
    key = str(axis or "z").lower()
    if key not in NIFTI_AXIS_INDEX:
        raise ValueError("axis must be one of x, y, z")
    return NIFTI_AXIS_INDEX[key]


def nifti_volume_info(nifti_path: Path) -> dict[str, Any]:
    import nibabel as nib

    img = nib.load(str(nifti_path))
    shape = tuple(int(dim) for dim in img.shape[:3])
    if len(shape) != 3:
        raise ValueError(f"Preview expects a 3D or 4D NIfTI: {nifti_path}")
    return {
        "shape": list(shape),
        "voxel_spacing": [float(abs(img.header.get_zooms()[index])) for index in range(3)],
        "axes": {
            "x": {"size": shape[0], "default_index": shape[0] // 2, "label": "X"},
            "y": {"size": shape[1], "default_index": shape[1] // 2, "label": "Y"},
            "z": {"size": shape[2], "default_index": shape[2] // 2, "label": "Z"},
        },
        "default_axis": "z",
        "segmentation": is_segmentation_nifti(nifti_path),
    }


def render_nifti_slice_png(nifti_path: Path, axis: str, index: int) -> tuple[BytesIO, dict[str, Any]]:
    data, zooms = _load_nifti_volume(nifti_path)
    axis_no = _axis_index(axis)
    max_index = data.shape[axis_no] - 1
    slice_index = min(max(int(index), 0), max_index)

    if axis_no == 0:
        array = np.rot90(data[slice_index, :, :])
        axis_key = "x"
        pixel_spacing = (zooms[1], zooms[2])
    elif axis_no == 1:
        array = np.rot90(data[:, slice_index, :])
        axis_key = "y"
        pixel_spacing = (zooms[0], zooms[2])
    else:
        array = np.rot90(data[:, :, slice_index])
        axis_key = "z"
        pixel_spacing = (zooms[0], zooms[1])

    image = _slice_image(array, pixel_spacing, is_segmentation_nifti(nifti_path))

    stream = BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    return stream, {
        "axis": axis_key,
        "index": slice_index,
        "size": data.shape[axis_no],
        "width": image.width,
        "height": image.height,
    }


def _label_color(label: int) -> tuple[int, int, int]:
    if label == 0:
        return (0, 0, 0)
    value = abs(int(label))
    return (
        48 + (value * 37) % 208,
        48 + (value * 73) % 208,
        48 + (value * 109) % 208,
    )


def _colorize_label_slice(data: np.ndarray) -> Image.Image:
    labels = np.rint(np.nan_to_num(data, copy=False)).astype(np.int64, copy=False)
    rgb = np.zeros((*labels.shape, 3), dtype=np.uint8)
    for label in np.unique(labels):
        if label == 0:
            continue
        rgb[labels == label] = _label_color(int(label))
    return Image.fromarray(rgb, mode="RGB")


def generate_segmentation_preview(nifti_path: Path, preview_dir: Path) -> Path:
    preview_dir.mkdir(parents=True, exist_ok=True)
    montage_path = preview_dir / preview_name_for(nifti_path)
    view_paths = [preview_dir / segmentation_preview_name_for(nifti_path, view) for view in SEGMENTATION_VIEWS]
    outputs = [montage_path, *view_paths]
    source_mtime = nifti_path.stat().st_mtime
    if all(_preview_is_current(path, source_mtime) for path in outputs):
        return montage_path

    data, zooms = _load_nifti_volume(nifti_path)
    canvas = Image.new("RGB", (780, 286), color=(12, 16, 22))
    for idx, (label, array, pixel_spacing) in enumerate(_slice_triplet(data, zooms)):
        tile = _tile(_slice_image(array, pixel_spacing, segmentation=True), label)
        tile.save(preview_dir / segmentation_preview_name_for(nifti_path, label))
        canvas.paste(tile, (idx * 260, 0))
    canvas.save(montage_path)
    return montage_path


def generate_grayscale_nifti_preview(nifti_path: Path, preview_dir: Path) -> Path:
    preview_dir.mkdir(parents=True, exist_ok=True)
    out_path = preview_dir / preview_name_for(nifti_path)
    if _preview_is_current(out_path, nifti_path.stat().st_mtime):
        return out_path

    data, zooms = _load_nifti_volume(nifti_path)

    canvas = Image.new("RGB", (780, 286), color=(12, 16, 22))
    for idx, (label, array, pixel_spacing) in enumerate(_slice_triplet(data, zooms)):
        canvas.paste(_tile(_slice_image(array, pixel_spacing, segmentation=False), label), (idx * 260, 0))
    canvas.save(out_path)
    return out_path


def generate_nifti_preview(nifti_path: Path, preview_dir: Path) -> Path:
    if is_segmentation_nifti(nifti_path):
        return generate_segmentation_preview(nifti_path, preview_dir)
    return generate_grayscale_nifti_preview(nifti_path, preview_dir)


def generate_previews(workspace: Path) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    previews: list[dict[str, Any]] = []
    preview_dir = workspace / "previews"

    for path in iter_output_files(workspace):
        if not is_nifti(path):
            continue
        try:
            preview_path = generate_nifti_preview(path, preview_dir)
            previews.append(
                {
                    "source": path.relative_to(workspace).as_posix(),
                    "preview": preview_path.relative_to(workspace).as_posix(),
                    "type": "segmentation_slices" if is_segmentation_nifti(path) else "nifti_slices",
                }
            )
        except Exception as exc:  # pragma: no cover - surfaced in job logs
            warnings.append(f"Could not generate preview for {path.name}: {exc}")

    return previews, warnings
