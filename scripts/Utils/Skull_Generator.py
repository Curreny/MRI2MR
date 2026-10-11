import nibabel as nib
import numpy as np
from scipy.ndimage import label, median_filter
from skimage import measure
import trimesh
from skimage.morphology import remove_small_objects
from vedo import Mesh
import Utils.util
from nilearn import image  # <--- 新增导入，用于重采样


# --- 从 Main_627.py 移植过来的辅助函数 (此函数无需修改) ---
def _calculate_centered_affine(nifti_img):
    t1_affine = nifti_img.affine

    translation, t1_rotation, scale = Utils.util.decompose_affine_matrix(t1_affine)
    tmp_affine = Utils.util.compose_affine_matrix_noRotation(translation, scale)
    center = np.array(nifti_img.shape) // 2
    offset = nib.affines.apply_affine(tmp_affine, center)
    new_affine = Utils.util.compose_affine_matrix_noRotation(translation - offset, scale)
    affine = new_affine

    return affine


# ==============================================================================
# 核心修改部分 1: 修改函数定义，增加一个 reference_t1_file 参数
# ==============================================================================
def process_nifti_to_glb(nifti_file, reference_t1_file, output_glb_file, smoothing_iterations=35,
                         decimation_fraction=0.08):
    """
    处理一个NIfTI文件，并根据一个参考NIfTI文件进行空间对齐，最终导出为GLB模型。

    Args:
        nifti_file (str): 输入的头骨NIfTI文件路径。
        reference_t1_file (str): 用于对齐的参考T1 NIfTI文件路径。
        output_glb_file (str): 输出的GLB文件路径。
        smoothing_iterations (int): Laplacian平滑的迭代次数。
        decimation_fraction (float): 网格减面的比例。
    """
    # 1. 加载NIfTI图像
    try:
        # ==============================================================================
        # 核心修改部分 2: 加载两个NIfTI文件
        # ==============================================================================
        print(f"Loading skull data from: {nifti_file}")
        img_skull = nib.load(nifti_file)

        print(f"Loading reference geometry from: {reference_t1_file}")
        img_reference = nib.load(reference_t1_file)

        # ==============================================================================
        # 新增步骤：在线重采样，这是最稳健的方法，确保体素网格完全对齐
        # ==============================================================================
        print("Resampling skull data to match reference space in-memory...")
        # 使用'nearest'插值，因为它适用于掩码/标签数据
        img_skull_resampled = image.resample_to_img(img_skull, img_reference, interpolation='nearest')

        # 从重采样后的图像中获取数据
        data = img_skull_resampled.get_fdata()

    except Exception as e:
        print(f"Error loading NIfTI file(s): {e}")
        return

    # --- 原有的预处理逻辑保持不变 ---
    # 注意：这里的 data 已经是重采样后、与参考T1对齐的数据了
    print("Preprocessing skull data (thresholding, largest component, etc.)...")
    data_ = np.zeros_like(data)
    data_[data > 0.38] = 1

    binary_data = data_.astype(bool)

    labeled_data, num_features = label(binary_data)
    if num_features == 0:
        print("No connected components found.")
        return
    sizes = np.bincount(labeled_data.flatten())
    largest_component_label = np.argmax(sizes[1:]) + 1
    largest_component_data = (labeled_data == largest_component_label).astype(data.dtype)

    cleaned_data = remove_small_objects(largest_component_data.astype(bool), min_size=100)

    smoothed_data = median_filter(cleaned_data.astype(float), size=10)

    # 6. Marching Cubes (表面提取)
    print("Performing Marching Cubes...")
    try:
        verts, faces, normals, _ = measure.marching_cubes(smoothed_data, level=0.5)
    except Exception as e:
        print(f"Error in marching cubes: {e}")
        return

    # 7. 创建Trimesh对象并进行平滑
    print("Smoothing mesh...")
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_normals=normals)
    mesh = trimesh.smoothing.filter_laplacian(mesh, iterations=smoothing_iterations, lamb=0.8)

    # ==============================================================================
    # 核心修改部分 3: 使用参考T1图像来计算仿射矩阵
    # ==============================================================================
    try:
        print("Calculating centered affine transform based on the REFERENCE image...")
        # 这里传入的是 img_reference，而不是 img_skull！
        centered_affine = _calculate_centered_affine(img_reference)

        print("Applying transform to mesh vertices...")
        mesh.vertices = nib.affines.apply_affine(centered_affine, mesh.vertices)

        # 9. 应用缩放 (mm -> m)
        mesh.apply_scale(1 / 1000)

        # 10. 使用Vedo进行高效的网格减面
        print(f"Decimating mesh (fraction: {decimation_fraction})...")
        vedo_mesh = Mesh([mesh.vertices, mesh.faces])
        decimated_mesh = vedo_mesh.decimate(fraction=decimation_fraction)

        # 11. 将减面后的网格转换回Trimesh对象
        final_mesh = trimesh.Trimesh(
            vertices=decimated_mesh.points,
            faces=decimated_mesh.cells
        )

        # 12. 修正因仿射变换可能导致的面顺序问题
        final_mesh.faces = final_mesh.faces[:, [0, 2, 1]]

        # 13. 导出为GLB文件
        final_mesh.export(output_glb_file, file_type='glb')
        print(f"✅ GLB file saved successfully to: {output_glb_file}")

    except Exception as e:
        print(f"An error occurred during mesh processing or export: {e}")


if __name__ == '__main__':
    # ==============================================================================
    # 核心修改部分 4: 在这里填入你的两个文件路径
    # ==============================================================================

    # 1. 你的头骨 NIfTI 文件路径
    skull_nifti_file = r"D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\patient_input\c4eg_T1.nii"

    # 2. 你的参考 T1 NIfTI 文件路径 (与 main_1013.py 中使用的一致)
    #    请确保这个路径是正确的！
    reference_t1_file = r"D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\patient_input\eg_T1.nii"

    # 3. 输出的 GLB 模型文件路径
    output_glb_file = r"D:\Tang_DATA\VRReadingroom\SPM_eg_T1\a\c4_skull_aligned.glb"

    print("--- Starting Skull Model Generation with Alignment ---")

    # 调用更新后的函数，传入三个路径
    process_nifti_to_glb(
        skull_nifti_file,
        reference_t1_file,
        output_glb_file,
        smoothing_iterations=35,
        decimation_fraction=0.01
    )
    print("--- Process Finished ---")

