import trimesh
import trimesh
from pathlib import Path  # 使用 pathlib 以更现代、更健壮的方式处理路径


def process_meshes(tumor_path, brain_regions_dir, output_dir):
    """
    对肿瘤ROI和多个脑功能区模型进行布尔交集运算。

    :param tumor_path: 肿瘤ROI模型的文件路径 (例如 .glb, .obj, .stl)
    :param brain_regions_dir: 包含所有脑功能区模型的文件夹路径
    :param output_dir: 保存布尔运算结果的文件夹路径
    """
    # --- 1. 准备工作 ---
    # 将字符串路径转换为 Path 对象
    tumor_path = Path(tumor_path)
    brain_regions_dir = Path(brain_regions_dir)
    output_dir = Path(output_dir)

    # 创建输出文件夹（如果它不存在）
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出文件夹已准备好: {output_dir}")

    # --- 2. 加载并预处理肿瘤ROI模型 ---
    if not tumor_path.exists():
        print(f"错误：找不到肿瘤ROI文件: {tumor_path}")
        return

    print(f"正在加载肿瘤ROI模型: {tumor_path.name}...")
    try:
        tumor_mesh = trimesh.load_mesh(tumor_path)
    except Exception as e:
        print(f"加载肿瘤ROI模型失败: {e}")
        return

    # 布尔运算要求网格是“水密”的（没有洞）。Trimesh可以尝试修复。
    if not tumor_mesh.is_watertight:
        print("肿瘤模型不是水密的，正在尝试修复...")
        tumor_mesh.fill_holes()
        if not tumor_mesh.is_watertight:
            print("警告：修复后肿瘤模型仍然不是水密的，布尔运算可能会失败或产生不正确的结果。")
        else:
            print("肿瘤模型修复成功。")

    # --- 3. 遍历所有脑功能区并执行布尔运算 ---
    # 获取文件夹中所有的模型文件 (这里以 .glb 为例, 您可以改为 '*.obj', '*.stl' 等)
    brain_files = list(brain_regions_dir.glob('*.glb'))
    if not brain_files:
        print(f"错误：在文件夹 {brain_regions_dir} 中未找到任何模型文件（例如 *.glb）。请检查路径和文件扩展名。")
        return

    print(f"\n在 {brain_regions_dir} 中找到 {len(brain_files)} 个脑功能区模型。开始批量处理...")

    for i, brain_region_path in enumerate(brain_files):
        if i > 20:
            print("已处理20个脑功能区，停止处理。")
            break

        print(f"\n--- [{i + 1}/{len(brain_files)}] 正在处理: {brain_region_path.name} ---")

        try:
            # 加载当前的脑功能区模型
            brain_mesh = trimesh.load_mesh(brain_region_path)

            # 同样检查并修复水密性
            if not brain_mesh.is_watertight:
                print(f"注意: {brain_region_path.name} 不是水密的，正在尝试修复。")
                brain_mesh.fill_holes()

            # 执行布尔交集运算 (Intersection)
            # engine='manifold' 是目前最稳定和推荐的后端
            print("正在执行布尔交集运算...")
            intersection_mesh = tumor_mesh.intersection(brain_mesh, engine='manifold')

            # --- 4. 处理并保存结果 ---
            # 检查运算结果是否为空（即脑区和肿瘤没有重叠）
            if intersection_mesh.is_empty:
                print(f"结果: {brain_region_path.name} 与肿瘤没有交集。")
                continue  # 跳过保存，处理下一个文件

            # 如果有交集，则保存结果
            output_filename = f"intersected_{brain_region_path.name}"
            output_path = output_dir / output_filename
            intersection_mesh.export(output_path)
            print(f"成功！运算结果已保存到: {output_path}")

        except Exception as e:
            print(f"处理 {brain_region_path.name} 时发生错误: {e}")
            print("跳过此文件，继续处理下一个。")
            continue

    print("\n所有文件处理完毕！")




if __name__ == "__main__":
    # --- 1. 加载或生成您需要的模型 ---
    # 假设您已经运行了相应的处理模式，并得到了这些trimesh对象
    # 如果没有，您可以从已保存的 .glb 文件加载它们
    # 注意：加载时，trimesh会自动处理坐标，它们已经是-对齐的

    # print("start mesh boolean operation...")
    #
    # # 1. load Mesh
    # whole_brain_mesh = trimesh.load_mesh(r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\model_output\OBJ_gm_wm\w1.glb')
    # # ventricle_mesh = trimesh.load_mesh('Data/model_output/OBJ_ventricle/ventricle.glb')
    # vessel_mesh = trimesh.load_mesh(r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\model_output\OBJ_vessel\vessel.glb')
    #
    # # # (可选) 为了更好的布尔运算，可以稍微扩大要减去的物体，避免表面共面的问题
    # # ventricle_mesh.apply_scale(1.01)
    # # vessel_mesh.apply_scale(1.01)
    #
    # # 2. (Watertight)
    # # 布尔运算要求网格是“水密的”（没有洞）。Trimesh可以尝试修复。
    # print(f"是否水密? {whole_brain_mesh.is_watertight}  {vessel_mesh.is_watertight}")
    #
    # if not whole_brain_mesh.is_watertight:
    #     print("尝试修复大脑网格...")
    #     whole_brain_mesh.fill_holes()
    #     print(f"修复后大脑是否水密? {whole_brain_mesh.is_watertight}")
    # #
    # # print(f"脑室是否水密? {ventricle_mesh.is_watertight}")
    # # if not ventricle_mesh.is_watertight:
    # #     print("尝试修复脑室网格...")
    # #     ventricle_mesh.fill_holes()
    # #
    # print(f"血管是否水密? {vessel_mesh.is_watertight}")
    # if not vessel_mesh.is_watertight:
    #     print("尝试修复血管网格...")
    #     vessel_mesh.fill_holes()
    #
    # # --- 3. 执行布尔运算（差集） ---
    # # 使用 manifold3d 作为后端 (确保已 pip install manifold3d)
    # print("\n开始布尔运算：从大脑中减去脑室...")
    #
    #
    # final_brain = whole_brain_mesh.difference(vessel_mesh, engine='manifold')
    #
    # print("布尔运算成功！")
    #
    # # --- 4. 保存并/或显示结果 ---
    # print("正在导出最终结果...")
    # final_brain.export(r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\model_output_exclusion\Test_Boolean\final_hollow_brain.glb')
    # print("最终模型已保存为 'final_hollow_brain.glb'")
    #
    # # 可视化检查（需要 pip install pyglet）
    # print("正在显示结果场景... 关闭窗口以继续。")




    # In[]
    # --- 请在这里配置您的路径 ---

    # 1. 肿瘤ROI模型的完整路径
    TUMOR_MODEL_PATH = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\model_output\OBJ_roi\ROI.glb'

    # 2. 包含120个脑功能区模型的文件夹路径
    BRAIN_REGIONS_FOLDER = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\model_output\OBJ_individual_regions'

    # 3. 用于存放运算结果的输出文件夹路径 (脚本会自动创建)
    OUTPUT_FOLDER = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\model_output_exclusion'

    # --------------------------------

    # 运行主处理函数
    process_meshes(TUMOR_MODEL_PATH, BRAIN_REGIONS_FOLDER, OUTPUT_FOLDER)





