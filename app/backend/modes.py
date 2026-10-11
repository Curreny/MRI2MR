from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .config import CONFIG_DIR


FALLBACK_MODES: list[dict[str, Any]] = [
    {
        "mode": "dicom_convert",
        "label": "DICOM 转换",
        "description": "把 DICOM 文件夹转换为标准命名的 NIfTI 输入文件。",
        "primary_input": "dicom_dir",
        "fields": [
            {"name": "dicom_dir", "label": "DICOM 文件夹", "type": "folder", "cli": "--dicom-dir", "required": True},
            {"name": "dicom_decompress_dcmtk", "label": "启用 DCMTK 解压", "type": "boolean", "cli": "--dicom-decompress-dcmtk", "default": False},
            {"name": "dicom_only_dti", "label": "只处理 DTI", "type": "boolean", "cli": "--dicom-only-dti", "default": False},
            {"name": "dicom_t1_keywords", "label": "T1 关键词", "type": "list", "cli": "--dicom-t1-keywords", "default": "t1,mprage,bravo,spgr,tfl,3dt1", "advanced": True},
            {"name": "dicom_mra_keywords", "label": "MRA 关键词", "type": "list", "cli": "--dicom-mra-keywords", "default": "mra,tof,angio,artery", "advanced": True},
            {"name": "dicom_mrv_keywords", "label": "MRV 关键词", "type": "list", "cli": "--dicom-mrv-keywords", "default": "mrv,venography,venogram,vein,venous", "advanced": True},
            {"name": "dicom_dti_keywords", "label": "DTI 关键词", "type": "list", "cli": "--dicom-dti-keywords", "default": "dti,dwi,diff,diffusion,noddi,dir", "advanced": True},
        ],
    },
    {
        "mode": "synthseg_segmentation",
        "label": "SynthSeg 分割",
        "description": "使用 Docker SynthSeg 生成 T1_synthseg.nii。",
        "primary_input": "t1_file",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "dk_file", "label": "输出标签图", "type": "file", "cli": "--dk-file", "default_path": "SynthSeg_result/T1_synthseg.nii", "advanced": True},
            {"name": "synthseg_threads", "label": "CPU 线程数", "type": "number", "cli": "--synthseg-threads", "default": 4},
        ],
    },
    {
        "mode": "spm_segmentation",
        "label": "SPM 分割",
        "description": "用 MATLAB/SPM 生成灰质、白质分割结果。",
        "primary_input": "t1_file",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
        ],
    },
    {
        "mode": "individual_regions",
        "label": "DK 脑区模型",
        "description": "根据 SynthSeg 标签图生成 DK 脑区 GLB 模型。",
        "primary_input": "t1_file",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "dk_file", "label": "SynthSeg 标签图", "type": "file", "cli": "--dk-file", "required": True, "default_path": "SynthSeg_result/T1_synthseg.nii"},
            {"name": "dk_name_file", "label": "DK 区域名称文件", "type": "file", "cli": "--dk-name-file", "default_path": "template/DK_Regions.txt", "advanced": True},
            {"name": "num_processes", "label": "并行进程数", "type": "number", "cli": "--num-processes", "default": 8},
            {"name": "mesh_decimation_fraction", "label": "减面比例", "type": "number", "cli": "--mesh-decimation-fraction", "default": 0.08, "advanced": True},
        ],
    },
    {
        "mode": "gm_wm",
        "label": "灰白质模型",
        "description": "根据 SPM 白质 mask 生成 GLB 模型。",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "mask_file", "label": "白质 mask", "type": "file", "cli": "--mask-file", "required": True, "default_path": "patient_input/c2T1.nii"},
        ],
    },
    {
        "mode": "vessel",
        "label": "动脉模型",
        "description": "从 MRA NIfTI 生成动脉血管 GLB 模型。",
        "primary_input": "mra_file",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "mra_file", "label": "MRA NIfTI 文件", "type": "file", "cli": "--mra-file", "required": True, "default_path": "patient_input/MRA.nii"},
            {"name": "vessel_threshold", "label": "血管阈值", "type": "number", "cli": "--vessel-threshold", "default": 400},
            {"name": "vessel_min_object_size", "label": "最小连通区域", "type": "number", "cli": "--vessel-min-object-size", "default": 1000},
            {"name": "vessel_decimation_fraction", "label": "减面比例", "type": "number", "cli": "--vessel-decimation-fraction", "default": 0.5},
        ],
    },
    {
        "mode": "mrv",
        "label": "静脉模型",
        "description": "从 MRV NIfTI 生成静脉血管 GLB 模型。",
        "primary_input": "mrv_file",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "mrv_file", "label": "MRV NIfTI 文件", "type": "file", "cli": "--mrv-file", "required": True, "default_path": "patient_input/MRV.nii"},
            {"name": "mrv_strong_seed_percentile", "label": "强种子百分位", "type": "number", "cli": "--mrv-strong-seed-percentile", "default": 99.9},
            {"name": "mrv_weak_seed_percentile", "label": "弱种子百分位", "type": "number", "cli": "--mrv-weak-seed-percentile", "default": 99.8},
            {"name": "mrv_post_process_min_size", "label": "后处理最小大小", "type": "number", "cli": "--mrv-post-process-min-size", "default": 1000},
        ],
    },
    {
        "mode": "lobes",
        "label": "脑叶模型",
        "description": "根据 DK_Lobes 映射生成脑叶 GLB 模型。",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "dk_file", "label": "SynthSeg 标签图", "type": "file", "cli": "--dk-file", "required": True, "default_path": "SynthSeg_result/T1_synthseg.nii"},
            {"name": "lobe_map_file", "label": "脑叶映射文件", "type": "file", "cli": "--lobe-map-file", "required": True, "default_path": "template/DK_Lobes.txt"},
        ],
    },
    {
        "mode": "hemispheres",
        "label": "脑半球模型",
        "description": "生成左、右脑半球 GLB 模型。",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "dk_file", "label": "SynthSeg 标签图", "type": "file", "cli": "--dk-file", "required": True, "default_path": "SynthSeg_result/T1_synthseg.nii"},
        ],
    },
    {
        "mode": "ventricle",
        "label": "脑室模型",
        "description": "根据 robust SynthSeg 标签图生成脑室模型。",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "synthseg_robust_file", "label": "robust SynthSeg 标签图", "type": "file", "cli": "--synthseg-robust-file", "required": True, "default_path": "SynthSeg_result/T1_synthseg.nii"},
        ],
    },
    {
        "mode": "multiroi",
        "label": "多层 ROI 模型",
        "description": "从多层 ROI NIfTI 生成多个 GLB 模型。",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "multiroi_file", "label": "多层 ROI 文件", "type": "file", "cli": "--multiroi-file", "required": True, "default_path": "patient_input/Segmentation_multilayer.nii"},
        ],
    },
    {
        "mode": "fiber_tracking",
        "label": "普通纤维束",
        "description": "根据 DTI、bval、bvec 和白质 mask 生成纤维束 GLB。",
        "primary_input": "dti_file",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "dti_file", "label": "DTI NIfTI 文件", "type": "file", "cli": "--dti-file", "required": True, "default_path": "patient_input/DTI.nii.gz"},
            {"name": "dti_bvals_file", "label": "bval 文件", "type": "file", "cli": "--dti-bvals-file", "required": True, "default_path": "patient_input/DTI.bval"},
            {"name": "dti_bvecs_file", "label": "bvec 文件", "type": "file", "cli": "--dti-bvecs-file", "required": True, "default_path": "patient_input/DTI.bvec"},
            {"name": "mask_file", "label": "白质 mask", "type": "file", "cli": "--mask-file", "required": True, "default_path": "patient_input/c2T1.nii"},
            {"name": "fiber_gfa_threshold", "label": "GFA 阈值", "type": "number", "cli": "--fiber-gfa-threshold", "default": 0.25},
            {"name": "fiber_stop_threshold", "label": "停止阈值", "type": "number", "cli": "--fiber-stop-threshold", "default": 0.2},
            {"name": "fiber_step", "label": "采样步长", "type": "number", "cli": "--fiber-step", "default": 10},
            {"name": "fiber_seed_density", "label": "种子密度", "type": "number", "cli": "--fiber-seed-density", "default": 1},
        ],
    },
    {
        "mode": "fiber_tracking_region",
        "label": "脑区间纤维连接",
        "description": "生成脑区之间的纤维连接 GLB 模型。",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "dk_file", "label": "DK atlas", "type": "file", "cli": "--dk-file", "required": True, "default_path": "SynthSeg_result/T1_synthseg.nii"},
            {"name": "dti_file", "label": "DTI NIfTI 文件", "type": "file", "cli": "--dti-file", "required": True, "default_path": "patient_input/DTI.nii.gz"},
            {"name": "dti_bvals_file", "label": "bval 文件", "type": "file", "cli": "--dti-bvals-file", "required": True, "default_path": "patient_input/DTI.bval"},
            {"name": "dti_bvecs_file", "label": "bvec 文件", "type": "file", "cli": "--dti-bvecs-file", "required": True, "default_path": "patient_input/DTI.bvec"},
            {"name": "mask_file", "label": "白质 mask", "type": "file", "cli": "--mask-file", "required": True, "default_path": "patient_input/c2T1.nii"},
            {"name": "dk_name_file", "label": "DK 区域名称文件", "type": "file", "cli": "--dk-name-file", "default_path": "template/DK_Regions.txt", "advanced": True},
            {"name": "force_rebuild_gwi", "label": "重建 GWI atlas", "type": "boolean", "cli": "--force-rebuild-gwi", "default": False, "advanced": True},
        ],
    },
    {
        "mode": "tissue",
        "label": "其他组织",
        "description": "生成 SynthSeg 中的皮层下组织结构。",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "synthseg_robust_file", "label": "robust SynthSeg 标签图", "type": "file", "cli": "--synthseg-robust-file", "required": True, "default_path": "SynthSeg_result/T1_synthseg.nii"},
        ],
    },
    {
        "mode": "fiber_tracking_dki",
        "label": "DKI 纤维束",
        "description": "根据多 b 值 DKI 数据生成纤维束模型。",
        "fields": [
            {"name": "t1_file", "label": "T1 NIfTI 文件", "type": "file", "cli": "--t1-file", "required": True, "default_path": "patient_input/T1.nii"},
            {"name": "dki_file", "label": "DKI NIfTI 文件", "type": "file", "cli": "--dki-file", "required": True, "default_path": "patient_input/dki_4d.nii.gz"},
            {"name": "dki_bvals_file", "label": "DKI bval 文件", "type": "file", "cli": "--dki-bvals-file", "required": True, "default_path": "patient_input/bvals.bval"},
            {"name": "dki_bvecs_file", "label": "DKI bvec 文件", "type": "file", "cli": "--dki-bvecs-file", "required": True, "default_path": "patient_input/bvecs.bvec"},
            {"name": "mask_file", "label": "白质 mask", "type": "file", "cli": "--mask-file", "required": True, "default_path": "patient_input/c2T1.nii"},
        ],
    },
]


