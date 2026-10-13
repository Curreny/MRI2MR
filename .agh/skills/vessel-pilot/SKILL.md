---
name: vessel-pilot
description: 将已脱敏的脑血管 DICOM 转换并重建为动脉和静脉 GLB，在有限候选中自动调整三项公开参数并执行技术质量检查。用于用户明确请求脑血管重建、MRA/MRV GLB 或 VesselPilot 流程时；不用于临床诊断。
---

# VesselPilot

只通过 VesselPilot MCP 工具处理数据。不要直接运行命令、拼接路径、修改脚本，或传递工具 Schema 之外的参数。

## 流程

1. 获取一个或多个 DICOM 目录：用户已给出绝对路径时直接使用；输入框“选择 DICOM 文件夹”按钮每次写入一个目录，用户可重复点击追加多个病例；用户通过文字要求打开选择器且尚未给出路径时调用 `choose_dicom_folder`。Windows 选择器应以浏览器前方的最上层模态窗口显示；若未出现，不要重复触发多个选择器，应提示用户检查任务栏或改为粘贴绝对路径。选择取消时不要继续。显式选择或输入的目录可以位于 Agnes 工作区外，但不得自行枚举、猜测或扫描用户未提供的其他目录。
2. 确认每个目录中的 DICOM 已脱敏，并取得用户明确确认。用户在同一请求中明确写出“已脱敏”可视为确认；否则必须询问。只有确认后才能逐目录调用 `inspect_dicom_case`，每个目录保存独立 `case_id`。文件夹选择本身不代表脱敏确认。
3. 单例调用 `start_dicom_conversion`，再用 `get_vessel_job(wait_seconds=55)` 等待。批量任务先逐例登记，再最多同时启动 2 个转换或重建作业；某例失败只停止该例，不得把其他病例结果混入该例。
4. 首个候选固定使用：
   - `vessel_threshold=800`
   - `mrv_weak_grow_tolerance=0.85`
   - `mrv_post_process_min_size=1000`
5. 调用 `start_vessel_candidate`，以唯一、可读的 `candidate_id` 保存参数组合；用 `get_vessel_job(wait_seconds=55)` 等待到终态。
6. 成功后调用 `evaluate_vessel_candidate`。工具会在会话中返回动脉、静脉六视角拼图，并在报告中返回 `vein_distribution_proxy`。动脉判断为 `good / too_dense / too_sparse / uncertain`；静脉还可判断为 `scalp_dominant / intracranial_sparse`。只有技术报告 `conclusion=pass` 的候选才能进入最终选择。
7. 若模型明显过密或过疏，调用 `suggest_vessel_parameters` 把上述两项视觉判断转换为一个未尝试、且只改变一项参数的建议，再启动新候选。可调值仅限：
   - 动脉阈值：`700 / 800 / 900`
   - 静脉弱生长容差：`0.83 / 0.85 / 0.88`
   - 静脉最小区域大小：`800 / 1000 / 1500`
8. 候选技术合格，拼图未见明显过密/过疏，且颅内/头皮外周静脉代理占比相对其他候选没有明显恶化时，调用 `finalize_vessel_case`。判断为 `uncertain` 时停止自动优化并请求人工复核。

## 批量病例

- 多个目录必须分别执行完整流程并保持 `input_path → case_id → job_id → candidate_id → final` 映射，绝不跨病例复用 ID、报告或 GLB。
- 最多同时运行 2 个长作业；有空位时再启动下一例。轮询时轮换病例，不要对同一作业连续快速查询。
- 状态汇报按病例归并，列出已完成、运行中、等待中和失败数量；只有状态变化或达到常规汇报间隔才向用户更新。
- 每例分别应用最多 6 个候选和停止条件。批量最终答复使用一例一行的结果表，并明确失败或需复核的病例。

## 输入失败与序列边界

- `inspect_dicom_case` 的 DICOM 计数只是扩展名/标准 preamble 预检，不代表影像或临床内容已验证。空目录、无 DICOM 迹象、符号链接、越界路径直接停止该例。
- 混有说明文件或其他序列不等于失败；引用工具返回的计数与选择证据。T1、扩散、MIP/MPR、Scout/Localizer、损坏或非三维序列不能替代 MRA/MRV。
- 转换必须同时得到不同来源、可读取的三维 MRA 和 MRV。`MISSING_REQUIRED_MODALITY`、`AMBIGUOUS_MODALITY_SELECTION`、`INVALID_CONVERTED_NIFTI` 或 `DICOM_CONVERSION_FAILED` 均停止该例，不得启动候选，也不得把单侧结果称为完成。
- 出现 `multiple_matching_candidates_ranked_deterministically` 或 `selected_series_has_derived_image_type` 时，先向用户列出所选序列和警告并请求确认，再进入候选重建。
- `INPUT_CHANGED_SINCE_INSPECTION` 表示登记后源目录发生变化；要求用户确认后重新检查目录。不要自动重试转换，不要复用旧病例状态规避指纹检查。
- `already_running=true` 表示已有转换作业；继续轮询该 `job_id`，不得重复提交。

## 长任务与状态汇报

