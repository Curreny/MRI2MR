# VesselPilot：面向混合现实的脑血管数字孪生自动重建工具

> 竞赛主题：数字孪生与仿真到现实  
> 技术底座：Agnes Harness（AGH）+ Agnes 模型 + 独立脑血管处理工具

## 1. 项目背景

混合现实（MR）医学展示需要可交互、大小可控、血管连续的三维脑血管模型。常规流程中，操作者需要先把 DICOM 转为 NIfTI，再分别生成动脉与静脉模型，观察是否断裂、文件是否过大，随后人工调参并重新生成。

VesselPilot 是一套全新的独立血管处理工具。它参考 MRI2MR 中已有的 DICOM 转换与动静脉重建算法思路，但**不接入、依赖或公开整个 MRI2MR 工程**。Agnes 模型通过 AGH 调用受约束工具，完成“转换—重建—评估—调参—验证—导出”的可追溯闭环。

本项目面向混合现实展示和科研/教学可视化，不用于临床诊断或治疗决策。

## 2. 项目范围

### 包含

- DICOM 序列转换为 NIfTI（NII）。
- MRA 动脉和 MRV 静脉三维重建。
- 仅对三项公开参数进行自动调优。
- 候选模型的文件大小、网格有效性、连通性与标准化视觉预览。
- Agnes 依据量化报告、预览图与经验规则选择下一轮参数。
- 导出最佳 GLB、质控报告、参数快照和 AGH 执行轨迹。

### 不包含

- MRI2MR 工程、其 Web UI 和其他功能模块。
- DTI 纤维、脑叶、灰白质、脑室、ROI 等非血管模型。
- 头皮静脉筛除或头皮静脉质量评分。
- 患者原始数据、密钥、医院专用配置和未授权第三方资产。
- 临床诊断、治疗建议或医疗器械功能声明。

> 输入为已去颅骨、脱敏的数据，头皮静脉不属于重建目标，也不作为候选优劣指标。

## 3. 核心目标与验收标准

### 核心目标

从一例脱敏 DICOM 数据自动得到 MRA/MRV NIfTI，生成适用于 MR 展示的动脉和静脉 GLB。系统根据候选结果自动调整参数，输出质量最佳的一版模型及其完整可追溯证据。

### 硬性验收标准

- [ ] DICOM 转换成功，目标 MRA/MRV NIfTI 可读取。
- [ ] 动脉和静脉 GLB 成功生成，文件非空且可读取。
- [ ] GLB 文件大小不超过 MR 展示端上限。
- [ ] 模型没有明显主干血管断裂；无法可靠判断时标记为“需人工复核”。
- [ ] 最终模型、候选参数、评估报告和 AGH 调用轨迹可一一对应。

### 待项目组确认

- [ ] 单个 GLB 文件大小、顶点数和三角面数上限。
- [ ] “明显血管断裂”的视觉判定准则。
- [ ] 每个病例的最大候选数、迭代轮数和运行时间。
- [ ] 自动通过、自动失败与人工复核的边界。

## 4. 对大模型开放的参数

除下表三项外，DICOM 转换、滤波、网格处理、减面比例、输出格式和运行路径均固定。AGH 工具必须在服务端校验范围，模型不得传入其他命令行参数。

| 对象 | 公开参数 | 初始值 | 作用 |
| --- | --- | ---: | --- |
| 动脉（MRA） | vessel_threshold | 800 | 提高通常减少血管和噪声，也可能导致分支缺失或断裂 |
| 静脉（MRV） | mrv_weak_grow_tolerance | 0.85 | 降低通常扩大弱血管区域生长；提高通常收紧生长 |
| 静脉（MRV） | mrv_post_process_min_size | 1000 | 提高会删除更多小连通区域，也可能删除细小静脉 |

初版可使用以下离散候选，后续以脱敏验证集校准：

- 动脉阈值：700 / 800 / 900
- 静脉弱生长容差：0.83 / 0.85 / 0.88
- 静脉最小区域大小：800 / 1000 / 1500

## 5. AGH 智能体闭环

~~~
用户提交脱敏 DICOM
        ↓
AGH 规划：检查输入、制定候选参数与迭代预算
        ↓
工具 1：DICOM → MRA/MRV NIfTI
        ↓
工具 2：按当前参数生成动脉、静脉 GLB 候选
        ↓
工具 3：统计文件大小、连通性并生成标准多视角预览
        ↓
Agnes：读取报告和预览，按经验规则选择下一轮参数
        ↓
达到质量条件？──否──→ 返回工具 2
        │
       是
        ↓
工具 4：导出最佳 GLB、报告、参数与 AGH 轨迹
~~~

该流程包含任务规划、能力调用、反馈处理和结果验证；每步都由 AGH 记录。

## 6. 工具清单

| 工具 | 输入 | 输出 | 作用 |
| --- | --- | --- | --- |
| choose_dicom_folder | 无 | 用户选择的受控 DICOM 目录或取消状态 | 在会话触发本机文件夹选择对话框 |
| inspect_dicom_case | DICOM 目录、脱敏确认 | `case_id`、输入指纹、预检摘要 | 在受控输入根目录登记病例 |
| get_vessel_case | `case_id` | 转换状态、候选列表 | 查询病例当前状态 |
| start_dicom_conversion | `case_id` | 异步 `job_id` | 启动 DICOM → MRA/MRV NIfTI |
| start_vessel_candidate | `case_id`、候选 ID、三项白名单参数 | 异步 `job_id` | 生成一组不可变动脉/静脉候选 |
| get_vessel_job | `case_id`、`job_id`、等待秒数 | 阶段、权威耗时、终态产物或精简未变化状态 | 服务端长轮询最多 55 秒，阻止快速空转 |
| cancel_vessel_job | `case_id`、`job_id` | `cancelled` 终态 | 取消任务和子进程树 |
| list_vessel_candidates | `case_id` | 参数、产物和报告摘要 | 比较已生成候选 |
| evaluate_vessel_candidate | `case_id`、候选 ID | `report.json`、十二张预览 PNG、两张六视角拼图 | 技术网格质控并把可视预览送入会话 |
| suggest_vessel_parameters | 病例、基准候选、动/静脉视觉判断 | 一个未尝试的单参数调整建议 | 把 AI 的过密/过疏判断转换为受约束调参 |
| finalize_vessel_case | 通过技术质控的候选 ID | final/ 双 GLB、报告、参数、manifest | 固化最终交付物 |

