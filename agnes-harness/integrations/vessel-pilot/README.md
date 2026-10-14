# VesselPilot integration

This integration exposes `scripts/Vascular_cmd.py` to Agnes Harness as a constrained local stdio MCP server. The versioned Skill source is `skill/SKILL.md`. Install it under the active `AGH_HOME/skills/vessel-pilot/` so it is available in every workspace opened by that Agnes instance.

## Runtime

The server discovers the parent `MRI2MR` checkout and uses:

- `runtime/python/BrainAAL/python.exe`, or `venv/runtime/python/BrainAAL/python.exe` in this checkout
- `scripts/Vascular_cmd.py`
- `dcm2niix_win/dcm2niix.exe`
- `dcmtk-3.7.0-win64-dynamic/dcmtk-3.7.0-win64-dynamic/bin/dcmdjpeg.exe`

By default, DICOM input must be below `MRI2MR/workspace`, and case output is written to `MRI2MR/workspace/vessel-pilot`. This deployment uses `--allow-any-input` because source datasets live outside the project. That flag permits only a directory explicitly selected or supplied by the user; case outputs remain under the controlled case root and the service does not scan unrelated directories.

## Local protocol smoke test

The default suite checks routing contracts, numeric validation, command construction and protocol behavior with fixtures and mocked jobs; it does not run DICOM conversion or vessel reconstruction. A separate synthetic reconstruction test is skipped unless `VESSELPILOT_RUN_RECONSTRUCTION_TESTS=1` is explicitly set.

```powershell
& "..\venv\runtime\python\BrainAAL\python.exe" -B -m unittest integrations\vessel-pilot\test_vessel_pilot.py -v
```

## Register in Agnes Harness

Build or use the existing local Agnes CLI, then register the Python process as a stdio MCP server. Every `--arg` is a separate process argument.

```powershell
$env:AGH_HOME = (Resolve-Path ".\agh-home").Path
$env:AGNES_PROFILE = "local-dev"
$agnes = "packages\cli\dist\local\agnes.mjs"
$python = (Resolve-Path "..\venv\runtime\python\BrainAAL\python.exe").Path
$server = (Resolve-Path "integrations\vessel-pilot\server.py").Path
$inputRoot = (Resolve-Path "..\workspace").Path
$caseRoot = Join-Path $inputRoot "vessel-pilot"

node $agnes mcp add vessel-pilot `
  --name "VesselPilot" `
  --stdio $python `
  --arg $server `
  --arg "--input-root" `
  --arg $inputRoot `
  --arg "--allow-any-input" `
  --arg "--case-root" `
  --arg $caseRoot `
  --allow-tool choose_dicom_folder `
  --allow-tool inspect_dicom_case `
  --allow-tool get_vessel_case `
  --allow-tool start_dicom_conversion `
  --allow-tool start_vessel_candidate `
  --allow-tool get_vessel_job `
  --allow-tool cancel_vessel_job `
  --allow-tool list_vessel_candidates `
  --allow-tool evaluate_vessel_candidate `
  --allow-tool suggest_vessel_parameters `
  --allow-tool finalize_vessel_case
