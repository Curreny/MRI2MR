# VesselPilot integration

This integration exposes `scripts/Vascular_cmd.py` to Agnes Harness as a constrained local stdio MCP server. The active MRI2MR workspace Skill is stored at `../.agh/skills/vessel-pilot/SKILL.md`, relative to this `agnes-harness` checkout.

## Runtime

The server discovers the parent `MRI2MR-core` checkout and uses:

- `runtime/python/BrainAAL/python.exe`
- `scripts/Vascular_cmd.py`
- `dcm2niix_win/dcm2niix.exe`
- `dcmtk-3.7.0-win64-dynamic/dcmtk-3.7.0-win64-dynamic/bin/dcmdjpeg.exe`

By default, DICOM input must be below `MRI2MR-core/workspace`, and case output is written to `MRI2MR-core/workspace/vessel-pilot`. This deployment uses `--allow-any-input` because source datasets live outside the project. That flag permits only a directory explicitly selected or supplied by the user; case outputs remain under the controlled case root and the service does not scan unrelated directories.

## Local protocol smoke test

```powershell
& "..\runtime\python\BrainAAL\python.exe" -m unittest integrations\vessel-pilot\test_vessel_pilot.py -v
```

## Register in Agnes Harness

Build or use the existing local Agnes CLI, then register the Python process as a stdio MCP server. Every `--arg` is a separate process argument.