> 当前 MCP 实现包含以上 11 个工具。`pass` 仅代表技术网格质控通过，AI 拼图判断也只用于明显的过密/过疏筛查；最终仍保留 `clinical_quality_review_required=true`，不代表临床或解剖质量结论。

## 7. 候选质量评估

### 量化指标

- [ ] 转换、重建、渲染和导出均成功。
- [ ] GLB 非空、可读取，顶点数和面数有效。
- [ ] 文件大小、顶点数、三角面数不超过展示端上限。
- [ ] 最大连通域占比、有效连通域数及骨架端点/短支路异常指标在可接受范围。
- [ ] 包围盒尺寸和网格密度适合 MR 展示。

### 标准化视觉预览

每个候选生成前、后、左、右、上、下六个固定视角；动脉与静脉采用固定配色。Agnes 重点检查：

- [ ] 主干血管是否存在明显视觉断裂。
- [ ] 主要分支是否异常缺失。
- [ ] 是否有大面积噪声、块状伪影或异常融合。
- [ ] 模型整体密度和复杂度是否适合 MR 展示。

模型的视觉结论必须与量化报告一起保存，并说明观察依据；不得只返回“看起来不错”。

### 参数调整经验规则

| 问题 | 下一轮调整方向 |
| --- | --- |
| 动脉模型过密、噪声多或文件过大 | 提高 vessel_threshold |
| 动脉主要分支缺失或明显断裂 | 降低 vessel_threshold |
| 静脉模型过密、噪声多或文件过大 | 提高 mrv_weak_grow_tolerance，或提高 mrv_post_process_min_size |
| 静脉主要分支缺失或明显断裂 | 降低 mrv_weak_grow_tolerance，或降低 mrv_post_process_min_size |
| 指标和视觉结论冲突 | 保留候选并标记“需人工复核”，不得自动发布 |

> 规则给出调整方向，Agnes 只在允许的离散候选中选择下一轮组合，保证过程可复现、可审计。

## 8. 实施任务清单

### 8.1 已确认的实现基线

- [x] AGH 源码位于 `agnes-harness/`；当前重建会话 cwd 是项目根，因此 Skill 放在 `.agh/skills/vessel-pilot/SKILL.md`。Skill 路径必须相对实际会话工作区，而不是固定放在 Harness 源码目录。
- [x] Skill 只负责告诉 Agnes 如何规划、调用和判断，不直接执行 Python；血管能力应通过一个独立、受约束的 MCP 工具服务提供给 AGH。
- [x] 血管 CLI 位于 `scripts/Vascular_cmd.py`，已具备 `dicom_convert`、`artery` 和 `vein` 三种能力，且不 import `Main_cmd.py`。
- [x] 随项目运行时为 `runtime/python/BrainAAL/python.exe`（Python 3.9.21），已验证可导入当前脚本所需的 `nibabel`、`numpy`、`scipy`、`skimage`、`trimesh` 和 `vedo`。
- [x] dcm2niix 与 DCMTK 已随项目提供；正式接入时使用项目内绝对路径，不依赖操作者机器的全局 `PATH` 或外部 Conda 环境。
- [x] 当前 CLI 成功退出码为 `0`、失败为 `1`；默认动脉阈值是 `400`，而智能体基线要求显式传入 `800`。
- [ ] 修复/规避 Windows 下 CLI 帮助和日志中文乱码，保证 MCP 能稳定保存 UTF-8 日志并提取错误信息。

### 8.2 阶段 0：冻结需求、数据合同和验收门槛

- [x] 明确用户输入入口：用户可直接在会话输入绝对目录，或让 `choose_dicom_folder` 打开本机文件夹对话框；目录必须位于已配置输入根内，且仍需单独确认已脱敏。ZIP 上传暂不支持。
- [x] MVP 要求同时得到 MRA 与 MRV；转换未生成任一目标模态时作业失败，不能只产出一侧后声称成功。
- [x] 明确输出合同：最终包含 `artery.glb`、`vein.glb`、`report.json`、`parameters.json`、十二张预览图和 `manifest.json`。
- [ ] 确认单个 GLB 的文件大小、顶点数和三角面数上限，并写入版本化配置，禁止只写在 Skill 提示词中。
- [ ] 确认“明显主干断裂”、噪声过多、主要分支缺失的人工标注规范，以及自动通过、自动失败和人工复核边界。
- [ ] 确认每例的最大候选数、最大迭代轮数、单任务超时、总运行时间和磁盘占用上限。
- [x] 冻结首版三项参数白名单：`vessel_threshold ∈ {700,800,900}`、`mrv_weak_grow_tolerance ∈ {0.83,0.85,0.88}`、`mrv_post_process_min_size ∈ {800,1000,1500}`；其他算法参数由服务端固定。
- [x] 定义病例、任务、候选 ID 规则及 `queued/running/succeeded/failed/cancelled` 作业状态；Agnes 不依赖自由文本日志判断成功。

**阶段完成标准：** 输入、输出、参数、预算、质量阈值和失败语义均已形成可机器校验的 Schema；未确认的阈值不会被实现层自行猜测。

### 8.3 阶段 A：固化并加固独立血管 CLI

