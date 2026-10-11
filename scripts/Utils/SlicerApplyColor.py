#
# ############################# 原始版 -- 有脑区颜色相同的问题
# import os
# import trimesh
# from pathlib import Path
#
# ##
# # 对 Mesh 模型加入 PBR材质和颜色， 可对 Regions， Tissue， Ventricle 模型使用
# ##
#
# # 预定义的CSS颜色列表，用于根据文件名哈希值生成颜色
# CSS_colors = [
#     "#F0F8FF", "#FAEBD7", "#00FFFF", "#7FFFD4", "#F0FFFF", "#F5F5DC", "#FFE4C4", "#000000",
#     "#FFEBCD", "#0000FF", "#8A2BE2", "#A52A2A", "#DEB887", "#5F9EA0", "#7FFF00", "#D2691E",
#     "#FF7F50", "#6495ED", "#FFF8DC", "#DC143C", "#00FFFF", "#00008B", "#008B8B", "#B8860B",
#     "#A9A9A9", "#006400", "#BDB76B", "#8B008B", "#556B2F", "#FF8C00", "#9932CC", "#8B0000",
#     "#E9967A", "#8FBC8F", "#483D8B", "#2F4F4F", "#00CED1", "#9400D3", "#FF1493", "#00BFFF",
#     "#696969", "#1E90FF", "#B22222", "#FFFAF0", "#228B22", "#FF00FF", "#DCDCDC", "#F8F8FF",
#     "#FFD700", "#DAA520", "#808080", "#008000", "#ADFF2F", "#F0FFF0", "#FF69B4", "#CD5C5C",
#     "#4B0082", "#FFFFF0", "#F0E68C", "#E6E6FA", "#FFF0F5", "#7CFC00", "#FFFACD", "#ADD8E6",
#     "#F08080", "#E0FFFF", "#FAFAD2", "#D3D3D3", "#90EE90", "#FFB6C1", "#FFA07A", "#20B2AA",
#     "#87CEFA", "#778899", "#B0C4DE", "#FFFFE0", "#00FF00", "#32CD32", "#FAF0E6", "#FF00FF",
#     "#800000", "#66CDAA", "#0000CD", "#BA55D3", "#9370DB", "#3CB371", "#7B68EE", "#00FA9A",
#     "#48D1CC", "#C71585", "#191970", "#F5FFFA", "#FFE4E1", "#FFE4B5", "#FFDEAD", "#000080",
#     "#FDF5E6", "#808000", "#6B8E23", "#FFA500", "#FF4500", "#DA70D6", "#EEE8AA", "#98FB98",
#     "#AFEEEE", "#DB7093", "#FFEFD5", "#FFDAB9", "#CD853F", "#FFC0CB", "#DDA0DD", "#B0E0E6",
#     "#800080", "#663399", "#FF0000", "#BC8F8F", "#4169E1", "#8B4513", "#FA8072", "#F4A460",
#     "#2E8B57", "#FFF5EE", "#A0522D", "#C0C0C0", "#87CEEB", "#6A5ACD", "#708090", "#FFFAFA",
#     "#00FF7F", "#4682B4", "#D2B48C", "#008080", "#D8BFD8", "#FF6347", "#40E0D0", "#EE82EE",
#     "#F5DEB3", "#FFFFFF", "#F5F5F5", "#FFFF00", "#9ACD32"
# ]
#
#
# def _hex_to_rgb_tuple(hex_color: str) -> tuple:
#     """将十六进制颜色字符串（如'#RRGGBB'）转换为RGB元组（0-255）。"""
#     hex_color = hex_color.lstrip('#')
#     return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
#
#
# def apply_pbr_material_and_color(mesh: trimesh.Trimesh, model_filename: str):
#     """
#     根据模型文件名生成PBR材质和颜色，并应用到trimesh对象。
#     此函数逻辑完全复刻自你提供的参考脚本。
#
#     Args:
#         mesh (trimesh.Trimesh): 要应用材质的Trimesh网格对象。
#         model_filename (str): 模型的文件名 (例如 'my_model.obj')。
#     """
#     # 从文件名中获取不带扩展名的基础名，作为材质名
#     material_name = Path(model_filename).stem
#
#     # --- 核心颜色确定逻辑 ---
#     # 检查是否有特定名称，如有则使用预设颜色
#     if material_name == 'ventricle':
#         color_rgb = (32, 232, 252)
#     elif material_name == 'vessel_vein':
#         color_rgb = (20, 40, 252)
#     elif material_name == 'vessel':
#         color_rgb = (179, 29, 29)
#     elif material_name == 'w1':  # 通常代表白质 White Matter
#         color_rgb = (245, 245, 220)
#     elif material_name == 'w2':  # 通常代表灰质 Gray Matter
#         color_rgb = (121, 120, 114)
#     else:
#         # 如果没有特定名称，则使用哈希值从颜色列表中选择颜色
#         hex_color = CSS_colors[hash(material_name) % len(CSS_colors)]
#         color_rgb = _hex_to_rgb_tuple(hex_color)
#
#     # 创建PBR材质
#     # baseColorFactor接受 (R, G, B) 或 (R, G, B, A) 格式的元组，值范围 0-255
#     material = trimesh.visual.material.PBRMaterial(
#         name=material_name,
#         baseColorFactor=color_rgb,  # 基础颜色
#         metallicFactor=0.1,  # 金属度 (0=非金属, 1=金属)
#         roughnessFactor=0.8,  # 粗糙度 (0=光滑, 1=粗糙)
#         # alphaMode='OPAQUE'        # GLB默认就是不透明
#     )
#
#     # 将PBR材质应用到网格对象
#     # 对于GLB导出，需要将材质包裹在TextureVisuals中
#     mesh.visual = trimesh.visual.TextureVisuals(material=material)
#     print(f"Applied material '{material_name}' with color {color_rgb} to mesh.")
#
#
# def process_models_in_folder(input_folder: str, output_folder: str):
#     """
#     加载指定输入文件夹中的所有模型，为它们应用PBR材质，并以GLB格式导出到输出文件夹。
#
#     Args:
#         input_folder (str): 包含模型文件（如.obj, .stl）的文件夹路径。
#         output_folder (str): 导出GLB文件的目标文件夹路径。
#     """
#     # 确保输出文件夹存在
#     Path(output_folder).mkdir(parents=True, exist_ok=True)
#
#     # `trimesh.load` 支持多种格式，这里列出一些常见的
#     supported_extensions = ['.glb']
#
#     for filename in os.listdir(input_folder):
#         file_path = os.path.join(input_folder, filename)
#
#         # 检查是否是文件以及是否是支持的模型格式
#         if os.path.isfile(file_path) and Path(filename).suffix.lower() in supported_extensions:
#             print(f"\n--- Processing: {filename} ---")
#             try:
#                 # 1. 加载模型，不应用任何变换
#                 # process=False 确保trimesh不会自动合并顶点或做其他修改
#                 mesh = trimesh.load(file_path, process=False)
#
#                 # 如果加载的是场景（例如包含多个模型的DAE），我们只处理第一个几何体
#                 if isinstance(mesh, trimesh.Scene):
#                     mesh = mesh.dump(concatenate=True)
#                     print("  Scene detected, concatenated into a single mesh.")
#
#                 # 2. 调用函数应用PBR材质和颜色
#                 apply_pbr_material_and_color(mesh, filename)
#
#                 # 3. 准备导出路径和文件名
#                 base_name = Path(filename).stem
#                 output_path = os.path.join(output_folder, f"{base_name}.glb")
#
#                 # 4. 以GLB格式导出
#                 # GLB会自动包含PBR材质信息
#                 mesh.export(output_path, file_type='glb')
#                 print(f"  Successfully exported to: {output_path}")
#
#             except Exception as e:
#                 print(f"  [ERROR] Failed to process {filename}: {e}")
#
#
# # --- 主程序入口 ---
# if __name__ == '__main__':
#     # ==================================================================
#     #  --- 用户配置区 ---
#     #  请在此处修改你的输入和输出文件夹路径
#     # ==================================================================
#
#     # 包含你的源模型文件（如OBJ、STL等）的文件夹
#     types = 'ventricle'
#     INPUT_MODEL_FOLDER = rf'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\FinalRegionMeshName\{types}'
#
#     # 你希望保存生成的GLB文件的文件夹
#     OUTPUT_GLB_FOLDER = rf'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\FinalRegionMeshNameMaterials\{types}'
#
#     # ==================================================================
#
#     print(f"Starting batch processing...")
#     print(f"Input Folder: {INPUT_MODEL_FOLDER}")
#     print(f"Output Folder: {OUTPUT_GLB_FOLDER}")
#
#     process_models_in_folder(INPUT_MODEL_FOLDER, OUTPUT_GLB_FOLDER)
#
#     print("\nBatch processing finished.")
#
# #########################################################################################