```

Run these commands from `MRI2MR/agnes-harness` with the same `AGH_HOME` and profile used by WebUI. The current project-local home is `MRI2MR/agnes-harness/agh-home`; using another home creates a separate control plane.

For normal Web startup, run `MRI2MR/start_agnes.ps1` from the project root. It pins this checkout's home/profile, so they do not need to be typed on each launch.

The canonical local executable is `packages\cli\dist\local\agnes.mjs`. After changing Harness or composer source, rebuild that exact entry before testing:

```powershell
corepack pnpm --filter @agnes/cli build:local
```

Versioned directories such as `dist\local-vessel-pilot-*` may be used for isolated build checks only. Do not leave WebUI and daemon running from different build directories.

The MCP definition is created disabled and untrusted. Review it in **Settings → MCP**, then enable it. A normal local instance can approve the exact native Python executable through this review. If an administrator enforces a deployment allowlist, `AGNES_MCP_STDIO_ALLOWLIST` must contain the exact executable path; pre-setting that variable disables dynamic local approvals.

Install the user-level Skill into the same `AGH_HOME`, then refresh and enable it once for the profile:

```powershell
.\integrations\vessel-pilot\install-skill.ps1 -AgnesHome $env:AGH_HOME
node $agnes skills refresh --root-key user-agnes
node $agnes resources list --kind skill
```

In **Settings → Skills**, review and enable the `user/user-agnes` source. It is available in every selected workspace of this Agnes instance; a workspace-level Skill with the same name takes precedence and must be removed or explicitly reprioritized. Start a new turn or chat and explicitly ask Agnes to use `vessel-pilot`. Skill instructions do not install the MCP server: the MCP must also be enabled in this same home/profile.

## Diagnose missing tools

If Agnes says that `vessel-pilot` or its tools do not exist:

1. Check the Web and daemon command lines and confirm they use the same `AGH_HOME`, profile, data directory, and origin.
2. Run `mcp list/status/tools` only after setting that same `AGH_HOME`.
3. Confirm `AGH_HOME/skills/vessel-pilot/SKILL.md` exists and `user/user-agnes` is `ready`; a different `AGH_HOME` has a different Skill registry.
4. Confirm the Skill is `trust=trusted desired=enabled actual=ready winner` in the selected workspace. Check for a same-name workspace Skill shadowing the user-level one.
5. Confirm the MCP is `connection=ready` and exposes eleven tools, then begin a new turn so the resource snapshot is reloaded.

## Conversation entry points

The user may paste one or more absolute DICOM directory paths into the chat, ask Agnes to choose one folder through `choose_dicom_folder`, or use the folder button beside the composer attachment control. Both Windows picker entry points use an invisible modal owner that is pinned to the native topmost Z-order with `SetWindowPos(HWND_TOPMOST)` and promoted with `SetForegroundWindow`, so the dialog stays above the browser even when it is launched by the background Web or MCP process. The composer button appends a removable directory attachment to the draft, preserving existing text and attachments. It does not submit a message or generate reconstruction instructions. The backend resolves and checks directory readability and returns only input data. The user must enter a prompt and send it with the attachments; the agent then determines the requested scope before choosing tools. Cancellation and unreadable directories add nothing.

This is a local-directory handoff: the loopback Web launcher and local VesselPilot MCP use the same machine/account and read the selected absolute roots directly, including roots outside the session working directory when the MCP's configured input policy allows them. Large DICOM trees are not copied to temp or embedded in the model context. Keep selected directories available until processing finishes. This does not implement uploads from a remote browser to a different host. After manual submission, the original input attachment persists with the session. The backend projects `application/vnd.agnes.input+json` v1 input fields as untrusted data, ignoring any instruction field; the user's text determines the task. Existing explicit task attachments retain their previous projection for compatibility, but the DICOM picker no longer produces them. Selecting folders does not count as a reconstruction request or confirmation that the data is deidentified.

The composer entry has a visible “Select a DICOM folder” label beside the attachment control. If `GET /api/dicom-picker` returns 404, the Web service is running an older build: rebuild the local CLI and restart both the Web service and daemon with the same `AGH_HOME`, then reload the browser. Updating source files alone does not update `dist/local`. The generic `/api/folder-picker` path-list API is unchanged for other callers.

After either entry path, `inspect_dicom_case` performs the same allowlist and file-count checks. The model never receives permission to browse arbitrary directories.

Example chat requests:

```text
把这个已脱敏 DICOM 目录转成 nii，只要转换结果路径。
只重建动脉，阈值 850，保留网格面数比例 0.4。
只重建静脉，弱生长容差 0.87，其他参数用默认值。
只优化静脉，最多比较 4 个候选；弱生长容差在 0.83、0.85、0.87 中调整，固定最终最小区域为 14500。
使用 vessel-pilot。请打开文件夹选择器，我来选已脱敏的 DICOM 目录；完成后生成动脉和静脉 GLB。
使用 vessel-pilot，把已脱敏的 C:\Users\admin\Desktop\MRI2MR-core\workspace\Data_vessel_01 重建为动脉和静脉 GLB。
使用 vessel-pilot，批量处理以下已脱敏的 DICOM 目录，每个目录作为独立病例，最多并行两例：C:\Data\case-01 和 D:\MRI\case-02。
```

For the request to open a picker, Agnes should call `choose_dicom_folder` and wait for the user's selection. For attached or supplied paths, it should not open another dialog. Batch cases retain independent case/job/candidate identifiers and run at most two long jobs concurrently.

## Capabilities and parameters

### Conversation previews

The Agnes chat (port 4177) keeps visualization cards visible even when the execution trace is collapsed. `inspect_dicom_case` returns a bounded sample of original grayscale DICOM pixels (up to 2048 scanned files and three series, with no patient metadata overlays). Successful conversion polling and reused conversions return NIfTI middle slices in three canonical directions, respecting voxel spacing and using only the first frame for 4D volumes. Up to three converted volumes are shown per result, stacked in one composite image with numbered volume labels; all output paths remain in the tool details. The MCP production limit is two image blocks per result. NIfTI replies use one image and dual-vessel replies use at most two, each within the byte and pixel budgets. If a previous poll failed with `image count exceeds media limit`, poll that completed job again after reconnecting the updated MCP; do not rerun conversion.

Every `evaluate_vessel_candidate` shows the requested vessel's six-view GLB montage, case/candidate IDs, effective parameters, file size, vertices and faces. `suggest_vessel_parameters` shows that candidate's images, the Agent's assessments, its reason and the proposed parameter changes. `finalize_vessel_case` repeats the selected model preview. This implementation uses six-view images rather than an interactive GLB viewer. Each candidate remains a separate card so iterations can be compared without overwriting earlier results.

The MCP reply includes a version-1 `visualization` object and standard image content blocks. The Web client reads complete recorded tool details rather than parsing the clipped timeline preview, verifies each image descriptor against an artifact link in that same result, then uses the existing authenticated session artifact reader. No arbitrary local-file HTTP endpoint is added. Preview errors leave processing results intact; unavailable/compressed DICOM pixels produce a visible note, and failed image reads retain the candidate's parameters and metrics. Object URLs are released on unmount and session changes. Pre-update chat records do not contain this metadata; evaluate an existing candidate again to create a preview card without rebuilding it.

After updating source, rebuild `dist/local`, restart the Web service and its daemon, then reload the browser. The Python MCP process must also be restarted to load the new reply enrichment. Existing candidates and output files can be reused.

Synthetic preview checks (no patient data or long reconstruction jobs):

```powershell
& "..\venv\runtime\python\BrainAAL\python.exe" -B -m unittest integrations\vessel-pilot\test_vessel_pilot.py integrations\vessel-pilot\test_visualization.py -q
corepack pnpm exec vitest run packages/web/test/vessel-tool-preview.test.tsx packages/web/test/conversation-message-adapter.test.ts --maxWorkers=1
```

This remains the same `vessel-pilot` MCP server with eleven tools. Intent routing belongs to `skill/SKILL.md`; the MCP schema, service validation and job runner enforce the selected scope. No second MCP or independent medical algorithm is introduced. The implementation still runs `scripts/Vascular_cmd.py`.

| Tool | Capability and configurable inputs |
| --- | --- |
| `choose_dicom_folder` | Select one local input folder when requested. |
| `inspect_dicom_case` | Check and register the selected input; `input_path`, `confirm_deidentified`, optional `case_id`. |
| `get_vessel_case` | Read conversion status, exact NIfTI paths, available reconstruction targets and candidate count. |
| `start_dicom_conversion` | `conversion_mode`: `nifti` (all convertible series), `artery` (MRA), `vein` (MRV), or `vessel` (both, legacy default); `decompress_with_dcmtk` defaults to true. |
| `start_vessel_candidate` | Run one candidate with `target=artery/vein/both` (legacy default: both), optional numeric `parameters`, and immutable `candidate_id`. |
| `get_vessel_job` | Read progress; `wait_seconds` is 1–55, default 55. |
| `cancel_vessel_job` | Cancel the specified job and its child process tree. |
| `list_vessel_candidates` | Read candidates, targets, effective parameters and existing reports. |
| `evaluate_vessel_candidate` | Check requested output meshes and return corresponding montage images and metrics. |
| `suggest_vessel_parameters` | Suggest one untried change from the relevant visual assessment; optional `search_space`, `locked_parameters`, and `max_candidates` (1–100, default 6). Does not execute a candidate. |
| `finalize_vessel_case` | Save the selected technically passing candidate and return exact artifact paths and checksums. |

`parameters.py` is the shared definition for fourteen numeric parameters and their defaults, bounds and side-specific applicability. The complete user-facing table is in [the Skill](skill/SKILL.md#可指定的重建参数). Artery options cover intensity threshold, component size and mesh retention; vein options cover Frangi scales, strong/weak seed percentiles and growth tolerances, two component-size filters and mesh retention. `marching_cubes_level` applies to the requested vessel(s). All numeric parameters accept values within their bounds rather than a small discrete preset list. Integer sizes and scales must be integers, and invalid cross-parameter combinations are rejected before launching a job.

For example, `start_vessel_candidate(case_id=..., candidate_id=..., target="artery", parameters={"vessel_threshold": 850, "vessel_decimation_fraction": 0.4})` launches only the artery stage. Explicit user values are preserved, while omitted applicable parameters use defaults. The historical top-level `vessel_threshold`, `mrv_weak_grow_tolerance`, and `mrv_post_process_min_size` arguments remain supported for existing callers; conflicting duplicate values are rejected. Single-side requests must not pass parameters that apply only to the other side.

An ordinary reconstruction runs one candidate. Only an explicit request to optimize or compare settings starts a bounded search. “Automatic reconstruction” alone does not authorize additional candidates. Frangi cache keys include both the source MRV hash and scale parameters, so changing scales cannot reuse an incompatible cached filter result.

## Safety boundary

- The server maps case IDs to local directories. `--allow-any-input` relaxes only the read-side root check for a user-selected or explicitly supplied directory; outputs still stay under `--case-root`.
- Candidate IDs are immutable.
- Only the fourteen documented numeric reconstruction parameters are accepted, with type/range and target validation. Tool inputs cannot introduce arbitrary command-line flags or executable paths.
- Subprocess commands use fixed executables and argument arrays; the model cannot provide shell text.
- `conclusion=pass` means technical mesh checks passed. It is not clinical validation, and the manifest retains `clinical_quality_review_required=true`.

## Failure and boundary behavior

### Format-only conversion and Windows paths

For a request to convert DICOM to `.nii` only, call `start_dicom_conversion` with `conversion_mode="nifti"`. This converts all convertible series into `patient_input/nifti`, checks readable NIfTI headers and payloads, and returns exact paths in `result.outputs` and `get_vessel_case.nifti_outputs`. It does not require an MRA/MRV pair or restrict the result to non-degenerate 3D reconstruction inputs. `artery` prepares only MRA, `vein` only MRV, and the default `vessel` preserves MRA+MRV behavior. After conversion finishes, a case without candidates may prepare a different scope for a later user request. Once any candidate exists, register a new case to prepare different inputs; existing candidate sources must not be overwritten. A NIfTI-only case must prepare the required reconstruction input before starting candidates.

The MCP server explicitly configures stdin/stdout as UTF-8. Windows' default GBK decoding can corrupt a UTF-8 JSON request containing Chinese paths, producing a parse error with `id=null` while the client waits for the original request ID until timeout. A timeout is not evidence that a scan took too long or that the directory is inaccessible. After updating `server.py`, reconnect the VesselPilot MCP service so the running process and tool schema are refreshed. The protocol regression test forces a GBK parent environment and sends actual Unicode JSON with Chinese input and Unicode output paths.

The following modality restrictions apply to reconstruction input preparation (`artery`, `vein`, `vessel`). Input path checks and fingerprint checks apply to all four conversion modes.

Input inspection is deliberately lightweight: it recognizes non-empty `.dcm`, `.dicom`, and `.ima` files or files with the standard `DICM` preamble. This is a compatibility preflight, not proof that every file is valid DICOM. The actual converter remains authoritative.

| Situation | Behavior |
| --- | --- |
| Missing/unreadable path, empty folder, only unrelated files, only zero-byte DICOM-like files | Reject before creating a case with a stable `INPUT_*` error. |
| Symbolic link below the selected folder | Reject; the service never follows it outside the reviewed input tree. |
| DICOM-like files mixed with notes, JSON, or empty files | Register the case, return exact preflight counts, and emit warnings; unrelated files are not treated as target series. |
| Source files change after inspection | Reject conversion with `INPUT_CHANGED_SINCE_INSPECTION`; inspect again instead of running against a stale fingerprint. |
| A conversion is already queued/running | Return that job with `already_running=true` for the same mode; reject a different mode until the job ends. Never launch a second writer for the case. |
| Extra T1, diffusion, or unrelated series | Keep them in selection evidence but exclude them from MRA/MRV eligibility. |
| MIP, MPR, Scout, Localizer, unreadable, 2D, 4D, or degenerate converted series | Exclude them from reconstruction candidates. |
| Several usable candidates match one modality | Rank deterministically and return `multiple_matching_candidates_ranked_deterministically`; review `dicom_selection.json` before continuing automatically. |
| Only MRA or only MRV is available | Succeed for a request requiring that modality only; fail with `MISSING_REQUIRED_MODALITY` if the requested modality is missing or `vessel` requires the pair. |
| MRA and MRV resolve to the same source series in `vessel` mode | Fail with `AMBIGUOUS_MODALITY_SELECTION`. |
| Converted NIfTI is unreadable, non-3D, degenerate, has non-finite affine values, or invalid voxel sizes | Fail with `INVALID_CONVERTED_NIFTI`. |
| Retrying after a failed conversion | Remove the prior generated MRA/MRV and selection summary before the new command, preventing stale halves from being combined. |

Candidate generation requires `conversion_status=succeeded` plus the requested inputs: MRA for artery, MRV for vein, both for a combined candidate. A vein-only candidate uses MRV as its reference space and does not require MRA or T1. New conversions persist each validated output's size and SHA-256, and candidate generation rejects later changes to those files. A failed or partial conversion cannot advance merely because files with the expected names remain on disk. Candidates run sequentially within one case; independent cases may run concurrently. In batch mode, stop only the affected case and continue other independent cases.

## Human confirmation in WebUI

VesselPilot's skill calls Harness `request_user_input` for missing deidentification confirmation, ambiguous sequence choices and human review. The WebUI shows a card above the chat composer with the question, context and options; the choice returns as a tool result to the same running turn. No extra chat message is needed, and `request_user_input` has no default deadline. Cancellation, an unavailable approver or an invalid choice never authorizes reconstruction.

Native action approvals now also wait without a deadline by default (`approval.timeout_ms: 0`). Positive values keep timed rejection behavior. `tools.timeouts.request_user_input: 0` keeps human input separate from ordinary tool execution limits. These waits do not consume MCP's 60-second call timeout. Rebuild the canonical local CLI/Web bundle and reinstall the skill into the configured Agnes home after updating. Existing sessions may keep their saved preset; check the effective preset when resuming an older session.

Keep the browser and backend connected while deciding. Closing the page, switching sessions, stopping the task or losing the connection cancels/refuses a live request; this change does not add durable approval recovery across disconnects or daemon restarts. The recorded task and existing reconstruction outputs remain available.

## Long-running jobs

One artery/vein candidate normally takes about 20 minutes, and the first MRV Frangi calculation can take longer. `get_vessel_job` is a server-side long poll: each non-terminal call waits up to 55 seconds or returns early when status/phase changes. The 55-second cap leaves room before the current Agnes MCP SDK's 60-second per-call timeout. It returns authoritative `elapsed_seconds` and `elapsed_minutes`; the model must not derive elapsed time from timestamps.

- Call `get_vessel_job(wait_seconds=55)` for non-terminal work. The wait is enforced in the MCP process, preventing fast model loops from producing repeated payloads.
- Report unchanged progress to the user no more than every 2–4 minutes.
- Report state transitions, completion, cancellation, and failure immediately.
- A long unchanged `running` state is not itself a failure. Do not resubmit the same immutable candidate or launch a duplicate job.
- Running responses are compact and omit log paths and repeated notices. `phase` identifies DICOM conversion, artery reconstruction, vein reconstruction, and completion.

## Automatic parameter refinement

`evaluate_vessel_candidate` performs technical mesh checks and returns six-view montage images only for the requested vessel(s). For combined candidates it also reports `vein_distribution_proxy`: vein triangle area inside versus outside an artery-derived bounding box expanded by 15%. This enables within-case comparison of intracranial versus scalp/peripheral vein tendency after face-only deidentification, but it is not skull segmentation and must not be treated as a clinical anatomical label. Single-side candidates return this proxy as null with a reason; missing the unrequested vessel is not an evaluation failure and must not trigger additional reconstruction.

The local Agnes build must include the bounded MCP image policy in `packages/base/extensions/mcp-server/src/extension.ts` (two images per result, at most 1456² pixels and 2 MiB each). The current local Web was rebuilt and restarted on port 4177 with that policy. An older Agnes build will reject MCP image blocks even though the Python server successfully produced PNGs.

The daemon must also project successful image `resource_link` blocks from registered `mcp_<slug>_<hash8>_<tool>` results into the session-scoped artifact-read authority. Without that projection, the PNG is present in CAS but the next model step fails with `E_STEP_FAILED: artifact <sha256> could not be read`. The projection accepts only the Host-owned MCP naming shape, untrusted successful results, PNG/JPEG links, and artifacts whose hash, MIME, size, session, lane, and owner are independently verified.

An Agnes session that already ended on this pre-fix error still contains the unreadable image reference and may fail again during media preflight. After upgrading and restarting Agnes, open a new session and call `evaluate_vessel_candidate` again for the existing successful candidate. Evaluation is repeatable and reuses the existing GLBs; do not rerun the 20-minute candidate reconstruction merely to recover montage authorization.

`suggest_vessel_parameters` uses only the requested vessel assessments to propose one untried change. By default it explores local changes to artery threshold, vein weak growth tolerance and vein first-stage component size. A custom `search_space` maps applicable parameter names to 1–25 allowed values each, replacing the default search space; `locked_parameters` cannot change. `max_candidates` counts all existing candidates for that target, including failed attempts, and defaults to six (supported range 1–100). The helper returns advice only and never starts a long job itself.

In addition to density judgments, vein assessment accepts `scalp_dominant` and `intracranial_sparse`; use montage evidence and, when available, comparison with the same case's distribution proxy baseline. An uncertain preview requires human review even when another side could be adjusted. Agnes stops at the budget, after two rounds without clear improvement, on failure/cancellation, or when visual assessment is uncertain. For an ordinary optimization request it may stop when technical checks pass and the preview is `good`; an explicit request to compare listed combinations should complete that comparison within the requested budget. Return the best of the evaluated candidates with parameters and reasons, never a guaranteed global optimum. This is technical/visual optimization, not clinical validation.

If the selected model cannot inspect the returned images, Agnes must ask for human review instead of inventing a visual assessment. The native folder dialogs are user-driven; cancellation never registers a case.