- [x] 实现 DICOM 转 T1/MRA/MRV NIfTI，并支持无 T1 时以 MRA 作为参考空间。
- [x] 实现动脉预处理、网格生成和 GLB 导出。
- [x] 实现静脉预处理、网格生成和 GLB 导出。
- [ ] 将 CLI 默认 Python 路径、`dcm2niix.exe` 和 `dcmdjpeg.exe` 解析到项目内运行时，并在启动自检中验证文件、依赖和版本。
- [x] MCP 作业层增加机器可读的 `spec.json`、`state.json`、命令日志和终态结果，记录模式、参数、输出、状态和安全错误。
- [x] 候选输出使用不可变目录 `<case_root>/<case_id>/candidates/<candidate_id>/`；ID 已存在即拒绝，禁止覆盖历史候选。
- [x] 隔离每例临时文件，并以 MRV SHA-256 派生 Frangi 缓存名；影响 Frangi 的参数在 MVP 中由服务端固定。
- [ ] 保存评估所需的中间分割/掩膜，或输出足以计算连通性与骨架指标的标准化中间结果。
- [ ] 支持进程超时和取消；失败或取消后写入终态，清理半成品，同时保留诊断日志。
- [ ] 对空分割、Marching Cubes 无表面、内存不足、磁盘不足、损坏 NIfTI、无效 affine 和外部工具失败给出稳定错误码。
- [ ] 竞赛公开前把脚本、运行时声明及必要依赖抽取到独立 `vessel-pilot` 目录，记录原创改造、算法来源和第三方许可证。

**阶段完成标准：** 使用项目内 `runtime/python/BrainAAL/python.exe` 可从干净 PowerShell 完成一次 MRA/MRV 转换与两侧重建；同一命令可复现，同名候选不会覆盖，失败有结构化结果。

### 8.4 阶段 B：实现受约束的 VesselPilot MCP 服务

- [x] 采用独立 stdio MCP 服务接入 AGH，不侵入修改 AGH Core；MCP 服务仅调用固定的 Python 可执行文件和固定脚本，不接受 shell 命令或任意附加参数。
- [ ] 实现 `create_case`/`inspect_dicom_case`：接收已授权输入入口，生成 `case_id`，识别序列、检查脱敏和模态完整性，返回预检报告。
- [x] 实现 `start_dicom_conversion`：只接收 `case_id`，在受控病例目录内完成转换，返回异步作业状态与日志索引。
- [x] 实现 `start_vessel_candidate`：接收 `case_id`、`candidate_id` 与严格的三参数对象，一次生成对应动脉和静脉候选；服务端补齐全部固定参数。
- [x] 实现 `evaluate_vessel_candidate`：返回技术硬性约束、网格指标、预览路径和 `pass/fail` 结论。
- [x] 实现 `finalize_vessel_case`：仅允许选择已成功评估的候选，复制到 `final/` 并生成 manifest、参数快照和校验和。
- [x] 对转换和首次 MRV Frangi 等长任务采用 `start_*` + `get_vessel_job` + `cancel_vessel_job` 的异步作业语义。
- [x] 为 11 个工具定义严格 JSON Schema：`additionalProperties: false`，并限制参数类型、枚举、ID 格式和字符串长度；只读查询与建议工具声明 `readOnlyHint=true`。
- [x] 对 `case_id` 和 `candidate_id` 使用服务端映射；DICOM 输入经规范化后必须位于配置的 input root 内，ID 不能提供路径。
- [x] 使用参数数组启动子进程，捕获 stdout/stderr，固定工作目录和 UTF-8；任何用户文本都不拼接成 shell 命令。
- [ ] 限制并发任务数、单病例磁盘配额和日志大小；实现重复请求幂等、服务重启后的状态恢复和孤儿进程清理。
- [x] MCP 返回产物引用和摘要，不把 DICOM/NIfTI 二进制或超大 GLB 直接塞进模型上下文。

**阶段完成标准：** MCP inspector 能列出预期工具；合法调用可产生真实文件，越权路径、第四个调参项、越界参数、重复候选和取消场景均被服务端可靠处理。

### 8.5 阶段 C：建立可审计的质量评估与预览

- [x] 验证 GLB 文件存在、非空、可由 `trimesh` 重新加载，并统计字节数、顶点数、三角面数、包围盒、重复面和非有限坐标。
- [ ] 从分割结果计算连通域数、最大连通域占比、体素/体积变化；从骨架计算端点、分叉点、短支路等断裂风险指标。
- [x] 动脉与静脉分别生成前、后、左、右、上、下固定正交视角 PNG，固定尺度、配色和背景，并按候选目录隔离。
- [x] 将每侧六视角合成为一张拼图，并由 `evaluate_vessel_candidate` 以 MCP image content 返回会话，使 Agnes 可直接执行明显过密/过疏复核。
- [ ] 定义并版本化 `report.json` Schema，包含输入指纹、工具版本、参数、指标、阈值版本、问题标签、硬性失败原因、评分、结论和产物校验和。
- [ ] 将“硬门槛”和“软评分”分离：损坏/超限/缺失任何一侧直接失败；软指标只对通过硬门槛的候选排序。
- [ ] 对量化指标与视觉判断冲突、视觉低置信度或不在校准分布内的情况输出 `review`，不得自动发布。
- [ ] 用人工认可的脱敏验证集校准阈值和权重，保留每例人工标签、版本和回归结果；禁止用演示病例本身调阈值后再宣称泛化通过。

**阶段完成标准：** 对同一候选重复评估得到一致报告和预览；报告可追溯到唯一输入、参数、代码/配置版本和 GLB 校验和。

### 8.6 阶段 D：编写 VesselPilot Skill 与有限调参策略

- [x] 在项目根 `.agh/skills/vessel-pilot/SKILL.md` 创建 Skill，包含明确触发描述、工具调用顺序、三参数规则、停止条件、人工复核条件和最终答复格式。
- [x] Skill 明确要求先预检和转换，再运行基线候选：动脉 `800`，静脉 `0.85 / 1000`；不得跳过评估直接导出。
- [x] Skill 只允许从离散白名单选择下一轮，记录每次选择依据；不得修改固定参数，不得重复已运行组合，不得无边界搜索。
- [x] 定义参数更新优先级，并要求一轮只改变一个变量以便归因。
- [x] 定义停止条件：已有合格候选、最多 6 个候选、连续两轮无改善、工具失败/取消或需要人工判断预览。
- [x] 定义长任务交互：候选重建启动后提示用户通常约需 20 分钟；`get_vessel_job` 在服务端长轮询 55 秒，普通运行状态每 2–4 分钟汇报一次，终态和阶段变化立即汇报。
- [x] 作业状态返回 `phase`、`server_time`、`elapsed_seconds` 和 `elapsed_minutes`；Skill 禁止 Agnes 自行用时间戳、CPU 时间或轮询次数推算耗时。
- [x] 实现 `suggest_vessel_parameters`：Agnes 阅读动静脉拼图后分别标记 `good/too_dense/too_sparse/uncertain`，服务端只返回未尝试且一次改变一个参数的候选建议。
- [ ] 最佳候选选择由服务端根据版本化报告和评分执行或复核，Agnes 负责提出候选与解释，不能凭文字声称某个未评估模型最佳。
- [x] 最终回复必须列出病例状态、动脉/静脉 GLB 产物、最佳参数、关键指标、迭代次数、是否需人工复核和报告位置；失败时列出安全错误原因与下一步。
- [ ] 准备 Skill 正向/反向行为用例：正常生成、分支缺失降阈值、模型过密升阈值、无改善停止、工具失败停止、越界参数拒绝、报告冲突转人工复核。

