# ## 1
# # 可用于与CS脚本传递.bin数据，但是（224，224，40，210）的数据量太大，需要降采样
# ##
# # In[]
# import nibabel as nib
# import numpy as np
# import os
#
# def convert_nii_to_bin(nii_filepath, output_filepath, data_type=np.float32):
#     try:
#         # --- 1. 加载NIfTI文件 ---
#         print(f"Loading NIfTI file from: {nii_filepath}")
#         img = nib.load(nii_filepath)
#
#         # --- 2. 获取数据数组 ---
#         data = img.get_fdata(dtype=data_type)
#         print(f"Original data shape: {data.shape}")
#
#         # --- 新增步骤: 诊断数据 ---
#         print("\n--- Running Data Diagnostics ---")
#         # 检查是否存在NaN值
#         nan_count = np.isnan(data).sum()
#         if nan_count > 0:
#             print(f"WARNING: Found {nan_count} NaN values in the original data.")
#             # 打印一个NaN样本的位置
#             nan_coords = np.argwhere(np.isnan(data))
#             print(f"Example NaN coordinate (x,y,z,t): {tuple(nan_coords[0])}")
#
#             # --- 新增步骤: 清洗数据 ---
#             print("Cleaning data: Replacing all NaN values with 0.0")
#             data = np.nan_to_num(data, nan=0.0)
#             print("Data cleaning complete.")
#         else:
#             print("No NaN values found in the data. All good!")
#
#         # 打印我们关心的几个点的值，用于和C#端对比
#         print(f"Value at (0,0,0,0) in Python before saving: {data[0, 0, 0, 0]}")
#         print("--------------------------------\n")
#
#         # --- 3. 重排并保存 (这部分逻辑保持不变) ---
#         x, y, z, t = data.shape
#         data_reordered = data.transpose(2, 1, 0, 3)
#         data_reshaped = data_reordered.reshape((x * y * z, t))
#
#         print(f"Reshaped for saving: {data_reshaped.shape}")
#
#         # --- 4. 写入文件 ---
#         print(f"Writing binary data to: {output_filepath}")
#         data_reshaped.tofile(output_filepath)
#
#         print("\n--- Conversion successful! ---")
#         # ... (后续打印信息不变)
#
#     except Exception as e:
#         print(f"An error occurred: {e}")
#
#
# # --- 使用示例 (保持不变) ---
# if __name__ == "__main__":
#     nii_file = 'your_bold_data.nii.gz'
#     bin_file = 'bold_data.bin'
#
#     if not os.path.exists(nii_file):
#         # ... (创建假文件的逻辑不变)
#         pass  # 省略
#
#     # 替换为你真实的NIfTI文件路径和期望的输出路径
#     real_nii_path = r"D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\patient_input\raSub_001_FE_EPI-11_20251013003253_601.nii"
#     # 确保输出到你的Unity项目的StreamingAssets文件夹！
#     # unity_project_path = r"D:\UnityProject\ComputeShaderTest"
#     # output_bin_path = os.path.join(unity_project_path, "Assets", "StreamingAssets", "bold_data.bin")
#
#     output_bin_path = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\temp\bold_results\bold_data2.bin'
#
#
#     convert_nii_to_bin(real_nii_path, output_bin_path)
#


## 2
#  降采样版
##
# In[]
# boldExportcs.py
import nibabel as nib
import numpy as np
import os

# 确保你已经安装了 nilearn: pip install nilearn
try:
    from nilearn import image as nilearn_image
except ImportError:
    print("错误：需要 nilearn 库。请通过 'pip install nilearn' 安装。")
    exit()


