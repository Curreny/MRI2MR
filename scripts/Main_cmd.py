###
#  10.13 正常人模型生成
#  问题在于生成的模型使用的拉普拉斯
###

import glob
import os
import random
import shutil
import argparse
import subprocess
import json
import re

import numpy as np
import trimesh.visual.material
from scipy.ndimage import zoom
from fontTools.subset import closure_lookups

from skimage import measure
from skimage.draw import ellipsoid
import trimesh
from scipy.linalg import polar
from skimage.morphology import remove_small_objects
import nibabel as nib
import multiprocessing as mp
from vedo import Mesh
from dipy.io.image import load_nifti, load_nifti_data
from enum import Enum, auto
from pathlib import Path
import Utils.util
from dipy.io.gradients import read_bvals_bvecs
from nilearn import image
from dipy.core.gradients import gradient_table
from dipy.reconst.csdeconv import (ConstrainedSphericalDeconvModel,auto_response_ssst)

from dipy.reconst.shm import CsaOdfModel
from dipy.tracking.stopping_criterion import ThresholdStoppingCriterion
from dipy.tracking import utils
from dipy.direction import DeterministicMaximumDirectionGetter
from dipy.data import default_sphere
from dipy.tracking.local_tracking import LocalTracking
from dipy.tracking.streamline import Streamlines
from skimage import data, filters
from skimage.filters import frangi
from scipy.ndimage import binary_erosion, binary_dilation, binary_opening, binary_closing
from collections import deque
from trimesh.visual.material import SimpleMaterial
from scipy import ndimage
from PIL import Image, ImageDraw
from io import BytesIO

import vtk
from vtk.util import numpy_support
from scipy.ndimage import convolve

##########################
## Configuration Management
##########################
class ProcessMode(Enum):
    """modes for processing different brain meshes."""
    DICOM_CONVERT = auto()
    SPM_SEGMENTATION = auto()
    SYNTHSEG_SEGMENTATION = auto()
    INDIVIDUAL_REGIONS = auto()
    GM_WM = auto()
    VESSEL = auto()
    LOBES = auto()
    HEMISPHERES = auto()
    ROI = auto()
    FIBER_TRACKING = auto()
    MRV = auto()
    VENTRICLE = auto()
    MULTIROI = auto()
    FIBER_TRACKING_REGION = auto()
    TISSUE = auto()
    FIBER_TRACKING_DKI = auto()

class Config:
    """Configuration class for parameters."""

    def __init__(
        self,
        mode: ProcessMode,
        base_data_dir=None,
        patient_data_dir=None,
        synthseg_data_dir=None,
        spm_dir=None,
        spm_script_dir=None,
        spm_backend="auto",
        matlab_exe=None,
        mcr_home=None,
        spm_standalone_exe=None,
        spm_compiled_exe=None,
        template_dir=None,
        output_dir=None,
        dcm2niix_exe=None,
        dcmtk_dcmdjpeg_exe=None,
        dicom_decompress_dcmtk=False,
        dicom_decompress_dir=None,
        dicom_only_dti=False,
        docker_exe=None,
        synthseg_docker_image="pwesp/synthseg:py38",
        synthseg_threads=None,
        dicom_dir=None,
        dicom_temp_dir=None,
        dicom_t1_source=None,
        dicom_mra_source=None,
        dicom_mrv_source=None,
        dicom_dti_source=None,
        dicom_t1_keywords=None,
        dicom_mra_keywords=None,
        dicom_mrv_keywords=None,
        dicom_dti_keywords=None,
        t1_file=None,
        dk_file=None,
        mra_file=None,
        mrv_file=None,
        roi_file=None,
        multiroi_file=None,
        dti_file=None,
        dti_bvals_file=None,
        dti_bvecs_file=None,
        mask_file=None,
        gwi_atlas_file=None,
        dki_file=None,
        dki_bvals_file=None,
        dki_bvecs_file=None,
        synthseg_robust_file=None,
        dk_name_file=None,
        lobe_map_file=None,
        smoothing_iterations=20,
        smoothing_lambda=0.7,
        marching_cubes_level=0.7,
        min_object_size=14500,
        mesh_decimation_fraction=0.08,
        num_processes=8,
        gwi_dilation_iterations=2,
        vessel_threshold=400,
        vessel_min_object_size=1000,
        vessel_decimation_fraction=0.5,
        mrv_frangi_cache_file=None,
        mrv_frangi_sigmas_start=1,
        mrv_frangi_sigmas_end=12,
        mrv_frangi_sigmas_step=1,
        mrv_strong_seed_percentile=99.9,
        mrv_strong_grow_tolerance=0.95,
        mrv_weak_seed_percentile=99.8,
        mrv_weak_grow_tolerance=0.85,
        mrv_post_process_min_size=1000,
        fiber_gfa_cache_file=None,
        fiber_gfa_threshold=0.25,
        fiber_step=10,
        fiber_stop_threshold=0.2,
        fiber_step_size=0.5,
        fiber_radius=0.1,
        fiber_sections=3,
        fiber_max_angle=45.0,
        fiber_seed_density=1,
        fiber_auto_response_roi_radii=10,
        fiber_auto_response_fa_thr=0.7,
        fiber_region_gfa_threshold=0.25,
        fiber_region_stop_threshold=0.01,
        fiber_region_step_size=0.5,
        fiber_region_radius=0.1,
        fiber_region_sections=3,
        fiber_region_max_angle=45.0,
        fiber_region_seed_density=1,
        fiber_region_min_streamlines=10,
    ):
        self.mode = mode

        self.BASE_DATA_DIR = Path(base_data_dir) if base_data_dir else Path(__file__).resolve().parents[1] / 'workspace' / 'default'
        self.PATIENT_DATA_DIR = Path(patient_data_dir) if patient_data_dir else self.BASE_DATA_DIR / 'patient_input'
        self.SYNTHSEG_DATA_DIR = Path(synthseg_data_dir) if synthseg_data_dir else self.BASE_DATA_DIR / 'SynthSeg_result'
        self.TEMPLATE_DIR = Path(template_dir) if template_dir else self.BASE_DATA_DIR / 'template'
        self.OUTPUT_DIR = Path(output_dir) if output_dir else self.BASE_DATA_DIR / 'model_output'
        
        self.SPM_DIR = Path(spm_dir) if spm_dir else self.BASE_DATA_DIR / 'spm'
        self.SPM_SCRIPT_DIR = Path(spm_script_dir) if spm_script_dir else Path(__file__).resolve().parent
        self.SPM_BACKEND = (spm_backend or "auto").strip().lower()
        self.MATLAB_EXE = str(matlab_exe).strip() if matlab_exe else "matlab"
        self.MCR_HOME = Path(mcr_home) if mcr_home else None
        self.SPM_STANDALONE_EXE = Path(spm_standalone_exe) if spm_standalone_exe else None
        self.SPM_COMPILED_EXE = Path(spm_compiled_exe) if spm_compiled_exe else None
        
        self.DCM2NIIX_EXE = str(dcm2niix_exe) if dcm2niix_exe else "dcm2niix.exe"
        self.DCMTK_DCMDJPEG_EXE = str(dcmtk_dcmdjpeg_exe) if dcmtk_dcmdjpeg_exe else "dcmdjpeg.exe"
        self.DICOM_DECOMPRESS_DCMTK = bool(dicom_decompress_dcmtk)
        self.DICOM_DECOMPRESS_DIR = (Path(dicom_decompress_dir) if dicom_decompress_dir else self.BASE_DATA_DIR / 'temp' / 'dicom_dcmtk_decompressed')
        self.DICOM_ONLY_DTI = bool(dicom_only_dti)
        self.DOCKER_EXE = str(docker_exe) if docker_exe else "docker"
        self.SYNTHSEG_DOCKER_IMAGE = synthseg_docker_image or "pwesp/synthseg:py38"
        self.SYNTHSEG_THREADS = int(synthseg_threads) if synthseg_threads else None
        self.DICOM_DIR = Path(dicom_dir) if dicom_dir else None
        self.DICOM_TEMP_DIR = (Path(dicom_temp_dir) if dicom_temp_dir else self.BASE_DATA_DIR / 'temp' / 'dicom2niix_output')
        self.DICOM_T1_SOURCE = Path(dicom_t1_source) if dicom_t1_source and str(dicom_t1_source).strip() else None
        self.DICOM_MRA_SOURCE = Path(dicom_mra_source) if dicom_mra_source and str(dicom_mra_source).strip() else None
        self.DICOM_MRV_SOURCE = Path(dicom_mrv_source) if dicom_mrv_source and str(dicom_mrv_source).strip() else None
        self.DICOM_DTI_SOURCE = Path(dicom_dti_source) if dicom_dti_source and str(dicom_dti_source).strip() else None
        
        self.DICOM_T1_KEYWORDS = dicom_t1_keywords if dicom_t1_keywords else [
            "t1", "mprage", "bravo", "spgr", "tfl", "3dt1"
        ]
        self.DICOM_MRA_KEYWORDS = dicom_mra_keywords if dicom_mra_keywords else [
            "mra", "tof", "angio", "artery"
        ]
        self.DICOM_MRV_KEYWORDS = dicom_mrv_keywords if dicom_mrv_keywords else [
            "mrv", "venography", "venogram", "vein", "venous"
        ]
        self.DICOM_DTI_KEYWORDS = dicom_dti_keywords if dicom_dti_keywords else [
            "dti", "dwi", "diff", "diffusion", "noddi", "dir"
        ]

        self.DK_NAME_FILE = Path(dk_name_file) if dk_name_file else self.TEMPLATE_DIR / 'DK_Regions.txt'
        self.LOBE_MAP_FILE = Path(lobe_map_file) if lobe_map_file else self.TEMPLATE_DIR / 'DK_Lobes.txt'

        self.T1_FILE = Path(t1_file) if t1_file else self.PATIENT_DATA_DIR / 'T1.nii'
        self.DK_FILE = Path(dk_file) if dk_file else self.SYNTHSEG_DATA_DIR / 'T1_synthseg.nii'

        self.MRA_FILE = Path(mra_file) if mra_file else self.PATIENT_DATA_DIR / 'MRA.nii'
        self.MRV_FILE = Path(mrv_file) if mrv_file else self.PATIENT_DATA_DIR / 'MRV.nii'

        self.ROI_FILE = Path(roi_file) if roi_file else self.TEMPLATE_DIR / 'ROI_ED_Filter.nii.gz'
        self.MULTIROI_FILE = Path(multiroi_file) if multiroi_file else self.PATIENT_DATA_DIR / 'Segmentation_multilayer.nii'

        self.DTI_FILE = Path(dti_file) if dti_file else self.PATIENT_DATA_DIR / 'DTI.nii.gz'
        self.DTI_BVALS_FILE = Path(dti_bvals_file) if dti_bvals_file else self.PATIENT_DATA_DIR / 'DTI.bval'
        self.DTI_BVECS_FILE = Path(dti_bvecs_file) if dti_bvecs_file else self.PATIENT_DATA_DIR / 'DTI.bvec'
        self.MASK_FILE = Path(mask_file) if mask_file else self.PATIENT_DATA_DIR / 'c2T1.nii'
        self.GWI_ATLAS_FILE = Path(gwi_atlas_file) if gwi_atlas_file else self.BASE_DATA_DIR / 'temp/interface_atlas.nii.gz'

        self.DKI_FILE = Path(dki_file) if dki_file else self.PATIENT_DATA_DIR / 'dki_4d.nii.gz'
        self.DKI_BVALS_FILE = Path(dki_bvals_file) if dki_bvals_file else self.PATIENT_DATA_DIR / 'bvals.bval'
        self.DKI_BVECS_FILE = Path(dki_bvecs_file) if dki_bvecs_file else self.PATIENT_DATA_DIR / 'bvecs.bvec'

        self.SYNTHSEG_ROBUST_FILE = Path(synthseg_robust_file) if synthseg_robust_file else self.DK_FILE

        self.SMOOTHING_ITERATIONS = int(smoothing_iterations)
        self.SMOOTHING_LAMBDA = float(smoothing_lambda)
        self.MARCHING_CUBES_LEVEL = float(marching_cubes_level)
        self.MIN_OBJECT_SIZE = int(min_object_size)
        self.MESH_DECIMATION_FRACTION = float(mesh_decimation_fraction)
        self.NUM_PROCESSES = int(num_processes)
        self.GWI_DILATION_ITERATIONS = int(gwi_dilation_iterations)

        self.output_path = self.OUTPUT_DIR / self.mode.name.lower()
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.SYNTHSEG_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.DK_FILE.parent.mkdir(parents=True, exist_ok=True)

        self.VESSEL_THRESHOLD = int(vessel_threshold)
        self.VESSEL_MIN_OBJECT_SIZE = int(vessel_min_object_size)
        self.VESSEL_DECIMATION_FRACTION = float(vessel_decimation_fraction)
        self.MRV_FRANGI_CACHE_FILE = (Path(mrv_frangi_cache_file) if mrv_frangi_cache_file else self.BASE_DATA_DIR / 'temp/out_figma12_1000.nii')
        self.MRV_FRANGI_SIGMAS_START = int(mrv_frangi_sigmas_start)
        self.MRV_FRANGI_SIGMAS_END = int(mrv_frangi_sigmas_end)
        self.MRV_FRANGI_SIGMAS_STEP = int(mrv_frangi_sigmas_step)
        self.MRV_STRONG_SEED_PERCENTILE = float(mrv_strong_seed_percentile)
        self.MRV_STRONG_GROW_TOLERANCE = float(mrv_strong_grow_tolerance)
        self.MRV_WEAK_SEED_PERCENTILE = float(mrv_weak_seed_percentile)
        self.MRV_WEAK_GROW_TOLERANCE = float(mrv_weak_grow_tolerance)
        self.MRV_POST_PROCESS_MIN_SIZE = int(mrv_post_process_min_size)
        self.FORCE_REBUILD_GWI = False
        
        self.FIBER_GFA_CACHE_FILE = (Path(fiber_gfa_cache_file) if fiber_gfa_cache_file else self.BASE_DATA_DIR / 'temp/gfa.nii')
        self.FIBER_GFA_THRESHOLD = float(fiber_gfa_threshold)
        self.FIBER_STEP = int(fiber_step)
        self.FIBER_STOP_THRESHOLD = float(fiber_stop_threshold)
        self.FIBER_STEP_SIZE = float(fiber_step_size)
        self.FIBER_RADIUS = float(fiber_radius)
        self.FIBER_SECTIONS = int(fiber_sections)
        self.FIBER_MAX_ANGLE = float(fiber_max_angle)
        self.FIBER_SEED_DENSITY = int(fiber_seed_density)
        self.FIBER_AUTO_RESPONSE_ROI_RADII = int(fiber_auto_response_roi_radii)
        self.FIBER_AUTO_RESPONSE_FA_THR = float(fiber_auto_response_fa_thr)

        self.FIBER_REGION_GFA_THRESHOLD = float(fiber_region_gfa_threshold)
        self.FIBER_REGION_STOP_THRESHOLD = float(fiber_region_stop_threshold)
        self.FIBER_REGION_STEP_SIZE = float(fiber_region_step_size)
        self.FIBER_REGION_RADIUS = float(fiber_region_radius)
        self.FIBER_REGION_SECTIONS = int(fiber_region_sections)
        self.FIBER_REGION_MAX_ANGLE = float(fiber_region_max_angle)
        self.FIBER_REGION_SEED_DENSITY = int(fiber_region_seed_density)
        self.FIBER_REGION_MIN_STREAMLINES = int(fiber_region_min_streamlines)

        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.GWI_ATLAS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.FIBER_GFA_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.MRV_FRANGI_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.DICOM_TEMP_DIR.mkdir(parents=True, exist_ok=True)


# --- Global data for multiprocess ---
# global params
shared_data = {}
CSS_colors = [
    "#F0F8FF", "#FAEBD7", "#00FFFF", "#7FFFD4", "#F0FFFF", "#F5F5DC", "#FFE4C4", "#000000",
    "#FFEBCD", "#0000FF", "#8A2BE2", "#A52A2A", "#DEB887", "#5F9EA0", "#7FFF00", "#D2691E",
    "#FF7F50", "#6495ED", "#FFF8DC", "#DC143C", "#00FFFF", "#00008B", "#008B8B", "#B8860B",
    "#A9A9A9", "#006400", "#BDB76B", "#8B008B", "#556B2F", "#FF8C00", "#9932CC", "#8B0000",
    "#E9967A", "#8FBC8F", "#483D8B", "#2F4F4F", "#00CED1", "#9400D3", "#FF1493", "#00BFFF",
    "#696969", "#1E90FF", "#B22222", "#FFFAF0", "#228B22", "#FF00FF", "#DCDCDC", "#F8F8FF",
    "#FFD700", "#DAA520", "#808080", "#008000", "#ADFF2F", "#F0FFF0", "#FF69B4", "#CD5C5C",
    "#4B0082", "#FFFFF0", "#F0E68C", "#E6E6FA", "#FFF0F5", "#7CFC00", "#FFFACD", "#ADD8E6",
    "#F08080", "#E0FFFF", "#FAFAD2", "#D3D3D3", "#90EE90", "#FFB6C1", "#FFA07A", "#20B2AA",
    "#87CEFA", "#778899", "#B0C4DE", "#FFFFE0", "#00FF00", "#32CD32", "#FAF0E6", "#FF00FF",
    "#800000", "#66CDAA", "#0000CD", "#BA55D3", "#9370DB", "#3CB371", "#7B68EE", "#00FA9A",
    "#48D1CC", "#C71585", "#191970", "#F5FFFA", "#FFE4E1", "#FFE4B5", "#FFDEAD", "#000080",
    "#FDF5E6", "#808000", "#6B8E23", "#FFA500", "#FF4500", "#DA70D6", "#EEE8AA", "#98FB98",
    "#AFEEEE", "#DB7093", "#FFEFD5", "#FFDAB9", "#CD853F", "#FFC0CB", "#DDA0DD", "#B0E0E6",
    "#800080", "#663399", "#FF0000", "#BC8F8F", "#4169E1", "#8B4513", "#FA8072", "#F4A460",
    "#2E8B57", "#FFF5EE", "#A0522D", "#C0C0C0", "#87CEEB", "#6A5ACD", "#708090", "#FFFAFA",
    "#00FF7F", "#4682B4", "#D2B48C", "#008080", "#D8BFD8", "#FF6347", "#40E0D0", "#EE82EE",
    "#F5DEB3", "#FFFFFF", "#F5F5F5", "#FFFF00", "#9ACD32"
]