**阶段完成标准：** 在模拟报告与真实工具目录下，Agnes 能按规则产生有限且可解释的下一轮参数；不会调用未授权参数、重复候选或绕过 `review` 状态发布结果。

### 8.7 阶段 E：注册到 Agnes Harness 并验证真实调用

- [x] 为 VesselPilot MCP 准备可移植启动入口和注册命令，使用 `runtime/python/BrainAAL/python.exe`，默认病例根为 `workspace/vessel-pilot`。
- [x] 已将更新后的 11 工具目录重新加载到本机 AGH local-dev，确认 `connection=ready`，文件夹选择与调参建议工具在目录中可见。
- [x] 已刷新测试会话实际使用的 `MRI2MR-core` 工作区 Skill；本机状态为 `trust=trusted`、`desired=enabled`、`actual=ready`、`winner`。
- [ ] 新会话中显式调用 `vessel-pilot` Skill，确认模型上下文已加载正确版本，并确认 MCP 工具目录与 Skill 中的工具名一致。
- [ ] 从用户给出的 DICOM 入口跑一次完整流程，核对 AGH 轨迹中确有 `tools/call`、参数、返回状态和产物引用，而不是只有自然语言模拟。
- [ ] 验证资源更新边界：修改 Skill 或 MCP 定义后重新审核 revision，并在新一轮/新会话确认生效，不把“文件已修改”当成“AGH 已加载”。
- [ ] 验证断线、AGH 重启、MCP 重启、任务取消和重复提交后不会重复生成或丢失已完成候选。

**阶段完成标准：** 用户在 AGH 提供一个受支持的 DICOM 入口后，系统可在同一病例任务中得到可下载/可定位的动脉和静脉 GLB，并能从最终产物反查完整工具轨迹。

### 8.8 阶段 F：自动优化、导出与端到端验收

- [ ] 正常样例：基线或有限调参后同时导出合格动脉/静脉 GLB，所有硬门槛通过。
- [ ] 边界样例：构造或选择模型过大、过密、分支缺失场景，证明参数方向正确且报告指标改善。
- [ ] 失败样例：缺少 MRV、损坏 DICOM、空分割、外部工具失败、超时、磁盘不足和全部候选不合格时安全退出，不留下“成功”假象。
- [ ] 安全样例：验证路径穿越、符号链接逃逸、额外 CLI 参数、越界数值、超长 ID、并发超配额和恶意 ZIP（若支持）均被拒绝。
- [ ] 可复现性：同一输入指纹、参数和版本重复运行，产物指标在约定容差内一致；报告记录不能被后续候选覆盖。
- [ ] 性能：记录转换、动脉、首次静脉、缓存静脉、评估各阶段耗时、峰值内存和磁盘占用，确认满足阶段 0 预算。
- [ ] 人工验收：至少由一名领域人员盲审最终模型与预览，记录通过/失败/复核结论及原因。
- [ ] 生成最终 `manifest.json`，列出两份 GLB、预览、报告、参数、输入指纹、工具/Skill/配置版本、校验和及 AGH 轨迹索引。
- [ ] 保存正常、边界、失败三类完整 AGH 轨迹和真实工具调用证据，录制 3–5 分钟演示视频。
- [ ] 完成 README、安装/启动配置、依赖清单、复现步骤、已知限制和非临床用途免责声明。
- [ ] 发布前扫描仓库和演示材料，确认不含患者原始数据、直接标识符、密钥、机器私有路径和未授权资产。

### 8.9 建议实施顺序与里程碑

| 里程碑 | 依赖 | 可演示结果 |
| --- | --- | --- |
| M0：合同冻结 | 无 | 输入/输出 Schema、三参数白名单、质量阈值和预算已确认 |
| M1：单候选工具化 | M0、阶段 A/B | AGH 经 MCP 对一个病例完成转换并生成一组动静脉 GLB |
| M2：质量闭环 | M1、阶段 C | 每个候选有结构化报告和六视角预览，可判定 pass/fail/review |
| M3：智能调参 | M2、阶段 D | Agnes 在有限预算内自动选择新参数并停止于最佳候选或人工复核 |
| M4：AGH 集成验收 | M3、阶段 E/F | 从 DICOM 入口到最终双 GLB、manifest 和完整 AGH 轨迹端到端通过 |

> 实施时不要先写“全自动优化”再补工具合同。优先完成 M0 与 M1，使真实的 DICOM → NIfTI → 动/静脉 GLB 链路可调用、可取消、可追溯，再接质量评估和模型决策。

### 8.10 AGH 资源实例与工作区排错记录

首次 AGH 测试曾返回“找不到 `vessel-pilot` 工具或 Skill”。原因不是血管算法缺失，而是资源注册上下文不一致：

- 浏览器连接的 daemon 使用 `agnes-harness/agh-home/data`，而 MCP 曾误注册到 `C:/Users/admin/.agh/data`；两个实例都叫 `local-dev`，但控制面数据互不相通。
- 测试会话 cwd 是 `MRI2MR-core`，而 Skill 曾放在 `agnes-harness/.agh/skills`；工作区 Skill 只从当前会话工作区的 `.agh/skills` 发现。

