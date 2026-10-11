from scipy.linalg import polar
import numpy as np

def decompose_affine_matrix(matrix):
    # 提取平移向量
    translation = matrix[:3, 3]

    # 提取旋转缩放部分
    rs_matrix = matrix[:3, :3]

    # 使用 polar 分解得到旋转矩阵和缩放矩阵
    rotation_matrix, scale_matrix = polar(rs_matrix)

    return translation, rotation_matrix, scale_matrix[((0, 1, 2), (0, 1, 2))]


def compose_affine_matrix_noRotation(translation, scale_matrix):
    # 创建一个 4x4 的单位矩阵
    affine_matrix = np.zeros((4, 4))
    affine_matrix[3, 3] = 1

    # 将缩放矩阵填入仿射矩阵的左上角 3x3 部分
    affine_matrix[((0, 1, 2), (0, 1, 2))] = scale_matrix

    # 将平移向量填入仿射矩阵的最后一列的前三个元素
    affine_matrix[:3, 3] = translation

    return affine_matrix
