# ==============================================================================
# 脚本 1 (已修改): generate_gwi_atlas.py (生成灰质-白质接口图谱)
#
# 版本 2: 增加了自动重采样功能，以处理输入文件维度不匹配的问题。
# ==============================================================================
import numpy as np
import nibabel as nib
from scipy.ndimage import binary_dilation
import os
from nilearn import image  # 引入nilearn用于重采样


def create_gwi_atlas(dk_atlas_path, wm_mask_path, output_path, dilation_iterations=2):
    """
    创建一个灰质-白质接口（GWI）图谱。

    该函数加载一个皮层图谱（如DK图谱）和一个白质掩码。如果两者的空间不一致，
    它会自动将白质掩码重采样到DK图谱的空间。然后对图谱中的每个皮层区域
    进行膨胀，与白质掩码取交集，最终生成一个新的、只包含接口区域且
    互不重叠的图谱。

    参数:
    - dk_atlas_path (str): 原始DK图谱文件的路径 (作为参考空间)。
    - wm_mask_path (str): 白质掩码（WM Mask）文件的路径。
    - output_path (str): 输出的GWI图谱文件保存路径。
    - dilation_iterations (int): 膨胀操作的迭代次数，控制接口的厚度（建议1或2）。
    """
    print("--- 开始创建灰质-白质接口（GWI）图谱 ---")

    # 1. 加载DK图谱作为参考标准
    print(f"1. 加载DK图谱 (参考空间): {dk_atlas_path}")
    dk_img = nib.load(dk_atlas_path)
    dk_data = dk_img.get_fdata().astype(int)
    # GWI图谱将继承DK图谱的affine和header
    dk_affine = dk_img.affine
    dk_header = dk_img.header

    # 2. 加载白质掩码并处理空间对齐问题
    print(f"2. 加载白质掩码: {wm_mask_path}")
    wm_img_orig = nib.load(wm_mask_path)

    # 检查维度是否匹配
    if dk_img.shape != wm_img_orig.shape:
        print(
            f"   [警告] DK图谱和白质掩码的维度不匹配! "
            f"DK: {dk_img.shape}, WM: {wm_img_orig.shape}."
        )
        print("   -> 正在将白质掩码重采样到DK图谱空间...")

        # 使用 nilearn.image.resample_to_img 进行重采样
        # target_img 是 dk_img，它定义了目标的空间（维度, affine, voxel size）
        # interpolation='nearest' 用于标签或掩码文件，避免产生0-1之间的模糊值
        wm_img_resampled = image.resample_to_img(wm_img_orig, dk_img, interpolation='nearest')

        wm_data = wm_img_resampled.get_fdata()
        print(f"   -> 重采样完成。新的WM掩码维度: {wm_data.shape}")
    else:
        print("   图谱与掩码维度匹配，无需重采样。")
        wm_data = wm_img_orig.get_fdata()

    # 二值化白质掩码
    wm_data = (wm_data > 0).astype(np.uint8)

    # 3. 初始化输出图谱和已分配体素的掩码
    interface_atlas_data = np.zeros_like(dk_data, dtype=np.int32)
    # 用于确保互斥性，记录哪些体素已经被分配给一个接口
    assigned_voxels_mask = np.zeros_like(dk_data, dtype=bool)

    # 4. 遍历所有DK脑区标签进行处理
    # 只处理皮层标签（通常 > 1000 for Freesurfer, or > 99 for your case)
    all_labels = np.unique(dk_data)
    # 根据您的代码，皮层标签 > 99
    cortical_labels = [label for label in all_labels if label > 99]

    print(f"\n3. 找到 {len(cortical_labels)} 个皮层标签进行处理。膨胀迭代次数: {dilation_iterations}")

    for i, label in enumerate(cortical_labels):
        # 简单的进度条
        print(f"   - 正在处理 Label {label} ({i + 1}/{len(cortical_labels)})...", end='\r')

        # a. 创建当前标签的二值掩码
        roi_mask = (dk_data == label)

        # b. 对该掩码进行膨胀
        dilated_roi_mask = binary_dilation(roi_mask, iterations=dilation_iterations)

        # c. 取膨胀区域与重采样后的白质掩码的交集
        potential_interface = dilated_roi_mask & (wm_data > 0)

        # d. 关键：从潜在接口中移除已经被其他标签分配的体素，确保互斥性
        final_interface = potential_interface & ~assigned_voxels_mask

        # e. 更新GWI图谱和已分配体素掩码
        interface_atlas_data[final_interface] = label
        assigned_voxels_mask[final_interface] = True

    print("\n   ...所有标签处理完毕。")

    # 5. 保存结果
    print(f"\n4. GWI图谱创建完成，正在保存到: {output_path}")
    output_img = nib.Nifti1Image(interface_atlas_data, dk_affine, dk_header)
    nib.save(output_img, output_path)

    num_interface_voxels = np.sum(interface_atlas_data > 0)
    print(f"--- 处理完毕！共生成 {num_interface_voxels} 个接口体素。---\n")


if __name__ == "__main__":
    # --- 使用示例 ---
    # 请将下面的路径替换为您自己的文件路径

    # 您的DK图谱文件路径 (SynthSeg的结果) -> 这个将作为目标参考空间
    DK_ATLAS_FILE = r"F:/Desktop/BrainVRReadingRoom/BrainVRReadingRoom/Data_Zhu/SynthSeg_result/T1_synthseg.nii"

    # 您的白质掩码文件路径 (SPM c2的结果) -> 这个将被重采样
    WM_MASK_FILE = r"F:/Desktop/BrainVRReadingRoom/BrainVRReadingRoom/Data_Zhu/patient_input/c2T1.nii"

    # 定义输出文件的路径
    OUTPUT_GWI_ATLAS_FILE = r"F:/Desktop/BrainVRReadingRoom/BrainVRReadingRoom/Data_Zhu/temp/interface_atlas.nii.gz"

    # 如果输出路径的文件夹不存在，则创建它
    output_dir = os.path.dirname(OUTPUT_GWI_ATLAS_FILE)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 运行函数
    create_gwi_atlas(
        dk_atlas_path=DK_ATLAS_FILE,
        wm_mask_path=WM_MASK_FILE,
        output_path=OUTPUT_GWI_ATLAS_FILE,
        dilation_iterations=2  # 膨胀2个体素通常是个不错的选择
    )