修复后的约束：

- [x] 启动 Web、daemon 和执行 `mcp`/`skills` 管理命令前，显式使用同一个绝对 `AGH_HOME`；当前本机为 `agnes-harness/agh-home`。
- [x] 当前 MCP 在浏览器连接的实例中已刷新为 11 个工具，`connection=ready`；本机 Web 已切换到包含 MCP 图片限额的新构建，仍使用 4177 端口和原数据目录。
- [x] Skill 已迁移到 `MRI2MR-core/.agh/skills/vessel-pilot/SKILL.md`，根工作区状态为 `actual=ready` 且为同名 winner。
- [x] 已停止无会话的 `C:/Users/admin/.agh/data` 错误 daemon；未删除其数据。浏览器使用的 `agnes-harness/agh-home/data` daemon 保持运行。
- [ ] 资源变更后在新一轮或新会话重新测试真实 DICOM 调用；旧的进行中轮次持有不可变资源快照，不以磁盘文件存在或另一实例显示 ready 作为成功依据。

排错时按以下顺序检查：当前 Web 进程 → daemon 的 `data-dir`/origin → `AGH_HOME` → 会话 cwd → Skill workspace ID → MCP status/tools → 新一轮真实 `tools/call`。

### 8.11 长耗时任务的轮询与用户提示

动静脉候选重建按约 20 分钟设计，首次 MRV Frangi 计算可能更久。此前真实轨迹中，同一作业 14 分钟内调用 `get_vessel_job` 94 次，绝大多数间隔小于 60 秒；模型还曾把约 8–13 分钟误报为 31–75 分钟。根因是 Skill 的间隔仅为提示、MCP 未强制等待，并且模型自行解释时间戳或进程信息。

修复后由 MCP 服务端而非模型控制频率和计时：

- `get_vessel_job(wait_seconds=55)` 是长轮询：非终态调用会在 MCP 进程内等待最多 55 秒，或在 `status/phase` 变化时提前返回，因此即使模型立即再次调用也不会形成秒级空转。当前 Agnes MCP SDK 单次调用默认 60 秒超时，55 秒为传输和处理预留余量；若将来要严格 60–120 秒单次等待，需要同步提高 Harness 调用超时。
- 状态包含 `dicom_conversion / artery_reconstruction / vein_reconstruction / complete` 等阶段，Agnes 不再通过 shell、PID 或日志探测存活。
- 服务端返回权威 `elapsed_seconds` 和 `elapsed_minutes`；Agnes 只能引用这两个字段，不得自行从时间戳、CPU 时间、轮询次数或“体感”换算。
- 非终态响应去除日志路径和重复耗时提示，使用 `observation_token` 与 `unchanged` 表达是否发生变化，降低每次调用的上下文体积。
- 非终态作业的普通进度最多每 2–4 分钟汇报一次，避免每次轮询都重复相同消息。
- `queued → running`、阶段变化、完成、取消和失败立即汇报；用户主动询问时立即查询一次。
- 长时间保持 `running` 不直接判定失败，不自动重试，也不重复提交相同候选。
- 终态返回的建议轮询间隔为 0，收到终态后停止轮询并进入评估或失败处理。

### 8.12 会话输入与 AI 调参闭环

- 会话示例：`使用 vessel-pilot。请打开文件夹选择器，我来选已脱敏的 DICOM 目录；完成后生成动脉和静脉 GLB。` 或 `使用 vessel-pilot，把已脱敏的 C:\Users\admin\Desktop\MRI2MR-core\workspace\Data_vessel_01 重建为动脉和静脉 GLB。`
- 用户直接粘贴目录时，Skill 将路径原样传给 `inspect_dicom_case`，服务端完成规范化和 input-root 校验。
- 用户要求“选择文件夹”或没有提供入口时，Agnes 调用 `choose_dicom_folder` 打开 Windows 原生目录对话框；取消、越界路径均不会登记病例。选择目录不等同于确认脱敏。
- `evaluate_vessel_candidate` 除十二张固定视角 PNG 外，还生成动脉与静脉各一张六视角拼图，并直接作为 MCP 图片内容送入会话。
- Harness 的 MCP 图片通道启用了明确上限：单次最多 2 张，每张不超过 2 MiB、总像素不超过 `1456²`；旧构建虽可生成图片，但会拒绝送入模型。当前本地 Web 已重新构建并启动，Python 协议与 Harness 图片桥接测试均通过。
- 如果所选模型不支持图片理解，Agnes 应将视觉判断设为 `uncertain` 并请求人工复核。
- Agnes 对每侧仅给出 `good / too_dense / too_sparse / uncertain` 四类技术视觉判断；`uncertain` 立即转人工复核，不能自动发布。
- `suggest_vessel_parameters` 根据该判断从白名单中选择一个未运行组合，一次只改一个参数；它只建议，不自动启动长任务。
- 自动搜索最多 6 个候选，已有技术通过且两侧视觉均为 `good`、连续两轮无明确改善、工具失败/取消或视觉不确定时停止。

本轮验证：VesselPilot Python 测试 8/8 通过（含 DICOM 目录选择路径校验、MCP 两张图片返回、建议参数和取消长轮询）；Harness MCP 图片桥接测试 15/15 通过，`packages/base` 类型检查通过；本机 Web `HTTP 200`，MCP 11 工具 `ready`，根工作区 Skill `ready/winner`。原生对话框的人工点击和完整约 20 分钟真实重建仍需在 Agnes 新一轮会话中验收。

## 9. 推荐目录结构

~~~
MRI2MR-core/
├── .agh/
│   └── skills/
│       └── vessel-pilot/
│           └── SKILL.md       # AGH 工作区 Skill：规划、调参和停止规则
├── agnes-harness/
│   └── integrations/
│       └── vessel-pilot/      # 受约束的 stdio MCP 服务、工具 Schema 和作业管理
├── vessel_tool/
│   ├── convert_dicom.py        # DICOM → NIfTI
│   ├── reconstruct_artery.py   # 动脉重建
│   ├── reconstruct_vein.py     # 静脉重建
│   ├── render_preview.py       # 固定视角预览
│   └── evaluate_candidate.py   # 文件大小、网格和连通性评估
├── configs/                    # 固定参数、三参数白名单、预算和评分规则
├── schemas/                    # MCP 输入输出、report 和 manifest JSON Schema
├── tests/                      # 正常、边界、失败、安全和端到端测试
├── examples/                   # 脱敏/合成小样例；不放患者原始数据
├── docs/                       # 架构、数据说明和竞赛证据
└── README.md                   # 安装、运行、复现、限制与免责声明
~~~

