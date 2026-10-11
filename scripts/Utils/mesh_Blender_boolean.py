import trimesh
from pathlib import Path
import subprocess  # 【新增】导入subprocess模块
import shutil  # 【新增】用于清理临时文件夹


# =========================================================================
#  【新增】使用Blender进行布尔运算的核心函数
# =========================================================================
def boolean_with_blender(mesh1, mesh2, operation: str, blender_executable_path: str, temp_dir_base: Path):
    """
    使用Blender对两个Trimesh对象执行布尔运算。

    Args:
        mesh1 (trimesh.Trimesh): 第一个网格 (目标)
        mesh2 (trimesh.Trimesh): 第二个网格 (操作数)
        operation (str): 'intersect', 'difference', or 'union'
        blender_executable_path (str): Blender可执行文件的路径.
        temp_dir_base (Path): 用于创建临时文件夹的基础路径.

    Returns:
        trimesh.Trimesh or None: 运算结果网格。如果运算失败或结果为空，则返回 None.
    """
    # 映射到Blender的布尔操作类型
    op_map = {'intersect': 'INTERSECT', 'difference': 'DIFFERENCE', 'union': 'UNION'}
    blender_op = op_map.get(operation.lower())
    if not blender_op:
        raise ValueError(f"不支持的操作: {operation}. 请使用 'intersect', 'difference', 或 'union'.")

    # --- 1. 准备临时文件和Blender脚本 ---
    temp_dir = temp_dir_base / "blender_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    path1 = temp_dir / "mesh1.obj"
    path2 = temp_dir / "mesh2.obj"
    output_path = temp_dir / "result.obj"
    script_path = temp_dir / "blender_script.py"

    blender_script_content = f"""
import bpy
import sys

argv = sys.argv[sys.argv.index("--") + 1:]
mesh1_in, mesh2_in, mesh_out, op_type = argv[0], argv[1], argv[2], argv[3]

# 清理场景
bpy.ops.wm.read_factory_settings(use_empty=True)

# 导入网格
bpy.ops.import_scene.obj(filepath=mesh1_in)
obj1 = bpy.context.selected_objects[0]

bpy.ops.import_scene.obj(filepath=mesh2_in)
obj2 = bpy.context.selected_objects[0]

# 添加并配置布尔修改器
modifier = obj1.modifiers.new(name="Boolean", type='BOOLEAN')
modifier.object = obj2
modifier.operation = op_type
modifier.solver = 'EXACT'  # 使用强大的'EXACT'求解器
modifier.use_self = True

# 应用修改器
try:
    bpy.context.view_layer.objects.active = obj1
    bpy.ops.object.modifier_apply(modifier=modifier.name)
except RuntimeError as e:
    print(f"Blender Error applying modifier: {{e}}")
    # 即使应用失败，也可能有一个有效（尽管不完美）的结果，所以我们继续尝试导出
    pass

# 清理第二个物体
bpy.data.objects.remove(obj2, do_unlink=True)

# 导出结果
bpy.ops.object.select_all(action='DESELECT')
obj1.select_set(True)
bpy.ops.export_scene.obj(filepath=mesh_out, use_selection=True)
"""
    script_path.write_text(blender_script_content)

    # --- 2. 导出网格并执行命令 ---
    mesh1.export(str(path1))
    mesh2.export(str(path2))

    command = [
        blender_executable_path,
        "-b",  # 后台无头模式
        "-P", str(script_path),  # 运行脚本
        "--",  # 参数分隔符
        str(path1), str(path2), str(output_path), blender_op
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"--- 错误: 找不到Blender可执行文件 '{blender_executable_path}' ---")
        print("--- 请在脚本末尾的 main 部分设置正确的 BLENDER_EXECUTABLE_PATH ---")
        return None
    except subprocess.CalledProcessError as e:
        print(f"--- Blender执行时发生错误 (返回码: {e.returncode}) ---")
        print("Blender STDERR:", e.stderr)
        return None

    # --- 3. 加载结果并清理 ---
    if output_path.exists() and output_path.stat().st_size > 0:
        result_mesh = trimesh.load_mesh(output_path)
        shutil.rmtree(temp_dir)  # 清理临时文件
        if result_mesh.is_empty:
            return None
        return result_mesh
    else:
        shutil.rmtree(temp_dir)  # 清理临时文件
        return None


