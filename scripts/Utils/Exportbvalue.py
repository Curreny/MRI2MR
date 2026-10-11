
# In[]
import pydicom
import numpy as np
import os
from pydicom.tag import Tag
def extract_dicom_values(dcm_path, tag_dict):
    ds = pydicom.dcmread(dcm_path, force=True)
    remaining_tags = {key: {Tag(tag) for tag in tags} for key, tags in tag_dict.items()}
    result = {}

    # 遍历 DICOM 数据集（仅一次）
    for elem in ds.iterall():
        for key, tags in list(remaining_tags.items()):  # 遍历未匹配的tags
            if elem.tag in tags:  # 确保tag匹配，并且value非空
                if key == 'PatientName':
                    result[key] = elem.value  # 记录值
                else: result[key] = np.array(elem.value) if elem.value is not None else np.array([])
                del remaining_tags[key]  # 删除key，后续不再检查
                break  # 立即跳出，避免重复匹配

        # 如果所有key都已匹配完，提前终止
        if not remaining_tags:
            break


    return result


tag_dict1 = {#用于写node
        "bval": [(0x0018, 0x9087)],
        "bvec": [(0x0018, 0x9089)],

    }

bvals = []
bvecs = []
dicom_folder = r"D:\Tang_DATA\VRReadingroom\Data1013\S0\S8010"
output1 = r"D:\Tang_DATA\VRReadingroom\Data1013\S_nii\8010_DKI\example_DKI.bval"
output2 = r"D:\Tang_DATA\VRReadingroom\Data1013\S_nii\8010_DKI\example_DKI.bvec"
# 遍历文件夹内所有 DICOM 文件
for fname in sorted(os.listdir(dicom_folder)):
    # if not fname.lower().endswith(".dcm"):
    #     continue
    fpath = os.path.join(dicom_folder, fname)
    values1 = extract_dicom_values(fpath, tag_dict1)
    # print(values1)
    bval = values1.get('bval')
    bvec = values1.get('bvec')
    if bval is None:
        bval = 0.0
    if bvec is None:
        bvec = [0.0, 0.0, 0.0]
    bvals.append(bval)
    bvecs.append(bvec)

bvals = np.array(bvals)
bvecs = np.array(bvecs).T  # (3, N)
print(len(bvals))
print(len(bvecs))
np.savetxt(output1, bvals[np.newaxis, :], fmt="%.6f", delimiter=" ")
np.savetxt(output2, bvecs, fmt="%.6f", delimiter=" ")
print("完成，输出到：")

print("done")
# In[]