## 10. 独立血管脚本命令行手册

当前独立实现位于 `scripts/Vascular_cmd.py`，只包含以下三项血管相关能力，不会 import `Main_cmd.py`：

- `dicom_convert`：DICOM 转标准化 T1/MRA/MRV NIfTI。
- `artery`：MRA 动脉预处理和 GLB 重建；兼容模式名 `vessel`。
- `vein`：MRV 静脉预处理和 GLB 重建；兼容模式名 `mrv`。

以下命令均以 Windows PowerShell 为例。先定义 Python 和脚本路径：

~~~powershell
$python = "C:\Users\admin\Desktop\MRI2MR-core\runtime\python\BrainAAL\python.exe"
$script = "C:\Users\admin\Desktop\MRI2MR-core\scripts\Vascular_cmd.py"
~~~

查看脚本提供的全部参数：

~~~powershell
& $python $script --help
~~~

脚本成功时退出码为 `0`，发生输入、转换或重建错误时退出码为 `1`。

### 10.1 默认目录约定

只设置 `--base-data-dir D:\Patient01` 时，脚本使用以下目录：

~~~text
D:\Patient01\
├── patient_input\
│   ├── T1.nii                 # 可选；没有 T1 时可用 MRA 统一空间
│   ├── MRA.nii
│   ├── MRV.nii
│   └── dicom_selection.json
├── model_output\
│   ├── vessel\vessel.glb
│   └── mrv\vessel_vein.glb
└── temp\
    ├── dicom2niix_output\
    ├── dicom_dcmtk_decompressed\
    ├── dicom_candidates.json
    └── out_figma12_1000.nii   # MRV Frangi 缓存
~~~

通用目录和输入参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--mode` | 必填 | `dicom_convert`、`artery`、`vein`、`vessel` 或 `mrv` |
| `--base-data-dir` | `<项目>/workspace/default` | 病例工作根目录 |
| `--patient-data-dir` | `<base>/patient_input` | 标准化 NIfTI 存放目录 |
| `--output-dir` | `<base>/model_output` | GLB 输出根目录 |
| `--t1-file` | `<patient_input>/T1.nii` | 自定义 T1 输入路径 |
| `--mra-file` | `<patient_input>/MRA.nii` | 自定义 MRA 输入路径 |
| `--mrv-file` | `<patient_input>/MRV.nii` | 自定义 MRV 输入路径 |

### 10.2 DICOM 转 NIfTI

#### 自动识别并转换 T1、MRA、MRV

~~~powershell
& $python $script `
  --mode dicom_convert `
  --dicom-dir "D:\Patient01\DICOM" `
  --dicom-modalities T1 MRA MRV `
  --base-data-dir "D:\Patient01"
~~~

`--dicom-modalities` 默认值就是 `T1 MRA MRV`。没有 T1 的纯血管数据应明确指定：

~~~powershell
& $python $script `
  --mode dicom_convert `
  --dicom-dir "D:\Patient01\DICOM" `
  --dicom-modalities MRA MRV `
  --base-data-dir "D:\Patient01"
~~~

脚本会根据序列描述、协议名、序列名和影像类型选择候选，同时降低 MIP、BatchMIP、MPR、Scout、Localizer 等派生序列的优先级。选择结果写入 `patient_input/dicom_selection.json`，全部候选写入 `temp/dicom_candidates.json`。

#### 对 JPEG 压缩 DICOM 先使用 DCMTK 解压

解压只操作工作目录中的副本，不修改原始 DICOM：

~~~powershell
& $python $script `
  --mode dicom_convert `
  --dicom-dir "D:\Patient01\DICOM" `
  --dicom-modalities MRA MRV `
  --base-data-dir "D:\Patient01" `
  --dcm2niix-exe "C:\path\to\dcm2niix.exe" `
  --dicom-decompress-dcmtk `
  --dcmtk-dcmdjpeg-exe "C:\path\to\dcmdjpeg.exe"
~~~

#### 手动指定已有 NIfTI

`--dicom-*-source` 可以是 `.nii`、`.nii.gz`，也可以是只包含一个序列的 DICOM 文件夹：

~~~powershell
& $python $script `
  --mode dicom_convert `
  --base-data-dir "D:\Patient01" `
  --dicom-modalities MRA MRV `
  --dicom-mra-source "D:\Input\artery.nii.gz" `
  --dicom-mrv-source "D:\Input\vein.nii.gz"
~~~

如需同时导入 T1：

~~~powershell
& $python $script `
  --mode dicom_convert `
  --base-data-dir "D:\Patient01" `
  --dicom-modalities T1 MRA MRV `
  --dicom-t1-source "D:\Input\t1.nii.gz" `
  --dicom-mra-source "D:\Input\artery.nii.gz" `
  --dicom-mrv-source "D:\Input\vein.nii.gz"
~~~

#### DICOM 参数接口

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--dicom-dir` | 无 | 包含多个序列的总 DICOM 目录；自动选择模态时必填 |
| `--dicom-modalities` | `T1 MRA MRV` | 需要转换的模态，可指定 `MRA MRV` 跳过 T1 |
| `--dicom-temp-dir` | `<base>/temp/dicom2niix_output` | dcm2niix 临时输出目录；重新转换会清理并重建此目录 |
| `--dcm2niix-exe` | `dcm2niix.exe` | dcm2niix 可执行文件名或完整路径 |
| `--dcmtk-dcmdjpeg-exe` | `dcmdjpeg.exe` | DCMTK dcmdjpeg 可执行文件名或完整路径 |
| `--dicom-decompress-dcmtk` | 关闭 | 转换前复制并解压 DICOM |
| `--dicom-decompress-dir` | `<base>/temp/dicom_dcmtk_decompressed` | DICOM 解压副本目录 |
| `--dicom-t1-source` | 无 | 手动 T1 NIfTI 或单序列 DICOM 文件夹 |
| `--dicom-mra-source` | 无 | 手动 MRA NIfTI 或单序列 DICOM 文件夹 |
| `--dicom-mrv-source` | 无 | 手动 MRV NIfTI 或单序列 DICOM 文件夹 |
| `--dicom-t1-keywords` | `t1 mprage bravo spgr tfl 3dt1` | 自定义 T1 匹配关键词，空格分隔 |
| `--dicom-mra-keywords` | `mra tof angio artery` | 自定义 MRA 匹配关键词，空格分隔 |
| `--dicom-mrv-keywords` | `mrv venography venogram vein venous` | 自定义 MRV 匹配关键词，空格分隔 |

