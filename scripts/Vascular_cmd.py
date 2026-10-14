"""Standalone command-line pipeline for vascular MRI data.

This module contains only the three vascular-related operations that used to
live in ``Main_cmd.py``:

* DICOM -> standardized T1/MRA/MRV NIfTI files
* arterial (MRA) preprocessing and GLB reconstruction
* venous (MRV) preprocessing and GLB reconstruction

Examples (PowerShell):

    python scripts/Vascular_cmd.py --mode dicom_convert --dicom-dir D:\dicom
    python scripts/Vascular_cmd.py --mode artery --base-data-dir D:\case01
    python scripts/Vascular_cmd.py --mode vein --base-data-dir D:\case01

Without T1, convert only MRA/MRV; reconstruction will automatically use MRA
as the common reference space:

    python scripts/Vascular_cmd.py --mode dicom_convert --dicom-dir D:\dicom --dicom-modalities MRA MRV
    python scripts/Vascular_cmd.py --mode artery --base-data-dir D:\case01 --reference-modality auto

The legacy mode names ``vessel`` and ``mrv`` are accepted as aliases for
``artery`` and ``vein`` respectively.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import nibabel as nib
import numpy as np
import trimesh
from scipy import ndimage
from scipy.linalg import polar
from skimage import measure
from skimage.filters import frangi
from skimage.morphology import remove_small_objects
from vedo import Mesh


DEFAULT_T1_KEYWORDS = ("t1", "mprage", "bravo", "spgr", "tfl", "3dt1")
DEFAULT_MRA_KEYWORDS = ("mra", "tof", "angio", "artery")
DEFAULT_MRV_KEYWORDS = ("mrv", "venography", "venogram", "vein", "venous")
DERIVED_SERIES_KEYWORDS = (
    "mip",
    "batchmip",
    "mpr",
    "scout",
    "motion",
    "curve",
    "localizer",
    "survey",
    "ref",
)


@dataclass
class VascularConfig:
    mode: str
    base_data_dir: Path
    patient_data_dir: Path
    output_dir: Path
    t1_file: Path
    mra_file: Path
    mrv_file: Path
    reference_file: Path | None
    reference_modality: str
    dcm2niix_exe: str
    dcmtk_dcmdjpeg_exe: str
    dicom_decompress_dcmtk: bool
    dicom_decompress_dir: Path
    dicom_dir: Path | None
    dicom_temp_dir: Path
    dicom_t1_source: Path | None
    dicom_mra_source: Path | None
    dicom_mrv_source: Path | None
    dicom_modalities: tuple[str, ...]
    dicom_t1_keywords: tuple[str, ...]
    dicom_mra_keywords: tuple[str, ...]
    dicom_mrv_keywords: tuple[str, ...]
    marching_cubes_level: float
    min_object_size: int
    mesh_decimation_fraction: float
    vessel_threshold: float
    vessel_min_object_size: int
    vessel_decimation_fraction: float
    mrv_frangi_cache_file: Path
    mrv_frangi_sigmas_start: int
    mrv_frangi_sigmas_end: int
    mrv_frangi_sigmas_step: int
    mrv_strong_seed_percentile: float
    mrv_strong_grow_tolerance: float
    mrv_weak_seed_percentile: float
    mrv_weak_grow_tolerance: float
    mrv_post_process_min_size: int
    force_rebuild_frangi: bool
    artery_output_file: Path
    vein_output_file: Path


def nifti_stem(path: Path) -> str:
    name = path.name
    if name.lower().endswith(".nii.gz"):
        return name[:-7]
    if name.lower().endswith(".nii"):
        return name[:-4]
    return path.stem


def is_nifti_path(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".nii") or name.endswith(".nii.gz")


def read_json_safely(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve_executable(executable: str, option_name: str) -> str:
    path = Path(executable)
    if path.exists():
        return str(path.resolve())
    found = shutil.which(executable)
    if found:
        return found
    raise FileNotFoundError(
        f"Executable not found: {executable}. Provide {option_name} or add it to PATH."
    )


def centered_affine(t1_img: nib.spatialimages.SpatialImage) -> np.ndarray:
    """Match the centered, rotation-free coordinate system used by Main_cmd.py."""
    original = t1_img.affine
    translation = original[:3, 3]
    _, scale_matrix = polar(original[:3, :3])
    scale = scale_matrix[(0, 1, 2), (0, 1, 2)]

    affine = np.zeros((4, 4), dtype=float)
    affine[(0, 1, 2), (0, 1, 2)] = scale
    affine[3, 3] = 1.0
    affine[:3, 3] = translation
    center = np.asarray(t1_img.shape[:3]) // 2
    offset = nib.affines.apply_affine(affine, center)
    affine[:3, 3] = translation - offset
    return affine


def apply_material(mesh: trimesh.Trimesh, material_name: str) -> None:
    colors = {
        "vessel": (179, 29, 29),
        "vessel_vein": (20, 40, 252),
    }
    material = trimesh.visual.material.PBRMaterial(
        name=material_name,
        baseColorFactor=colors[material_name],
        metallicFactor=0.1,
        roughnessFactor=0.8,
    )
    mesh.visual = trimesh.visual.TextureVisuals(material=material)


def export_mesh(
    mesh: trimesh.Trimesh,
    output_file: Path,
    decimation_fraction: float,
    material_name: str,
) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if decimation_fraction < 1.0:
        vedo_mesh = Mesh([mesh.vertices, mesh.faces])
        decimated = vedo_mesh.decimate(fraction=decimation_fraction)
        mesh = trimesh.Trimesh(vertices=decimated.points, faces=decimated.cells)
    apply_material(mesh, material_name)
    mesh.faces = mesh.faces[:, [0, 2, 1]]
    mesh.export(str(output_file), file_type="glb")
    print(f"[完成] 已导出模型: {output_file}")
    return output_file


class DicomConverter:
    def __init__(self, config: VascularConfig):
        self.config = config

    @staticmethod
    def _text_tokens(text: str) -> set[str]:
        return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}

    def _matched_derived_keywords(self, text: str) -> list[str]:
        tokens = self._text_tokens(text)
        compact = re.sub(r"[^a-z0-9]+", "", text.lower())
        matched: list[str] = []
        for keyword in DERIVED_SERIES_KEYWORDS:
            if keyword == "batchmip" and "batchmip" in compact:
                matched.append(keyword)
            elif keyword in {"mip", "mpr", "ref"} and keyword in tokens:
                matched.append(keyword)
            elif keyword not in {"batchmip", "mip", "mpr", "ref"} and (
                keyword in tokens or keyword in text.lower()
            ):
                matched.append(keyword)
        return matched

    @staticmethod
    def _matched_keywords(text: str, keywords: Iterable[str]) -> list[str]:
        lowered = text.lower()
        return [keyword for keyword in keywords if keyword.lower() in lowered]

    @staticmethod
    def _header_info(path: Path) -> tuple[list[int], list[float], str | None]:
        try:
            image = nib.load(str(path))
            return (
                [int(value) for value in image.shape],
                [float(value) for value in image.header.get_zooms()[:3]],
                None,
            )
        except Exception as exc:  # corrupted converter output must be logged
            return [], [], str(exc)

    def _collect_candidates(self, output_dir: Path) -> list[dict[str, Any]]:
        paths = sorted(output_dir.rglob("*.nii")) + sorted(output_dir.rglob("*.nii.gz"))
        candidates: list[dict[str, Any]] = []
        for path in paths:
            stem = nifti_stem(path)
            json_path = path.with_name(stem + ".json")
            bval_path = path.with_name(stem + ".bval")
            bvec_path = path.with_name(stem + ".bvec")
            metadata = read_json_safely(json_path)
            image_type = metadata.get("ImageType", "")
            image_type_text = " ".join(image_type) if isinstance(image_type, list) else str(image_type)
            description_parts = (
                path.name,
                str(metadata.get("SeriesDescription", "")),
                str(metadata.get("ProtocolName", "")),
                str(metadata.get("SequenceName", "")),
                image_type_text,
            )
            shape, voxel_size, load_error = self._header_info(path)
            candidates.append(
                {
                    "nii": path,
                    "json": json_path,
                    "desc": " ".join(description_parts).lower(),
                    "series_description": metadata.get("SeriesDescription", ""),
                    "protocol_name": metadata.get("ProtocolName", ""),
                    "sequence_name": metadata.get("SequenceName", ""),
                    "series_number": metadata.get("SeriesNumber"),
                    "image_type": image_type,
                    "is_original_image_type": "ORIGINAL" in image_type_text.upper(),
                    "is_derived_image_type": any(
                        marker in image_type_text.upper() for marker in ("DERIVED", "SECONDARY")
                    ),
                    "has_bval_bvec": bval_path.exists() and bvec_path.exists(),
                    "shape": shape,
                    "voxel_size": voxel_size,
                    "nifti_load_error": load_error,
                    "size": path.stat().st_size,
                }
            )
        return candidates

    def _candidate_summary(
        self,
        candidate: dict[str, Any],
        *,
        score: float | None = None,
        matched_keywords: list[str] | None = None,
        reason: str | None = None,
        eligible: bool | None = None,
    ) -> dict[str, Any]:
        summary = {
            "name": candidate["nii"].name,
            "path": str(candidate["nii"]),
            "json": str(candidate["json"]) if candidate["json"].exists() else None,
            "series_description": candidate.get("series_description"),
            "protocol_name": candidate.get("protocol_name"),
            "sequence_name": candidate.get("sequence_name"),
            "series_number": candidate.get("series_number"),
            "image_type": candidate.get("image_type"),
            "shape": candidate.get("shape", []),
            "voxel_size": candidate.get("voxel_size", []),
            "size": candidate.get("size", 0),
            "matched_keywords": matched_keywords or [],
            "derived_keywords": self._matched_derived_keywords(candidate.get("desc", "")),
            "score": score,
            "reason": reason,
        }
        if eligible is not None:
            summary["eligible"] = eligible
        if candidate.get("nifti_load_error"):
            summary["nifti_load_error"] = candidate["nifti_load_error"]
        return summary

    def _rank_candidate(
        self,
        candidates: list[dict[str, Any]],
        keywords: tuple[str, ...],
        modality: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        evaluated: list[dict[str, Any]] = []
        for candidate in candidates:
            matched = self._matched_keywords(candidate["desc"], keywords)
            derived = self._matched_derived_keywords(candidate["desc"])
            shape = candidate.get("shape", [])
            valid_3d = len(shape) == 3 and all(int(value) > 1 for value in shape)
            eligible = False
            score: float | None = None
            if candidate["has_bval_bvec"]:
                reason = "excluded: diffusion sidecars present"
            elif not matched:
                reason = "excluded: no modality keyword match"
            elif candidate.get("nifti_load_error"):
                reason = "excluded: converted NIfTI is unreadable"
            elif not valid_3d:
                reason = "excluded: reconstruction requires a non-degenerate 3D volume"
            elif derived:
                reason = f"excluded: derived/localizer series ({', '.join(derived)})"
            else:
                eligible = True
                score = float(100 * len(matched))
                score += 40 if candidate["is_original_image_type"] else 0
                score += 20
                score -= 60 if candidate["is_derived_image_type"] else 0
                score += min(candidate["size"] / 1_000_000.0, 50.0) / 100.0
                reason = "eligible: keyword match"
            evaluated.append(
                {
                    "candidate": candidate,
                    "matched": matched,
                    "score": score,
                    "eligible": eligible,
                    "reason": reason,
                }
            )

        eligible_items = [item for item in evaluated if item["eligible"]]
        selected_item = max(
            eligible_items,
            key=lambda item: (item["score"], item["candidate"]["size"]),
            default=None,
        )
        selected = selected_item["candidate"] if selected_item else None
        warnings: list[str] = []
        if len(eligible_items) > 1:
            warnings.append("multiple_matching_candidates_ranked_deterministically")
        if len(eligible_items) < len(candidates):
            warnings.append("nonmatching_or_unsupported_series_ignored")
        if selected and selected.get("is_derived_image_type"):
            warnings.append("selected_series_has_derived_image_type")
        report = {
            "modality": modality,
            "reason": selected_item["reason"] if selected_item else "no matching candidate",
            "matched_keywords": selected_item["matched"] if selected_item else [],
            "candidate_count": len(candidates),
            "eligible_candidate_count": len(eligible_items),
            "ignored_candidate_count": len(candidates) - len(eligible_items),
            "warnings": warnings,
            "selected_candidate": (
                self._candidate_summary(
                    selected,
                    score=selected_item["score"],
                    matched_keywords=selected_item["matched"],
                    reason=selected_item["reason"],
                    eligible=True,
                )
                if selected_item
                else None
            ),
            "candidates": [
                self._candidate_summary(
                    item["candidate"],
                    score=item["score"],
                    matched_keywords=item["matched"],
                    reason=item["reason"],
                    eligible=item["eligible"],
                )
                for item in evaluated
            ],
        }
        if selected:
            print(
                f"[DICOM] {modality} 选择: {selected['nii'].name} "
                f"(score={selected_item['score']:.3f}, keywords={selected_item['matched']})"
            )
        else:
            print(f"[DICOM 警告] 未找到匹配的 {modality} 序列，关键词: {list(keywords)}")
        return selected, report

    def _decompress(self, source_dir: Path, output_dir: Path) -> Path:
        command = resolve_executable(
            self.config.dcmtk_dcmdjpeg_exe, "--dcmtk-dcmdjpeg-exe"
        )
        source_dir = source_dir.resolve()
        output_dir = output_dir.resolve()
        if output_dir == source_dir or source_dir in output_dir.parents or output_dir in source_dir.parents:
            raise ValueError("DCMTK temporary directory must be separate from the DICOM source tree.")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.copytree(source_dir, output_dir)
        files = [path for path in output_dir.rglob("*") if path.is_file()]
        if not files:
            raise RuntimeError(f"No files found in DICOM directory: {source_dir}")

        succeeded = 0
        failed = 0
        for path in files:
            temporary = path.with_name(path.name + ".dcmtk_tmp")
            result = subprocess.run(
                [command, str(path), str(temporary)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
            )
            if result.returncode == 0 and temporary.exists():
                os.replace(temporary, path)
                succeeded += 1
            else:
                temporary.unlink(missing_ok=True)
                failed += 1
        print(f"[DCMTK] 解压完成: success={succeeded}, skipped/failed={failed}")
        return output_dir

    def _run_dcm2niix(self, source_dir: Path, output_dir: Path) -> list[dict[str, Any]]:
        command = resolve_executable(self.config.dcm2niix_exe, "--dcm2niix-exe")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        arguments = [
            command,
            "-z",
            "n",
            "-b",
            "y",
            "-f",
            "%p_%s_%t_%j",
            "-o",
            str(output_dir),
            str(source_dir),
        ]
        print("[DICOM] 执行:", subprocess.list2cmdline(arguments))
        result = subprocess.run(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
        )
        if result.stdout:
            print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"dcm2niix failed with return code {result.returncode}")
        candidates = self._collect_candidates(output_dir)
        if not candidates:
            raise RuntimeError(f"dcm2niix did not create NIfTI files in: {output_dir}")
        return candidates

    @staticmethod
    def _save_nifti(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() == destination.resolve():
            return
        same_compression = source.name.lower().endswith(".nii") and destination.name.lower().endswith(".nii")
        same_compression |= source.name.lower().endswith(".nii.gz") and destination.name.lower().endswith(".nii.gz")
        if same_compression:
            shutil.copy2(source, destination)
        else:
            nib.save(nib.load(str(source)), str(destination))

    def _convert_manual_source(
        self,
        modality: str,
        source: Path,
        keywords: tuple[str, ...],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not source.exists():
            raise FileNotFoundError(f"Manual {modality} source not found: {source}")
        if source.is_file() and is_nifti_path(source):
            shape, voxel_size, load_error = self._header_info(source)
            stem = nifti_stem(source)
            candidate = {
                "nii": source,
                "json": source.with_name(stem + ".json"),
                "desc": f"{source.name} manual_nifti".lower(),
                "series_description": source.name,
                "protocol_name": "",
                "sequence_name": "",
                "series_number": None,
                "image_type": "manual_nifti",
                "is_original_image_type": False,
                "is_derived_image_type": False,
                "has_bval_bvec": False,
                "shape": shape,
                "voxel_size": voxel_size,
                "nifti_load_error": load_error,
                "size": source.stat().st_size,
            }
            report = {
                "modality": modality,
                "selection_mode": "manual_nifti",
                "reason": "manual NIfTI source",
                "matched_keywords": self._matched_keywords(candidate["desc"], keywords),
                "candidate_count": 1,
                "selected_candidate": self._candidate_summary(candidate, eligible=True),
                "candidates": [self._candidate_summary(candidate, eligible=True)],
            }
            return candidate, report
        if not source.is_dir():
            raise ValueError(f"Manual {modality} source must be a NIfTI file or DICOM folder: {source}")

        dicom_input = source
        if self.config.dicom_decompress_dcmtk:
            dicom_input = self._decompress(
                source,
                self.config.dicom_decompress_dir.parent / f"manual_{modality.lower()}_dcmtk",
            )
        candidates = self._run_dcm2niix(
            dicom_input,
            self.config.dicom_temp_dir.parent / f"manual_{modality.lower()}",
        )
        anatomical = [candidate for candidate in candidates if not candidate["has_bval_bvec"]]
        if len(anatomical) != 1:
            names = ", ".join(candidate["nii"].name for candidate in anatomical) or "none"
            raise RuntimeError(
                f"Manual {modality} DICOM folder must contain exactly one anatomical series; "
                f"found {len(anatomical)}: {names}"
            )
        candidate = anatomical[0]
        report = {
            "modality": modality,
            "selection_mode": "manual_dicom_series",
            "reason": "single anatomical series in manual source",
            "matched_keywords": self._matched_keywords(candidate["desc"], keywords),
            "candidate_count": len(candidates),
            "selected_candidate": self._candidate_summary(candidate, eligible=True),
            "candidates": [self._candidate_summary(item) for item in candidates],
        }
        return candidate, report

    def run(self) -> list[Path]:
        if "ALL" in self.config.dicom_modalities:
            if self.config.dicom_modalities != ("ALL",):
                raise ValueError("ALL cannot be combined with selected modalities")
            source = self.config.dicom_dir
            if source is None or not source.is_dir():
                raise ValueError("--dicom-dir must be an existing directory")
            if self.config.dicom_decompress_dcmtk:
                source = self._decompress(source, self.config.dicom_decompress_dir)
            candidates = self._run_dcm2niix(source, self.config.patient_data_dir / "nifti")
            return [item["nii"] for item in candidates]
        available_modalities = {
            "T1": (self.config.dicom_t1_source, self.config.dicom_t1_keywords),
            "MRA": (self.config.dicom_mra_source, self.config.dicom_mra_keywords),
            "MRV": (self.config.dicom_mrv_source, self.config.dicom_mrv_keywords),
        }
        modalities = {
            name: available_modalities[name] for name in self.config.dicom_modalities
        }
        auto_modalities = [name for name, (source, _) in modalities.items() if source is None]
        automatic_candidates: list[dict[str, Any]] | None = None
        if auto_modalities:
            if self.config.dicom_dir is None:
                raise ValueError(
                    "--dicom-dir is required for automatic selection of: "
                    + ", ".join(auto_modalities)
                )
            if not self.config.dicom_dir.is_dir():
                raise FileNotFoundError(f"DICOM directory not found: {self.config.dicom_dir}")
            dicom_input = self.config.dicom_dir
            if self.config.dicom_decompress_dcmtk:
                dicom_input = self._decompress(dicom_input, self.config.dicom_decompress_dir)
            automatic_candidates = self._run_dcm2niix(dicom_input, self.config.dicom_temp_dir)

        outputs: list[Path] = []
        reports: list[dict[str, Any]] = []
        for modality, (manual_source, keywords) in modalities.items():
            if manual_source is None:
                assert automatic_candidates is not None
                candidate, report = self._rank_candidate(
                    automatic_candidates, keywords, modality
                )
                report["selection_mode"] = "auto"
                report["source_path"] = str(self.config.dicom_dir)
            else:
                candidate, report = self._convert_manual_source(
                    modality, manual_source, keywords
                )
                report["source_path"] = str(manual_source)
            destination = self.config.patient_data_dir / f"{modality}.nii"
            if candidate is not None:
                self._save_nifti(candidate["nii"], destination)
                outputs.append(destination)
                report["output_paths"] = {"nii": str(destination)}
                print(f"[DICOM] 已导出 {modality}: {destination}")
            else:
                report["output_paths"] = {}
            reports.append(report)

        candidates_log = self.config.base_data_dir / "temp" / "dicom_candidates.json"
        selection_log = self.config.patient_data_dir / "dicom_selection.json"
        candidates_log.parent.mkdir(parents=True, exist_ok=True)
        selection_log.parent.mkdir(parents=True, exist_ok=True)
        candidates_log.write_text(
            json.dumps({"records": reports}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        compact_reports = [{key: value for key, value in report.items() if key != "candidates"} for report in reports]
        selection_log.write_text(
            json.dumps({"records": compact_reports}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[DICOM] 选择日志: {selection_log}")
        return outputs


class VascularProcessor:
    def __init__(self, config: VascularConfig):
        self.config = config

    def _resolve_reference_file(self) -> tuple[Path, str]:
        if self.config.reference_file is not None:
            return self.config.reference_file, "custom"
        if self.config.reference_modality == "t1":
            return self.config.t1_file, "T1"
        if self.config.reference_modality == "mra":
            return self.config.mra_file, "MRA"
        if self.config.t1_file.exists():
            return self.config.t1_file, "T1"
        return self.config.mra_file, "MRA (T1 不存在，自动回退)"

    def _load_reference(self) -> tuple[nib.spatialimages.SpatialImage, np.ndarray]:
        reference_file, reference_name = self._resolve_reference_file()
        if not reference_file.exists():
            raise FileNotFoundError(
                f"Reference image not found ({reference_name}): {reference_file}"
            )
        image = nib.load(str(reference_file))
        if len(image.shape) < 3:
            raise ValueError(f"Reference image is not 3D: {reference_file}")
        print(f"[空间] 使用 {reference_name} 作为统一参考空间: {reference_file}")
        return image, centered_affine(image)

    @staticmethod
    def _mesh_in_reference_space(
        mask: np.ndarray,
        source_affine: np.ndarray,
        reference_img: nib.spatialimages.SpatialImage,
        target_affine: np.ndarray,
        level: float,
    ) -> trimesh.Trimesh:
        vertices, faces, _, _ = measure.marching_cubes(mask, level=level)
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
        mesh = trimesh.smoothing.filter_humphrey(mesh)
        source_to_reference_voxel = np.linalg.inv(reference_img.affine).dot(source_affine)
        mesh.vertices = nib.affines.apply_affine(source_to_reference_voxel, mesh.vertices)
        mesh.vertices = nib.affines.apply_affine(target_affine, mesh.vertices)
        mesh.apply_scale(1 / 1000)
        return mesh

    def process_artery(self) -> Path:
        if not self.config.mra_file.exists():
            raise FileNotFoundError(f"MRA image not found: {self.config.mra_file}")
        reference_img, target_affine = self._load_reference()
        mra_img = nib.load(str(self.config.mra_file))
        mra = mra_img.get_fdata()
        if mra.ndim != 3:
            raise ValueError(f"MRA image must be 3D, got shape {mra.shape}")

        thresholded = mra > self.config.vessel_threshold
        cleaned = remove_small_objects(
            thresholded, min_size=self.config.vessel_min_object_size
        )
        if not cleaned.any():
            raise RuntimeError(
                "No artery voxels remain after thresholding. Lower --vessel-threshold "
                "or --vessel-min-object-size."
            )
        labels, count = measure.label(cleaned, connectivity=2, return_num=True)
        sizes = np.bincount(labels.ravel())
        largest_label = int(np.argmax(sizes[1:]) + 1)
        print(
            f"[动脉] 找到 {count} 个连通域，保留最大连通域 "
            f"#{largest_label} ({sizes[largest_label]} voxels)"
        )
        artery_mask = labels == largest_label
        mesh = self._mesh_in_reference_space(
            artery_mask,
            mra_img.affine,
            reference_img,
            target_affine,
            self.config.marching_cubes_level,
        )
        return export_mesh(
            mesh,
            self.config.artery_output_file,
            self.config.vessel_decimation_fraction,
            "vessel",
        )

    @staticmethod
    def region_growing_3d(
        image: np.ndarray, seeds_mask: np.ndarray, intensity_threshold: float
    ) -> np.ndarray:
        segmented = np.zeros_like(image, dtype=bool)
        visited = np.zeros_like(image, dtype=bool)
        queue: deque[tuple[int, int, int]] = deque()
        for seed in np.argwhere(seeds_mask):
            point = tuple(int(value) for value in seed)
            queue.append(point)
            visited[point] = True
            segmented[point] = True
        neighbors = ((0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0), (1, 0, 0), (-1, 0, 0))
        while queue:
            z, y, x = queue.popleft()
            for dz, dy, dx in neighbors:
                nz, ny, nx = z + dz, y + dy, x + dx
                if not (0 <= nz < image.shape[0] and 0 <= ny < image.shape[1] and 0 <= nx < image.shape[2]):
                    continue
                if visited[nz, ny, nx]:
                    continue
                visited[nz, ny, nx] = True
                if image[nz, ny, nx] >= intensity_threshold:
                    segmented[nz, ny, nx] = True
                    queue.append((nz, ny, nx))
        return segmented

    def _load_or_build_frangi(
        self, mrv: np.ndarray, mrv_img: nib.spatialimages.SpatialImage
    ) -> np.ndarray:
        cache = self.config.mrv_frangi_cache_file
        if cache.exists() and not self.config.force_rebuild_frangi:
            cached = nib.load(str(cache)).get_fdata()
            if cached.shape == mrv.shape:
                print(f"[静脉] 复用 Frangi 缓存: {cache}")
                return cached
            print(f"[静脉] 缓存尺寸 {cached.shape} 与 MRV {mrv.shape} 不一致，将重新计算")
        sigmas = range(
            self.config.mrv_frangi_sigmas_start,
            self.config.mrv_frangi_sigmas_end,
            self.config.mrv_frangi_sigmas_step,
        )
        print(f"[静脉] 计算 Frangi，sigmas={list(sigmas)}")
        volume = frangi(mrv, sigmas=sigmas, black_ridges=False) * 1000
        cache.parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(volume, mrv_img.affine, header=mrv_img.header), str(cache))
        print(f"[静脉] 已保存 Frangi 缓存: {cache}")
        return volume

    def process_vein(self) -> Path:
        if not self.config.mrv_file.exists():
            raise FileNotFoundError(f"MRV image not found: {self.config.mrv_file}")
        reference_img, target_affine = self._load_reference()
        mrv_img = nib.load(str(self.config.mrv_file))
        mrv = mrv_img.get_fdata()
        if mrv.ndim != 3:
            raise ValueError(f"MRV image must be 3D, got shape {mrv.shape}")
        volume = self._load_or_build_frangi(mrv, mrv_img)
        positive = volume[volume > 0]
        if positive.size == 0:
            raise RuntimeError("Frangi filter produced no positive vessel response.")

        strong_threshold = np.percentile(
            positive, self.config.mrv_strong_seed_percentile
        )
        strong_seeds = volume > strong_threshold
        strong_intensities = mrv[strong_seeds]
        print(
            f"[静脉] 强种子阈值={strong_threshold:.4f}, "
            f"种子数={int(strong_seeds.sum())}"
        )
        if strong_intensities.size:
            strong_growth_threshold = (
                float(np.min(strong_intensities))
                * self.config.mrv_strong_grow_tolerance
            )
            strong = self.region_growing_3d(
                mrv, strong_seeds, strong_growth_threshold
            )
        else:
            strong = np.zeros_like(mrv, dtype=bool)

        weak_threshold = np.percentile(positive, self.config.mrv_weak_seed_percentile)
        weak_seeds = (volume > weak_threshold) & ~strong
        weak_intensities = mrv[weak_seeds]
        print(
            f"[静脉] 弱种子阈值={weak_threshold:.4f}, "
            f"新增种子数={int(weak_seeds.sum())}"
        )
        if weak_intensities.size:
            weak_growth_threshold = (
                float(np.min(weak_intensities))
                * self.config.mrv_weak_grow_tolerance
            )
            weak = self.region_growing_3d(mrv, weak_seeds, weak_growth_threshold)
        else:
            weak = np.zeros_like(mrv, dtype=bool)

        segmentation = remove_small_objects(
            strong | weak, min_size=self.config.mrv_post_process_min_size
        )
        segmentation = ndimage.binary_fill_holes(segmentation)
        segmentation = remove_small_objects(
            segmentation.astype(bool), min_size=self.config.min_object_size
        )
        if not segmentation.any():
            raise RuntimeError(
                "No vein voxels remain after post-processing. Lower the MRV minimum-size settings."
            )
        mesh = self._mesh_in_reference_space(
            segmentation,
            mrv_img.affine,
            reference_img,
            target_affine,
            self.config.marching_cubes_level,
        )
        return export_mesh(
            mesh,
            self.config.vein_output_file,
            self.config.mesh_decimation_fraction,
            "vessel_vein",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="血管 MRI 独立处理工具：DICOM 转 NIfTI、动脉重建、静脉重建。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("dicom_convert", "artery", "vein", "vessel", "mrv"),
        help="运行模式；vessel=artery，mrv=vein。",
    )
    parser.add_argument("--base-data-dir")
    parser.add_argument("--patient-data-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--t1-file")
    parser.add_argument("--mra-file")
    parser.add_argument("--mrv-file")
    parser.add_argument(
        "--reference-file",
        help="显式指定统一空间参考影像；设置后优先级高于 --reference-modality。",
    )
    parser.add_argument(
        "--reference-modality",
        choices=("auto", "t1", "mra"),
        default="auto",
        help="auto 优先 T1，T1 不存在时自动使用 MRA。",
    )

    dicom = parser.add_argument_group("DICOM 转换")
    dicom.add_argument("--dicom-dir")
    dicom.add_argument("--dicom-temp-dir")
    dicom.add_argument("--dcm2niix-exe", default="dcm2niix.exe")
    dicom.add_argument("--dcmtk-dcmdjpeg-exe", default="dcmdjpeg.exe")
    dicom.add_argument("--dicom-decompress-dcmtk", action="store_true")
    dicom.add_argument("--dicom-decompress-dir")
    dicom.add_argument("--dicom-t1-source")
    dicom.add_argument("--dicom-mra-source")
    dicom.add_argument("--dicom-mrv-source")
    dicom.add_argument(
        "--dicom-modalities",
        nargs="+",
        type=str.upper,
        choices=("T1", "MRA", "MRV", "ALL"),
        default=("T1", "MRA", "MRV"),
        help="选择血管相关模态，或单独指定 ALL 仅转换所有可转换序列，不进行重建序列筛选。",
    )
    dicom.add_argument("--dicom-t1-keywords", nargs="*")
    dicom.add_argument("--dicom-mra-keywords", nargs="*")
    dicom.add_argument("--dicom-mrv-keywords", nargs="*")

    mesh = parser.add_argument_group("通用网格")
    mesh.add_argument("--marching-cubes-level", type=float, default=0.7)
    mesh.add_argument("--min-object-size", type=int, default=14500)
    mesh.add_argument("--mesh-decimation-fraction", type=float, default=0.08)

    artery = parser.add_argument_group("动脉 MRA")
    artery.add_argument("--vessel-threshold", type=float, default=400)
    artery.add_argument("--vessel-min-object-size", type=int, default=1000)
    artery.add_argument("--vessel-decimation-fraction", type=float, default=0.5)
    artery.add_argument("--artery-output-file")

    vein = parser.add_argument_group("静脉 MRV")
    vein.add_argument("--mrv-frangi-cache-file")
    vein.add_argument("--force-rebuild-frangi", action="store_true")
    vein.add_argument("--mrv-frangi-sigmas-start", type=int, default=1)
    vein.add_argument("--mrv-frangi-sigmas-end", type=int, default=12)
    vein.add_argument("--mrv-frangi-sigmas-step", type=int, default=1)
    vein.add_argument("--mrv-strong-seed-percentile", type=float, default=99.9)
    vein.add_argument("--mrv-strong-grow-tolerance", type=float, default=0.95)
    vein.add_argument("--mrv-weak-seed-percentile", type=float, default=99.8)
    vein.add_argument("--mrv-weak-grow-tolerance", type=float, default=0.85)
    vein.add_argument("--mrv-post-process-min-size", type=int, default=1000)
    vein.add_argument("--vein-output-file")
    return parser


def path_or_none(value: str | None) -> Path | None:
    return Path(value).expanduser().resolve() if value and value.strip() else None


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    for name in ("mesh_decimation_fraction", "vessel_decimation_fraction"):
        value = getattr(args, name)
        if not 0 < value <= 1:
            parser.error(f"--{name.replace('_', '-')} must be in (0, 1].")
    for name in ("mrv_strong_seed_percentile", "mrv_weak_seed_percentile"):
        value = getattr(args, name)
        if not 0 <= value <= 100:
            parser.error(f"--{name.replace('_', '-')} must be in [0, 100].")
    if args.mrv_frangi_sigmas_step <= 0:
        parser.error("--mrv-frangi-sigmas-step must be greater than zero.")
    if args.mrv_frangi_sigmas_end <= args.mrv_frangi_sigmas_start:
        parser.error("--mrv-frangi-sigmas-end must be greater than --mrv-frangi-sigmas-start.")
    for name in ("min_object_size", "vessel_min_object_size", "mrv_post_process_min_size"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1.")


def make_config(args: argparse.Namespace) -> VascularConfig:
    mode = {"vessel": "artery", "mrv": "vein"}.get(args.mode, args.mode)
    project_root = Path(__file__).resolve().parents[1]
    base = path_or_none(args.base_data_dir) or project_root / "workspace" / "default"
    patient = path_or_none(args.patient_data_dir) or base / "patient_input"
    output = path_or_none(args.output_dir) or base / "model_output"
    return VascularConfig(
        mode=mode,
        base_data_dir=base,
        patient_data_dir=patient,
        output_dir=output,
        t1_file=path_or_none(args.t1_file) or patient / "T1.nii",
        mra_file=path_or_none(args.mra_file) or patient / "MRA.nii",
        mrv_file=path_or_none(args.mrv_file) or patient / "MRV.nii",
        reference_file=path_or_none(args.reference_file),
        reference_modality=args.reference_modality,
        dcm2niix_exe=args.dcm2niix_exe,
        dcmtk_dcmdjpeg_exe=args.dcmtk_dcmdjpeg_exe,
        dicom_decompress_dcmtk=args.dicom_decompress_dcmtk,
        dicom_decompress_dir=path_or_none(args.dicom_decompress_dir) or base / "temp" / "dicom_dcmtk_decompressed",
        dicom_dir=path_or_none(args.dicom_dir),
        dicom_temp_dir=path_or_none(args.dicom_temp_dir) or base / "temp" / "dicom2niix_output",
        dicom_t1_source=path_or_none(args.dicom_t1_source),
        dicom_mra_source=path_or_none(args.dicom_mra_source),
        dicom_mrv_source=path_or_none(args.dicom_mrv_source),
        dicom_modalities=tuple(dict.fromkeys(args.dicom_modalities)),
        dicom_t1_keywords=tuple(args.dicom_t1_keywords or DEFAULT_T1_KEYWORDS),
        dicom_mra_keywords=tuple(args.dicom_mra_keywords or DEFAULT_MRA_KEYWORDS),
        dicom_mrv_keywords=tuple(args.dicom_mrv_keywords or DEFAULT_MRV_KEYWORDS),
        marching_cubes_level=args.marching_cubes_level,
        min_object_size=args.min_object_size,
        mesh_decimation_fraction=args.mesh_decimation_fraction,
        vessel_threshold=args.vessel_threshold,
        vessel_min_object_size=args.vessel_min_object_size,
        vessel_decimation_fraction=args.vessel_decimation_fraction,
        mrv_frangi_cache_file=path_or_none(args.mrv_frangi_cache_file) or base / "temp" / "out_figma12_1000.nii",
        mrv_frangi_sigmas_start=args.mrv_frangi_sigmas_start,
        mrv_frangi_sigmas_end=args.mrv_frangi_sigmas_end,
        mrv_frangi_sigmas_step=args.mrv_frangi_sigmas_step,
        mrv_strong_seed_percentile=args.mrv_strong_seed_percentile,
        mrv_strong_grow_tolerance=args.mrv_strong_grow_tolerance,
        mrv_weak_seed_percentile=args.mrv_weak_seed_percentile,
        mrv_weak_grow_tolerance=args.mrv_weak_grow_tolerance,
        mrv_post_process_min_size=args.mrv_post_process_min_size,
        force_rebuild_frangi=args.force_rebuild_frangi,
        artery_output_file=path_or_none(args.artery_output_file) or output / "vessel" / "vessel.glb",
        vein_output_file=path_or_none(args.vein_output_file) or output / "mrv" / "vessel_vein.glb",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)
    config = make_config(args)
    print(f"--- Vascular pipeline mode: {config.mode} ---")
    try:
        if config.mode == "dicom_convert":
            DicomConverter(config).run()
        elif config.mode == "artery":
            VascularProcessor(config).process_artery()
        elif config.mode == "vein":
            VascularProcessor(config).process_vein()
        else:  # argparse guards this branch
            raise ValueError(f"Unsupported mode: {config.mode}")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