DK_COLORS = {
    # =========================================================
    # Frontal / executive / reward / control
    # 额叶、执行控制、奖赏决策
    # 色系：琥珀、金橙、朱橙、秋香
    # 高亮高饱和，但避免荧光橙
    # =========================================================
    "caudalmiddlefrontal_L": "#D8862E",   # 亮琥珀
    "caudalmiddlefrontal_R": "#B9651F",   # 深亮琥珀

    "rostralmiddlefrontal_L": "#E29535",  # 金橙
    "rostralmiddlefrontal_R": "#BF6F25",  # 深金橙

    "lateralorbitofrontal_L": "#C85A35",  # 朱橙
    "lateralorbitofrontal_R": "#9E3F28",  # 深朱橙

    "medialorbitofrontal_L": "#D06A3A",   # 棠梨橙
    "medialorbitofrontal_R": "#A24C2C",   # 深棠梨橙

    "superiorfrontal_L": "#D9A63A",       # 亮秋香金
    "superiorfrontal_R": "#B27E28",       # 深秋香金

    "parsorbitalis_L": "#CB5638",         # 柿红橙
    "parsorbitalis_R": "#A23C28",         # 深柿红橙

    "parstriangularis_L": "#D26B45",      # 枫橙
    "parstriangularis_R": "#A84A31",      # 深枫橙

    "parsopercularis_L": "#BD4933",       # 朱砂橙
    "parsopercularis_R": "#933426",       # 深朱砂橙

    "precentral_L": "#B34B35",            # 赤红褐
    "precentral_R": "#893629",            # 深赤红褐

    "caudalanteriorcingulate_L": "#D18E2F", # 金茶橙
    "caudalanteriorcingulate_R": "#A96A22", # 深金茶橙

    "rostralanteriorcingulate_L": "#D4A83E", # 明秋香
    "rostralanteriorcingulate_R": "#AA812B", # 深明秋香

    "frontalpole_L": "#D0792C",           # 蜜橙
    "frontalpole_R": "#A55820",           # 深蜜橙


    # =========================================================
    # Sensorimotor / parietal attention
    # 顶叶、感觉运动、空间注意
    # 色系：石青、天蓝、青瓷、孔雀蓝、翠青、靛蓝
    # 逻辑：保持冷色统一感，但拉开色相差异，避免“看起来都一样”
    # =========================================================
    "postcentral_L": "#2F9BB3",           # 亮石青
    "postcentral_R": "#227489",           # 深石青

    "inferiorparietal_L": "#2588C2",      # 孔雀蓝
    "inferiorparietal_R": "#1C5F8B",      # 深孔雀蓝

    "supramarginal_L": "#38A6A0",         # 青瓷绿
    "supramarginal_R": "#287974",         # 深青瓷绿

    "superiorparietal_L": "#4A95C8",      # 天青蓝
    "superiorparietal_R": "#356D95",      # 深天青蓝

    "paracentral_L": "#4CA68A",           # 翠青
    "paracentral_R": "#377863",           # 深翠青

    "precuneus_L": "#2E7FB0",             # 靛蓝青
    "precuneus_R": "#205B7E",             # 深靛蓝青


    # =========================================================
    # Temporal / auditory / language / semantic / memory
    # 颞叶、听觉、语言、语义、记忆
    # 色系：青莲紫、紫藤、葡萄紫、绀紫、玫紫
    # 逻辑：保持同一紫系，但拉开色相与明度差异，避免视觉上“全一样”
    # =========================================================
    "superiortemporal_L": "#7D63D1",      # 亮青莲紫
    "superiortemporal_R": "#5A439F",      # 深青莲紫

    "bankssts_L": "#9A6ED8",              # 紫藤紫
    "bankssts_R": "#6F4FA8",              # 深紫藤紫

    "middletemporal_L": "#6E57B7",        # 绀紫
    "middletemporal_R": "#4F3C8C",        # 深绀紫

    "inferiortemporal_L": "#9B5A8E",      # 玫紫
    "inferiortemporal_R": "#734268",      # 深玫紫

    "transversetemporal_L": "#B06ED6",    # 葡萄紫
    "transversetemporal_R": "#8250A3",    # 深葡萄紫

    "temporalpole_L": "#C06A9A",          # 玫瑰紫
    "temporalpole_R": "#8F4A73",          # 深玫瑰紫

    "parahippocampal_L": "#5D4BB0",       # 青莲
    "parahippocampal_R": "#43367F",       # 深青莲

    "entorhinal_L": "#4B3E87",            # 绀青紫
    "entorhinal_R": "#362D62",            # 深绀青紫

    "isthmuscingulate_L": "#7A58B2",      # 紫檀紫
    "isthmuscingulate_R": "#57407F",      # 深紫檀紫

    "posteriorcingulate_L": "#5A468D",    # 黛紫
    "posteriorcingulate_R": "#403261",    # 深黛紫


    # =========================================================
    # Occipital / visual processing
    # 枕叶：视觉处理
    # 主色相：翠绿、松花绿、苍绿、铜绿
    # 逻辑：视觉系统统一绿色系，和颞叶紫系形成明确对比
    # =========================================================
    "lateraloccipital_L": "#53A45A",      # 翠绿
    "lateraloccipital_R": "#3B7641",      # 深翠绿

    "cuneus_L": "#799B3C",                # 松花绿
    "cuneus_R": "#586F2C",                # 深松花绿

    "lingual_L": "#3E9C6A",               # 铜绿
    "lingual_R": "#2D6F4C",               # 深铜绿

    "pericalcarine_L": "#6E8F4C",         # 苍绿
    "pericalcarine_R": "#4E6436",         # 深苍绿


    # =========================================================
    # Limbic / salience / emotion
    # 边缘系统与显著性网络：情绪、唤醒、整合
    # 主色相：胭脂、朱砂、海棠红、绛红
    # 逻辑：这是全脑最适合用暖红做强调的一组
    # =========================================================
    "insula_L": "#C64F67",                # 胭脂
    "insula_R": "#913647",                # 深胭脂

    # =========================================================
    # Fusiform / face-object recognition
    # 梭状回、面孔/物体识别
    # 色系：梅紫、玫瑰紫
    # 作为颞叶紫与枕叶绿之间的高饱和过渡
    # =========================================================
    "fusiform_L": "#B45388",              # 亮梅紫
    "fusiform_R": "#873C66",              # 深梅紫
}

hemisphere_map ={
    "left": [
        1001, 1002, 1003, 1005, 1006, 1007, 1008, 1009, 1010, 1011,
        1012, 1013, 1014, 1015, 1016, 1017, 1018, 1019, 1020, 1021,
        1022, 1023, 1024, 1025, 1026, 1027, 1028, 1029, 1030, 1031,
        1032, 1033, 1034, 1035
    ],
    "right": [
        2001, 2002, 2003, 2005, 2006, 2007, 2008, 2009, 2010, 2011,
        2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021,
        2022, 2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030, 2031,
        2032, 2033, 2034, 2035
    ],
    "cerebellum": [
        8,
        47,
        7,
        46
    ],
    "brainstem": [
        16
    ]
}

def worker_init(data):
    """多进程工作单元的初始化函数"""
    global shared_data
    shared_data = data