import os
import trimesh
from pathlib import Path
import seaborn as sns
import numpy as np
import colorsys

# --- 用户可调参数 ---
# 定义右半球颜色相对于左半球的饱和度和亮度衰减因子
# 值越小，衰减越明显。1.0代表不衰减。
RIGHT_HEMISPHERE_SATURATION_FACTOR = 0.55  # 降低25%的饱和度
RIGHT_HEMISPHERE_BRIGHTNESS_FACTOR = 0.70  # 降低10%的亮度


def _hex_to_rgb_tuple(hex_color: str) -> tuple:
    """将十六进制颜色字符串（如'#RRGGBB'）转换为RGB元组（0-255）。"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _modify_color_s_v(rgb_0_255: tuple, sat_factor: float, bright_factor: float) -> tuple:
    """
    调整RGB颜色的饱和度和亮度。
    Args:
        rgb_0_255 (tuple): 0-255范围的RGB颜色元组。
        sat_factor (float): 饱和度乘数。
        bright_factor (float): 亮度乘数。
    Returns:
        tuple: 调整后的0-255范围的RGB颜色元组。
    """
    # 1. 将RGB (0-255) 归一化到 (0-1)
    r, g, b = [x / 255.0 for x in rgb_0_255]

    # 2. 从RGB转换到HSV (色相, 饱和度, 亮度)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    # 3. 调整饱和度和亮度
    s *= sat_factor
    v *= bright_factor

    # 4. 从HSV转换回RGB (0-1)
    r_new, g_new, b_new = colorsys.hsv_to_rgb(h, s, v)

    # 5. 转换回RGB (0-255) 并返回
    return tuple(int(x * 255) for x in (r_new, g_new, b_new))


def apply_pbr_material_and_color(mesh: trimesh.Trimesh, model_filename: str, types: str, region_color_map: dict):
    """
    根据模型文件名生成PBR材质和颜色，并应用到trimesh对象。

    Args:
        mesh (trimesh.Trimesh): 要应用材质的Trimesh网格对象。
        model_filename (str): 模型的文件名。
        types (str): 当前处理的模型类型 ('regions', 'ventricle', etc.)。
        region_color_map (dict): 包含左脑区颜色映射的字典。
    """
    material_name = Path(model_filename).stem
    color_rgb = (128, 128, 128)  # 默认灰色，以防万一

    # --- 核心颜色确定逻辑 ---
    # 检查是否有特定名称，如有则使用预设颜色 (**此部分逻辑保持不变**)
    if material_name == 'ventricle':
        color_rgb = (32, 232, 252)
    elif material_name == 'vessel_vein':
        color_rgb = (20, 40, 252)
    elif material_name == 'vessel':
        color_rgb = (179, 29, 29)
    elif material_name == 'w1':
        color_rgb = (245, 245, 220)
    elif material_name == 'w2':
        color_rgb = (121, 120, 114)
    # --- 新增的、只针对 'regions' 的颜色逻辑 ---
    elif types == 'individual_regions':
        is_left = '_L' in material_name
        is_right = '_R' in material_name

        if is_left:
            # 左脑区：直接从预生成的颜色映射表中查找
            color_rgb = region_color_map.get(material_name, color_rgb)
        elif is_right:
            # 右脑区：找到对应的左脑区颜色，然后进行变换
            left_name = material_name.replace('_R', '_L')
            left_color = region_color_map.get(left_name)
            if left_color:
                color_rgb = _modify_color_s_v(
                    left_color,
                    RIGHT_HEMISPHERE_SATURATION_FACTOR,
                    RIGHT_HEMISPHERE_BRIGHTNESS_FACTOR
                )
            else:
                print(f"  [WARNING] Could not find corresponding left hemisphere color for {material_name}")
        else:
            print(f"  [WARNING] Region file {material_name} does not conform to L/R naming. Using default color.")

    # 创建PBR材质
    material = trimesh.visual.material.PBRMaterial(
        name=material_name,
        baseColorFactor=color_rgb,
        metallicFactor=0.1,
        roughnessFactor=0.8,
    )

    mesh.visual = trimesh.visual.TextureVisuals(material=material)
    print(f"Applied material '{material_name}' with color {color_rgb} to mesh.")


def process_models_in_folder_SmallDistance(input_folder: str, output_folder: str, types: str):
    """
    加载指定输入文件夹中的所有模型，为它们应用PBR材质，并以GLB格式导出。
    """
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    supported_extensions = ['.glb', '.obj', '.stl', '.ply']

    # --- 为 'regions' 预生成颜色映射 ---
    region_color_map = {}
    if types == 'individual_regions':
        print("Generating color map for brain regions using 'flare' palette...")
        # 1. 找出所有左脑区的文件名并排序，以确保颜色分配的稳定性
        all_files = os.listdir(input_folder)
        left_region_files = sorted([Path(f).stem for f in all_files if '_L' in f])

        if not left_region_files:
            print("[WARNING] No left hemisphere files ('_L') found. Color mapping will not be accurate.")
        else:
            # 2. 加载 'flare' 调色板
            # cmap = sns.color_palette("flare", as_cmap=True)
            # cmap = sns.color_palette("rocket", as_cmap=True)
            cmap = sns.color_palette("icefire", as_cmap=True)



            # 3. 为每个左脑区均匀采样颜色并存入字典
            num_left_regions = len(left_region_files)
            for i, region_name in enumerate(left_region_files):
                # np.linspace(0, 1, N) 会在0和1之间生成N个等间距的点
                sample_point = i / (num_left_regions - 1) if num_left_regions > 1 else 0.5
                # cmap返回(R,G,B,A)元组，值范围0-1，我们只需要RGB
                color_0_1 = cmap(sample_point)[:3]
                # 转换为0-255范围并存储
                region_color_map[region_name] = tuple(int(c * 255) for c in color_0_1)
            print(f"Color map generated for {num_left_regions} left hemisphere regions.")

    for filename in os.listdir(input_folder):
        file_path = os.path.join(input_folder, filename)

        if os.path.isfile(file_path) and Path(filename).suffix.lower() in supported_extensions:
            print(f"\n--- Processing: {filename} ---")
            try:
                mesh = trimesh.load(file_path, process=False)
                if isinstance(mesh, trimesh.Scene):
                    mesh = mesh.dump(concatenate=True)
                    print("  Scene detected, concatenated into a single mesh.")

                # 调用函数应用PBR材质和颜色，传入新的参数
                apply_pbr_material_and_color(mesh, filename, types, region_color_map)

                base_name = Path(filename).stem
                output_path = os.path.join(output_folder, f"{base_name}.glb")

                mesh.export(output_path, file_type='glb')
                print(f"  Successfully exported to: {output_path}")

            except Exception as e:
                print(f"  [ERROR] Failed to process {filename}: {e}")


def process_models_in_folder(input_folder: str, output_folder: str, types: str):
    """
    加载指定输入文件夹中的所有模型，为它们应用PBR材质，并以GLB格式导出。
    """
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    supported_extensions = ['.glb', '.obj', '.stl', '.ply']

    region_color_map = {}
    if types == 'individual_regions':
        print("Generating color map for brain regions using 'flare' palette...")
        all_files = os.listdir(input_folder)
        left_region_files = sorted([Path(f).stem for f in all_files if '_L.glb' in f or '_l.glb' in f])  # 保持字母排序

        if not left_region_files:
            print("[WARNING] No left hemisphere files found. Color mapping will not happen.")
        else:
            num_left_regions = len(left_region_files)
            print(f"Found {num_left_regions} left hemisphere regions. Generating high-contrast colors...")
            # cmap = sns.color_palette("flare", as_cmap=True)
            # cmap = sns.color_palette("rocket", as_cmap=True)
            cmap = sns.color_palette("icefire", as_cmap=True)
            # --- 这是新的核心逻辑：创建非线性的、跳跃式的采样点 ---

            # 1. 首先，生成一个标准的、线性的采样点列表 (0.0, 0.03, 0.06, ..., 1.0)
            linear_samples = np.linspace(0, 1, num_left_regions)

            # 2. 将线性列表一分为二
            mid_point = (num_left_regions + 1) // 2
            first_half = linear_samples[:mid_point]
            second_half = linear_samples[mid_point:]

            # 3. 交错合并这两个列表，生成跳跃式的采样顺序
            interleaved_samples = []
            i, j = 0, 0
            while i < len(first_half) or j < len(second_half):
                if i < len(first_half):
                    interleaved_samples.append(first_half[i])
                    i += 1
                if j < len(second_half):
                    interleaved_samples.append(second_half[j])
                    j += 1

            # 4. 使用这个跳跃式的采样点列表为已排序的脑区分配颜色
            for i, region_name in enumerate(left_region_files):
                # 从打乱顺序的列表中获取采样点
                sample_point = interleaved_samples[i]

                color_0_1 = cmap(sample_point)[:3]
                region_color_map[region_name] = tuple(int(c * 255) for c in color_0_1)

            print("High-contrast color map generated successfully.")

    # ... 后续处理文件的代码保持不变 ...
    for filename in os.listdir(input_folder):
        file_path = os.path.join(input_folder, filename)
        if os.path.isfile(file_path):
            # and Path(filename).suffix.lower() in supported_extensions:
            print(f"\n--- Processing: {filename} ---")
            try:
                mesh = trimesh.load(file_path, process=False)
                if isinstance(mesh, trimesh.Scene):
                    mesh = mesh.dump(concatenate=True)
                    print("  Scene detected, concatenated into a single mesh.")

                apply_pbr_material_and_color(mesh, filename, types, region_color_map)

                base_name = Path(filename).stem
                output_path = os.path.join(output_folder, f"{base_name}.glb")
                mesh.export(output_path, file_type='glb')
                print(f"  Successfully exported to: {output_path}")

            except Exception as e:
                print(f"  [ERROR] Failed to process {filename}: {e}")


# --- 主程序入口 ---
if __name__ == '__main__':
    # ==================================================================
    #  --- 用户配置区 ---
    # ==================================================================

    # 正常人
    # types = 'individual_regions'
    # INPUT_MODEL_FOLDER = rf'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\FinalRegionMeshName\{types}'
    # # 你希望保存生成的GLB文件的文件夹
    # OUTPUT_GLB_FOLDER = rf'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\FinalRegionMeshNameMaterialsRegionColor\{types}'

    # ==================================================================

    # 肿瘤
    # types = 'individual_regions'
    # INPUT_MODEL_FOLDER = rf'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\FinalRegionMeshNameMaterialsRegionColor\individual_regions_Tumor'
    # # 你希望保存生成的GLB文件的文件夹
    # OUTPUT_GLB_FOLDER = rf'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data_Health\model_output_Material_New\SlicerRegion\FinalRegionMeshNameMaterialsRegionColor\individual_regions_Tumor_ColorFit'

    # 脑龄
    types = 'individual_regions'
    INPUT_MODEL_FOLDER = rf'C:\Users\AiYing212106001\Desktop\SlicerregionTestProblem\SlicerLobeBrainAge\origin\LOBE_ColorFit'
    # 你希望保存生成的GLB文件的文件夹
    OUTPUT_GLB_FOLDER = rf'C:\Users\AiYing212106001\Desktop\SlicerregionTestProblem\SlicerLobeBrainAge\LOBE_ColorFit'

    print(f"Starting batch processing for type: '{types}'")
    print(f"Input Folder: {INPUT_MODEL_FOLDER}")
    print(f"Output Folder: {OUTPUT_GLB_FOLDER}")

    process_models_in_folder(INPUT_MODEL_FOLDER, OUTPUT_GLB_FOLDER, types)

    print("\nBatch processing finished.")