自定义关键词示例：

~~~powershell
& $python $script `
  --mode dicom_convert `
  --dicom-dir "D:\Patient01\DICOM" `
  --dicom-modalities MRA MRV `
  --dicom-mra-keywords tof mra angio artery `
  --dicom-mrv-keywords pc3d mrv vein venous `
  --base-data-dir "D:\Patient01"
~~~

### 10.3 参考空间选择

参考空间参数用于动脉和静脉重建，优先级如下：

1. 如果设置 `--reference-file`，使用该 NIfTI，优先级最高。
2. `--reference-modality t1` 强制使用 T1。
3. `--reference-modality mra` 强制使用 MRA。
4. 默认 `--reference-modality auto`：T1 存在时使用 T1，否则自动回退到 MRA。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--reference-file` | 无 | 显式指定统一空间参考 NIfTI |
| `--reference-modality` | `auto` | 可选 `auto`、`t1`、`mra` |
| `--t1-file` | `<patient_input>/T1.nii` | T1 参考文件路径 |
| `--mra-file` | `<patient_input>/MRA.nii` | MRA 输入及可选参考文件路径 |

无 T1 时可依靠自动回退，也可明确指定：

~~~powershell
--reference-modality mra
~~~

使用任意自定义参考影像：

~~~powershell
--reference-file "D:\Input\reference.nii.gz"
~~~

> 当前“空间统一”使用 NIfTI affine 完成坐标转换，并不执行影像配准。如果 MRA 与 MRV 不是同一次检查、患者发生移动或头信息不可靠，应先进行刚性/仿射配准。

### 10.4 动脉预处理和重建

使用默认输入与输出路径：

~~~powershell
& $python $script `
  --mode artery `
  --base-data-dir "D:\Patient01"
~~~

无 T1 时强制使用 MRA 作为参考空间：

~~~powershell
& $python $script `
  --mode artery `
  --base-data-dir "D:\Patient01" `
  --reference-modality mra
~~~

完全指定输入、输出和主要参数：

~~~powershell
& $python $script `
  --mode artery `
  --mra-file "D:\Input\MRA.nii" `
  --reference-modality mra `
  --vessel-threshold 400 `
  --vessel-min-object-size 1000 `
  --vessel-decimation-fraction 0.5 `
  --marching-cubes-level 0.7 `
  --artery-output-file "D:\Output\artery.glb"
~~~

动脉处理步骤为：阈值分割 → 移除小区域 → 保留最大连通域 → Marching Cubes → Humphrey 平滑 → 减面 → 参考空间转换 → GLB 导出。

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `--mra-file` | `<patient_input>/MRA.nii` | MRA 输入文件 |
| `--vessel-threshold` | `400` | MRA 灰度分割阈值 |
| `--vessel-min-object-size` | `1000` | 初步清理时保留的最小体素数 |
| `--vessel-decimation-fraction` | `0.5` | 动脉减面后保留比例，范围 `(0, 1]` |
| `--marching-cubes-level` | `0.7` | 二值体积等值面提取阈值 |
| `--artery-output-file` | `<output>/vessel/vessel.glb` | 自定义动脉 GLB 路径 |

血管过少或分支断裂时可降低 `--vessel-threshold`；噪声或非血管结构过多时可提高阈值或 `--vessel-min-object-size`。

> CLI 的算法默认阈值是 `400`。本 README 第 4 节定义的 `800` 是竞赛智能体候选搜索的初始策略值，AGH 运行基线候选时必须显式传入 `--vessel-threshold 800`。

### 10.5 静脉预处理和重建

使用默认参数：

~~~powershell
& $python $script `
  --mode vein `
  --base-data-dir "D:\Patient01"
~~~

无 T1 时使用 MRA 作为参考空间：