def process_meshes(tumor_path, brain_regions_dir, output_dir, blender_executable_path: str):  # 【修改】增加blender路径参数
    """
    对肿瘤ROI和多个脑功能区模型进行布尔交集运算。
    【修改】此版本使用Blender进行布尔运算以提高鲁棒性。

    :param tumor_path: 肿瘤ROI模型的文件路径
    :param brain_regions_dir: 包含所有脑功能区模型的文件夹路径
    :param output_dir: 保存布尔运算结果的文件夹路径
    :param blender_executable_path: Blender可执行文件的路径
    """
    # --- 1. 准备工作 (无变化) ---
    tumor_path = Path(tumor_path)
    brain_regions_dir = Path(brain_regions_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出文件夹已准备好: {output_dir}")

    # --- 2. 加载肿瘤ROI模型 (不再需要修复水密性) ---
    if not tumor_path.exists():
        print(f"错误：找不到肿瘤ROI文件: {tumor_path}")
        return

    print(f"正在加载肿瘤ROI模型: {tumor_path.name}...")
    try:
        tumor_mesh = trimesh.load_mesh(tumor_path)
    except Exception as e:
        print(f"加载肿瘤ROI模型失败: {e}")
        return

    # 【修改】不再需要检查水密性，因为Blender可以处理
    # if not tumor_mesh.is_watertight: ... (这部分代码可以安全删除)


    # --- 3. 遍历所有脑功能区并执行布尔运算 ---
    brain_files = list(brain_regions_dir.glob('*.glb'))
    if not brain_files:
        print(f"错误：在文件夹 {brain_regions_dir} 中未找到任何模型文件（例如 *.glb）。")
        return

    print(f"\n在 {brain_regions_dir} 中找到 {len(brain_files)} 个脑功能区模型。开始批量处理...")

    processed_count = 0
    for i, brain_region_path in enumerate(brain_files):
        # 取消了 break 限制，您可以根据需要加回来
        # if processed_count >= 20:
        #     print("已处理20个脑功能区，停止处理。")
        #     break

        print(f"\n--- [{i + 1}/{len(brain_files)}] 正在处理: {brain_region_path.name} ---")

        try:
            brain_mesh = trimesh.load_mesh(brain_region_path)


            print(f"模型{brain_region_path.name}水密: {brain_mesh.is_watertight}")


            # 【核心修改】使用新的Blender函数替换trimesh的布尔运算

            intersection_mesh = boolean_with_blender(
                mesh1=tumor_mesh,
                mesh2=brain_mesh,
                operation='intersect',
                blender_executable_path=blender_executable_path,
                temp_dir_base=output_dir
            )

            # --- 4. 处理并保存结果 ---
            # 【修改】检查返回是否为None，这同时处理了运算失败和结果为空两种情况
            if intersection_mesh is None:
                print(f"结果: {brain_region_path.name} 与肿瘤没有交集或运算失败。")
                continue

            output_filename = f"intersected_{brain_region_path.stem}.glb"  # 使用 .glb 扩展名
            output_path = output_dir / output_filename
            intersection_mesh.export(output_path)
            print(f"成功！运算结果已保存到: {output_path}")
            processed_count += 1

        except Exception as e:
            print(f"处理 {brain_region_path.name} 时发生未知错误: {e}")
            print("跳过此文件，继续处理下一个。")
            continue

    print("\n所有文件处理完毕！")


if __name__ == "__main__":
    # In[]
    # --- 请在这里配置您的路径 ---

    # 【重要】请将此路径修改为您电脑上Blender可执行文件的实际位置
    # Windows 示例: r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe"
    # macOS 示例: "/Applications/Blender.app/Contents/MacOS/Blender"
    # Linux 示例: "/usr/bin/blender"
    BLENDER_EXECUTABLE_PATH = r"D:\Tang_DATA\Blender\blender.exe"

    # 1. 肿瘤ROI模型的完整路径
    TUMOR_MODEL_PATH = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\model_output_Material_Boolean\OBJ_roi\ROI.glb'

    # 2. 包含脑功能区模型的文件夹路径
    BRAIN_REGIONS_FOLDER = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\model_output_Material_Boolean\OBJ_individual_regions'

    # 3. 用于存放运算结果的输出文件夹路径
    OUTPUT_FOLDER = r'D:\Tang_DATA\Python_Code\BrainVRReadingRoom\Data\model_output_Material_Boolean\Boolean_Output'

    # --------------------------------

    # 运行主处理函数，【修改】传入Blender路径
    process_meshes(TUMOR_MODEL_PATH, BRAIN_REGIONS_FOLDER, OUTPUT_FOLDER, BLENDER_EXECUTABLE_PATH)