def _expand_mode_schema(data: dict[str, Any], modes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    common_model_fields = data.get("common_model_fields") or []
    expanded: list[dict[str, Any]] = []
    for mode in modes:
        item = copy.deepcopy(mode)
        if item.get("include_common_model_fields") and isinstance(common_model_fields, list):
            existing = {field.get("name") for field in item.get("fields", []) if isinstance(field, dict)}
            additions = [
                copy.deepcopy(field)
                for field in common_model_fields
                if isinstance(field, dict) and field.get("name") not in existing
            ]
            item["fields"] = list(item.get("fields") or []) + additions
        expanded.append(item)
    return expanded


def load_modes() -> list[dict[str, Any]]:
    modes_file = CONFIG_DIR / "modes.json"
    if not modes_file.exists():
        return copy.deepcopy(FALLBACK_MODES)

    with modes_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        modes = data.get("modes", [])
        if isinstance(modes, list) and modes:
            return _expand_mode_schema(data, modes)
    else:
        modes = data
    if not isinstance(modes, list) or not modes:
        return copy.deepcopy(FALLBACK_MODES)
    return modes


def get_mode(modes: list[dict[str, Any]], mode_name: str) -> dict[str, Any] | None:
    for mode in modes:
        if mode.get("mode") == mode_name:
            return mode
    return None


def iter_fields(mode: dict[str, Any]) -> list[dict[str, Any]]:
    fields = mode.get("fields", [])
    return fields if isinstance(fields, list) else []