def convert_nii_to_bin(nii_filepath,
                       output_filepath,
                       target_spatial_shape=(40, 40, 40),
                       target_time_points=40,
                       data_type=np.float32):
    """
    读取一个4D NIfTI文件，对其进行空间降采样和时间浓缩，然后将其数据保存为扁平的二进制文件。
    Args:
        nii_filepath (str): 输入的 .nii 或 .nii.gz 文件路径。
        output_filepath (str): 输出的二进制 .bin 文件路径。
        target_spatial_shape (tuple): 目标空间维度 (x, y, z)。
        target_time_points (int): 目标时间点数量。
        data_type (numpy.dtype): 存储数据的类型 (例如, np.float32 C#中的float)。
    """
    try:
        # --- 1. 加载NIfTI文件 ---
        print(f"步骤 1: 加载 NIfTI 文件: {nii_filepath}")
        original_img = nib.load(nii_filepath)
        # 打印原始信息
        original_data = original_img.get_fdata(dtype=np.float64)  # 使用高精度读取以减少误差
        original_affine = original_img.affine
        original_shape_spatial = original_img.shape[:3]
        print(f"原始数据形状 (x, y, z, t): {original_img.shape}")
        print("\n--- 原始仿射矩阵 ---")
        print(original_affine)
        print("--------------------")
        # --- 2. 清理数据 (处理NaN值) ---
        print("\n步骤 2: 检查并清理数据")
        nan_count = np.isnan(original_data).sum()
        if nan_count > 0:
            print(f"警告: 在原始数据中发现 {nan_count} 个 NaN 值。")
            print("清理数据: 将所有 NaN 值替换为 0.0")
            cleaned_data = np.nan_to_num(original_data, nan=0.0)
        else:
            print("数据中未发现 NaN 值，无需清理。")
            cleaned_data = original_data

        # 创建一个临时的、清理过数据的Nifti图像对象，以便nilearn处理
        cleaned_img = nib.Nifti1Image(cleaned_data, original_affine)
        # --- 3. 空间降采样 (主流方法) ---
        print(f"\n步骤 3: 空间降采样至 {target_spatial_shape}")

        # --- **核心修正部分** ---
        # 计算新的目标仿射矩阵，以匹配新的目标形状
        # 1. 复制原仿射矩阵作为基础
        new_target_affine = np.copy(original_affine)

        # 2. 计算从原始shape到目标shape的缩放因子
        #    例如, x轴的缩放是 原始x维度 / 目标x维度 (224 / 40)
        scaling_factor = np.array(original_shape_spatial) / np.array(target_spatial_shape)

        # 3. 将缩放因子应用到仿射矩阵的“缩放/旋转”部分
        #    这是通过将原仿射矩阵的3x3部分与一个对角缩放矩阵相乘来实现的
        new_target_affine[:3, :3] = original_affine[:3, :3] @ np.diag(scaling_factor)
        # --- **修正结束** ---

        # nilearn.image.resample_img 是神经影像公认的标准方法
        resampled_img = nilearn_image.resample_img(
            cleaned_img,
            target_affine=new_target_affine,  # <--- 使用我们新计算的仿射矩阵
            target_shape=target_spatial_shape,  # <--- 指定目标形状
            interpolation='linear',  # 线性插值是fMRI数据的标准选择
            copy_header=True,  # 推荐选项，用于处理 nilearn 未来版本的警告
        )
        # 获取降采样后的数据和新的仿射矩阵
        resampled_data = resampled_img.get_fdata(dtype=data_type)
        final_affine = resampled_img.affine  # 这就是您需要的新的仿射矩阵
        print(f"空间降采样后的数据形状: {resampled_data.shape}")
        print("\n--- 新的仿射矩阵 (降采样后) ---")
        # 打印您需要的新的仿射矩阵值
        print(final_affine)
        print("-----------------------------------")
        # --- 4. 时间点浓缩 (主流方法) ---
        # (这部分代码无需修改)
        print(f"\n步骤 4: 时间点浓缩至 {target_time_points} 个点")

        current_time_points = resampled_data.shape[3]

        if current_time_points % target_time_points != 0:
            block_size = current_time_points // target_time_points
            num_timepoints_to_use = target_time_points * block_size
            print(f"时间点无法整除。将从 {current_time_points} 截断至 {num_timepoints_to_use} 个点进行平均。")
            truncated_data = resampled_data[..., :num_timepoints_to_use]
        else:
            block_size = current_time_points // target_time_points
            truncated_data = resampled_data
            print(f"每 {block_size} 个时间点平均为1个点。")
        reshaped_for_averaging = truncated_data.reshape(
            target_spatial_shape + (target_time_points, block_size)
        )
        final_data = reshaped_for_averaging.mean(axis=-1)

        print(f"时间浓缩后的最终数据形状: {final_data.shape}")
        print("---------------------------------")

        # --- 5. 最终数据重排并保存为二进制文件 ---
        print("\n步骤 5: 重排数据并写入二进制文件")
        x, y, z, t = final_data.shape
        data_reordered = final_data.transpose(2, 1, 0, 3)
        data_reshaped = data_reordered.reshape((x * y * z, t))
        print(f"为存储重塑后的形状: {data_reshaped.shape}")
        print(f"总计写入数值数量: {data_reshaped.size}")
        print(f"预期文件大小: {data_reshaped.size * np.dtype(data_type).itemsize / (1024 * 1024):.2f} MB")
        # --- 6. 写入文件 ---
        print(f"写入二进制数据到: {output_filepath}")
        data_reshaped.tofile(output_filepath)
        print("\n--- 转换成功! ---")
        # ... (后续打印信息不变)
    except FileNotFoundError:
        print(f"错误: 文件 {nii_filepath} 未找到。")
    except Exception as e:
        print(f"发生错误: {e}")


# --- 使用示例 ---
if __name__ == "__main__":
    nii_file = r"/Data_Health/patient_input/raSub_001_FE_EPI-11_20251013003253_601.nii"
    bin_file = r'/Data_Health/temp/bold_results/bold_data_40x40x40x40.bin'
    if not os.path.exists(nii_file):
        print(f"错误: 输入文件 '{nii_file}' 不存在。请检查路径和文件名。")
    else:
        convert_nii_to_bin(nii_file, bin_file,
                           target_spatial_shape=(40, 40, 40),
                           target_time_points=40)