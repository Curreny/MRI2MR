import os
import numpy as np
import nibabel as nib
import trimesh


# --- 核心辅助函数 (无需修改) ---

def compose_affine_matrix_noRotation(translation, scale):
    """构造不含旋转的仿射矩阵"""
    affine = np.eye(4)
    affine[:3, :3] = np.diag(scale)
    affine[:3, 3] = translation
    return affine


def decompose_affine_matrix(affine):
    """分解仿射矩阵，得到平移、旋转、缩放"""
    scale = np.linalg.norm(affine[:3, :3], axis=0)
    # 防止除以零
    non_zero_scale = np.where(scale == 0, 1, scale)
    rotation = affine[:3, :3] / non_zero_scale
    translation = affine[:3, 3]
    return translation, rotation, scale


def calculate_centered_affine(ref_img):
    """
    从参考影像的 affine 计算居中后 affine，以适配VR/Unity中的显示。
    """
    shape = ref_img.shape[:3]
    center = np.array(shape) / 2.0

    ref_affine = ref_img.affine
    translation, rotation, scale = decompose_affine_matrix(ref_affine)

    # 注意：此处只使用平移和缩放来计算中心偏移，忽略旋转，
    # 这与您原始脚本行为一致，以确保在不同朝向的影像上表现稳定。
    tmp_affine_no_rotation = compose_affine_matrix_noRotation(translation, scale)
    offset = nib.affines.apply_affine(tmp_affine_no_rotation, center)

    centered_affine = compose_affine_matrix_noRotation(translation - offset, scale)
    return centered_affine


# --- 主处理函数 (优化了变量名) ---

def transform_slicer_models(slicer_model_dir, reference_img_path, output_dir):
    """
    使用参考影像的仿射矩阵，将Slicer导出的模型重对齐到Unity坐标系。

    Args:
        slicer_model_dir (str): 包含.glb模型的输入文件夹。
        reference_img_path (str): '解码'模型坐标所需要的参考影像文件路径。
                                  这必须是Slicer中生成模型时所依据的那个主影像
                                  或分割文件本身（如果它自成几何参考）。
        output_dir (str): 保存对齐后模型的输出文件夹。
    """
    print(f"--- Processing batch for {os.path.basename(slicer_model_dir)} ---")
    print(f"Using reference image: {reference_img_path}")

    # 读取参考影像信息
    try:
        ref_img = nib.load(reference_img_path)
    except FileNotFoundError:
        print(f"❌ ERROR: Reference image not found at '{reference_img_path}'")
        return

    ref_affine = ref_img.affine
    centered_affine = calculate_centered_affine(ref_img)

    os.makedirs(output_dir, exist_ok=True)
    model_files = [f for f in os.listdir(slicer_model_dir)
                   if f.lower().endswith(('.glb'))]

    if not model_files:
        print("No .glb models found in the directory.")
        return

    for fname in model_files:
        in_path = os.path.join(slicer_model_dir, fname)
        mesh = trimesh.load(in_path, force='mesh')

        print(f'→ Processing {fname}, vertices count: {len(mesh.vertices)}')

        # 1. 世界坐标 → Voxel坐标
        # 使用参考影像的仿射矩阵的逆矩阵，将模型的RAS世界坐标转换回其原始的IJK体素坐标。
        # 这是最关键的一步，reference_img_path必须正确！
        voxel_vertices = nib.affines.apply_affine(np.linalg.inv(ref_affine), mesh.vertices)

        # 2. Voxel坐标 → Unity居中坐标
        # 将体素坐标应用新的、经过中心化的仿射变换，得到在Unity中可以居中显示的坐标。
        aligned_vertices = nib.affines.apply_affine(centered_affine, voxel_vertices)

        # 3. 单位转换 (mm → m)
        # Unity通常使用米作为单位，而医学影像模型是毫米，因此缩放1000倍。
        aligned_vertices /= 1000.0

        mesh.vertices[:] = aligned_vertices

        out_path = os.path.join(output_dir, fname)
        mesh.export(out_path)
        print(f'✅ Saved aligned model: {out_path}')

    print("--- Batch processing complete. ---\n")


# --- 程序入口和参数配置 ---

if __name__ == '__main__':
    # ==============================================================================
    #  案例一: '成功'的案例 (模型来自 GLBSegments_Decimate_Use)
    #  这个案例之所以成功，是因为模型导出的参考几何就是 'example_T1.nii'。
    # ==============================================================================

    # # --- 取消注释以运行此案例 ---
    # print("Running Case 1: Successful Alignment")
    # slicer_model_dir_1 = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\GLBSegments_Decimate_Use'
    # reference_img_path_1 = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\patient_input\example_T1.nii'
    # output_dir_1 = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\GLBSegments_Decimate_Use_Realign'
    # transform_slicer_models(slicer_model_dir_1, reference_img_path_1, output_dir_1)

    # ==============================================================================
    #  案例二: '失败'的案例 (模型来自 SlicerSTLtoGLB) - 【修正版】
    #  这个案例之前失败，是因为它错误地使用了'eg_T1.nii'作为参考。
    #  要修正它，必须提供正确的参考文件。
    # ==============================================================================

    # --- 取消注释以运行此案例 ---
    print("Running Case 2: Corrected Alignment")

    slicer_model_dir_2 = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\SlicerRegionModel\SlicerSTLtoGLB'  # 输入文件夹
    reference_img_path_2 = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\temp\synthseg_results\eg_T1_robust_parc.nii'  # 原始影像
    output_dir_2 = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\SlicerRegionModel\SlicerGLBAxisRealign'

    transform_slicer_models(slicer_model_dir_2, reference_img_path_2, output_dir_2)