```powershell
$env:AGH_HOME = "C:\Users\admin\Desktop\MRI2MR-core\agnes-harness\agh-home"
$env:AGNES_PROFILE = "local-dev"
$agnes = "packages\cli\dist\local\agnes.mjs"
$python = (Resolve-Path "..\runtime\python\BrainAAL\python.exe").Path
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

For this VesselPilot checkout, `AGH_HOME` is fixed to `C:\Users\admin\Desktop\MRI2MR-core\agnes-harness\agh-home`. WebUI, daemon, MCP/Skill management, and validation commands must all use that exact absolute home. Do not fall back to `C:\Users\admin\.agh` or create a temporary home: either creates a second control plane that the browser cannot see.

The canonical local executable is `packages\cli\dist\local\agnes.mjs`. After changing Harness or composer source, rebuild that exact entry before testing:

```powershell
corepack pnpm --filter @agnes/cli build:local
```

Versioned directories such as `dist\local-vessel-pilot-*` may be used for isolated build checks only. Do not leave WebUI and daemon running from different build directories.

The MCP definition is created disabled and untrusted. Review it in **Settings → MCP**, then enable it. A normal local instance can approve the exact native Python executable through this review. If an administrator enforces a deployment allowlist, `AGNES_MCP_STDIO_ALLOWLIST` must contain the exact executable path; pre-setting that variable disables dynamic local approvals.

In **Settings → Skills**, select the workspace in which the reconstruction chat runs. For the current project that is `C:\Users\admin\Desktop\MRI2MR-core`, so the Skill must be at `MRI2MR-core/.agh/skills/vessel-pilot/SKILL.md`. Refresh, review, and enable it. Start a new turn or a new chat and explicitly ask Agnes to use `vessel-pilot`.

## Diagnose missing tools

If Agnes says that `vessel-pilot` or its tools do not exist:

1. Check the Web and daemon command lines and confirm they use the same `AGH_HOME`, profile, data directory, and origin.
2. Run `mcp list/status/tools` only after setting that same `AGH_HOME`.
3. Check the chat's `cwd`; workspace Skills are discovered from `<cwd>/.agh/skills`, not from the Harness source directory automatically.
4. Confirm the Skill is `trust=trusted desired=enabled actual=ready winner` for that workspace.
5. Confirm the MCP is `connection=ready` and exposes eleven tools, then begin a new turn so the resource snapshot is reloaded.

## Conversation entry points

The user may paste one or more absolute DICOM directory paths into the chat, ask Agnes to choose one folder through `choose_dicom_folder`, or use the folder button beside the composer attachment control. Both Windows picker entry points use an invisible modal owner that is pinned to the native topmost Z-order with `SetWindowPos(HWND_TOPMOST)` and promoted with `SetForegroundWindow`, so the dialog stays above the browser even when it is launched by the background Web or MCP process. The composer button inserts one reviewable path; click it repeatedly to append more cases to the same draft. It does not upload or copy DICOM files. Selecting folders does not count as confirmation that the data is deidentified.

After either entry path, `inspect_dicom_case` performs the same allowlist and file-count checks. The model never receives permission to browse arbitrary directories.

Example chat requests:

```text
使用 vessel-pilot。请打开文件夹选择器，我来选已脱敏的 DICOM 目录；完成后生成动脉和静脉 GLB。
使用 vessel-pilot，把已脱敏的 C:\Users\admin\Desktop\MRI2MR-core\workspace\Data_vessel_01 重建为动脉和静脉 GLB。
使用 vessel-pilot，批量处理以下已脱敏的 DICOM 目录，每个目录作为独立病例，最多并行两例：C:\Data\case-01 和 D:\MRI\case-02。
```

For the first request, Agnes should call `choose_dicom_folder` and wait for the user's selection. For supplied paths, it should not open another dialog. Batch cases retain independent case/job/candidate identifiers and run at most two long jobs concurrently.

## Safety boundary

- The server maps case IDs to local directories. `--allow-any-input` relaxes only the read-side root check for a user-selected or explicitly supplied directory; outputs still stay under `--case-root`.
- Candidate IDs are immutable.
- Only the three documented discrete tuning parameters are accepted.
- Subprocess commands use fixed executables and argument arrays; the model cannot provide shell text.
- `conclusion=pass` means technical mesh checks passed. It is not clinical validation, and the manifest retains `clinical_quality_review_required=true`.

## Failure and boundary behavior

Input inspection is deliberately lightweight: it recognizes non-empty `.dcm`, `.dicom`, and `.ima` files or files with the standard `DICM` preamble. This is a compatibility preflight, not proof that every file is valid DICOM. The actual converter remains authoritative.

| Situation | Behavior |
| --- | --- |
| Missing/unreadable path, empty folder, only unrelated files, only zero-byte DICOM-like files | Reject before creating a case with a stable `INPUT_*` error. |
| Symbolic link below the selected folder | Reject; the service never follows it outside the reviewed input tree. |
| DICOM-like files mixed with notes, JSON, or empty files | Register the case, return exact preflight counts, and emit warnings; unrelated files are not treated as target series. |
| Source files change after inspection | Reject conversion with `INPUT_CHANGED_SINCE_INSPECTION`; inspect again instead of running against a stale fingerprint. |
| A conversion is already queued/running | Return that job with `already_running=true`; do not launch a second writer for the case. |
| Extra T1, diffusion, or unrelated series | Keep them in selection evidence but exclude them from MRA/MRV eligibility. |
| MIP, MPR, Scout, Localizer, unreadable, 2D, 4D, or degenerate converted series | Exclude them from reconstruction candidates. |
| Several usable candidates match one modality | Rank deterministically and return `multiple_matching_candidates_ranked_deterministically`; review `dicom_selection.json` before continuing automatically. |
| Only MRA or only MRV is available | Fail with `MISSING_REQUIRED_MODALITY`; a single modality is never presented as a completed VesselPilot case. |
| MRA and MRV resolve to the same source series | Fail with `AMBIGUOUS_MODALITY_SELECTION`. |
| Converted NIfTI is unreadable, non-3D, degenerate, has non-finite affine values, or invalid voxel sizes | Fail with `INVALID_CONVERTED_NIFTI`. |
| Retrying after a failed conversion | Remove the prior generated MRA/MRV and selection summary before the new command, preventing stale halves from being combined. |

Candidate generation requires `conversion_status=succeeded` plus non-empty MRA and MRV outputs. New conversions persist each validated output's size and SHA-256, and candidate generation rejects later changes to those files. A failed or partial conversion cannot advance merely because files with the expected names remain on disk. In batch mode, stop only the affected case and continue other independent cases.

## Long-running jobs

One artery/vein candidate normally takes about 20 minutes, and the first MRV Frangi calculation can take longer. `get_vessel_job` is a server-side long poll: each non-terminal call waits up to 55 seconds or returns early when status/phase changes. The 55-second cap leaves room before the current Agnes MCP SDK's 60-second per-call timeout. It returns authoritative `elapsed_seconds` and `elapsed_minutes`; the model must not derive elapsed time from timestamps.

- Call `get_vessel_job(wait_seconds=55)` for non-terminal work. The wait is enforced in the MCP process, preventing fast model loops from producing repeated payloads.
- Report unchanged progress to the user no more than every 2–4 minutes.
- Report state transitions, completion, cancellation, and failure immediately.
- A long unchanged `running` state is not itself a failure. Do not resubmit the same immutable candidate or launch a duplicate job.
- Running responses are compact and omit log paths and repeated notices. `phase` identifies DICOM conversion, artery reconstruction, vein reconstruction, and completion.

## Automatic parameter refinement

`evaluate_vessel_candidate` performs technical mesh checks, saves six fixed views per vessel, builds one artery montage and one vein montage, and returns both montage images to the conversation. It also reports `vein_distribution_proxy`: vein triangle area inside versus outside an artery-derived bounding box expanded by 15%. This enables within-case comparison of intracranial versus scalp/peripheral vein tendency after face-only deidentification, but it is not skull segmentation and must not be treated as a clinical anatomical label.

The local Agnes build must include the bounded MCP image policy in `packages/base/extensions/mcp-server/src/extension.ts` (two images per result, at most 1456² pixels and 2 MiB each). The current local Web was rebuilt and restarted on port 4177 with that policy. An older Agnes build will reject MCP image blocks even though the Python server successfully produced PNGs.

The daemon must also project successful image `resource_link` blocks from registered `mcp_<slug>_<hash8>_<tool>` results into the session-scoped artifact-read authority. Without that projection, the PNG is present in CAS but the next model step fails with `E_STEP_FAILED: artifact <sha256> could not be read`. The projection accepts only the Host-owned MCP naming shape, untrusted successful results, PNG/JPEG links, and artifacts whose hash, MIME, size, session, lane, and owner are independently verified.

An Agnes session that already ended on this pre-fix error still contains the unreadable image reference and may fail again during media preflight. After upgrading and restarting Agnes, open a new session and call `evaluate_vessel_candidate` again for the existing successful candidate. Evaluation is repeatable and reuses the existing GLBs; do not rerun the 20-minute candidate reconstruction merely to recover montage authorization.

`suggest_vessel_parameters` converts that assessment into one untried change from the three discrete parameter allowlists. In addition to density judgments, vein assessment accepts `scalp_dominant` and `intracranial_sparse`; Agnes must compare the proxy with the same case's baseline and inspect the montage before using either label. It changes only one parameter per candidate and never starts a long job itself. Agnes stops when a technical-QC-passing candidate is visually `good`, after six candidates, after two rounds without clear improvement, or when the preview is uncertain and needs human review. This is technical/visual optimization, not clinical validation.

If the selected model cannot inspect the returned images, Agnes must ask for human review instead of inventing a visual assessment. The native folder dialogs are user-driven; cancellation never registers a case.
