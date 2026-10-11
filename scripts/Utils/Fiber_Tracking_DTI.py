

import numpy as np
import trimesh.visual.material
from scipy.ndimage import zoom
from fontTools.subset import closure_lookups

from skimage import measure
from skimage.draw import ellipsoid
import plotly.graph_objects as go
import SimpleITK as sitk
import matplotlib.cm as cm
import matplotlib.colors as mcolors
from scipy.ndimage import measurements
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
from dipy.reconst.csdeconv import (ConstrainedSphericalDeconvModel,
                                   auto_response_ssst)

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

from trimesh.visual.material import SimpleMaterial


if __name__ == '__main__':
    DTI_FILE = r"D:\Tang_DATA\HCP\103818\T1w\Diffusion\data.nii.gz"
    MASK_FILE = r"D:\Tang_DATA\HCP\103818\T1w\Diffusion\nodif_brain_mask.nii.gz"
    DTI_BVALS_FILE = r"D:\Tang_DATA\HCP\103818\T1w\Diffusion\bvals"
    DTI_BVECS_FILE = r"D:\Tang_DATA\HCP\103818\T1w\Diffusion\bvecs"
    output_path = r"D:\Tang_DATA\HCP\103818\T1w\Diffusion"


    dti_data, affine, dti_img = load_nifti(DTI_FILE, return_img=True)

    _, __, mask_img = load_nifti(MASK_FILE, return_img=True)

    # 将白质模板重采样到DTI图像。注意最邻近插值
    mask_img_rs = image.resample_to_img(mask_img, dti_img, interpolation='nearest', copy_header=True)
    mask = mask_img_rs.get_fdata()
    mask[mask >= 0.5] = 1
    mask[mask < 0.5] = 0

    # --- 纤维追踪 ---
    bvals, bvecs = read_bvals_bvecs(str(DTI_BVALS_FILE), str(DTI_BVECS_FILE))
    gtab = gradient_table(bvals=bvals, bvecs=bvecs)

    response, ratio = auto_response_ssst(gtab, dti_data, roi_radii=10, fa_thr=0.7)

    csd_model = ConstrainedSphericalDeconvModel(gtab, response, sh_order_max=6)
    csd_fit = csd_model.fit(dti_data, mask=mask)

    # tensor_fit = compute_tensor_model(dti_data, gtab)

    csa_model = CsaOdfModel(gtab, sh_order_max=6)
    csa_fit = csa_model.fit(dti_data, mask=mask)
    gfa = csa_fit.gfa
    stopping_criterion = ThresholdStoppingCriterion(gfa, .25)

    # seeds = np.array(np.where(gfa > 0.3)).T
    # seeds = [tuple(seed) for seed in seeds]

    seed_mask = np.zeros_like(gfa)
    seed_mask[gfa > 0.3] = 1

    seeds = utils.seeds_from_mask(seed_mask, np.eye(4), density=1)

    seeds = seeds[::5, :]  # 按5为间隔采样，避免纤维过多渲染压力太大

    detmax_dg = DeterministicMaximumDirectionGetter.from_shcoeff(
        csd_fit.shm_coeff, max_angle=30., sphere=default_sphere, sh_to_pmf=True)

    streamline_generator = LocalTracking(detmax_dg, stopping_criterion, seeds,
                                         np.eye(4), step_size=.5)

    streamlines = Streamlines(streamline_generator)
    # --- 绘制纤维模型 ---
    mesh_list = []

    radius = 0.1
    sections = 3

    transparent = int(1.0 * 255)

    for streamline in streamlines:
        # print(f" line points {len(streamline)}")

        for i in range(1, len(streamline)):
            # point = streamline[i]

            # 绘制单段纤维
            tmp = trimesh.creation.cylinder(radius=radius,
                                            sections=sections,
                                            segment=streamline[i - 1:i + 1])

            primary_direction = streamline[i] - streamline[i - 1]

            primary_direction /= np.linalg.norm(primary_direction)

            # 基于方向向量计算颜色 (方向向量的正值映射到RGB通道)
            color = np.abs(primary_direction * 255)
            color = color.astype(np.uint8)  # 转换为整数值
            color = np.array(list(color) + [transparent])

            # # 着色并添加  ----顶点着色
            # visual = SimpleMaterial()
            # visual.face_colors = color
            # tmp.visual = visual

            # 着色并添加  ----创建并分配PBR材质 (核心修改)
            # Trimesh 在导出GLB时会使用PBR材质系统。
            # 我们创建一个简单的PBR材质，并设置其漫反射颜色。
            material = trimesh.visual.material.PBRMaterial(
                name=f"fiber_mat_{i}",  # 给材质一个唯一的名字（可选）
                baseColorFactor=color,
                metallicFactor=0.1,  # 金属感，可以调整
                roughnessFactor=0.8  # 粗糙度，可以调整
            )

            tmp.visual = trimesh.visual.TextureVisuals(material=material)

            # tmp.visual.face_colors = color

            mesh_list.append(tmp)

    # --- export ---

    fiber_mesh = trimesh.util.concatenate(mesh_list)
    del mesh_list

    # trans = np.linalg.inv(self.t1_img.affine).dot(affine)  # 计算DTI体素空间到T1体素空间的变化
    # fiber_mesh.vertices = nib.affines.apply_affine(trans, fiber_mesh.vertices)  # 应用之
    #
    # fiber_mesh.vertices = nib.affines.apply_affine(self.affine, fiber_mesh.vertices)  # 从T1体素空间变换到volume rendering的空间
    #
    # fiber_mesh.apply_scale(1 / 1000)  # 从mm单位转换到m单位

    filename = output_path / "Fiber.glb"

    # # fix affine normal order
    # fiber_mesh.faces = fiber_mesh.faces[:, [0, 2, 1]]

    fiber_mesh.export(str(filename), file_type='glb')