动静脉候选重建通常需要约 20 分钟，首次静脉 Frangi 计算可能更久。启动 `start_vessel_candidate` 后，立即向用户说明预计耗时、`case_id`、`candidate_id` 和 `job_id`，让用户知道任务已真实开始且仍可取消。

- 非终态作业使用 `get_vessel_job(wait_seconds=55)` 长轮询；工具会在服务端等待状态/阶段变化或等待期结束。55 秒上限为当前 Agnes MCP 60 秒单次调用超时预留余量。不要缩短等待时间，也不要在调用之间插入 shell 查询。
- 普通“仍在运行”状态最多每 2–4 分钟向用户汇报一次；状态和阶段没有变化时保持简短，不重复相同说明。
- 状态从 `queued` 变为 `running`、进入下一处理阶段、失败、取消或完成时可以立即汇报，不必等待固定间隔。
- 转换任务通常比重建短，也使用服务端长轮询；收到终态立即停止查询。
- 轮询期间保留状态汇报能力，但不要通过 shell、额外进程或重复提交候选来“确认”任务是否存活。
- 用户主动询问进度时立即查询一次并回复；这次查询会重置下一次常规轮询计时。
- 耗时只引用工具返回的 `elapsed_seconds` 或 `elapsed_minutes`，禁止自行用时间戳、CPU 时间、轮询次数或主观感觉计算。`typical_duration_minutes` 是通常耗时，不是当前已耗时。
- `unchanged=true` 表示等待期间没有状态变化，只需继续下一次长轮询；不要重复输出完整 JSON 或路径。

## 调参与视觉复核

- 动脉过密、噪声多或文件超限：提高 `vessel_threshold`。
- 动脉主要分支缺失或明显断裂：降低 `vessel_threshold`。
- 静脉过密、噪声多或文件超限：先提高 `mrv_weak_grow_tolerance`；仍无改善时提高 `mrv_post_process_min_size`。
- 静脉分支缺失或明显断裂：先降低 `mrv_weak_grow_tolerance`；仍无改善时降低 `mrv_post_process_min_size`。
- `vein_distribution_proxy` 使用动脉包围盒扩张 15% 作为病例内“颅内空间”代理。它不是颅骨分割或临床解剖标签，只能比较同一病例的候选，不能跨患者套用固定正常值。
- 若静脉拼图显示头皮/外周静脉明显占优，且报告的 `scalp_peripheral_proxy_area_ratio` 相对基线升高，将静脉判断为 `scalp_dominant`：先提高 `mrv_weak_grow_tolerance`，必要时再提高 `mrv_post_process_min_size`。
- 若降低头皮/外周代理占比的同时颅内主要分支明显减少，或 `intracranial_proxy_area_ratio` 相对基线明显下降，将静脉判断为 `intracranial_sparse` 并向相反方向单参数回退。不要为了降低头皮比例而删除颅内静脉。
- 一轮只改变一个参数，以便归因。
- 必须先查看 `evaluate_vessel_candidate` 返回的两张拼图再给出视觉判断；不要仅凭文件大小、顶点数或组件数断言分支完整性。
- 如果当前模型不能读取工具图片，或图片返回失败，将视觉判断设为 `uncertain` 并请求人工复核；不要假装已经看过模型。
- 若评估已成功生成报告和拼图，但 Agnes 随后报 `E_STEP_FAILED: artifact <sha256> could not be read`，不要重建候选或调整参数。这表示会话中的拼图制品读取授权失败；说明需升级/重启 Agnes 后新建会话，并对原 `case_id/candidate_id` 重新调用 `evaluate_vessel_candidate`。旧会话可能在推理前重复失败，不能作为恢复入口。
- 技术报告若仅因某侧文件大小、顶点或面数超限而失败，可将该侧视为 `too_dense` 尝试一次受限调参；损坏、空网格或非有限坐标不是调参依据，应停止并报告错误。
- `suggest_vessel_parameters` 只生成建议，不会自动启动长任务。启动下一候选前核对候选总数和停止条件。
- 基线已技术通过且两类血管均为 `good` 时直接完成，不为“尝试优化”而无目的增加候选。

当前技术报告、空间代理指标与模型拼图复核只能发现明显的空模型、过密、过疏和网格异常，不能可靠替代颅骨分割、医学或解剖质量判断。不要声称“临床合格”“诊断正确”“头皮静脉已完全去除”或“无断裂”。

## 停止条件

满足任一条件就停止继续搜索：已有技术通过且视觉判断为 `good` 的候选；尝试 6 个候选；连续两轮无明确改善；工具失败或取消；视觉判断为 `uncertain`、需要人工复核。

不要自动重试失败的长任务。向用户说明失败原因，由用户决定是否重新发起。长时间没有阶段变化不等于失败；以工具终态或明确超时为准。

## 最终答复

单例列出 `case_id`、最终状态、最佳三参数、颅内/头皮外周静脉代理比、动脉/静脉 GLB、技术报告、预览目录、候选次数，以及仍需人工复核的限制。批量任务逐例列出这些字段并给出成功/失败/复核汇总。没有候选通过时明确返回“需人工复核”，不要生成成功结论。
