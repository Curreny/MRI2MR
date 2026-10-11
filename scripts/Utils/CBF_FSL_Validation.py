import nibabel as nib
import matplotlib.pyplot as plt
import numpy as np
import os

# ================= 配置区域 =================
# 替换为你的文件名，建议使用去过颅骨的 'unity_final_cbf.nii.gz'
# file_path = r'D:\Tang_DATA\Docker_Project\ASL\dcmniix_NIfTI_Output\output_cbf\native_space\unity_final_cbf.nii.gz'
file_path = r'D:\Tang_DATA\Docker_Project\ASL\dcmniix_NIfTI_Output\output_cbf_fixed\native_space\unity_final_cbf_fixed.nii.gz'

# 选择切片方向: 'axial'(轴位/俯视), 'coronal'(冠状/正视), 'sagittal'(矢状/侧视)
view_plane = 'axial'


# ===========================================

def show_cbf_heatmap(nii_path):
    if not os.path.exists(nii_path):
        print(f"错误: 找不到文件 {nii_path}")
        return

    # 1. 加载数据
    img = nib.load(nii_path)
    data = img.get_fdata()

    # 2. 处理异常值 (可选: 去掉极端的噪点值，让对比度更好)
    # 将超过 98% 分位数的值截断，防止个别极亮噪点导致整体画面变暗
    vmax = np.percentile(data[data > 0], 99)

    # 3. 选择中间切片
    x, y, z = data.shape
    if view_plane == 'axial':
        # 轴位通常是第 3 个维度 (z)，我们需要旋转一下让它正过来
        slice_data = np.rot90(data[:, :, z // 2])
        aspect_ratio = 1.0
    elif view_plane == 'coronal':
        slice_data = np.rot90(data[:, y // 2, :])
        aspect_ratio = z / x  # 矫正长宽比
    elif view_plane == 'sagittal':
        slice_data = np.rot90(data[x // 2, :, :])
        aspect_ratio = z / y

    # 4. 设置掩模 (让背景全黑)
    # 这一步很关键：把数值为 0 的背景设为 NaN，这样 matplotlib 就会把它画成透明/黑色
    masked_data = np.ma.masked_where(slice_data < 0.1, slice_data)

    # 5. 绘图
    plt.figure(figsize=(8, 8), facecolor='black')  # 设置画布背景为黑
    ax = plt.gca()
    ax.set_facecolor('black')  # 设置绘图区背景为黑

    # 使用 'jet' 颜色映射 (蓝-绿-黄-红) 模仿你的参考图
    # vmin=0, vmax=vmax 确保颜色范围固定
    im = plt.imshow(masked_data, cmap='jet', vmin=0, vmax=vmax, aspect=aspect_ratio)

    plt.title(f"CBF Heatmap Check: {nii_path}\n(Slice: Center {view_plane})", color='white')
    plt.axis('off')  # 关掉坐标轴

    # 添加色条
    cbar = plt.colorbar(im, fraction=0.046, pad=0.04)
    cbar.ax.yaxis.set_tick_params(color='white')  # 色条刻度设为白色
    plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')  # 色条文字设为白色
    cbar.set_label('Relative CBF Intensity', color='white')

    plt.show()


if __name__ == "__main__":
    show_cbf_heatmap(file_path)