~~~powershell
& $python $script `
  --mode vein `
  --base-data-dir "D:\Patient01" `
  --reference-modality mra
~~~

完整参数示例：

~~~powershell
& $python $script `
  --mode vein `
  --base-data-dir "D:\Patient01" `
  --reference-modality mra `
  --mrv-frangi-sigmas-start 1 `
  --mrv-frangi-sigmas-end 12 `
  --mrv-frangi-sigmas-step 1 `
  --mrv-strong-seed-percentile 99.9 `
  --mrv-strong-grow-tolerance 0.95 `
  --mrv-weak-seed-percentile 99.8 `
  --mrv-weak-grow-tolerance 0.85 `
  --mrv-post-process-min-size 1000 `
  --min-object-size 14500 `
  --mesh-decimation-fraction 0.08 `
  --marching-cubes-level 0.7
~~~

静脉处理步骤为：多尺度 Frangi 增强 → 强种子区域生长 → 弱种子区域生长 → 去除小区域和填孔 → Marching Cubes → Humphrey 平滑 → 减面 → 参考空间转换 → GLB 导出。

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `--mrv-file` | `<patient_input>/MRV.nii` | MRV 输入文件 |
| `--mrv-frangi-cache-file` | `<base>/temp/out_figma12_1000.nii` | Frangi 结果缓存路径 |
| `--force-rebuild-frangi` | 关闭 | 忽略已有缓存并重新计算 Frangi |
| `--mrv-frangi-sigmas-start` | `1` | Frangi 起始尺度 |
| `--mrv-frangi-sigmas-end` | `12` | Frangi 结束尺度，不包含该值；默认实际使用 1–11 |
| `--mrv-frangi-sigmas-step` | `1` | Frangi 尺度步长，必须大于 0 |
| `--mrv-strong-seed-percentile` | `99.9` | 强血管种子百分位，范围 `[0, 100]` |
| `--mrv-strong-grow-tolerance` | `0.95` | 强种子区域生长容差 |
| `--mrv-weak-seed-percentile` | `99.8` | 弱血管种子百分位，范围 `[0, 100]` |
| `--mrv-weak-grow-tolerance` | `0.85` | 弱种子区域生长容差 |
| `--mrv-post-process-min-size` | `1000` | 第一次后处理最小区域体素数 |
| `--min-object-size` | `14500` | 最终网格生成前最小区域体素数 |
| `--mesh-decimation-fraction` | `0.08` | 静脉减面后保留比例，范围 `(0, 1]` |
| `--marching-cubes-level` | `0.7` | 二值体积等值面提取阈值 |
| `--vein-output-file` | `<output>/mrv/vessel_vein.glb` | 自定义静脉 GLB 路径 |

首次运行会计算 Frangi 并保存缓存。后续运行会复用缓存；修改 Frangi 尺度或更换 MRV 后应执行：

~~~powershell
& $python $script `
  --mode vein `
  --base-data-dir "D:\Patient01" `
  --force-rebuild-frangi
~~~

脚本发现缓存尺寸与当前 MRV 不一致时会自动重新计算。

### 10.6 真实无 T1 数据集完整复现命令

以下命令已经在 `Data_vessel_01/20260208/MR` 数据集上实际验证。该数据的 JPEG Lossless 封装不能由 dcm2niix 直接解码，因此必须启用 DCMTK 解压：

~~~powershell
$python = "C:\Users\admin\Desktop\MRI2MR-core\runtime\python\BrainAAL\python.exe"
$script = "C:\Users\admin\Desktop\MRI2MR-core\scripts\Vascular_cmd.py"

$source = "C:\Users\admin\Downloads\aiying_export_20261011_160135_af24f88c\A01\Data_vessel_01\20260208\MR"
$output = "C:\Users\admin\Downloads\aiying_export_20261011_160135_af24f88c\A01\Data_vessel_01\20260208\test"

$dcm2niix = "C:\Users\admin\Desktop\MRI2MR-core\dcm2niix_win\dcm2niix.exe"
$dcmdjpeg = "C:\Users\admin\Desktop\MRI2MR-core\dcmtk-3.7.0-win64-dynamic\dcmtk-3.7.0-win64-dynamic\bin\dcmdjpeg.exe"

# 1. DICOM → MRA/MRV NIfTI
& $python $script `
  --mode dicom_convert `
  --dicom-dir $source `
  --dicom-modalities MRA MRV `
  --base-data-dir $output `
  --dcm2niix-exe $dcm2niix `
  --dicom-decompress-dcmtk `
  --dcmtk-dcmdjpeg-exe $dcmdjpeg

if ($LASTEXITCODE -ne 0) {
    throw "DICOM 转换失败"
}

# 2. 动脉重建
& $python $script `
  --mode artery `
  --base-data-dir $output `
  --reference-modality mra

if ($LASTEXITCODE -ne 0) {
    throw "动脉重建失败"
}

# 3. 静脉重建
& $python $script `
  --mode vein `
  --base-data-dir $output `
  --reference-modality mra

if ($LASTEXITCODE -ne 0) {
    throw "静脉重建失败"
}

Write-Host "全部处理完成：$output"
~~~

该数据集的实测自动选择结果：

- MRA：序列 401，`tof3d_tra`，尺寸 `550 × 672 × 276`。
- MRV：序列 501，`pc3d_sag_veins`，尺寸 `260 × 444 × 544`。
- MIP/BatchMIP 派生序列未被选择。
- 动脉输出：`model_output/vessel/vessel.glb`。
- 静脉输出：`model_output/mrv/vessel_vein.glb`。

高分辨率 MRV 首次执行多尺度 Frangi 时可能占用较多内存和时间；缓存生成后重复运行会显著加快。DICOM 解压副本和 dcm2niix 候选文件保留在 `temp` 中，确认结果后可按病例工作目录的清理策略处理。

## 11. 演示步骤

1. 在 AGH 中请求：将某病例 DICOM 自动生成适用于 MR 展示的脑血管模型。
2. AGH 调用 inspect_dicom_case 和 convert_dicom_to_nii。
3. Agnes 制定动脉和静脉首轮参数。
4. 调用重建工具，生成隔离保存的候选 GLB。
5. 调用评估工具，展示文件大小、连通性报告和六视角预览。
6. Agnes 按经验规则解释问题并选择下一轮三项参数。
7. 系统选择合格的最佳候选，调用导出工具固化最终模型。
8. 展示 AGH 轨迹、参数变化和最终质控报告。

## 12. 竞赛交付物检查清单

- [ ] 可运行的独立血管处理工具代码仓库。
- [ ] AGH 插件、Skill 与配置模板。
- [ ] DICOM 转 NIfTI、动脉重建、静脉重建、评估和预览源码。
- [ ] README：环境、安装、模型配置、运行命令、复现和限制说明。
- [ ] 参数范围、经验规则及 report.json Schema。
- [ ] 正常、边界、失败三类测试结果。
- [ ] 可人工核查的 AGH 执行记录和模型真实工具调用证据。
- [ ] 演示视频链接和公开项目介绍。
- [ ] 脱敏/合成样例或明确的数据获取说明。
- [ ] 第三方算法、依赖、模型和素材来源声明。

## 13. 风险与原则

- DICOM 与 NIfTI 必须脱敏并在受控本地目录处理；未经授权不得上传原始影像到云端模型。
- 大模型只能经受约束工具选择三项参数，不能任意读写文件、修改脚本或执行命令。
- 视觉判断是辅助质控；低置信度、质量冲突和无法达到硬约束的结果必须交由人工复核。