class BrainMeshProcessor:
    """ Main for processing different brain meshes based on the configuration """

    DK_NAME_REQUIRED_MODES = {
        ProcessMode.INDIVIDUAL_REGIONS,
        ProcessMode.FIBER_TRACKING_REGION,
    }

    def __init__(self, config: Config):
        self.config = config
        # DICOM_CONVERT 模式下，T1.nii 还没有生成，不能提前 load
        if self.config.mode in (ProcessMode.DICOM_CONVERT, ProcessMode.SYNTHSEG_SEGMENTATION):
            self.t1_img = None
            self.affine = np.eye(4)
            self.DK_names = {}
        else:
            self.t1_img = nib.load(self.config.T1_FILE)
            self.affine = self._calculate_centered_affine()
            if self.config.mode in self.DK_NAME_REQUIRED_MODES:
                self.DK_names = self._load_dk_names()
            else:
                self.DK_names = {}

        # Manager 只在真正进入多进程模型生成时创建。DICOM/SynthSeg/SPM 等模式
        # 不需要共享列表，提前创建 Manager 会在部分 Windows 环境中触发管道权限错误。
        self.manager = None
        self.unprocessed_items = []

    def _load_dk_names(self):
        """从文件加载DK区域名称"""
        with open(self.config.DK_NAME_FILE, 'r') as f:
            lines = [line.strip().split() for line in f.readlines()]
            return {int(line[0]): line[1] for line in lines}
        
    def _load_lobe_mapping(filepath):
        """从文件加载脑叶到区域编号列表的映射，忽略注释行"""
        
        lobe_mapping = {}
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) > 1:
                    lobe_name = parts[0]
                    region_indices = [int(i) for i in parts[1:]]
                    lobe_mapping[lobe_name] = region_indices
        return lobe_mapping

    # differ
    def _calculate_centered_affine(self):
        """计算用于网格生成的中心化仿射矩阵"""
        t1_affine = self.t1_img.affine

        translation, t1_rotation, scale = Utils.util.decompose_affine_matrix(t1_affine)
        tmp_affine = Utils.util.compose_affine_matrix_noRotation(translation, scale)
        center = np.array(self.t1_img.shape) // 2
        offset = nib.affines.apply_affine(tmp_affine, center)
        # 这个new affine很重要之后会用到
        new_affine = Utils.util.compose_affine_matrix_noRotation(translation - offset, scale)
        affine = new_affine  # 由t1得到的 new_affine

        return new_affine

    def run(self):
        """根据配置的模式执行相应处理流程"""
        print(f"--- Running in mode: {self.config.mode.name} ---")

        mode_runners = {
            ProcessMode.DICOM_CONVERT: self._process_dicom_convert,
            ProcessMode.SPM_SEGMENTATION: self._process_spm_segmentation,
            ProcessMode.SYNTHSEG_SEGMENTATION: self._process_synthseg_segmentation,
            ProcessMode.INDIVIDUAL_REGIONS: self._process_individual_regions_synthseg,
            ProcessMode.GM_WM: self._process_gm_wm,
            ProcessMode.VESSEL: self._process_vessel,
            ProcessMode.LOBES: self._process_lobes_synthseg,
            ProcessMode.HEMISPHERES: self._process_hemispheres_synthseg,
            ProcessMode.ROI: self._process_roi,
            ProcessMode.FIBER_TRACKING: self._process_fiber_tracking,
            ProcessMode.MRV: self._process_mrv,
            ProcessMode.VENTRICLE: self._process_ventricle,
            ProcessMode.MULTIROI: self._process_roimutilayer,
            ProcessMode.FIBER_TRACKING_REGION: self._process_fiber_tracking_region_synthseg_Interface,
            ProcessMode.TISSUE: self._process_tissues,
            ProcessMode.FIBER_TRACKING_DKI: self._process_fiber_tracking_Multi,
        }

        runner = mode_runners.get(self.config.mode)
        if runner:
            runner()
        else:
            print(f"Mode {self.config.mode.name} is not implemented yet.")
        print(f"\nProcessing finished for mode: {self.config.mode.name}")
        if self.unprocessed_items:
            print(f"Items that were too small to form a mesh: {list(self.unprocessed_items)}")
    
    #################################
    # --- DICOM to NIfTI by dcm2niix ---
    #################################

    DICOM_DERIVED_SERIES_KEYWORDS = (
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

    @staticmethod
    def _nifti_stem(path: Path):
        """
        Return stem for .nii or .nii.gz.
        Example:
            xxx.nii.gz -> xxx
            xxx.nii -> xxx
        """
        name = path.name
        if name.endswith(".nii.gz"):
            return name[:-7]
        if name.endswith(".nii"):
            return name[:-4]
        return path.stem

    @staticmethod
    def _read_json_safely(json_path: Path):
        if not json_path.exists():
            return {}
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def _read_bval_count(bval_path: Path):
        """
        Count number of b-values. Used to select the most likely DTI series.
        """
        if not bval_path.exists():
            return 0
        try:
            text = bval_path.read_text().strip()
            if not text:
                return 0
            return len(text.replace("\n", " ").split())
        except Exception:
            return 0

    @staticmethod
    def _read_bvec_info(bvec_path: Path):
        """
        Return bvec matrix shape and inferred gradient vector count.
        dcm2niix usually writes 3 x N, while some tools write N x 3.
        """
        if not bvec_path.exists():
            return [], 0
        try:
            rows = []
            for line in bvec_path.read_text().strip().splitlines():
                values = line.replace(",", " ").split()
                if values:
                    rows.append(values)

            if not rows:
                return [], 0

            row_count = len(rows)
            col_count = max(len(row) for row in rows)
            if row_count == 3:
                vector_count = col_count
            elif col_count == 3:
                vector_count = row_count
            else:
                vector_count = col_count if col_count >= row_count else row_count

            return [row_count, col_count], int(vector_count)
        except Exception:
            return [], 0

    @staticmethod
    def _nifti_header_info(nii_path: Path):
        try:
            img = nib.load(str(nii_path))
            shape = [int(v) for v in img.shape]
            zooms = [float(v) for v in img.header.get_zooms()[:3]]
            return shape, zooms, None
        except Exception as exc:
            return [], [], str(exc)

    @staticmethod
    def _volume_count_from_shape(shape):
        if len(shape) >= 4:
            return int(shape[3])
        if len(shape) == 3:
            return 1
        return 0

    @staticmethod
    def _is_nifti_path(path: Path):
        name = path.name.lower()
        return name.endswith(".nii") or name.endswith(".nii.gz")

    @staticmethod
    def _resolve_executable(exe, option_name: str):
        exe_path = Path(exe)
        if exe_path.exists():
            return str(exe_path)

        found = shutil.which(exe)
        if found is None:
            raise FileNotFoundError(
                f"Executable not found: {exe}. "
                f"Please provide {option_name} or add it to PATH."
            )
        return found

    def _decompress_dicom_with_dcmtk(self, source_dir: Path, output_dir: Path = None):
        """
        Decompress JPEG-compressed DICOM files with DCMTK dcmdjpeg before dcm2niix.
        Raw DICOM data is copied to a temporary directory first, so the source is not modified.
        """
        dcmdjpeg_cmd = self._resolve_executable(
            self.config.DCMTK_DCMDJPEG_EXE,
            "--dcmtk-dcmdjpeg-exe",
        )

        source_dir = Path(source_dir).resolve()
        decompress_dir = Path(output_dir if output_dir else self.config.DICOM_DECOMPRESS_DIR).resolve()

        if decompress_dir == source_dir or source_dir in decompress_dir.parents or decompress_dir in source_dir.parents:
            raise ValueError(
                "DICOM decompression temp dir must be separate from the source DICOM directory "
                "and must not be its parent or child."
            )

        if decompress_dir.exists():
            print(f"[DCMTK] Cleaning decompression temp dir: {decompress_dir}")
            shutil.rmtree(decompress_dir)

        print(f"[DCMTK] Copying DICOM files to decompression temp dir: {decompress_dir}")
        shutil.copytree(source_dir, decompress_dir)

        dicom_files = [p for p in decompress_dir.rglob("*") if p.is_file()]
        if not dicom_files:
            raise RuntimeError(f"No files found for DCMTK decompression in: {decompress_dir}")

        print(f"[DCMTK] Running dcmdjpeg on {len(dicom_files)} files...")
        success_count = 0
        failed_count = 0

        for dicom_file in dicom_files:
            tmp_file = dicom_file.with_name(dicom_file.name + ".dcmtk_tmp")
            if tmp_file.exists():
                tmp_file.unlink()

            result = subprocess.run(
                [dcmdjpeg_cmd, str(dicom_file), str(tmp_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
            )

            if result.returncode == 0 and tmp_file.exists():
                os.replace(tmp_file, dicom_file)
                success_count += 1
            else:
                if tmp_file.exists():
                    tmp_file.unlink()
                failed_count += 1
                if failed_count <= 10:
                    message = (result.stdout or "").strip().splitlines()
                    last_line = message[-1] if message else "no output"
                    print(f"[DCMTK Warning] Could not decompress {dicom_file.name}: {last_line}")

        print(f"[DCMTK] Decompression finished. Success: {success_count}, skipped/failed: {failed_count}")
        if success_count == 0:
            print("[DCMTK Warning] No files were decompressed. The input may already be uncompressed, or the series may need inspection.")

        return decompress_dir

    def _collect_dcm2niix_candidates(self, output_dir: Path):
        """
        Collect converted NIfTI files and their sidecar json/bval/bvec files.
        """
        nii_files = list(output_dir.rglob("*.nii")) + list(output_dir.rglob("*.nii.gz"))

        candidates = []
        for nii_path in nii_files:
            stem = self._nifti_stem(nii_path)

            json_path = nii_path.with_name(stem + ".json")
            bval_path = nii_path.with_name(stem + ".bval")
            bvec_path = nii_path.with_name(stem + ".bvec")

            meta = self._read_json_safely(json_path)

            series_description = str(meta.get("SeriesDescription", ""))
            protocol_name = str(meta.get("ProtocolName", ""))
            sequence_name = str(meta.get("SequenceName", ""))
            image_type = meta.get("ImageType", "")
            desc_parts = [
                nii_path.name,
                series_description,
                protocol_name,
                sequence_name,
                str(image_type),
            ]
            desc = " ".join(desc_parts).lower()
            shape, voxel_size, load_error = self._nifti_header_info(nii_path)
            bvec_shape, bvec_count = self._read_bvec_info(bvec_path)
            bval_count = self._read_bval_count(bval_path)
            image_type_text = " ".join(image_type) if isinstance(image_type, list) else str(image_type)
            image_type_upper = image_type_text.upper()

            candidates.append({
                "nii": nii_path,
                "json": json_path,
                "bval": bval_path,
                "bvec": bvec_path,
                "desc": desc,
                "series_description": series_description,
                "protocol_name": protocol_name,
                "sequence_name": sequence_name,
                "series_number": meta.get("SeriesNumber"),
                "image_type": image_type,
                "is_original_image_type": "ORIGINAL" in image_type_upper,
                "is_derived_image_type": "DERIVED" in image_type_upper or "SECONDARY" in image_type_upper,
                "has_bval_bvec": bval_path.exists() and bvec_path.exists(),
                "bval_count": bval_count,
                "bvec_shape": bvec_shape,
                "bvec_count": bvec_count,
                "shape": shape,
                "voxel_size": voxel_size,
                "volume_count": self._volume_count_from_shape(shape),
                "nifti_load_error": load_error,
                "size": nii_path.stat().st_size if nii_path.exists() else 0,
            })

        return candidates

    @staticmethod
    def _match_keywords(text: str, keywords):
        text = text.lower()
        return any(str(k).lower() in text for k in keywords)

    @staticmethod
    def _matched_keywords(text: str, keywords):
        text = text.lower()
        return [str(k) for k in keywords if str(k).lower() in text]

    @staticmethod
    def _text_tokens(text: str):
        return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}

    def _matched_derived_keywords(self, text: str):
        tokens = self._text_tokens(text)
        compact = re.sub(r"[^a-z0-9]+", "", text.lower())
        matched = []

        for keyword in self.DICOM_DERIVED_SERIES_KEYWORDS:
            if keyword == "batchmip":
                if "batchmip" in compact:
                    matched.append(keyword)
            elif keyword in {"mip", "mpr", "ref"}:
                if keyword in tokens:
                    matched.append(keyword)
            elif keyword in tokens or keyword in text.lower():
                matched.append(keyword)

        return matched

    @staticmethod
    def _brief_path(path):
        return str(path) if path else None

    def _candidate_summary(self, candidate, score=None, matched_keywords=None, reason=None, eligible=None):
        derived_keywords = self._matched_derived_keywords(candidate.get("desc", ""))
        summary = {
            "name": candidate["nii"].name,
            "path": self._brief_path(candidate.get("nii")),
            "json": self._brief_path(candidate.get("json")) if candidate.get("json") and candidate["json"].exists() else None,
            "series_description": candidate.get("series_description"),
            "protocol_name": candidate.get("protocol_name"),
            "sequence_name": candidate.get("sequence_name"),
            "series_number": candidate.get("series_number"),
            "image_type": candidate.get("image_type"),
            "shape": candidate.get("shape", []),
            "voxel_size": candidate.get("voxel_size", []),
            "volume_count": candidate.get("volume_count", 0),
            "size": candidate.get("size", 0),
            "has_bval_bvec": bool(candidate.get("has_bval_bvec")),
            "bval_count": candidate.get("bval_count", 0),
            "bvec_shape": candidate.get("bvec_shape", []),
            "bvec_count": candidate.get("bvec_count", 0),
            "matched_keywords": matched_keywords or [],
            "derived_keywords": derived_keywords,
            "is_original_image_type": bool(candidate.get("is_original_image_type")),
            "is_derived_image_type": bool(candidate.get("is_derived_image_type")),
            "score": score,
            "reason": reason,
        }
        if eligible is not None:
            summary["eligible"] = bool(eligible)
        if candidate.get("nifti_load_error"):
            summary["nifti_load_error"] = candidate.get("nifti_load_error")
        return summary

    @staticmethod
    def _excluded_candidate_briefs(evaluated_candidates, selected_candidate=None, limit=30):
        selected_path = str(selected_candidate["nii"]) if selected_candidate else None
        excluded = []
        for item in evaluated_candidates:
            candidate = item["candidate"]
            if selected_path and str(candidate["nii"]) == selected_path:
                continue
            excluded.append({
                "name": candidate["nii"].name,
                "path": str(candidate["nii"]),
                "score": item.get("score"),
                "reason": item.get("reason"),
                "matched_keywords": item.get("matched_keywords", []),
                "derived_keywords": item.get("derived_keywords", []),
                "shape": candidate.get("shape", []),
                "volume_count": candidate.get("volume_count", 0),
                "bval_count": candidate.get("bval_count", 0),
            })
            if len(excluded) >= limit:
                break
        return excluded

    def _rank_anatomical_candidates(self, candidates, keywords, modality_name):
        """
        Select T1/MRA/MRV candidates by modality keywords, while downranking
        derived display/reformat series such as MIP, MPR, scout, survey, ref.
        """
        evaluated = []
        for candidate in candidates:
            matched_keywords = self._matched_keywords(candidate["desc"], keywords)
            derived_keywords = self._matched_derived_keywords(candidate["desc"])
            eligible = bool(matched_keywords) and not candidate["has_bval_bvec"]
            score = None

            if candidate["has_bval_bvec"]:
                reason = "excluded: diffusion sidecars present"
            elif not matched_keywords:
                reason = "excluded: no modality keyword match"
            else:
                score = 100 * len(matched_keywords)
                if candidate.get("is_original_image_type"):
                    score += 40
                if len(candidate.get("shape", [])) == 3:
                    score += 20
                if candidate.get("is_derived_image_type"):
                    score -= 60
                if derived_keywords:
                    score -= 90 + 20 * len(derived_keywords)
                score += min(candidate.get("size", 0) / 1000000.0, 50.0) / 100.0
                if derived_keywords or candidate.get("is_derived_image_type"):
                    reason = "eligible: matched keywords but downranked as derived/reformatted"
                else:
                    reason = "eligible: matched keywords and preferred as acquisition-like series"

            evaluated.append({
                "candidate": candidate,
                "score": score,
                "matched_keywords": matched_keywords,
                "derived_keywords": derived_keywords,
                "eligible": eligible,
                "reason": reason,
                "summary": self._candidate_summary(
                    candidate,
                    score=score,
                    matched_keywords=matched_keywords,
                    reason=reason,
                    eligible=eligible,
                ),
            })

        eligible_items = [item for item in evaluated if item["eligible"]]
        if not eligible_items:
            print(f"[Warning] No {modality_name} candidate matched keywords: {keywords}")
            return {
                "selected": None,
                "reason": f"no {modality_name} candidate matched keywords",
                "matched_keywords": [],
                "candidate_count": len(candidates),
                "excluded_candidates": self._excluded_candidate_briefs(evaluated, None),
                "candidates": [item["summary"] for item in evaluated],
            }

        selected_item = sorted(
            eligible_items,
            key=lambda item: (item["score"], item["candidate"].get("size", 0)),
            reverse=True,
        )[0]
        selected = selected_item["candidate"]
        reason = selected_item["reason"]
        if selected_item["derived_keywords"] or selected.get("is_derived_image_type"):
            reason = "selected derived/reformatted series because it ranked highest among keyword matches"
        else:
            reason = "selected highest-ranked acquisition-like series"

        print(f"[DICOM] Selected {modality_name}: {selected['nii'].name}")
        print(f"        score: {selected_item['score']:.3f}")
        print(f"        matched keywords: {selected_item['matched_keywords']}")
        if selected_item["derived_keywords"]:
            print(f"        derived keywords downranked: {selected_item['derived_keywords']}")
        print(f"        desc: {selected['desc'][:200]}")

        return {
            "selected": selected,
            "reason": reason,
            "matched_keywords": selected_item["matched_keywords"],
            "candidate_count": len(candidates),
            "excluded_candidates": self._excluded_candidate_briefs(evaluated, selected),
            "candidates": [item["summary"] for item in evaluated],
        }

    def _select_anatomical_candidate(self, candidates, keywords, modality_name):
        """
        Select T1/MRA/MRV candidate by keywords.
        If multiple candidates match, choose the largest one.
        """
        return self._rank_anatomical_candidates(candidates, keywords, modality_name)

    def _select_dti_candidate(self, candidates):
        """
        Select DTI candidate.
        Priority:
        1. Must have bval/bvec.
        2. Prefer 4D candidates whose volume count matches bval count.
        3. Then prefer DTI keyword matches and larger bval count.
        """
        evaluated = []
        for candidate in candidates:
            matched_keywords = self._matched_keywords(candidate["desc"], self.config.DICOM_DTI_KEYWORDS)
            is_4d = len(candidate.get("shape", [])) >= 4 and candidate.get("volume_count", 0) > 1
            bval_count = int(candidate.get("bval_count", 0))
            volume_count = int(candidate.get("volume_count", 0))
            bvec_count = int(candidate.get("bvec_count", 0))
            volume_bval_match = is_4d and volume_count == bval_count
            bval_bvec_match = bval_count > 0 and bvec_count == bval_count
            eligible = bool(candidate["has_bval_bvec"]) and bval_count > 0
            score = None
            priority = None

            if not candidate["has_bval_bvec"]:
                reason = "excluded: missing bval/bvec"
            elif bval_count <= 0:
                reason = "excluded: bval file is empty or unreadable"
            else:
                priority = (
                    int(volume_bval_match),
                    int(is_4d),
                    bval_count,
                    int(bval_bvec_match),
                    len(matched_keywords),
                    int(candidate.get("size", 0)),
                )
                score = {
                    "volume_bval_match": bool(volume_bval_match),
                    "is_4d": bool(is_4d),
                    "bval_count": bval_count,
                    "bval_bvec_match": bool(bval_bvec_match),
                    "keyword_match_count": len(matched_keywords),
                }
                reason = "eligible: has bval/bvec"
                if volume_bval_match:
                    reason += ", 4D volume count matches bval count"
                elif is_4d:
                    reason += ", 4D but volume count does not match bval count"

            evaluated.append({
                "candidate": candidate,
                "score": score,
                "priority": priority,
                "matched_keywords": matched_keywords,
                "derived_keywords": self._matched_derived_keywords(candidate["desc"]),
                "eligible": eligible,
                "reason": reason,
                "summary": self._candidate_summary(
                    candidate,
                    score=score,
                    matched_keywords=matched_keywords,
                    reason=reason,
                    eligible=eligible,
                ),
            })

        eligible_items = [item for item in evaluated if item["eligible"]]

        if not eligible_items:
            print("[Warning] No DTI candidate found because no bval/bvec files exist.")
            return {
                "selected": None,
                "reason": "no DTI candidate with readable bval/bvec",
                "matched_keywords": [],
                "candidate_count": len(candidates),
                "excluded_candidates": self._excluded_candidate_briefs(evaluated, None),
                "candidates": [item["summary"] for item in evaluated],
            }

        selected_item = sorted(
            eligible_items,
            key=lambda item: item["priority"],
            reverse=True,
        )[0]
        selected = selected_item["candidate"]

        print(f"[DICOM] Selected DTI: {selected['nii'].name}")
        print(f"        score: {selected_item['score']}")
        print(f"        bval count: {selected['bval_count']}")
        print(f"        volume count: {selected.get('volume_count', 0)}")
        print(f"        bvec shape: {selected.get('bvec_shape', [])}")
        print(f"        matched keywords: {selected_item['matched_keywords']}")
        print(f"        desc: {selected['desc'][:200]}")
        return {
            "selected": selected,
            "reason": selected_item["reason"],
            "matched_keywords": selected_item["matched_keywords"],
            "candidate_count": len(candidates),
            "excluded_candidates": self._excluded_candidate_briefs(evaluated, selected),
            "candidates": [item["summary"] for item in evaluated],
        }

    def _save_nifti_as(self, src_nii: Path, dst_nii: Path):
        """
        Save/copy NIfTI to target path.
        Supports:
            .nii -> .nii
            .nii -> .nii.gz
            .nii.gz -> .nii
            .nii.gz -> .nii.gz
        """
        dst_nii.parent.mkdir(parents=True, exist_ok=True)

        src_name = src_nii.name.lower()
        dst_name = dst_nii.name.lower()

        # Same compression type: direct copy
        if (src_name.endswith(".nii") and dst_name.endswith(".nii")) or \
           (src_name.endswith(".nii.gz") and dst_name.endswith(".nii.gz")):
            shutil.copy2(src_nii, dst_nii)
            return

        # Different compression type: use nibabel to save
        img = nib.load(str(src_nii))
        nib.save(img, str(dst_nii))

    @staticmethod
    def _standard_output_paths_for_modality(out_dir: Path, modality_name: str):
        if modality_name == "T1":
            return {"nii": out_dir / "T1.nii"}
        if modality_name == "MRA":
            return {"nii": out_dir / "MRA.nii"}
        if modality_name == "MRV":
            return {"nii": out_dir / "MRV.nii"}
        if modality_name == "DTI":
            return {
                "nii": out_dir / "DTI.nii.gz",
                "bval": out_dir / "DTI.bval",
                "bvec": out_dir / "DTI.bvec",
            }
        raise ValueError(f"Unsupported modality: {modality_name}")

    @staticmethod
    def _json_output_paths(output_paths):
        return {key: str(value) for key, value in output_paths.items()}

    def _log_dti_export_metadata(self, dti_nii: Path, dti_bval: Path, dti_bvec: Path):
        print("[DICOM] DTI metadata:")
        try:
            img = nib.load(str(dti_nii))
            shape = [int(v) for v in img.shape]
            voxel_size = [float(v) for v in img.header.get_zooms()[:3]]
        except Exception as exc:
            print(f"        failed to read DTI NIfTI header: {exc}")
            return

        bval_count = self._read_bval_count(dti_bval)
        bvec_shape, bvec_count = self._read_bvec_info(dti_bvec)
        volume_count = self._volume_count_from_shape(shape)
        is_4d = len(shape) >= 4

        unique_bvals = []
        gradient_directions = 0
        try:
            bvals, bvecs = read_bvals_bvecs(str(dti_bval), str(dti_bvec))
            if bvals is not None:
                rounded = np.round(np.asarray(bvals, dtype=float), 3)
                unique_bvals = np.unique(rounded).tolist()
                gradient_directions = int(np.sum(rounded > 50))
            if bvecs is not None:
                bvec_array = np.asarray(bvecs)
                bvec_shape = [int(v) for v in bvec_array.shape]
                if bvec_array.ndim == 2:
                    if bvec_array.shape[1] == 3:
                        bvec_count = int(bvec_array.shape[0])
                    elif bvec_array.shape[0] == 3:
                        bvec_count = int(bvec_array.shape[1])
        except Exception as exc:
            print(f"        failed to parse bval/bvec with DIPY: {exc}")

        matches_volume = bool(is_4d and volume_count and bval_count == volume_count and bvec_count == bval_count)
        print(f"        image shape: {shape}")
        print(f"        voxel size: {voxel_size}")
        print(f"        bval count: {bval_count}")
        print(f"        bvec shape: {bvec_shape}")
        print(f"        unique b-values: {unique_bvals}")
        print(f"        gradient directions: {gradient_directions}")
        print(
            "        bval/bvec count matches DTI volumes: "
            f"{matches_volume} (volumes={volume_count}, bvals={bval_count}, bvecs={bvec_count})"
        )

    def _export_dicom_candidate(self, candidate, modality_name: str):
        """
        Rename selected candidate to standard output name.
        """
        out_dir = self.config.PATIENT_DATA_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        output_paths = self._standard_output_paths_for_modality(out_dir, modality_name)

        if modality_name == "T1":
            dst_nii = output_paths["nii"]
            self._save_nifti_as(candidate["nii"], dst_nii)
            print(f"[DICOM] Exported T1: {dst_nii}")

        elif modality_name == "MRA":
            dst_nii = output_paths["nii"]
            self._save_nifti_as(candidate["nii"], dst_nii)
            print(f"[DICOM] Exported MRA: {dst_nii}")

        elif modality_name == "MRV":
            dst_nii = output_paths["nii"]
            self._save_nifti_as(candidate["nii"], dst_nii)
            print(f"[DICOM] Exported MRV: {dst_nii}")

        elif modality_name == "DTI":
            dst_nii = output_paths["nii"]
            dst_bval = output_paths["bval"]
            dst_bvec = output_paths["bvec"]

            self._save_nifti_as(candidate["nii"], dst_nii)

            if candidate["bval"].exists():
                shutil.copy2(candidate["bval"], dst_bval)
            else:
                print(f"[Warning] DTI bval not found: {candidate['bval']}")

            if candidate["bvec"].exists():
                shutil.copy2(candidate["bvec"], dst_bvec)
            else:
                print(f"[Warning] DTI bvec not found: {candidate['bvec']}")

            print(f"[DICOM] Exported DTI: {dst_nii}")
            print(f"[DICOM] Exported DTI bval: {dst_bval}")
            print(f"[DICOM] Exported DTI bvec: {dst_bvec}")
            self._log_dti_export_metadata(dst_nii, dst_bval, dst_bvec)

        return self._json_output_paths(output_paths)

    def _resolve_dcm2niix_cmd(self):
        return self._resolve_executable(self.config.DCM2NIIX_EXE, "--dcm2niix-exe")

    def _run_dcm2niix_conversion(self, source_dir: Path, output_dir: Path):
        output_dir = Path(output_dir)

        if output_dir.exists():
            print(f"[DICOM] Cleaning temp dir: {output_dir}")
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self._resolve_dcm2niix_cmd(),
            "-z", "n",
            "-b", "y",
            "-f", "%p_%s_%t_%j",
            "-o", str(output_dir),
            str(source_dir),
        ]

        print("[DICOM] Running command:")
        print(" ".join(cmd))

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
        )

        print(result.stdout)

        if result.returncode != 0:
            raise RuntimeError(f"dcm2niix failed with return code {result.returncode}")

        candidates = self._collect_dcm2niix_candidates(output_dir)
        if not candidates:
            raise RuntimeError(f"No NIfTI files generated by dcm2niix in: {output_dir}")

        print(f"[DICOM] Found {len(candidates)} converted NIfTI files in {output_dir}.")
        return candidates

    def _keywords_for_modality(self, modality_name: str):
        if modality_name == "T1":
            return self.config.DICOM_T1_KEYWORDS
        if modality_name == "MRA":
            return self.config.DICOM_MRA_KEYWORDS
        if modality_name == "MRV":
            return self.config.DICOM_MRV_KEYWORDS
        if modality_name == "DTI":
            return self.config.DICOM_DTI_KEYWORDS
        raise ValueError(f"Unsupported modality: {modality_name}")

    def _source_for_modality(self, modality_name: str):
        if modality_name == "T1":
            return self.config.DICOM_T1_SOURCE
        if modality_name == "MRA":
            return self.config.DICOM_MRA_SOURCE
        if modality_name == "MRV":
            return self.config.DICOM_MRV_SOURCE
        if modality_name == "DTI":
            return self.config.DICOM_DTI_SOURCE
        raise ValueError(f"Unsupported modality: {modality_name}")

    def _select_auto_candidate_for_modality(self, modality_name: str, candidates):
        if modality_name == "DTI":
            return self._select_dti_candidate(candidates)
        return self._select_anatomical_candidate(
            candidates,
            self._keywords_for_modality(modality_name),
            modality_name,
        )

    def _candidate_from_nifti_source(self, source_path: Path, modality_name: str):
        source_path = Path(source_path)
        stem = self._nifti_stem(source_path)
        bval_path = source_path.with_name(stem + ".bval")
        bvec_path = source_path.with_name(stem + ".bvec")

        if modality_name == "DTI":
            bval_path, bvec_path = self._find_dti_sidecars_for_nifti(source_path)

        shape, voxel_size, load_error = self._nifti_header_info(source_path)
        bval_count = self._read_bval_count(bval_path)
        bvec_shape, bvec_count = self._read_bvec_info(bvec_path)
        desc = f"{source_path.name} manual_nifti".lower()

        return {
            "nii": source_path,
            "json": source_path.with_name(stem + ".json"),
            "bval": bval_path,
            "bvec": bvec_path,
            "desc": desc,
            "series_description": source_path.name,
            "protocol_name": "",
            "sequence_name": "",
            "series_number": None,
            "image_type": "manual_nifti",
            "is_original_image_type": False,
            "is_derived_image_type": False,
            "has_bval_bvec": bval_path.exists() and bvec_path.exists(),
            "bval_count": bval_count,
            "bvec_shape": bvec_shape,
            "bvec_count": bvec_count,
            "shape": shape,
            "voxel_size": voxel_size,
            "volume_count": self._volume_count_from_shape(shape),
            "nifti_load_error": load_error,
            "size": source_path.stat().st_size if source_path.exists() else 0,
        }

    def _find_dti_sidecars_for_nifti(self, source_path: Path):
        source_path = Path(source_path)
        parent = source_path.parent
        stem = self._nifti_stem(source_path)

        bval_candidates = [parent / f"{stem}.bval", parent / f"{stem}.bvals"]
        bvec_candidates = [parent / f"{stem}.bvec", parent / f"{stem}.bvecs"]

        bval_path = next((path for path in bval_candidates if path.exists()), None)
        bvec_path = next((path for path in bvec_candidates if path.exists()), None)

        if bval_path is None:
            directory_bvals = sorted(list(parent.glob("*.bval")) + list(parent.glob("*.bvals")))
            if len(directory_bvals) == 1:
                bval_path = directory_bvals[0]

        if bvec_path is None:
            directory_bvecs = sorted(list(parent.glob("*.bvec")) + list(parent.glob("*.bvecs")))
            if len(directory_bvecs) == 1:
                bvec_path = directory_bvecs[0]

        missing = []
        if bval_path is None or not bval_path.exists():
            missing.append("bval")
        if bvec_path is None or not bvec_path.exists():
            missing.append("bvec")
        if missing:
            raise FileNotFoundError(
                f"Manual DTI NIfTI source needs matching sidecars. Missing {', '.join(missing)} for: {source_path}"
            )

        return bval_path, bvec_path

    def _select_unique_manual_dicom_candidate(self, candidates, modality_name: str):
        evaluated = []
        for candidate in candidates:
            matched_keywords = self._matched_keywords(candidate["desc"], self._keywords_for_modality(modality_name))
            if modality_name == "DTI":
                eligible = bool(candidate["has_bval_bvec"]) and candidate.get("bval_count", 0) > 0
                reason = "eligible: manual DICOM DTI candidate with bval/bvec" if eligible else "excluded: missing readable bval/bvec"
            else:
                eligible = not candidate["has_bval_bvec"]
                reason = "eligible: manual DICOM anatomical candidate" if eligible else "excluded: diffusion sidecars present"

            evaluated.append({
                "candidate": candidate,
                "score": None,
                "matched_keywords": matched_keywords,
                "derived_keywords": self._matched_derived_keywords(candidate["desc"]),
                "eligible": eligible,
                "reason": reason,
                "summary": self._candidate_summary(
                    candidate,
                    score=None,
                    matched_keywords=matched_keywords,
                    reason=reason,
                    eligible=eligible,
                ),
            })

        eligible_items = [item for item in evaluated if item["eligible"]]
        if len(eligible_items) != 1:
            names = ", ".join(item["candidate"]["nii"].name for item in eligible_items) or "none"
            raise RuntimeError(
                f"Manual {modality_name} DICOM source must convert to exactly one usable candidate; "
                f"found {len(eligible_items)}: {names}"
            )

        selected_item = eligible_items[0]
        selected = selected_item["candidate"]
        print(f"[DICOM] Selected manual {modality_name} DICOM series: {selected['nii'].name}")

        return {
            "selected": selected,
            "reason": selected_item["reason"],
            "matched_keywords": selected_item["matched_keywords"],
            "candidate_count": len(candidates),
            "excluded_candidates": self._excluded_candidate_briefs(evaluated, selected),
            "candidates": [item["summary"] for item in evaluated],
        }

    def _build_dicom_record(
        self,
        modality_name: str,
        selection_mode: str,
        source_path,
        source_name,
        output_paths,
        selection_result,
        include_candidates=False,
    ):
        selected = selection_result.get("selected") if selection_result else None
        record = {
            "modality": modality_name,
            "selection_mode": selection_mode,
            "source_path": str(source_path) if source_path else (str(selected["nii"]) if selected else None),
            "source_name": source_name if source_name else (selected["nii"].name if selected else None),
            "output_paths": output_paths or {},
            "reason": selection_result.get("reason") if selection_result else None,
            "matched_keywords": selection_result.get("matched_keywords", []) if selection_result else [],
            "candidate_count": selection_result.get("candidate_count", 0) if selection_result else 0,
            "excluded_candidates": selection_result.get("excluded_candidates", []) if selection_result else [],
        }

        if selected:
            record["selected_candidate"] = self._candidate_summary(
                selected,
                matched_keywords=record["matched_keywords"],
                reason=record["reason"],
                eligible=True,
            )

        if include_candidates and selection_result:
            record["candidates"] = selection_result.get("candidates", [])

        return record

    def _write_dicom_json_records(self, candidate_records, selection_records):
        candidates_path = self.config.BASE_DATA_DIR / "temp" / "dicom_candidates.json"
        selection_path = self.config.PATIENT_DATA_DIR / "dicom_selection.json"
        candidates_path.parent.mkdir(parents=True, exist_ok=True)
        selection_path.parent.mkdir(parents=True, exist_ok=True)

        with open(candidates_path, "w", encoding="utf-8") as f:
            json.dump({"records": candidate_records}, f, indent=2, ensure_ascii=False)

        with open(selection_path, "w", encoding="utf-8") as f:
            json.dump({"records": selection_records}, f, indent=2, ensure_ascii=False)

        print(f"[DICOM] Wrote candidates log: {candidates_path}")
        print(f"[DICOM] Wrote selection log: {selection_path}")

    def _process_manual_nifti_source(self, modality_name: str, source_path: Path):
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Manual {modality_name} source not found: {source_path}")
        if not source_path.is_file() or not self._is_nifti_path(source_path):
            raise ValueError(f"Manual {modality_name} NIfTI source must be .nii or .nii.gz: {source_path}")

        candidate = self._candidate_from_nifti_source(source_path, modality_name)
        output_paths = self._export_dicom_candidate(candidate, modality_name)
        selection_result = {
            "selected": candidate,
            "reason": "manual NIfTI source exported directly to standard output name",
            "matched_keywords": self._matched_keywords(candidate["desc"], self._keywords_for_modality(modality_name)),
            "candidate_count": 1,
            "excluded_candidates": [],
            "candidates": [
                self._candidate_summary(
                    candidate,
                    matched_keywords=self._matched_keywords(candidate["desc"], self._keywords_for_modality(modality_name)),
                    reason="manual NIfTI source",
                    eligible=True,
                )
            ],
        }
        return output_paths, selection_result

    def _process_manual_dicom_series_source(self, modality_name: str, source_path: Path):
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Manual {modality_name} DICOM source not found: {source_path}")
        if not source_path.is_dir():
            raise ValueError(
                f"Manual {modality_name} DICOM source must be a single-series folder "
                f"or a .nii/.nii.gz file: {source_path}"
            )

        dicom_input_dir = source_path
        if self.config.DICOM_DECOMPRESS_DCMTK:
            manual_decompress_dir = Path(self.config.DICOM_DECOMPRESS_DIR).parent / f"manual_{modality_name.lower()}_dcmtk"
            dicom_input_dir = self._decompress_dicom_with_dcmtk(source_path, manual_decompress_dir)

        manual_temp_dir = Path(self.config.DICOM_TEMP_DIR).parent / f"manual_{modality_name.lower()}"
        candidates = self._run_dcm2niix_conversion(dicom_input_dir, manual_temp_dir)
        selection_result = self._select_unique_manual_dicom_candidate(candidates, modality_name)
        output_paths = self._export_dicom_candidate(selection_result["selected"], modality_name)
        return output_paths, selection_result

    def _process_dicom_convert(self):
        """
        Convert DICOM folder to standardized NIfTI files using dcm2niix.

        Input:
            --dicom-dir

        Output in patient_input:
            T1.nii
            MRA.nii
            MRV.nii
            DTI.nii.gz
            DTI.bval
            DTI.bvec
        """
        print("--- Running DICOM conversion by dcm2niix ---")

        modalities = ["DTI"] if self.config.DICOM_ONLY_DTI else ["T1", "MRA", "MRV", "DTI"]
        if self.config.DICOM_ONLY_DTI:
            print("[DICOM] --dicom-only-dti enabled. Skipping T1/MRA/MRV export.")

        sources = {modality: self._source_for_modality(modality) for modality in modalities}
        auto_modalities = [modality for modality, source in sources.items() if source is None]
        auto_candidates = None
        candidate_records = []
        selection_records = []

        if auto_modalities:
            if self.config.DICOM_DIR is None:
                raise ValueError(
                    "Please provide --dicom-dir for modalities without --dicom-*-source: "
                    + ", ".join(auto_modalities)
                )

            dicom_dir = Path(self.config.DICOM_DIR)
            if not dicom_dir.exists():
                raise FileNotFoundError(f"DICOM directory not found: {dicom_dir}")

            dicom_input_dir = dicom_dir
            if self.config.DICOM_DECOMPRESS_DCMTK:
                dicom_input_dir = self._decompress_dicom_with_dcmtk(dicom_dir)

            auto_candidates = self._run_dcm2niix_conversion(dicom_input_dir, Path(self.config.DICOM_TEMP_DIR))
        else:
            print("[DICOM] All requested modalities use manual sources; skipping automatic DICOM conversion.")

        for modality_name in modalities:
            source_path = sources[modality_name]

            if source_path is None:
                selection_mode = "auto"
                selection_result = self._select_auto_candidate_for_modality(modality_name, auto_candidates)
                selected = selection_result.get("selected")

                if selected is not None:
                    output_paths = self._export_dicom_candidate(selected, modality_name)
                else:
                    output_paths = {}
                    print(f"[Warning] {modality_name} was not exported.")

                source_for_record = selected["nii"] if selected else self.config.DICOM_DIR
                source_name = selected["nii"].name if selected else Path(self.config.DICOM_DIR).name

            else:
                source_path = Path(source_path)
                if not source_path.exists():
                    raise FileNotFoundError(f"Manual {modality_name} source not found: {source_path}")
                if source_path.is_file() and self._is_nifti_path(source_path):
                    selection_mode = "manual_nifti"
                    output_paths, selection_result = self._process_manual_nifti_source(modality_name, source_path)
                elif source_path.is_dir():
                    selection_mode = "manual_dicom_series"
                    output_paths, selection_result = self._process_manual_dicom_series_source(modality_name, source_path)
                else:
                    raise ValueError(
                        f"--dicom-{modality_name.lower()}-source must be empty, a .nii/.nii.gz file, "
                        f"or a DICOM single-series folder: {source_path}"
                    )

                source_for_record = source_path
                source_name = source_path.name

            candidate_records.append(
                self._build_dicom_record(
                    modality_name,
                    selection_mode,
                    source_for_record,
                    source_name,
                    output_paths,
                    selection_result,
                    include_candidates=True,
                )
            )
            selection_records.append(
                self._build_dicom_record(
                    modality_name,
                    selection_mode,
                    source_for_record,
                    source_name,
                    output_paths,
                    selection_result,
                    include_candidates=False,
                )
            )

        self._write_dicom_json_records(candidate_records, selection_records)

        print("--- DICOM conversion finished ---")

    #################################
    # --- DICOM to NIfTI end ---
    #################################

    #################################
    # --- SynthSeg by Docker ---
    #################################
    def _process_synthseg_segmentation(self):
        """Run SynthSeg in Docker and save the parcellation result."""
        print("--- Running SynthSeg segmentation by Docker ---")

        docker_exe = self.config.DOCKER_EXE
        docker_path = Path(docker_exe)
        if docker_path.exists():
            docker_cmd = str(docker_path)
        else:
            found = shutil.which(docker_exe)
            if found is None:
                raise FileNotFoundError(
                    f"Docker executable not found: {docker_exe}. "
                    f"Please provide --docker-exe or add Docker to PATH."
                )
            docker_cmd = found

        input_file = Path(self.config.T1_FILE).resolve()
        output_file = Path(self.config.DK_FILE).resolve()

        if not input_file.exists():
            raise FileNotFoundError(f"SynthSeg input file not found: {input_file}")

        output_file.parent.mkdir(parents=True, exist_ok=True)

        input_mount = f"type=bind,source={input_file.parent},target=/input,readonly"
        output_mount = f"type=bind,source={output_file.parent},target=/output"

        cmd = [
            docker_cmd,
            "run",
            "--rm",
            "-e",
            "CUDA_VISIBLE_DEVICES=-1",
            "--mount",
            input_mount,
            "--mount",
            output_mount,
            "--entrypoint",
            "python",
            self.config.SYNTHSEG_DOCKER_IMAGE,
            "scripts/commands/SynthSeg_predict.py",
            "--i",
            f"/input/{input_file.name}",
            "--o",
            f"/output/{output_file.name}",
            "--parc",
            "--robust",
            "--cpu",
        ]

        if self.config.SYNTHSEG_THREADS:
            cmd.extend(["--threads", str(self.config.SYNTHSEG_THREADS)])

        print("[SynthSeg] Running command:")
        print(subprocess.list2cmdline(cmd))

        subprocess.run(cmd, check=True, shell=False)

        if not output_file.exists():
            raise RuntimeError(f"SynthSeg finished but output was not found: {output_file}")

        print(f"--- SynthSeg segmentation finished: {output_file} ---")

    #################################
    # --- SynthSeg by Docker end ---
    #################################

    #################################
    # --- SPM ---
    #################################
    def _process_spm_segmentation(self):
        """Segment T1 into GM/WM probability maps using the configured SPM backend."""
        backend = self._resolve_spm_backend()
        print(f"--- Running SPM segmentation ({backend}) ---")
        if backend == "compiled_exe":
            self._process_spm_segmentation_compiled()
        elif backend == "spm_standalone":
            self._process_spm_segmentation_standalone()
        elif backend == "matlab_cli":
            self._process_spm_segmentation_matlab_cli()
        elif backend == "matlab_engine":
            self._process_spm_segmentation_matlab_engine()
        else:
            raise RuntimeError(f"Unsupported SPM backend: {backend}")
        self._validate_spm_outputs()
        print("--- SPM segmentation finished ---")

    def _resolve_spm_backend(self):
        backend = (self.config.SPM_BACKEND or "auto").lower()
        valid = {"auto", "compiled_exe", "spm_standalone", "matlab_cli", "matlab_engine"}
        if backend not in valid:
            raise RuntimeError(f"Unsupported --spm-backend value: {backend}. Expected one of: {sorted(valid)}")
        if backend != "auto":
            return backend
        if self.config.SPM_COMPILED_EXE and self.config.SPM_COMPILED_EXE.exists():
            return "compiled_exe"
        if self.config.SPM_STANDALONE_EXE and self.config.SPM_STANDALONE_EXE.exists():
            return "spm_standalone"
        return "matlab_engine"

    def _spm_script_dir(self):
        spm_script_dir = Path(self.config.SPM_SCRIPT_DIR)
        return spm_script_dir.parent if spm_script_dir.is_file() else spm_script_dir

    def _validate_spm_inputs(self):
        t1_file = Path(self.config.T1_FILE)
        spm_dir = Path(self.config.SPM_DIR)
        spm_script_dir = self._spm_script_dir()
        spm_script_file = spm_script_dir / "run_spm_segmentation.m"

        if not t1_file.exists():
            raise FileNotFoundError(f"T1 file not found: {t1_file}")
        if not spm_dir.exists():
            raise FileNotFoundError(f"SPM directory not found: {spm_dir}")
        if not spm_script_dir.exists():
            raise FileNotFoundError(f"SPM script directory not found: {spm_script_dir}")
        if not spm_script_file.exists():
            raise FileNotFoundError(f"SPM MATLAB script not found: {spm_script_file}")
        return t1_file, spm_dir, spm_script_dir

    def _spm_output_paths(self):
        t1_file = Path(self.config.T1_FILE)
        name = t1_file.name
        if name.lower().endswith(".nii.gz"):
            base_name = name[:-7]
        elif name.lower().endswith(".nii"):
            base_name = name[:-4]
        else:
            base_name = t1_file.stem
        return [t1_file.with_name(f"c1{base_name}.nii"), t1_file.with_name(f"c2{base_name}.nii")]

    def _validate_spm_outputs(self):
        missing = [str(path) for path in self._spm_output_paths() if not path.exists()]
        if missing:
            raise RuntimeError("SPM segmentation finished but expected outputs were not found: " + "; ".join(missing))

    def _spm_runtime_env(self):
        env = os.environ.copy()
        mcr_home = self.config.MCR_HOME
        if not mcr_home:
            return env
        if not mcr_home.exists():
            raise FileNotFoundError(
                f"MATLAB Runtime directory not found: {mcr_home}. "
                "Install or bundle the matching MATLAB Runtime, or use --spm-backend=matlab_engine on a development machine."
            )

        env["MCR_HOME"] = str(mcr_home)
        runtime_paths = [
            mcr_home / "runtime" / "win64",
            mcr_home / "bin" / "win64",
            mcr_home / "sys" / "os" / "win64",
            mcr_home / "extern" / "bin" / "win64",
        ]
        existing_paths = [str(path) for path in runtime_paths if path.exists()]
        if existing_paths:
            env["PATH"] = os.pathsep.join(existing_paths + [env.get("PATH", "")])
        return env

    def _process_spm_segmentation_compiled(self):
        t1_file, spm_dir, _ = self._validate_spm_inputs()
        compiled_exe = self.config.SPM_COMPILED_EXE
        if not compiled_exe:
            raise RuntimeError("--spm-compiled-exe is required when --spm-backend=compiled_exe.")
        if not compiled_exe.exists():
            raise FileNotFoundError(f"SPM compiled executable not found: {compiled_exe}")

        env = self._spm_runtime_env()
        cmd = [str(compiled_exe), str(t1_file), str(spm_dir)]
        print("[SPM] " + subprocess.list2cmdline(cmd))
        subprocess.run(cmd, check=True, env=env)

    def _write_spm_standalone_batch(self, t1_file: Path, spm_dir: Path):
        spm_batch_dir = self.config.BASE_DATA_DIR / "temp" / "spm_batch"
        spm_batch_dir.mkdir(parents=True, exist_ok=True)
        batch_file = spm_batch_dir / "spm_segment_job.m"
        template_file = self._spm_script_dir() / "spm_segment_batch_template.m"
        if not template_file.exists():
            raise FileNotFoundError(f"SPM standalone batch template not found: {template_file}")
        tpm_file = spm_dir / "tpm" / "TPM.nii"
        text = template_file.read_text(encoding="utf-8")
        replacements = {
            "{{T1_FILE}}": str(t1_file).replace("\\", "/").replace("'", "''"),
            "{{SPM_DIR}}": str(spm_dir).replace("\\", "/").replace("'", "''"),
            "{{TPM_FILE}}": str(tpm_file).replace("\\", "/").replace("'", "''"),
        }
        for marker, value in replacements.items():
            text = text.replace(marker, value)
        batch_file.write_text(text, encoding="utf-8")
        return batch_file

    def _process_spm_segmentation_standalone(self):
        t1_file, spm_dir, _ = self._validate_spm_inputs()
        standalone_exe = self.config.SPM_STANDALONE_EXE
        if not standalone_exe:
            raise RuntimeError("--spm-standalone-exe is required when --spm-backend=spm_standalone.")
        if not standalone_exe.exists():
            raise FileNotFoundError(f"SPM standalone executable not found: {standalone_exe}")

        batch_file = self._write_spm_standalone_batch(t1_file, spm_dir)
        env = self._spm_runtime_env()
        if standalone_exe.parent.exists():
            env["SPM_HOME"] = str(standalone_exe.parent)

        cmd = [str(standalone_exe)]
        if self.config.MCR_HOME:
            cmd.append(str(self.config.MCR_HOME))
        cmd.extend(["batch", str(batch_file)])
        print("[SPM] " + subprocess.list2cmdline(cmd))
        subprocess.run(cmd, check=True, env=env)

    @staticmethod
    def _matlab_literal(value):
        return str(value).replace("\\", "/").replace("'", "''")

    def _resolve_matlab_exe(self):
        configured = (getattr(self.config, "MATLAB_EXE", "") or "").strip()
        env_configured = (os.environ.get("MATLAB_EXE") or "").strip()
        if (not configured or configured.lower() == "matlab") and env_configured:
            configured = env_configured
        if not configured:
            configured = "matlab"
        configured_path = Path(configured)
        looks_like_path = configured_path.is_absolute() or "\\" in configured or "/" in configured
        if looks_like_path:
            if configured_path.exists():
                return str(configured_path)
            raise FileNotFoundError(f"MATLAB executable not found: {configured_path}")

        found = shutil.which(configured)
        if found:
            return found

        candidates = [
            Path("D:/Matlab/bin/matlab.exe"),
        ]
        matlab_root = Path("C:/Program Files/MATLAB")
        if matlab_root.exists():
            candidates.extend(sorted(matlab_root.glob("R*/bin/matlab.exe"), reverse=True))

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        raise FileNotFoundError(
            "MATLAB executable was not found. Put matlab.exe on PATH, set MATLAB_EXE, "
            "or edit config/app_settings.json."
        )

    def _process_spm_segmentation_matlab_cli(self):
        """Use an installed MATLAB executable without requiring MATLAB Engine for Python."""
        t1_file, spm_dir, spm_script_dir = self._validate_spm_inputs()
        matlab_exe = self._resolve_matlab_exe()
        matlab_command = (
            f"addpath('{self._matlab_literal(spm_script_dir)}'); "
            f"addpath('{self._matlab_literal(spm_dir)}'); "
            f"run_spm_segmentation('{self._matlab_literal(t1_file)}', '{self._matlab_literal(spm_dir)}');"
        )
        cmd = [matlab_exe, "-batch", matlab_command]
        print("[SPM] " + subprocess.list2cmdline(cmd))
        subprocess.run(cmd, check=True)

    def _process_spm_segmentation_matlab_engine(self):
        """Use MATLAB Engine for Python as a development-machine fallback."""
        try:
            import matlab.engine
        except ImportError as e:
            raise RuntimeError(
                "matlab.engine not found. Please install MATLAB Engine for Python "
                "in this Python environment."
            ) from e

        t1_file, spm_dir, spm_script_dir = self._validate_spm_inputs()

        eng = matlab.engine.start_matlab()
        try:
            eng.addpath(str(spm_dir), nargout=0)
            eng.addpath(str(spm_script_dir), nargout=0)

            eng.run_spm_segmentation(str(t1_file), str(spm_dir), nargout=0)
        finally:
            eng.quit()

    #################################
    # --- SPM end ---
    #################################

    #################################
    # --- brain regions ---
    #################################

    # def voxel_conflict_resolve(self, label_volume):
    #     """解决脑区穿模问题，保留边界层但移除被其他标签包围过多的体素"""
    #     print("Running voxel conflict resolve...")

    #     label_volume = label_volume.copy()
    #     labels = np.unique(label_volume)
    #     labels = labels[labels > 0]
    #     struct = np.ones((3, 3, 3), dtype=np.int32)
    #     new_volume = label_volume.copy()
    #     for lab in labels:
    #         mask = (label_volume == lab)
    #         # 统计邻域内非本标签数量
    #         neighbor_diff = convolve((label_volume != lab).astype(np.int32),struct,mode="constant",cval=0)
    #         # 只处理真正冲突点（邻域中存在其他标签）
    #         conflict = mask & (neighbor_diff > 0)
    #         # 但只移除“被包围比例很高”的点
    #         # 避免破坏薄层
    #         overlap_points = 10 # 邻域内超过10个点是其他标签才认为是重度冲突
    #         heavy_conflict = conflict & (neighbor_diff > overlap_points)
    #         new_volume[heavy_conflict] = 0
    #     print("Conflict resolve done.")
    #     return new_volume
    
    def voxel_conflict_resolve(self, label_volume, overlap_points=10, margin=1):
        """
        解决脑区穿模问题：只在每个label的局部bounding box内处理冲突体素。
        相比原版本，不再对每个label扫描整幅volume，速度会明显提升。

        参数：
        overlap_points:
        邻域内其他脑区体素数量超过该值时，认为是重度冲突点。
        margin:
            bounding box外扩范围。3x3x3邻域一般设为1即可。
        """
        print("Running fast voxel conflict resolve...")

        label_volume = label_volume.astype(np.int32, copy=True)
        new_volume = label_volume.copy()

        labels = np.unique(label_volume)
        labels = labels[labels > 0]

        struct = np.ones((3, 3, 3), dtype=np.uint8)

        shape = label_volume.shape

        for lab in labels:
            coords = np.where(label_volume == lab)
            if coords[0].size == 0:
                continue

            # 当前label的bounding box，并外扩margin
            x_min = max(coords[0].min() - margin, 0)
            x_max = min(coords[0].max() + margin + 1, shape[0])

            y_min = max(coords[1].min() - margin, 0)
            y_max = min(coords[1].max() + margin + 1, shape[1])

            z_min = max(coords[2].min() - margin, 0)
            z_max = min(coords[2].max() + margin + 1, shape[2])

            slc = np.s_[x_min:x_max, y_min:y_max, z_min:z_max]

            crop = label_volume[slc]

            # 当前脑区mask
            mask_lab = crop == lab

            # 只统计“其他脑区”，不把背景0算作冲突
            other_labels = (crop > 0) & (crop != lab)

            # 局部卷积，只在小区域内做
            other_count = convolve(
                other_labels.astype(np.uint8),
                struct,
                mode="constant",
                cval=0
            )

            # 当前脑区中，被其他脑区包围过多的点认为是冲突点
            heavy_conflict = mask_lab & (other_count > overlap_points)

            if np.any(heavy_conflict):
                new_crop = new_volume[slc]
                new_crop[heavy_conflict] = 0
                new_volume[slc] = new_crop

        print("Fast conflict resolve done.")
        return new_volume

    def _reconstruct_multilabel_vtk(self, label_volume, output_dir):
        """使用 vtkDiscreteFlyingEdges3D 进行多标签联合重建"""
        print("Starting VTK multi-label reconstruction...")

        # --- numpy -> vtkImageData ---
        vtk_data = vtk.vtkImageData()
        depthArray = numpy_support.numpy_to_vtk(num_array=label_volume.ravel(order='F'),deep=True,array_type=vtk.VTK_INT)
        vtk_data.SetDimensions(label_volume.shape)
        vtk_data.GetPointData().SetScalars(depthArray)

        # spacing
        vtk_data.SetSpacing(1.0, 1.0, 1.0)

        # --- Discrete Flying Edges ---
        dmc = vtk.vtkDiscreteFlyingEdges3D()
        dmc.SetInputData(vtk_data)
        labels = np.unique(label_volume)
        labels = labels[labels > 0]
        for i, lab in enumerate(labels):
            dmc.SetValue(i, int(lab))
        dmc.Update()

        # --- 联合平滑 ---
        smoother = vtk.vtkWindowedSincPolyDataFilter()
        smoother.SetInputConnection(dmc.GetOutputPort())
        smoother.SetNumberOfIterations(40)
        smoother.SetPassBand(0.01)
        smoother.BoundarySmoothingOff()
        smoother.FeatureEdgeSmoothingOff()
        smoother.NonManifoldSmoothingOn()
        smoother.NormalizeCoordinatesOn()
        smoother.Update()

        smooth_output = smoother.GetOutput()
        print("VTK reconstruction done. Splitting regions...")

        # --- 按label拆分 ---
        for lab in labels:

            thresh = vtk.vtkThreshold()
            thresh.SetInputData(smooth_output)
            thresh.SetLowerThreshold(lab)
            thresh.SetUpperThreshold(lab)
            thresh.SetThresholdFunction(vtk.vtkThreshold.THRESHOLD_BETWEEN)
            thresh.Update()

            geom = vtk.vtkGeometryFilter()
            geom.SetInputConnection(thresh.GetOutputPort())
            geom.Update()

            poly = geom.GetOutput()

            if poly.GetNumberOfPoints() == 0:
                continue

            # --- decimation ---
            decimate = vtk.vtkQuadricDecimation()
            decimate.SetInputData(poly)
            decimate.SetTargetReduction(0.3)
            decimate.VolumePreservationOn()
            decimate.AttributeErrorMetricOn()
            decimate.Update()

            post_smooth = vtk.vtkWindowedSincPolyDataFilter()
            post_smooth.SetInputConnection(decimate.GetOutputPort())
            post_smooth.SetNumberOfIterations(40)
            post_smooth.SetPassBand(0.05)
            post_smooth.BoundarySmoothingOn()
            post_smooth.FeatureEdgeSmoothingOn()
            post_smooth.NonManifoldSmoothingOn()
            post_smooth.NormalizeCoordinatesOn()
            post_smooth.Update()

            normals = vtk.vtkPolyDataNormals()
            normals.SetInputData(post_smooth.GetOutput())
            normals.AutoOrientNormalsOn()
            normals.ConsistencyOn()
            normals.SplittingOff()
            normals.Update()
            
            final_poly = normals.GetOutput()

            self._export_vtk_polydata(final_poly, lab, output_dir)

    def _export_vtk_polydata(self, polydata, label, output_dir):
        """将vtk PolyData转换为trimesh并导出为glb"""

        points = numpy_support.vtk_to_numpy(polydata.GetPoints().GetData())
        faces = numpy_support.vtk_to_numpy(polydata.GetPolys().GetData())
        faces = faces.reshape(-1, 4)[:, 1:4]
        mesh = trimesh.Trimesh(vertices=points, faces=faces)
        mesh.vertices = nib.affines.apply_affine(self.affine, mesh.vertices)
        mesh.apply_scale(1 / 1000)

        name = self.DK_names.get(label, f"region_{label}")
        filename = output_dir / f"{name}.glb"

        BrainMeshProcessor._apply_material_from_mtl_static(mesh, filename, self.config)
        mesh.visual.material.doubleSided = True

        mesh.export(str(filename), file_type='glb')
        print(f"Exported {name}")
    
    def _process_individual_regions_synthseg(self):
        """处理模式1：每个脑区，使用SynthSeg分割结果"""

        nii_array_parc = nib.load(self.config.DK_FILE).get_fdata()
        t1_array = nib.load(self.config.T1_FILE).get_fdata()

        zoom_factors = tuple(np.array(t1_array.shape) / np.array(nii_array_parc.shape))
        nii_array = zoom(nii_array_parc, zoom_factors, order=0)

        # 只保留DK皮层
        nii_array[nii_array < 99] = 0
        nii_array = self.voxel_conflict_resolve(nii_array.astype(np.int32))

        self._reconstruct_multilabel_vtk(nii_array.astype(np.int32),self.config.output_path)
    
    #################################
    # --- brain regions end ---
    #################################


    #################################
    # --- GM/WM ---
    #################################
    
    def _process_gm_wm(self):
        """处理模式2：灰质白质"""

        gmwm_files = [ self.config.MASK_FILE ] # 只对WM
        # 逐一加载并生成导出的OBJ文件
        for idx, file_path in enumerate(gmwm_files, start=1):
            nii_array = nib.load(file_path).get_fdata()
            # 二值化体积
            volume = np.zeros_like(nii_array, dtype=np.uint8)
            volume[nii_array > 0] = 1
            # 移除小的体积对象
            cleaned_volume = remove_small_objects(volume.astype(bool), min_size=800)  # 灰质/白质处理使用800的object size
            if not cleaned_volume.any():
                print(f"No valid volume remains after cleaning for GM/WM file {file_path.name}. Skipping.")
                continue
            # 网格生成并导出
            filename = self.config.output_path / f"w{idx}.glb"
            self._generate_and_export_mesh(
                cleaned_volume,
                filename,
                iterations=15,
                lamb=0.8,
            )
    
    #################################
    # --- GM/WM end ---
    #################################

    #################################
    # --- MRA ---
    #################################

    def _process_vessel(self):
        """处理模式3：动脉血管"""

        mra_img = nib.load(self.config.MRA_FILE)
        nii_array = mra_img.get_fdata()
        affine_mra = mra_img.affine  # MRA仿射矩阵

        # 1. 阈值分割
        threshold = self.config.VESSEL_THRESHOLD
        volume = np.zeros_like(nii_array, dtype=np.uint8)
        volume[nii_array > threshold] = 1
        cleaned_volume = remove_small_objects(volume.astype(bool),min_size=self.config.VESSEL_MIN_OBJECT_SIZE)
        if not cleaned_volume.any():
            print("No valid volume remains after cleaning for vessels. Skipping.")
            return

        # 2. 连通域分割
        print("Performing connected component analysis to keep the LARGEST region...")
        # 标记连通域
        labeled_array, num_features = measure.label(cleaned_volume, connectivity=2, return_num=True)
        if num_features == 0:
            print("No features found after labeling. Skipping.")
            return
        # 计算每个连通域的大小 (bincount统计每个label出现的次数)
        component_sizes = np.bincount(labeled_array.ravel())
        # 忽略背景(label 0)，找到最大的连通域 Label
        # component_sizes[1:] 是除去背景后的数组
        # np.argmax 返回最大值的索引，因为切片去掉了第0个，所以真实label需要 +1
        largest_label = np.argmax(component_sizes[1:]) + 1
        print(f"Found {num_features} components. Keeping the largest: "
              f"label #{largest_label} (size: {component_sizes[largest_label]}).")
        # 生成只包含最大连通域的 Mask
        final_volume = (labeled_array == largest_label)
        verts, faces, _, _ = measure.marching_cubes(final_volume, level=self.config.MARCHING_CUBES_LEVEL)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        smoothed_mesh = trimesh.smoothing.filter_humphrey(mesh)
        t1_original_affine = self.t1_img.affine  # T1仿射矩阵

        # MRA空间 -> T1空间 (配准)
        trans = np.linalg.inv(t1_original_affine).dot(affine_mra)
        smoothed_mesh.vertices = nib.affines.apply_affine(trans, smoothed_mesh.vertices)

        # T1空间 -> 最终空间
        smoothed_mesh.vertices = nib.affines.apply_affine(self.affine, smoothed_mesh.vertices)
        smoothed_mesh.apply_scale(1 / 1000)

        filename = self.config.output_path / "vessel.glb"
        vedo_mesh = Mesh([smoothed_mesh.vertices, smoothed_mesh.faces])
        decimated_mesh = vedo_mesh.decimate(fraction=self.config.VESSEL_DECIMATION_FRACTION)

        # 将 vedo 减面后的结果转换回 Trimesh 对象以便导出
        final_mesh = trimesh.Trimesh(
            vertices=decimated_mesh.points,
            faces=decimated_mesh.cells
        )

        BrainMeshProcessor._apply_material_from_mtl_static(final_mesh, filename, self.config)
        final_mesh.faces = final_mesh.faces[:, [0, 2, 1]]
        final_mesh.export(str(filename), file_type='glb')
        print(f"Successfully processed and exported: {filename.name}")

    #################################
    # --- MRA end ---
    #################################

    #################################
    # --- Lobes ---
    #################################

    def _process_lobes_synthseg(self):
        """处理模式4：DK脑叶"""

        nii_array_parc = nib.load(self.config.DK_FILE).get_fdata()
        t1_array = nib.load(self.config.T1_FILE).get_fdata()
        ## SynthSeg 的分割结果是 1分辨率
        #  eg_T1 的分割结果是 0.5分辨率
        synthseg_shape = nii_array_parc.shape
        t1_shape = t1_array.shape
        zoom_factors = tuple(np.array(t1_shape) / np.array(synthseg_shape))
        nii_array = zoom(nii_array_parc, zoom_factors,
                         order=0)  # upscale 后的affine矩阵与 eg_T1 一致, 原本synthseg结果是 1mm, affine与 eg_T1一致

        lobe_dict = BrainMeshProcessor._load_lobe_mapping(self.config.LOBE_MAP_FILE)
        tasks = list(lobe_dict.keys())

        data_payload = {
            "nii_array": nii_array,
            "affine": self.affine,
            "unprocessed_items": self.unprocessed_items,
            "lookup_dict": lobe_dict,
            "output_path": self.config.output_path,
            "config": self.config
        }
        self._run_multiprocess(tasks, data_payload, self._worker_by_lookup)

    #################################
    # --- lobes end ---
    #################################

    #################################
    # --- hemispheres ---
    #################################

    def _process_hemispheres_synthseg(self):
        """处理模式5：DK半球"""

        nii_array_parc = nib.load(self.config.DK_FILE).get_fdata()
        t1_array = nib.load(self.config.T1_FILE).get_fdata()
        ## SynthSeg 的分割结果是 1分辨率
        #  eg_T1 的分割结果是 0.5分辨率
        synthseg_shape = nii_array_parc.shape
        t1_shape = t1_array.shape
        zoom_factors = tuple(np.array(t1_shape) / np.array(synthseg_shape))
        nii_array = zoom(nii_array_parc, zoom_factors,
                         order=0)  # upscale 后的affine矩阵与 eg_T1 一致, 原本synthseg结果是 1mm, affine与 eg_T1一致

        hemisphere_dict = hemisphere_map
        tasks = list(hemisphere_dict.keys())
        data_payload = {
            "nii_array": nii_array,
            "affine": self.affine,
            "unprocessed_items": self.unprocessed_items,
            "lookup_dict": hemisphere_dict,
            "output_path": self.config.output_path,
            "config": self.config
        }
        self._run_multiprocess(tasks, data_payload, self._worker_by_lookup)
    
    #################################
    # --- hemisphere end ---
    #################################

    #################################
    # --- ROI ---
    #################################

    def _process_roi(self):
        """处理模式6：ROI（感兴趣区域）"""
        # 加载感兴趣区域 (ROI) 的体积数据
        nii_array = nib.load(self.config.ROI_FILE).get_fdata()
        # 检查 ROI 的唯一值（按主脚本处理的假设：值为 0 和 1）
        unique_values = np.unique(nii_array)
        if len(unique_values) != 2 or set(unique_values) != {0, 1}:
            print(f"Warning: Unexpected ROI values found: {unique_values}. Expected values: {0, 1}. Processing skipped.")
            return
        # 二值化 ROI 的体积（只保留值为 1 的部分）
        volume = np.zeros_like(nii_array, dtype=np.uint8)
        volume[nii_array == 1] = 1
        # 移除过小的对象体积，防止生成无效网格
        cleaned_volume = remove_small_objects(volume.astype(bool), min_size=self.config.MIN_OBJECT_SIZE)
        if not cleaned_volume.any():
            print("ROI region is empty after cleaning. Skipping.")
            return

        filename = self.config.output_path / "ROI.glb"
        self._generate_and_export_mesh(
            cleaned_volume,
            filename,
            iterations=25,  # 使用更精细的优化参数
            lamb=1.0,
        )

    #################################
    # --- ROI end ---
    #################################

    #################################
    # --- DTI Fiber Tracking ---
    #################################

    def _process_fiber_tracking(self):
        """处理模式7：纤维追踪"""

        dti_data, affine, dti_img = load_nifti(self.config.DTI_FILE, return_img=True)
        _, __, mask_img = load_nifti(self.config.MASK_FILE, return_img=True)

        # 将白质模板重采样到DTI图像。注意最邻近插值
        mask_img_rs = image.resample_to_img(mask_img, dti_img, interpolation='nearest', copy_header=True)
        mask = mask_img_rs.get_fdata()
        mask[mask >= 0.5] = 1
        mask[mask < 0.5] = 0

        # --- 纤维追踪 ---
        bvals, bvecs = read_bvals_bvecs(str(self.config.DTI_BVALS_FILE), str(self.config.DTI_BVECS_FILE))
        gtab = gradient_table(bvals=bvals, bvecs=bvecs)
        response, ratio = auto_response_ssst(gtab, dti_data, roi_radii=self.config.FIBER_AUTO_RESPONSE_ROI_RADII,fa_thr=self.config.FIBER_AUTO_RESPONSE_FA_THR)
        csd_model = ConstrainedSphericalDeconvModel(gtab, response, sh_order_max=6)
        csd_fit = csd_model.fit(dti_data, mask=mask)
        csa_model = CsaOdfModel(gtab, sh_order_max=6)
        csa_fit = csa_model.fit(dti_data, mask=mask)
        gfa = csa_fit.gfa
        gfa_img = nib.Nifti1Image(gfa, affine, header=dti_img.header)
        output_path = str(self.config.FIBER_GFA_CACHE_FILE)  # 过程文件，存放在temp目录下
        nib.save(gfa_img, output_path)

        gfa_threshold = self.config.FIBER_GFA_THRESHOLD
        step = self.config.FIBER_STEP
        stop_threshold = self.config.FIBER_STOP_THRESHOLD

        stopping_criterion = ThresholdStoppingCriterion(gfa, stop_threshold)
        seed_mask = np.zeros_like(gfa)
        seed_mask[gfa > gfa_threshold] = 1
        seeds = utils.seeds_from_mask(seed_mask, np.eye(4), self.config.FIBER_SEED_DENSITY)
        seeds = seeds[::step, :]  # 按5为间隔采样，避免纤维过多渲染压力太大
        detmax_dg = DeterministicMaximumDirectionGetter.from_shcoeff(csd_fit.shm_coeff, max_angle=self.config.FIBER_MAX_ANGLE, sphere=default_sphere, sh_to_pmf=True)
        streamline_generator = LocalTracking(detmax_dg, stopping_criterion, seeds,np.eye(4), step_size=self.config.FIBER_STEP_SIZE)
        streamlines = Streamlines(streamline_generator)
        
        # --- 绘制纤维模型 ---
        mesh_list = []
        radius = self.config.FIBER_RADIUS
        sections = self.config.FIBER_SECTIONS
        transparent = int(1.0 * 255)
        for streamline in streamlines:
            for i in range(1, len(streamline)):
                # 绘制单段纤维
                tmp = trimesh.creation.cylinder(radius=radius, sections=sections, segment=streamline[i - 1:i + 1])
                primary_direction = streamline[i] - streamline[i - 1]
                primary_direction /= np.linalg.norm(primary_direction)
                # 基于方向向量计算颜色 (方向向量的正值映射到RGB通道)
                color = np.abs(primary_direction * 255)
                color = color.astype(np.uint8)  # 转换为整数值
                color = np.array(list(color) + [transparent])
                tmp.visual.face_colors = color
                mesh_list.append(tmp)

        # --- export ---
        fiber_mesh = trimesh.util.concatenate(mesh_list)
        del mesh_list
        trans = np.linalg.inv(self.t1_img.affine).dot(affine)  # 计算DTI体素空间到T1体素空间的变化
        fiber_mesh.vertices = nib.affines.apply_affine(trans, fiber_mesh.vertices) 
        fiber_mesh.vertices = nib.affines.apply_affine(self.affine,fiber_mesh.vertices)  # 从T1体素空间变换到volume rendering的空间
        fiber_mesh.apply_scale(1 / 1000)  # 从mm单位转换到m单位
        filename = self.config.output_path / f"Fiber_{gfa_threshold}_{step}_{stop_threshold}_uv.glb"
        
        # fix affine normal order
        fiber_mesh.faces = fiber_mesh.faces[:, [0, 2, 1]]
        fiber_mesh.export(str(filename), file_type='glb')
    
    #################################
    # --- DTI Fiber Tracking end ---
    #################################

    #################################
    # --- MRV ---
    #################################

    def region_growing_3d(self, image, seeds_mask, intensity_threshold):
        """
        一个简单的 3D 区域生长算法实现。
        """

        segmented_mask = np.zeros_like(image, dtype=bool)
        visited_mask = np.zeros_like(image, dtype=bool)
        seed_points = np.argwhere(seeds_mask)
        q = deque()
        for seed in seed_points:
            q.append(tuple(seed))
            visited_mask[tuple(seed)] = True
            segmented_mask[tuple(seed)] = True
        neighbors = [
            (0, 0, 1), (0, 0, -1),
            (0, 1, 0), (0, -1, 0),
            (1, 0, 0), (-1, 0, 0)
        ]
        while q:
            z, y, x = q.popleft()
            for dz, dy, dx in neighbors:
                nz, ny, nx = z + dz, y + dy, x + dx
                if 0 <= nz < image.shape[0] and 0 <= ny < image.shape[1] and 0 <= nx < image.shape[2]:
                    if not visited_mask[nz, ny, nx]:
                        visited_mask[nz, ny, nx] = True
                        if image[nz, ny, nx] >= intensity_threshold:
                            segmented_mask[nz, ny, nx] = True
                            q.append((nz, ny, nx))
        return segmented_mask

    def _process_mrv(self):
        """处理模式8：静脉血管"""

        output_path = str(self.config.MRV_FRANGI_CACHE_FILE) # 过程文件，存放在temp目录下，生成一次后可反复使用
        # 处理MRV数据
        mrv_img = nib.load(self.config.MRV_FILE)
        nii_array = mrv_img.get_fdata()
        affine_mrv = mrv_img.affine  # MRV仿射矩阵
        new_affine = affine_mrv
        if (not os.path.exists(output_path)):
            # Hessian
            sigmas = range(self.config.MRV_FRANGI_SIGMAS_START,self.config.MRV_FRANGI_SIGMAS_END,self.config.MRV_FRANGI_SIGMAS_STEP)
            volume = frangi(nii_array, sigmas=sigmas, black_ridges=False)
            volume = volume * 1000  # frangi 后的数据值偏小
            # 保存过程文件
            filtered_nii_image = nib.Nifti1Image(volume, affine_mrv, header=mrv_img.header)
            nib.save(filtered_nii_image, output_path)
            print("已输出 frangi 处理结果")
        else:
            # 读取frangi提取的中心线
            filtered_nii_image = nib.load(output_path)
            volume = filtered_nii_image.get_fdata()
        
        # MODIFICATION START: 采用分层区域生长策略        
        # --- 关键参数定义 (集中存放，便于调试) ---
        # 针对粗血管的高置信度参数
        STRONG_SEED_PERCENTILE = self.config.MRV_STRONG_SEED_PERCENTILE
        STRONG_GROW_TOLERANCE = self.config.MRV_STRONG_GROW_TOLERANCE  # 生长阈值容差 (原始灰度值的百分比)
        # 针对细血管的低置信度参数
        WEAK_SEED_PERCENTILE = self.config.MRV_WEAK_SEED_PERCENTILE  # 显著降低百分位数，以包含细血管的响应
        WEAK_GROW_TOLERANCE = self.config.MRV_WEAK_GROW_TOLERANCE  # 对细血管使用更宽松的生长容差
        # 后处理参数
        POST_PROCESS_MIN_SIZE = self.config.MRV_POST_PROCESS_MIN_SIZE  # 减小 min_size，避免误删细长血管 

        # --- 第一遍：分割粗大、信号强的血管 ---
        print("\n--- 开始第一遍：分割强信号血管 ---")
        strong_seed_threshold = np.percentile(volume[volume > 0], STRONG_SEED_PERCENTILE)
        strong_seeds_mask = volume > strong_seed_threshold
        print(f"强种子阈值 (Frangi > {strong_seed_threshold:.4f}), 生成 {np.sum(strong_seeds_mask)} 个种子")
        strong_seed_intensities = nii_array[strong_seeds_mask]
        if len(strong_seed_intensities) == 0:
            print("警告：在高阈值下没有找到任何强信号种子！")
            segmentation_strong = np.zeros_like(nii_array, dtype=bool)
        else:
            strong_growing_threshold = np.min(strong_seed_intensities) * STRONG_GROW_TOLERANCE
            print(f"强生长阈值 (原始图像灰度 > {strong_growing_threshold:.2f})")
            segmentation_strong = self.region_growing_3d(nii_array, strong_seeds_mask, strong_growing_threshold)
        print(f"第一遍完成，分割出 {np.sum(segmentation_strong)} 个体素。")

        # --- 第二遍：分割细小、信号弱的血管 ---
        print("\n--- 开始第二遍：分割弱信号血管 ---")
        weak_seed_threshold = np.percentile(volume[volume > 0], WEAK_SEED_PERCENTILE)
        weak_seeds_mask_all = volume > weak_seed_threshold

        # 关键步骤：只从未被分割的区域中寻找新的种子点
        weak_seeds_mask_new = weak_seeds_mask_all & ~segmentation_strong
        print(f"弱种子阈值 (Frangi > {weak_seed_threshold:.4f}), 额外生成 {np.sum(weak_seeds_mask_new)} 个新种子")
        weak_seed_intensities = nii_array[weak_seeds_mask_new]
        if len(weak_seed_intensities) == 0:
            print("没有找到额外的新种子，跳过第二遍。")
            segmentation_weak = np.zeros_like(nii_array, dtype=bool)
        else:
            weak_growing_threshold = np.min(weak_seed_intensities) * WEAK_GROW_TOLERANCE
            print(f"弱生长阈值 (原始图像灰度 > {weak_growing_threshold:.2f})")
            segmentation_weak = self.region_growing_3d(nii_array, weak_seeds_mask_new, weak_growing_threshold)
        print(f"第二遍完成，额外分割出 {np.sum(segmentation_weak)} 个体素。")

        # --- 合并与后处理 ---
        print("\n--- 合并与后处理 ---")
        final_segmentation = segmentation_strong | segmentation_weak
        print(f"开始移除小于 {POST_PROCESS_MIN_SIZE} 体素的微小区域...")
        segmentation_cleaned = remove_small_objects(final_segmentation, min_size=POST_PROCESS_MIN_SIZE)
        print("开始填充内部孔洞...")
        segmentation_filled = ndimage.binary_fill_holes(segmentation_cleaned)

        nii_thr = segmentation_filled > 0.03  # 0.03是在Slicer中调整后得到的结果，需要根据实际情况调整
        nii_thr = nii_thr.astype(np.uint8)
        cleaned_volume = remove_small_objects(nii_thr.astype(bool), min_size=self.config.MIN_OBJECT_SIZE)
        if not cleaned_volume.any():
            print("No valid volume remains after cleaning for vessels. Skipping.")
            return
        
        verts, faces, _, _ = measure.marching_cubes(cleaned_volume, level=self.config.MARCHING_CUBES_LEVEL)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        smoothed_mesh = trimesh.smoothing.filter_humphrey(mesh)
        t1_original_affine = self.t1_img.affine  # T1仿射矩阵

        # MRA空间 -> T1空间 (配准)
        trans = np.linalg.inv(t1_original_affine).dot(new_affine)
        smoothed_mesh.vertices = nib.affines.apply_affine(trans, smoothed_mesh.vertices)
        # T1空间 -> 最终空间
        smoothed_mesh.vertices = nib.affines.apply_affine(self.affine, smoothed_mesh.vertices)
        smoothed_mesh.apply_scale(1 / 1000)
        filename = self.config.output_path / "vessel_vein.glb"
        vedo_mesh = Mesh([smoothed_mesh.vertices, smoothed_mesh.faces])
        decimated_mesh = vedo_mesh.decimate(fraction=self.config.MESH_DECIMATION_FRACTION)

        # 将 vedo 减面后的结果转换回 Trimesh 对象以便导出
        final_mesh = trimesh.Trimesh(vertices=decimated_mesh.points, faces=decimated_mesh.cells)
        BrainMeshProcessor._apply_material_from_mtl_static(final_mesh, filename, self.config)
        final_mesh.faces = final_mesh.faces[:, [0, 2, 1]]
        final_mesh.export(str(filename), file_type='glb')
        print(f"Successfully processed and exported: {filename.name}")
    
    #################################
    # --- MRV end ---
    #################################

    #################################
    # --- ventricle ---
    #################################

    def _process_ventricle(self):
        """处理模式9：脑室"""
        nii_array_ori = nib.load(self.config.SYNTHSEG_ROBUST_FILE).get_fdata()
        t1_array = nib.load(self.config.T1_FILE).get_fdata()
        ## SynthSeg 的分割结果是 1分辨率
        #  eg_T1 的分割结果是 0.5分辨率
        # 读取目标图像和参考图像
        synthseg_shape = nii_array_ori.shape
        t1_shape = t1_array.shape
        zoom_factors = tuple(np.array(t1_shape) / np.array(synthseg_shape))
        nii_array = zoom(nii_array_ori, zoom_factors, order=0)  # upscale 后的affine矩阵与 eg_T1 一致, 原本synthseg结果是 1mm, affine与 eg_T1一致
        ventricle = [4, 5, 14, 15, 43, 44]
        volume = np.zeros_like(nii_array, dtype=np.uint8)
        volume[np.isin(nii_array, ventricle)] = 1
        # 移除过小的对象体积，防止生成无效网格
        cleaned_volume = volume.astype(bool)  # _generate_and_export_mesh_synthseg有remove操作
        if not cleaned_volume.any():
            print("ROI region is empty after cleaning. Skipping.")
            return
        filename = self.config.output_path / "ventricle.glb"
        self._generate_and_export_mesh_synthseg(
            cleaned_volume,
            filename,
            iterations=200,  # 使用更精细的优化参数
            alpha=0.01,
            beta=0.3,
            min_size=200
        )
    
    #################################
    # --- ventricle end ---
    #################################

    #################################
    # --- multiROI ---
    #################################

    def _process_roimutilayer(self):
        """处理模式10：multi-ROI（多层区域）"""

        nii_array = nib.load(self.config.MULTIROI_FILE).get_fdata()
        nii_1 = np.zeros_like(nii_array, dtype=np.uint8)
        nii_1[nii_array == 1] = 1
        nii_2 = np.zeros_like(nii_array, dtype=np.uint8)
        nii_2[nii_array == 2] = 2
        nii_4 = np.zeros_like(nii_array, dtype=np.uint8)
        nii_4[nii_array == 4] = 4
        roi_files = [nii_1, nii_2, nii_4,]

        # 逐一加载并生成导出的OBJ文件
        for idx, cleaned_volume in enumerate(roi_files, start=1):
            if not cleaned_volume.any():
                print(f"No valid volume remains after cleaning for Multilayer file {idx}. Skipping.")
                continue
            # 网格生成并导出
            filename = self.config.output_path / f"ROI{idx}.glb"
            self._generate_and_export_mesh_roi(
                cleaned_volume,
                filename,
                iterations=25,
                lamb=1,
            )
    
    #################################
    # --- multiROI end ---
    #################################

    #################################
    # --- fiber tracking region ---
    #################################
    def _create_gwi_atlas(self, dk_atlas_path, wm_mask_path, output_path, dilation_iterations=2):
        """
        Create a gray-white interface atlas from DK atlas and WM mask.
        """
        print("--- Creating gray-white interface (GWI) atlas ---")

        dk_atlas_path = Path(dk_atlas_path)
        wm_mask_path = Path(wm_mask_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Load DK atlas as reference
        print(f"1. Loading DK atlas: {dk_atlas_path}")
        dk_img = nib.load(str(dk_atlas_path))
        dk_data = dk_img.get_fdata().astype(int)
        dk_affine = dk_img.affine
        dk_header = dk_img.header

        # 2. Load WM mask and resample if needed
        print(f"2. Loading WM mask: {wm_mask_path}")
        wm_img_orig = nib.load(str(wm_mask_path))

        if dk_img.shape != wm_img_orig.shape:
            print(
                f"   [Warning] Shape mismatch. DK: {dk_img.shape}, WM: {wm_img_orig.shape}."
            )
            print("   -> Resampling WM mask to DK atlas space...")
            wm_img_resampled = image.resample_to_img(
                wm_img_orig, dk_img, interpolation="nearest"
            )
            wm_data = wm_img_resampled.get_fdata()
            print(f"   -> Resampling done. New WM shape: {wm_data.shape}")
        else:
            wm_data = wm_img_orig.get_fdata()

        wm_data = (wm_data > 0).astype(np.uint8)

        # 3. Build interface atlas
        interface_atlas_data = np.zeros_like(dk_data, dtype=np.int32)
        assigned_voxels_mask = np.zeros_like(dk_data, dtype=bool)

        all_labels = np.unique(dk_data)
        cortical_labels = [label for label in all_labels if label > 99]

        print(
            f"3. Found {len(cortical_labels)} cortical labels. "
            f"Dilation iterations: {dilation_iterations}"
        )

        for i, label in enumerate(cortical_labels):
            print(f"   - Processing label {label} ({i + 1}/{len(cortical_labels)})...", end="\r")

            roi_mask = (dk_data == label)
            dilated_roi_mask = binary_dilation(roi_mask, iterations=dilation_iterations)
            potential_interface = dilated_roi_mask & (wm_data > 0)
            final_interface = potential_interface & ~assigned_voxels_mask

            interface_atlas_data[final_interface] = label
            assigned_voxels_mask[final_interface] = True

        print("\n   ...all labels processed.")

        # 4. Save
        print(f"4. Saving GWI atlas to: {output_path}")
        output_img = nib.Nifti1Image(interface_atlas_data, dk_affine, dk_header)
        nib.save(output_img, str(output_path))

        num_interface_voxels = np.sum(interface_atlas_data > 0)
        print(f"--- Done. Generated {num_interface_voxels} interface voxels. ---")

        return output_path

    def _ensure_gwi_atlas(self, force_rebuild=False):
        """
        Ensure the GWI atlas exists. Create it if missing or if force_rebuild=True.
        """
        gwi_path = Path(self.config.GWI_ATLAS_FILE)

        if force_rebuild or (not gwi_path.exists()):
            print("GWI atlas not found, generating automatically...")
            self._create_gwi_atlas(
                dk_atlas_path=self.config.DK_FILE,
                wm_mask_path=self.config.MASK_FILE,
                output_path=gwi_path,
                dilation_iterations=self.config.GWI_DILATION_ITERATIONS,
            )

        return gwi_path

    def _process_fiber_tracking_region_synthseg_Interface(self):
        """
        处理模式11：基于脑区的纤维束追踪（使用灰质-白质接口 GWI）。
        提取并保存连接任意两个DK脑区的所有纤维束。
        """

        print("--- 开始处理：基于脑区的纤维束追踪 (GWI策略) ---")
        # === 步骤 1: 数据准备 ===
        print("1. 加载DTI数据和脑图谱...")
        dti_data, dti_affine, dti_img = load_nifti(self.config.DTI_FILE, return_img=True)
        # [GWI修改] 加载预处理好的 GWI 图谱，而不是原始的DK图谱
        print("   - 加载预先生成的灰质-白质接口（GWI）图谱...")
        # 这个GWI图谱应该是在T1空间下的，和原始DK图谱空间一致
        gwi_atlas_path = self._ensure_gwi_atlas(force_rebuild=self.config.FORCE_REBUILD_GWI)
        gwi_atlas_img = nib.load(str(gwi_atlas_path))
        # [GWI修改] 将 GWI 图谱重采样到DTI空间
        # 后续所有操作都基于这个在DTI空间中的GWI图谱
        print("   - 重采样GWI图谱以匹配DTI空间...")
        GWI_resampled_img = image.resample_to_img(gwi_atlas_img, dti_img, interpolation='nearest')
        GWI_data = GWI_resampled_img.get_fdata().astype(int)
        inv_GWI_affine = np.linalg.inv(GWI_resampled_img.affine)
        # 加载大脑掩码，这部分逻辑不变
        _, __, mask_img = load_nifti(self.config.MASK_FILE, return_img=True)
        mask_resampled_img = image.resample_to_img(mask_img, dti_img, interpolation='nearest')
        mask = mask_resampled_img.get_fdata()
        mask[mask >= 0.5] = 1
        mask[mask < 0.5] = 0
        # === 步骤 2: 生成全脑纤维束 (在体素空间中) ===
        # 这整个部分的代码完全不作修改 !!!
        print("2. 执行全脑纤维束追踪 (在体素空间中)...")
        bvals, bvecs = read_bvals_bvecs(str(self.config.DTI_BVALS_FILE), str(self.config.DTI_BVECS_FILE))
        gtab = gradient_table(bvals=bvals, bvecs=bvecs)
        response, _ = auto_response_ssst(gtab, dti_data, roi_radii=self.config.FIBER_AUTO_RESPONSE_ROI_RADII,fa_thr=self.config.FIBER_AUTO_RESPONSE_FA_THR)
        csd_model = ConstrainedSphericalDeconvModel(gtab, response, sh_order_max=6)
        csd_fit = csd_model.fit(dti_data, mask=mask)
        gfa_threshold = self.config.FIBER_REGION_GFA_THRESHOLD
        stop_threshold = self.config.FIBER_REGION_STOP_THRESHOLD
        csa_model = CsaOdfModel(gtab, sh_order_max=6)
        gfa = csa_model.fit(dti_data, mask=mask).gfa
        stopping_criterion = ThresholdStoppingCriterion(gfa, stop_threshold)
        seed_mask = (gfa > gfa_threshold)
        seeds = utils.seeds_from_mask(seed_mask, np.eye(4), density=self.config.FIBER_REGION_SEED_DENSITY)
        detmax_dg = DeterministicMaximumDirectionGetter.from_shcoeff(csd_fit.shm_coeff, max_angle=self.config.FIBER_REGION_MAX_ANGLE, sphere=default_sphere)
        streamline_generator = LocalTracking(detmax_dg, stopping_criterion, seeds, np.eye(4), step_size=self.config.FIBER_REGION_STEP_SIZE)
        streamlines = Streamlines(streamline_generator)
        print(f"   - 全脑追踪完成，共生成 {len(streamlines)} 条纤维束。")
        # === 步骤 3: 筛选并分组连接不同脑区的纤维束 (使用GWI图谱) ===
        print("3. 筛选并分组连接不同脑区的纤维束 (使用GWI图谱)...")
        connections = {}
        for sl in streamlines:
            start_point_vox_dti = sl[0]
            end_point_vox_dti = sl[-1]
            # [GWI修改] 坐标转换逻辑不变，但目标图谱变了
            start_point_world = nib.affines.apply_affine(dti_affine, start_point_vox_dti)
            end_point_world = nib.affines.apply_affine(dti_affine, end_point_vox_dti)
            # [GWI修改] 将世界坐标转换为 GWI 图谱的体素坐标
            start_point_vox_GWI = nib.affines.apply_affine(inv_GWI_affine, start_point_world).astype(int)
            end_point_vox_GWI = nib.affines.apply_affine(inv_GWI_affine, end_point_world).astype(int)
            dims = GWI_data.shape
            if not (0 <= start_point_vox_GWI[0] < dims[0] and 0 <= start_point_vox_GWI[1] < dims[1] and 0 <=
                    start_point_vox_GWI[2] < dims[2] and \
                    0 <= end_point_vox_GWI[0] < dims[0] and 0 <= end_point_vox_GWI[1] < dims[1] and 0 <=
                    end_point_vox_GWI[2] < dims[2]):
                continue
            # [GWI修改] 从GWI图谱数据中获取标签
            # 因为GWI图谱只包含我们关心的接口区域，所以这里的标签都是有效的
            label_start = GWI_data[tuple(start_point_vox_GWI)]
            label_end = GWI_data[tuple(end_point_vox_GWI)]
            # 这里的判断条件可以简化，因为GWI图谱中已经不包含=0或<100的无关标签
            if label_start != 0 and label_end != 0 and label_start != label_end:
                connection_key = tuple(sorted((label_start, label_end)))
                if connection_key not in connections:
                    connections[connection_key] = []
                connections[connection_key].append(sl)
        if not connections:
            print("--- 未找到任何连接不同GWI脑区的纤维束。处理结束。 ---")
            return
        print(f"   - 筛选完成，共找到 {len(connections)} 组不同的脑区连接。")
        # === 步骤 4: 为每个连接生成并导出GLB模型 ===
        # 这部分代码逻辑完全不变，因为它的输入已经是筛选好的纤维束组
        print("4. 正在为每个连接生成3D模型并导出...")
        radius = self.config.FIBER_REGION_RADIUS
        sections = self.config.FIBER_REGION_SECTIONS
        # 确保self.t1_img定义了正确的affine
        trans = np.linalg.inv(self.t1_img.affine).dot(dti_affine)
        for (label1, label2), sl_group in connections.items():
            name1 = self.DK_names.get(label1, f"ROI_{label1}")
            name2 = self.DK_names.get(label2, f"ROI_{label2}")
            output_filename = f"{name1}-{name2}.glb"
            output_path = self.config.output_path / output_filename
            if len(sl_group) < self.config.FIBER_REGION_MIN_STREAMLINES: continue
            print(f"   - 正在处理连接: {name1} <-> {name2} ({len(sl_group)}条纤维)...")

            # ... 后续的 trimesh 模型生成和导出代码完全不变 ...
            bundle_mesh_list = []
            for streamline in sl_group:
                for i in range(1, len(streamline)):
                    segment_mesh = trimesh.creation.cylinder(radius=radius, sections=sections, segment=streamline[i - 1:i + 1])
                    primary_direction = streamline[i] - streamline[i - 1]
                    primary_direction /= np.linalg.norm(primary_direction)
                    color = np.abs(primary_direction * 255).astype(np.uint8)
                    color = np.append(color, 255)
                    segment_mesh.visual.face_colors = color
                    bundle_mesh_list.append(segment_mesh)
            if not bundle_mesh_list:
                continue
            fiber_bundle_mesh = trimesh.util.concatenate(bundle_mesh_list)
            fiber_bundle_mesh.vertices = nib.affines.apply_affine(trans, fiber_bundle_mesh.vertices)
            fiber_bundle_mesh.vertices = nib.affines.apply_affine(self.affine, fiber_bundle_mesh.vertices)
            fiber_bundle_mesh.apply_scale(1 / 1000)
            fiber_bundle_mesh.faces = fiber_bundle_mesh.faces[:, [0, 2, 1]]
            fiber_bundle_mesh.export(str(output_path), file_type='glb')
            print(f"     => 成功导出到: {output_path}")
        print("\n--- 所有脑区连接的纤维束处理完毕！ ---")
    
    #################################
    # --- fiber tracking region end ---
    #################################

    #################################
    # --- tissues ---
    #################################

    def _process_tissues(self):
        """
        处理模式12: 重建皮层下脑组织结构。
        """

        # 定义要提取的结构及其对应的label值
        regions_to_process = {
            'caudate': [11, 50],  # 左、右尾状核
            'putamen': [12, 51],  # 左、右壳核
            'pallidum': [13, 52],  # 左、右苍白球
            'hippocampus': [17, 53],  # 左、右海马
            'amygdala': [18, 54],  # 左、右杏仁核
            'accumbens': [26, 58],  # 左、右伏隔核
            'cerebellum_cortex': [8, 47], #小脑皮层
            'cerebellum_wm': [7, 46] #小脑白质
        }
        nii_array = nib.load(self.config.SYNTHSEG_ROBUST_FILE).get_fdata()

        # SynthSeg的结果分辨率可能与T1不一致，需要重采样以对齐
        # 注意: _process_ventricle 中也有类似逻辑，这里为了独立性和清晰性再次实现
        t1_shape = self.t1_img.shape
        synthseg_shape = nii_array.shape
        if t1_shape != synthseg_shape:
            print(f"Resampling SynthSeg data from {synthseg_shape} to T1 shape {t1_shape}...")
            zoom_factors = tuple(np.array(t1_shape) / np.array(synthseg_shape))
            # 使用最近邻插值(order=0)，以保持label的整数值
            nii_array = zoom(nii_array, zoom_factors, order=0)

        # 为每个定义的结构生成网格
        for region_name, labels in regions_to_process.items():
            print(f"Processing region: {region_name} (labels: {labels})")
            # 创建一个只包含当前结构label的二值体积
            volume = np.zeros_like(nii_array, dtype=np.uint8)
            volume[np.isin(nii_array, labels)] = 1
            # 定义输出文件名
            filename = self.config.output_path / f"{region_name}.glb"
            cleaned_volume = volume.astype(bool)
            if not cleaned_volume.any():
                print("region is empty after cleaning. Skipping.")
                return
            self._generate_and_export_mesh_synthseg(
                cleaned_volume,
                filename,
                iterations=200,  # 使用更精细的优化参数
                alpha=0.01,
                beta=0.3,
                min_size=800
            )
    
    #################################
    # --- tissues end ---
    #################################

    #################################
    # --- DKI Fiber Tracking ---
    #################################

    def _process_fiber_tracking_Multi(self):
        """处理模式13：DKI序列的纤维追踪 - 使用多室模型"""
        
        from dipy.reconst.dki import DiffusionKurtosisModel
        from dipy.reconst.mcsd import MultiShellDeconvModel, multi_shell_fiber_response
        from dipy.reconst.mcsd import auto_response_msmt
        from dipy.data import get_sphere
        
        # 加载DKI数据
        dki_data, affine, dki_img = load_nifti(self.config.DKI_FILE, return_img=True)
        _, __, mask_img = load_nifti(self.config.MASK_FILE, return_img=True)
        # 重采样mask到DKI图像空间
        mask_img_rs = image.resample_to_img(mask_img, dki_img, interpolation='nearest', copy_header=True)
        mask = mask_img_rs.get_fdata()
        mask[mask >= 0.5] = 1
        mask[mask < 0.5] = 0
        # 读取多b值的bvals和bvecs
        bvals, bvecs = read_bvals_bvecs(str(self.config.DKI_BVALS_FILE), str(self.config.DKI_BVECS_FILE))
        gtab = gradient_table(bvals=bvals, bvecs=bvecs)
        # 验证多shell数据
        unique_bvals = np.unique(bvals)
        print(f"检测到的b值: {unique_bvals}")
        if len(unique_bvals) < 3:
            raise ValueError("DKI多室模型至少需要3个不同的b值")
        # --- DKI模型拟合 (用于获取组织特性) ---
        dki_model = DiffusionKurtosisModel(gtab)
        dki_fit = dki_model.fit(dki_data, mask=mask)
        # 计算DKI参数
        FA = dki_fit.fa
        MD = dki_fit.md
        MK = dki_fit.mk(0, 3)
        # 保存DKI参数
        self._save_dki_parameters(FA, MD, MK, None, None, affine, dki_img)
        # --- 多室模型 (Multi-Shell Multi-Tissue CSD) ---
        # 方法1: 使用auto_response_msmt自动计算多组织response
        try:
            response_wm, response_gm, response_csf = auto_response_msmt(gtab, dki_data, roi_radii=10)
            print("使用auto_response_msmt成功计算多组织response")
            # 创建多室CSD模型
            mcsd_model = MultiShellDeconvModel(gtab, response=[response_wm, response_gm, response_csf])
            mcsd_fit = mcsd_model.fit(dki_data, mask=mask)
            # 获取白质的FOD (Fiber Orientation Distribution)
            fod_coeff = mcsd_fit.shm_coeff[..., 0]  # 第一个组织类型通常是白质
        except Exception as e:
            print(f"auto_response_msmt失败: {e}")
            print("使用备选方法: 基于FA的多shell response")
            # 方法2: 手动设置多shell response
            response_wm = multi_shell_fiber_response(gtab, dki_data, mask, fa_thr=0.7)
            # 简化的多shell模型，只考虑白质
            from dipy.reconst.csdeconv import ConstrainedSphericalDeconvModel
            mcsd_model = ConstrainedSphericalDeconvModel(gtab, response_wm)
            mcsd_fit = mcsd_model.fit(dki_data, mask=mask)
            fod_coeff = mcsd_fit.shm_coeff
        # --- 或者使用DKI的ODF信息 ---
        # 这是另一种方法，直接使用DKI拟合的结果
        sphere = get_sphere('repulsion724')
        # 从DKI拟合结果计算ODF
        try:
            dki_odf = dki_fit.odf(sphere)
            # 使用DKI ODF进行方向获取
            from dipy.direction import peaks_from_model
            peaks = peaks_from_model(dki_model, dki_data, sphere,
                                     relative_peak_threshold=0.5,
                                     min_separation_angle=25,
                                     mask=mask)
            # 使用peaks进行纤维追踪
            from dipy.tracking.stopping_criterion import ThresholdStoppingCriterion
            from dipy.tracking.local_tracking import LocalTracking
            from dipy.direction import PeaksAndMetricsDirectionGetter
            # 使用DKI的FA作为stopping criterion
            fa_threshold = 0.15
            stopping_criterion = ThresholdStoppingCriterion(FA, fa_threshold)
            # 使用DKI peaks进行方向获取
            direction_getter = PeaksAndMetricsDirectionGetter.from_peaks(peaks)
            print("使用DKI ODF方法进行纤维追踪")
        except Exception as e:
            print(f"DKI ODF方法失败: {e}")
            print("回退到多室CSD方法")
            # 使用多室CSD结果
            from dipy.direction import DeterministicMaximumDirectionGetter
            direction_getter = DeterministicMaximumDirectionGetter.from_shcoeff(
                fod_coeff, max_angle=30., sphere=default_sphere)
            fa_threshold = 0.15
            stopping_criterion = ThresholdStoppingCriterion(FA, fa_threshold)

        # --- 种子点生成 ---
        gfa_threshold = 0.2
        step = 8
        # 使用FA和MK的组合条件
        seed_mask = np.zeros_like(FA)
        seed_condition = (FA > gfa_threshold) & (MK > 0) & (MK < 3)
        seed_mask[seed_condition] = 1
        seeds = utils.seeds_from_mask(seed_mask, np.eye(4), density=1)
        seeds = seeds[::step, :]
        # --- 纤维追踪 ---
        streamline_generator = LocalTracking(direction_getter, stopping_criterion, seeds, np.eye(4), step_size=0.5)
        streamlines = Streamlines(streamline_generator)
        print(f"生成了 {len(streamlines)} 条纤维束")
        # 过滤streamlines
        streamlines = self._filter_streamlines(streamlines)
        # --- 创建3D网格 (与之前相同) ---
        mesh_list = []
        radius = 0.1
        sections = 3
        transparent = int(1.0 * 255)
        for streamline in streamlines:
            for i in range(1, len(streamline)):
                tmp = trimesh.creation.cylinder(radius=radius,
                                                sections=sections,
                                                segment=streamline[i - 1:i + 1])
                primary_direction = streamline[i] - streamline[i - 1]
                primary_direction /= np.linalg.norm(primary_direction)
                color = np.abs(primary_direction * 255)
                color = color.astype(np.uint8)
                color = np.array(list(color) + [transparent])
                tmp.visual.face_colors = color
                mesh_list.append(tmp)
        # --- 导出 ---
        fiber_mesh = trimesh.util.concatenate(mesh_list)
        del mesh_list
        trans = np.linalg.inv(self.t1_img.affine).dot(affine)
        fiber_mesh.vertices = nib.affines.apply_affine(trans, fiber_mesh.vertices)
        fiber_mesh.vertices = nib.affines.apply_affine(self.affine, fiber_mesh.vertices)
        fiber_mesh.apply_scale(1 / 1000)
        filename = self.config.output_path / f"DKI_MultiShell_Fiber_{gfa_threshold}_{step}_{fa_threshold}.glb"
        fiber_mesh.faces = fiber_mesh.faces[:, [0, 2, 1]]
        fiber_mesh.export(str(filename), file_type='glb')
    
    def _save_dki_parameters(self, FA, MD, MK, AK, RK, affine, ref_img):
        """保存DKI参数图像"""
        output_dir = self.config.output_path / "dki_parameters"
        output_dir.mkdir(exist_ok=True)
        parameters = {
            'fa': FA,
            'md': MD,
            'mk': MK,
            'ak': AK,
            'rk': RK
        }
        for name, data in parameters.items():
            if data is not None:
                img = nib.Nifti1Image(data, affine, header=ref_img.header)
                nib.save(img, output_dir / f"dki_{name}.nii")

    def _filter_streamlines(self, streamlines):
        """纤维束过滤"""
        from dipy.tracking.utils import length

        min_length = 10
        max_length = 200
        filtered_streamlines = []
        for streamline in streamlines:
            stream_length = length(streamline)
            if min_length <= stream_length <= max_length:
                filtered_streamlines.append(streamline)
        print(f"过滤前: {len(streamlines)} 条纤维")
        print(f"过滤后: {len(filtered_streamlines)} 条纤维")
        return Streamlines(filtered_streamlines)

    #################################
    # --- DKI Fiber Tracking end ---
    #################################
    
    #################################
    # --- 通用函数 ---
    #################################

    def _run_multiprocess(self, tasks, data_payload, worker_func):
        """通用多进程执行器"""
        print(f"Starting multiprocessing with {self.config.NUM_PROCESSES} workers for {len(tasks)} tasks.")
        if self.manager is None:
            self.manager = mp.Manager()
        self.unprocessed_items = self.manager.list(list(self.unprocessed_items))
        if "unprocessed_items" in data_payload:
            data_payload["unprocessed_items"] = self.unprocessed_items
        with mp.Pool(self.config.NUM_PROCESSES, initializer=worker_init, initargs=(data_payload,)) as pool:
            pool.map(worker_func, tasks)

    @staticmethod
    def _hex_to_rgb(hex_value):
        # 去除十六进制颜色值中的'#'符号
        hex_value = hex_value.lstrip('#')
        # 从十六进制字符串中提取红、绿、蓝通道的值
        red = int(hex_value[0:2], 16)
        green = int(hex_value[2:4], 16)
        blue = int(hex_value[4:6], 16)
        # 返回RGB值
        return red, green, blue

    @staticmethod
    def _apply_material_from_mtl_static(mesh: trimesh.Trimesh, base_filename: Path, config: Config):
        """
        解析颜色并应用到Trimesh对象。
        """
        material_name = base_filename.stem
        # 顶点色 直接设置的是面的颜色
        if material_name == 'ventricle':
            color = (32, 232, 252)
        elif material_name == 'vessel_vein':
            color = (20, 40, 252)
        elif material_name == 'vessel':
            color = (179, 29, 29)
        elif material_name == 'w1':
            color = (245, 245, 220)
        elif material_name == 'w2':
            color = (121, 120, 114)
        else:
            # color = BrainMeshProcessor._hex_to_rgb(CSS_colors[hash(material_name) % len(CSS_colors)])  # DK
            color = BrainMeshProcessor._hex_to_rgb(DK_COLORS[material_name])  # DK脑区功能分区颜色
        material = trimesh.visual.material.PBRMaterial(
            name= material_name,
            baseColorFactor=color,
            metallicFactor=0.1,
            roughnessFactor=0.8
        )
        mesh.visual = trimesh.visual.TextureVisuals(material=material)

    @staticmethod
    def _worker_by_lookup(key):
        """多进程 Worker：根据字典查找处理"""

        labels = shared_data["lookup_dict"][key]
        volume = np.zeros_like(shared_data["nii_array"], dtype=np.uint8)
        volume[np.isin(shared_data["nii_array"], labels)] = 1
        filename = shared_data["output_path"] / (key + ".glb")
        BrainMeshProcessor._generate_and_export_mesh_static(volume, filename, key)

    @staticmethod
    def _generate_and_export_mesh_static(volume, filename, item_id_for_log):
        """
        Multi-thread
        each worker for MarchingCubes and export
        """

        # 移除小体积对象
        volume_bool = volume.astype(bool)
        if not (item_id_for_log in [1001, 1002, 1006, 1021, 1026, 1019, 1016, 1032, 1033, 1034, 1010, 2010, 2001, 2016, 2002, 2017, 2019, 2018, 2006, 2021, 2026, 2032, 2033,2034]):  # synthseg中过小的部分，为了保证移除错误的部分
            cleaned_volume = remove_small_objects(volume_bool, min_size=Config.MIN_OBJECT_SIZE)
        else:
            cleaned_volume = volume_bool

        if not cleaned_volume.any():
            print(f"Item {item_id_for_log} removed completely after cleaning. Skipping.")
            shared_data["unprocessed_items"].append(item_id_for_log)
            return
        # try:
        # Marching Cubes
        verts, faces, _, _ = measure.marching_cubes(cleaned_volume, level=Config.MARCHING_CUBES_LEVEL)
        # 平滑
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        smoothed_mesh = trimesh.smoothing.filter_laplacian(mesh, iterations=Config.SMOOTHING_ITERATIONS, lamb=Config.SMOOTHING_LAMBDA)
        # 仿射变换
        smoothed_mesh.vertices = nib.affines.apply_affine(shared_data["affine"], smoothed_mesh.vertices)
        smoothed_mesh.apply_scale(1 / 1000)  # mm -> m
        # vedo 减面并导出 (高效)
        vedo_mesh = Mesh([smoothed_mesh.vertices, smoothed_mesh.faces])
        decimated_mesh = vedo_mesh.decimate(fraction=Config.MESH_DECIMATION_FRACTION)
        # 将 vedo 减面后的结果转换回 Trimesh 对象以便导出
        final_mesh = trimesh.Trimesh(
            vertices=decimated_mesh.points,
            faces=decimated_mesh.cells
        )
        # --- APPLY MATERIAL BEFORE EXPORT ---
        # Get config from shared data payload
        config = shared_data.get("config")
        if config:
            BrainMeshProcessor._apply_material_from_mtl_static(final_mesh, filename, config)
        else:
            print(f"Warning: Config not found in shared data for item {item_id_for_log}. Cannot apply material.")
        # fix affine normal order
        final_mesh.faces = final_mesh.faces[:, [0, 2, 1]]
        final_mesh.export(str(filename), file_type='glb')
        print(f"Successfully processed and exported: {filename.name}")

    def _generate_and_export_mesh(self, volume, filename, **kwargs):
        """
        Signal thread
        mesh generation and export
        """
        
        # 合并默认参数和模式特定参数
        params = {
            'iterations': self.config.SMOOTHING_ITERATIONS,
            'lamb': self.config.SMOOTHING_LAMBDA,
            'decimation': self.config.MESH_DECIMATION_FRACTION,
            'min_size': self.config.MIN_OBJECT_SIZE
        }
        params.update(kwargs)
        volume_bool = volume.astype(bool)
        cleaned_volume = remove_small_objects(volume_bool, min_size=params['min_size'])
        if not cleaned_volume.any():
            print(f"Volume for {filename.name} is empty after cleaning. Skipping.")
            return
        verts, faces, _, _ = measure.marching_cubes(cleaned_volume, level=self.config.MARCHING_CUBES_LEVEL)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        smoothed_mesh = trimesh.smoothing.filter_laplacian(mesh, iterations=params['iterations'], lamb=params['lamb'])
        smoothed_mesh.vertices = nib.affines.apply_affine(self.affine, smoothed_mesh.vertices)
        smoothed_mesh.apply_scale(1 / 1000)
        vedo_mesh = Mesh([smoothed_mesh.vertices, smoothed_mesh.faces])
        decimated_mesh = vedo_mesh.decimate(fraction=params['decimation'])
        # 将 vedo 减面后的结果转换回 Trimesh 对象以便导出
        final_mesh = trimesh.Trimesh(
            vertices=decimated_mesh.points,
            faces=decimated_mesh.cells
        )
        BrainMeshProcessor._apply_material_from_mtl_static(final_mesh, filename, self.config)
        # fix affine normal order
        final_mesh.faces = final_mesh.faces[:, [0, 2, 1]]
        final_mesh.export(str(filename), file_type='glb')
        print(f"Successfully processed and exported: {filename.name}")

    def _generate_and_export_mesh_roi(self, volume, filename, **kwargs):
        """
        Signal thread
        mesh generation and export
        """

        # 合并默认参数和模式特定参数
        params = {
            'iterations': self.config.SMOOTHING_ITERATIONS,
            'lamb': self.config.SMOOTHING_LAMBDA,
            'decimation': self.config.MESH_DECIMATION_FRACTION,
            'min_size': self.config.MIN_OBJECT_SIZE
        }
        params.update(kwargs)
        cleaned_volume = volume
        if not cleaned_volume.any():
            print(f"Volume for {filename.name} is empty after cleaning. Skipping.")
            return
        verts, faces, _, _ = measure.marching_cubes(cleaned_volume, level=self.config.MARCHING_CUBES_LEVEL)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        smoothed_mesh = trimesh.smoothing.filter_laplacian(mesh, iterations=params['iterations'], lamb=params['lamb'])
        smoothed_mesh.vertices = nib.affines.apply_affine(self.affine, smoothed_mesh.vertices)
        smoothed_mesh.apply_scale(1 / 1000)
        vedo_mesh = Mesh([smoothed_mesh.vertices, smoothed_mesh.faces])
        decimated_mesh = vedo_mesh.decimate(fraction=params['decimation'])
        # 将 vedo 减面后的结果转换回 Trimesh 对象以便导出
        final_mesh = trimesh.Trimesh(
            vertices=decimated_mesh.points,
            faces=decimated_mesh.cells
        )
        BrainMeshProcessor._apply_material_from_mtl_static(final_mesh, filename, self.config)
        # fix affine normal order
        final_mesh.faces = final_mesh.faces[:, [0, 2, 1]]
        final_mesh.export(str(filename), file_type='glb')
        print(f"Successfully processed and exported: {filename.name}")

    def _generate_and_export_mesh_synthseg(self, volume, filename, **kwargs):
        """
        SynthSeg need resample
        mesh generation and export
        """

        # 合并默认参数和模式特定参数
        params = {
            'iterations': self.config.SMOOTHING_ITERATIONS,
            'lamb': self.config.SMOOTHING_LAMBDA,
            'decimation': self.config.MESH_DECIMATION_FRACTION,
            'min_size': self.config.MIN_OBJECT_SIZE
        }
        params.update(kwargs)
        volume_bool = volume.astype(bool)
        cleaned_volume = remove_small_objects(volume_bool, min_size=params['min_size'])
        if not cleaned_volume.any():
            print(f"Volume for {filename.name} is empty after cleaning. Skipping.")
            return
        verts, faces, _, _ = measure.marching_cubes(cleaned_volume, level=self.config.MARCHING_CUBES_LEVEL)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        smoothed_mesh = trimesh.smoothing.filter_humphrey(mesh, iterations=params['iterations'], alpha=params['alpha'],beta=params['beta'])
        smoothed_mesh.vertices = nib.affines.apply_affine(self.affine, smoothed_mesh.vertices)
        smoothed_mesh.apply_scale(1 / 1000)
        vedo_mesh = Mesh([smoothed_mesh.vertices, smoothed_mesh.faces])
        decimated_mesh = vedo_mesh
        # 将 vedo 减面后的结果转换回 Trimesh 对象以便导出
        final_mesh = trimesh.Trimesh(
            vertices=decimated_mesh.points,
            faces=decimated_mesh.cells
        )
        BrainMeshProcessor._apply_material_from_mtl_static(final_mesh, filename, self.config)
        # fix affine normal order
        final_mesh.faces = final_mesh.faces[:, [0, 2, 1]]
        final_mesh.export(str(filename), file_type='glb')
        print(f"Successfully processed and exported: {filename.name}")


#################################
# --- 主程序入口 ---
#################################
def parse_args():
    parser = argparse.ArgumentParser(
        description="Brain mesh generation pipeline with command-line configuration."
    )

    parser.add_argument(
        "--mode",
        type=str,
        required=True,
        choices=[m.name.lower() for m in ProcessMode],
        help="Processing mode, e.g. individual_regions, fiber_tracking_region",
    )

    parser.add_argument("--dcm2niix-exe", type=str, default=None)
    parser.add_argument("--dcmtk-dcmdjpeg-exe", type=str, default=None)
    parser.add_argument("--dicom-decompress-dcmtk", action="store_true")
    parser.add_argument("--dicom-decompress-dir", type=str, default=None)
    parser.add_argument("--dicom-only-dti", action="store_true")
    parser.add_argument("--docker-exe", type=str, default=None)
    parser.add_argument("--synthseg-docker-image", type=str, default="pwesp/synthseg:py38")
    parser.add_argument("--synthseg-threads", type=int, default=None)
    parser.add_argument("--dicom-dir", type=str, default=None)
    parser.add_argument("--dicom-temp-dir", type=str, default=None)
    parser.add_argument("--dicom-t1-source", type=str, default=None)
    parser.add_argument("--dicom-mra-source", type=str, default=None)
    parser.add_argument("--dicom-mrv-source", type=str, default=None)
    parser.add_argument("--dicom-dti-source", type=str, default=None)

    parser.add_argument("--dicom-t1-keywords", nargs="*", default=None)
    parser.add_argument("--dicom-mra-keywords", nargs="*", default=None)
    parser.add_argument("--dicom-mrv-keywords", nargs="*", default=None)
    parser.add_argument("--dicom-dti-keywords", nargs="*", default=None)

    parser.add_argument("--base-data-dir", type=str, default=None)
    parser.add_argument("--patient-data-dir", type=str, default=None)
    parser.add_argument("--synthseg-data-dir", type=str, default=None)
    parser.add_argument("--spm-dir", type=str, default=None)
    parser.add_argument("--spm-script-dir", type=str, default=None)
    parser.add_argument("--spm-backend", type=str, default="auto", choices=["auto", "compiled_exe", "spm_standalone", "matlab_cli", "matlab_engine"])
    parser.add_argument("--matlab-exe", type=str, default=None)
    parser.add_argument("--mcr-home", type=str, default=None)
    parser.add_argument("--spm-standalone-exe", type=str, default=None)
    parser.add_argument("--spm-compiled-exe", type=str, default=None)
    parser.add_argument("--template-dir", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=None)

    parser.add_argument("--t1-file", type=str, default=None)
    parser.add_argument("--dk-file", type=str, default=None)
    parser.add_argument("--mra-file", type=str, default=None)
    parser.add_argument("--mrv-file", type=str, default=None)
    parser.add_argument("--roi-file", type=str, default=None)
    parser.add_argument("--multiroi-file", type=str, default=None)
    parser.add_argument("--dti-file", type=str, default=None)
    parser.add_argument("--dti-bvals-file", type=str, default=None)
    parser.add_argument("--dti-bvecs-file", type=str, default=None)
    parser.add_argument("--mask-file", type=str, default=None)
    parser.add_argument("--gwi-atlas-file", type=str, default=None)
    parser.add_argument("--dki-file", type=str, default=None)
    parser.add_argument("--dki-bvals-file", type=str, default=None)
    parser.add_argument("--dki-bvecs-file", type=str, default=None)
    parser.add_argument("--synthseg-robust-file", type=str, default=None)
    parser.add_argument("--dk-name-file", type=str, default=None)
    parser.add_argument("--lobe-map-file", type=str, default=None)

    parser.add_argument("--smoothing-iterations", type=int, default=20)
    parser.add_argument("--smoothing-lambda", type=float, default=0.7)
    parser.add_argument("--marching-cubes-level", type=float, default=0.7)
    parser.add_argument("--min-object-size", type=int, default=14500)
    parser.add_argument("--mesh-decimation-fraction", type=float, default=0.08)
    parser.add_argument("--num-processes", type=int, default=8)

    parser.add_argument("--gwi-dilation-iterations", type=int, default=2)
    parser.add_argument(
        "--force-rebuild-gwi",
        action="store_true",
        help="Force rebuild GWI atlas even if it already exists.",
    )

    parser.add_argument("--vessel-threshold", type=int, default=400)
    parser.add_argument("--vessel-min-object-size", type=int, default=1000)
    parser.add_argument("--vessel-decimation-fraction", type=float, default=0.5)

    parser.add_argument("--mrv-frangi-cache-file", type=str, default=None)
    parser.add_argument("--mrv-frangi-sigmas-start", type=int, default=1)
    parser.add_argument("--mrv-frangi-sigmas-end", type=int, default=12)
    parser.add_argument("--mrv-frangi-sigmas-step", type=int, default=1)
    parser.add_argument("--mrv-strong-seed-percentile", type=float, default=99.9)
    parser.add_argument("--mrv-strong-grow-tolerance", type=float, default=0.95)
    parser.add_argument("--mrv-weak-seed-percentile", type=float, default=99.8)
    parser.add_argument("--mrv-weak-grow-tolerance", type=float, default=0.85)
    parser.add_argument("--mrv-post-process-min-size", type=int, default=1000)

    parser.add_argument("--fiber-gfa-cache-file", type=str, default=None)
    parser.add_argument("--fiber-gfa-threshold", type=float, default=0.25)
    parser.add_argument("--fiber-step", type=int, default=10)
    parser.add_argument("--fiber-stop-threshold", type=float, default=0.2)
    parser.add_argument("--fiber-step-size", type=float, default=0.5)
    parser.add_argument("--fiber-radius", type=float, default=0.1)
    parser.add_argument("--fiber-sections", type=int, default=3)
    parser.add_argument("--fiber-max-angle", type=float, default=45.0)
    parser.add_argument("--fiber-seed-density", type=int, default=1)
    parser.add_argument("--fiber-auto-response-roi-radii", type=int, default=10)
    parser.add_argument("--fiber-auto-response-fa-thr", type=float, default=0.7)

    parser.add_argument("--fiber-region-gfa-threshold", type=float, default=0.25)
    parser.add_argument("--fiber-region-stop-threshold", type=float, default=0.01)
    parser.add_argument("--fiber-region-step-size", type=float, default=0.5)
    parser.add_argument("--fiber-region-radius", type=float, default=0.1)
    parser.add_argument("--fiber-region-sections", type=int, default=3)
    parser.add_argument("--fiber-region-max-angle", type=float, default=45.0)
    parser.add_argument("--fiber-region-seed-density", type=int, default=1)
    parser.add_argument("--fiber-region-min-streamlines", type=int, default=10)

    return parser.parse_args()


def mode_from_string(mode_str: str) -> ProcessMode:
    return ProcessMode[mode_str.upper()]


if __name__ == '__main__':
    args = parse_args()
    selected_mode = mode_from_string(args.mode)

    config = Config(
        mode=selected_mode,
        dcm2niix_exe=args.dcm2niix_exe,
        dcmtk_dcmdjpeg_exe=args.dcmtk_dcmdjpeg_exe,
        dicom_decompress_dcmtk=args.dicom_decompress_dcmtk,
        dicom_decompress_dir=args.dicom_decompress_dir,
        dicom_only_dti=args.dicom_only_dti,
        docker_exe=args.docker_exe,
        synthseg_docker_image=args.synthseg_docker_image,
        synthseg_threads=args.synthseg_threads,
        dicom_dir=args.dicom_dir,
        dicom_temp_dir=args.dicom_temp_dir,
        dicom_t1_source=args.dicom_t1_source,
        dicom_mra_source=args.dicom_mra_source,
        dicom_mrv_source=args.dicom_mrv_source,
        dicom_dti_source=args.dicom_dti_source,
        dicom_t1_keywords=args.dicom_t1_keywords,
        dicom_mra_keywords=args.dicom_mra_keywords,
        dicom_mrv_keywords=args.dicom_mrv_keywords,
        dicom_dti_keywords=args.dicom_dti_keywords,
        base_data_dir=args.base_data_dir,
        patient_data_dir=args.patient_data_dir,
        synthseg_data_dir=args.synthseg_data_dir,
        spm_dir=args.spm_dir,
        spm_script_dir=args.spm_script_dir,
        spm_backend=args.spm_backend,
        matlab_exe=args.matlab_exe,
        mcr_home=args.mcr_home,
        spm_standalone_exe=args.spm_standalone_exe,
        spm_compiled_exe=args.spm_compiled_exe,
        template_dir=args.template_dir,
        output_dir=args.output_dir,
        t1_file=args.t1_file,
        dk_file=args.dk_file,
        mra_file=args.mra_file,
        mrv_file=args.mrv_file,
        roi_file=args.roi_file,
        multiroi_file=args.multiroi_file,
        dti_file=args.dti_file,
        dti_bvals_file=args.dti_bvals_file,
        dti_bvecs_file=args.dti_bvecs_file,
        mask_file=args.mask_file,
        gwi_atlas_file=args.gwi_atlas_file,
        dki_file=args.dki_file,
        dki_bvals_file=args.dki_bvals_file,
        dki_bvecs_file=args.dki_bvecs_file,
        synthseg_robust_file=args.synthseg_robust_file,
        dk_name_file=args.dk_name_file,
        lobe_map_file=args.lobe_map_file,
        smoothing_iterations=args.smoothing_iterations,
        smoothing_lambda=args.smoothing_lambda,
        marching_cubes_level=args.marching_cubes_level,
        min_object_size=args.min_object_size,
        mesh_decimation_fraction=args.mesh_decimation_fraction,
        num_processes=args.num_processes,
        gwi_dilation_iterations=args.gwi_dilation_iterations,
        vessel_threshold=args.vessel_threshold,
        vessel_min_object_size=args.vessel_min_object_size,
        vessel_decimation_fraction=args.vessel_decimation_fraction,
        mrv_frangi_cache_file=args.mrv_frangi_cache_file,
        mrv_frangi_sigmas_start=args.mrv_frangi_sigmas_start,
        mrv_frangi_sigmas_end=args.mrv_frangi_sigmas_end,
        mrv_frangi_sigmas_step=args.mrv_frangi_sigmas_step,
        mrv_strong_seed_percentile=args.mrv_strong_seed_percentile,
        mrv_strong_grow_tolerance=args.mrv_strong_grow_tolerance,
        mrv_weak_seed_percentile=args.mrv_weak_seed_percentile,
        mrv_weak_grow_tolerance=args.mrv_weak_grow_tolerance,
        mrv_post_process_min_size=args.mrv_post_process_min_size,
        fiber_gfa_cache_file=args.fiber_gfa_cache_file,
        fiber_gfa_threshold=args.fiber_gfa_threshold,
        fiber_step=args.fiber_step,
        fiber_stop_threshold=args.fiber_stop_threshold,
        fiber_step_size=args.fiber_step_size,
        fiber_radius=args.fiber_radius,
        fiber_sections=args.fiber_sections,
        fiber_max_angle=args.fiber_max_angle,
        fiber_seed_density=args.fiber_seed_density,
        fiber_auto_response_roi_radii=args.fiber_auto_response_roi_radii,
        fiber_auto_response_fa_thr=args.fiber_auto_response_fa_thr,
        fiber_region_gfa_threshold=args.fiber_region_gfa_threshold,
        fiber_region_stop_threshold=args.fiber_region_stop_threshold,
        fiber_region_step_size=args.fiber_region_step_size,
        fiber_region_radius=args.fiber_region_radius,
        fiber_region_sections=args.fiber_region_sections,
        fiber_region_max_angle=args.fiber_region_max_angle,
        fiber_region_seed_density=args.fiber_region_seed_density,
        fiber_region_min_streamlines=args.fiber_region_min_streamlines,
    )
    config.FORCE_REBUILD_GWI = args.force_rebuild_gwi

    processor = BrainMeshProcessor(config)

    if args.force_rebuild_gwi and selected_mode == ProcessMode.FIBER_TRACKING_REGION:
        if Path(config.GWI_ATLAS_FILE).exists():
            Path(config.GWI_ATLAS_FILE).unlink()

    processor.run()
