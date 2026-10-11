import os
import re
import shutil
import trimesh
from collections import defaultdict

# --- 1. 配置区域 ---

# 输入模型所在的文件夹路径
# 请根据您的实际情况修改此路径
# 例如: 'D:/DATADRIVE1/Tang_DATA/Python_Code/BrainVRReadingRoom/Data/SlicerRegionModel/SlicerGLBAxisRealign'
INPUT_DIR = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\FinalRegioMesh'

# DK Atlas 脑区定义文件
DK_REGIONS_FILE = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\template\DK_Regions.txt'

# 规则1: 脑室的标签
VENTRICLE_LABELS = {4, 5, 14, 15, 43, 44}

# 规则2: 需要合并的脑组织区域
REGIONS_TO_PROCESS = {
    'caudate': [11, 50],
    'putamen': [12, 51],
    'pallidum': [13, 52],
    'hippocampus': [17, 53],
    'amygdala': [18, 54],
    'accumbens': [26, 58],
    'cerebellum_cortex': [8, 47],
    'cerebellum_wm': [7, 46]
}


# --- 2. 辅助函数 ---

def parse_dk_regions(filepath):
    """解析 DK_Regions.txt 文件, 返回一个 {label: name} 的字典"""
    if not os.path.exists(filepath):
        print(f"错误: 找不到文件 {filepath}")
        return {}

    dk_map = {}
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                label_id, name = parts[0], parts[1]
                dk_map[int(label_id)] = name
    return dk_map


def merge_and_export_meshes(mesh_files, output_path):
    """加载多个mesh文件, 合并它们, 并导出为单个glb文件"""
    if not mesh_files:
        print(f"警告: 没有找到用于生成 {os.path.basename(output_path)} 的模型文件。")
        return

    print(f"正在合并 {len(mesh_files)} 个模型以创建 {os.path.basename(output_path)}...")

    # 使用trimesh加载所有模型
    # force='mesh' 确保即使文件包含场景图，也只加载几何体
    meshes_to_merge = [trimesh.load(f, force='mesh') for f in mesh_files]

    # 使用trimesh的工具进行合并
    combined_mesh = trimesh.util.concatenate(meshes_to_merge)

    # 导出合并后的模型
    combined_mesh.export(output_path)
    print(f"成功导出: {output_path}")


def copy_and_rename_mesh(source_path, dest_path):
    """
    加载并重新保存模型文件。这比直接复制更安全，
    可以确保输出格式是标准的glb。
    """
    try:
        print(f"正在处理: {os.path.basename(source_path)} -> {os.path.basename(dest_path)}")
        mesh = trimesh.load(source_path)
        mesh.export(dest_path)
        print(f"成功导出: {dest_path}")
    except Exception as e:
        print(f"错误: 处理文件 {source_path} 时发生错误: {e}")


# --- 3. 主逻辑 ---

def main():
    """主执行函数"""
    # 检查输入目录是否存在
    if not os.path.isdir(INPUT_DIR):
        print(f"错误: 输入目录 '{INPUT_DIR}' 不存在。请检查路径。")
        return

    # 解析DK分区文件
    dk_map = parse_dk_regions(DK_REGIONS_FILE)
    if not dk_map:
        print("警告: DK Regions 映射为空, 编号 > 99 的模型将无法处理。")

    # 定义输出目录 (在输入目录的父级)
    output_parent_dir = os.path.dirname(INPUT_DIR)
    ventricle_output_dir = os.path.join(output_parent_dir, 'ventricle')
    tissue_output_dir = os.path.join(output_parent_dir, 'tissue')
    individual_output_dir = os.path.join(output_parent_dir, 'individual_regions')

    # 创建输出目录
    os.makedirs(ventricle_output_dir, exist_ok=True)
    os.makedirs(tissue_output_dir, exist_ok=True)
    os.makedirs(individual_output_dir, exist_ok=True)

    print("输出目录已准备就绪。")

    # 用于分类文件的字典
    files_for_ventricle = []
    files_for_tissue = defaultdict(list)
    files_for_individual = {}  # {label: filepath}

    # 反向映射，用于快速查找label属于哪个tissue name
    label_to_tissue_name = {}
    for name, labels in REGIONS_TO_PROCESS.items():
        for label in labels:
            label_to_tissue_name[label] = name

    # 遍历输入目录中的所有文件
    print(f"\n开始扫描输入目录: {INPUT_DIR}")
    for filename in os.listdir(INPUT_DIR):
        # 使用正则表达式从文件名中提取编号
        match = re.search(r'_Segment_(\d+)\.glb$', filename)
        if match:
            label = int(match.group(1))
            full_path = os.path.join(INPUT_DIR, filename)

            # 根据规则进行分类
            if label in VENTRICLE_LABELS:
                files_for_ventricle.append(full_path)
            elif label > 99:
                files_for_individual[label] = full_path
            elif label in label_to_tissue_name:
                tissue_name = label_to_tissue_name[label]
                files_for_tissue[tissue_name].append(full_path)

    print("\n文件扫描和分类完成。开始处理模型...")

    # --- 处理分类好的文件 ---

    # 1. 处理脑室
    ventricle_output_path = os.path.join(ventricle_output_dir, 'ventricle.glb')
    merge_and_export_meshes(files_for_ventricle, ventricle_output_path)

    # 2. 处理特定脑组织
    for name, files in files_for_tissue.items():
        tissue_output_path = os.path.join(tissue_output_dir, f'{name}.glb')
        merge_and_export_meshes(files, tissue_output_path)

    # 3. 处理独立脑区
    for label, filepath in files_for_individual.items():
        if label in dk_map:
            new_name = f"{dk_map[label]}.glb"
            individual_output_path = os.path.join(individual_output_dir, new_name)
            copy_and_rename_mesh(filepath, individual_output_path)
        else:
            print(f"警告: 在 {DK_REGIONS_FILE} 中找不到编号为 {label} 的名称，跳过文件 {os.path.basename(filepath)}")

    print("\n所有任务处理完毕！")


if __name__ == '__main__':
    main()
