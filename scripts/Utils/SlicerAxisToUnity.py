import os
import numpy as np
import nibabel as nib
import trimesh

def compose_affine_matrix_noRotation(translation, scale):
    """构造不含旋转的仿射矩阵"""
    affine = np.eye(4)
    affine[:3, :3] = np.diag(scale)
    affine[:3, 3] = translation
    return affine

def decompose_affine_matrix(affine):
    """分解仿射矩阵，得到平移、旋转、缩放"""
    scale = np.linalg.norm(affine[:3, :3], axis=0)
    rotation = affine[:3, :3] / scale
    translation = affine[:3, 3]
    return translation, rotation, scale

def calculate_centered_affine(t1_img):
    """
    从原始影像 affine 计算居中后 affine，
    与你 VR 脚本中的 _calculate_centered_affine() 等效。
    """
    shape = t1_img.shape[:3]
    center = np.array(shape) / 2.0

    t1_affine = t1_img.affine
    translation, rotation, scale = decompose_affine_matrix(t1_affine)
    tmp_affine = compose_affine_matrix_noRotation(translation, scale)
    offset = nib.affines.apply_affine(tmp_affine, center)

    centered_affine = compose_affine_matrix_noRotation(translation - offset, scale)
    return centered_affine

def transform_slicer_models(slicer_model_dir, t1_img_path, output_dir):
    # 读取影像信息
    t1_img = nib.load(t1_img_path)
    t1_affine = t1_img.affine
    centered_affine = calculate_centered_affine(t1_img)

    os.makedirs(output_dir, exist_ok=True)
    model_files = [f for f in os.listdir(slicer_model_dir)
                   if f.lower().endswith(('.glb'))]

    for fname in model_files:
        in_path = os.path.join(slicer_model_dir, fname)
        mesh = trimesh.load(in_path, force='mesh')

        print(f'→ Processing {fname}, vertices count: {len(mesh.vertices)}')

        # 世界坐标 → voxel坐标
        voxel_vertices = nib.affines.apply_affine(np.linalg.inv(t1_affine), mesh.vertices)

        # voxel坐标 → VR居中坐标
        aligned_vertices = nib.affines.apply_affine(centered_affine, voxel_vertices)

        # 你脚本里有 mm → m 的缩放
        aligned_vertices /= 1000.0

        mesh.vertices[:] = aligned_vertices

        out_path = os.path.join(output_dir, fname)
        mesh.export(out_path)
        print(f'✅ Saved aligned model: {out_path}')

    print("All models processed.")

if __name__ == '__main__':
    # 示例参数
    # slicer_model_dir = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\GLBSegments_Decimate_Use'     # 输入文件夹
    # t1_img_path = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\patient_input\example_T1.nii'             # 原始影像
    # output_dir = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\GLBSegments_Decimate_Use_Realign'            # 输出文件夹

    # slicer_model_dir = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\SlicerRegionModel2\SlicerSTLtoGLB'  # 输入文件夹
    # t1_img_path = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\patient_input\eg_T1.nii'  # 原始影像
    # output_dir = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\SlicerRegionModel2\SlicerGLBAxisRealign'  # 输出文件夹

    # slicer_model_dir = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegionLobe\Lobes\STLTOGLB'  # 输入文件夹
    # t1_img_path = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\patient_input\example_T1.nii'  # 原始影像
    # output_dir = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegionLobe\Lobes\Axis'  # 输出文件夹

    slicer_model_dir = r'C:\Users\AiYing212106001\Desktop\Slicerregion\stltoglb'     # 输入文件夹
    t1_img_path = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\patient_input\example_T1.nii'             # 原始影像
    output_dir = r'C:\Users\AiYing212106001\Desktop\Slicerregion\axis'

    transform_slicer_models(slicer_model_dir, t1_img_path, output_dir)
