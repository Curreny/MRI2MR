import nibabel as nib
import numpy as np
import os
import struct


def convert_cbf_nii_to_bin(nii_filepath, output_filepath):
    try:
        if not os.path.exists(nii_filepath):
            print(f"❌ 错误: 找不到输入文件: {nii_filepath}")
            return

        print(f"📂 正在读取: {nii_filepath}")
        img = nib.load(nii_filepath)
        data = img.get_fdata(dtype=np.float32)

        # [新增 1] 获取物理维度信息
        shape = data.shape  # (x, y, z) 数量，例如 (80, 80, 20)
        zooms = img.header.get_zooms()[:3]  # (x, y, z) 单个格子大小，例如 (3.0, 3.0, 6.0) mm

        # 计算物理总尺寸 (Field of View)
        # 例如: 80*3=240mm, 20*6=120mm
        fov = (shape[0] * zooms[0], shape[1] * zooms[1], shape[2] * zooms[2])

        print(f"📏 像素维度 (Grid): {shape}")
        print(f"📐 物理体素 (Voxel): {zooms} mm")
        print(f"📦 物理总尺寸 (FOV): {fov} mm")

        # 数据清洗
        data = np.nan_to_num(data, nan=0.0)
        data[data < 0] = 0.0

        # 展平
        flat_data = data.flatten(order='F')

        # 写入
        output_dir = os.path.dirname(output_filepath)
        if output_dir and not os.path.exists(output_dir): os.makedirs(output_dir)

        print(f"💾 正在写入: {output_filepath}")
        with open(output_filepath, 'wb') as f:
            # [核心修改 2] 文件头写入更多信息
            # 格式: 3个int (维度) + 3个float (物理尺寸FOV)
            # 'iiifff' = int, int, int, float, float, float
            header = struct.pack('iiifff',
                                 shape[0], shape[1], shape[2],  # Grid Dimensions
                                 fov[0], fov[1], fov[2])  # Physical Size (mm)
            f.write(header)

            flat_data.tofile(f)

        print("\n✅ 转换成功！物理尺寸已写入文件头。")

    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    # 你的文件路径 (保持不变)
    input_nii = r"D:\Tang_DATA\Docker_Project\ASL\dcmniix_NIfTI_Output\output_cbf_fixed_Registration\CBF_HighRes_Aligned.nii.gz"
    output_bin = r"D:\UnityProject\ComputeShaderTest\Assets\StreamingAssets\unity_final_cbf_fixed_RealignT1_xyz_size.bin"
    convert_cbf_nii_to_bin(input_nii, output_bin)