# VesselPilot integration

This integration exposes `scripts/Vascular_cmd.py` to Agnes Harness as a constrained local stdio MCP server. The active MRI2MR workspace Skill is stored at `../.agh/skills/vessel-pilot/SKILL.md`, relative to this `agnes-harness` checkout.

## Runtime

The server discovers the parent `MRI2MR-core` checkout and uses:

- `runtime/python/BrainAAL/python.exe`
- `scripts/Vascular_cmd.py`
- `dcm2niix_win/dcm2niix.exe`
- `dcmtk-3.7.0-win64-dynamic/dcmtk-3.7.0-win64-dynamic/bin/dcmdjpeg.exe`

By default, DICOM input must be below `MRI2MR-core/workspace`, and case output is written to `MRI2MR-core/workspace/vessel-pilot`. Add one or more `--input-root PATH` arguments when an approved DICOM directory lives elsewhere.

## Local protocol smoke test

```powershell
& "..\runtime\python\BrainAAL\python.exe" -m unittest integrations\vessel-pilot\test_vessel_pilot.py -v
```

## Register in Agnes Harness

Build or use the existing local Agnes CLI, then register the Python process as a stdio MCP server. Every `--arg` is a separate process argument.

```powershell
$env:AGH_HOME = (Resolve-Path ".\agh-home").Path
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

`AGH_HOME` must be the same absolute home used by the running Web instance. This checkout's `start-local-windows.ps1` currently uses `agnes-harness/agh-home`; registering against the default `C:\Users\admin\.agh` creates a second control plane that the browser cannot see.

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

The user may paste an absolute DICOM directory path into the chat, or ask Agnes to choose a folder. In the latter flow Agnes calls `choose_dicom_folder`, which opens a native Windows directory dialog and returns the selected local path. The selection must still be below a configured `--input-root`, and selecting a folder does not count as confirmation that the DICOM data is deidentified.

After either entry path, `inspect_dicom_case` performs the same allowlist and file-count checks. The model never receives permission to browse arbitrary directories.

Example chat requests:

```text
使用 vessel-pilot。请打开文件夹选择器，我来选已脱敏的 DICOM 目录；完成后生成动脉和静脉 GLB。
使用 vessel-pilot，把已脱敏的 C:\Users\admin\Desktop\MRI2MR-core\workspace\Data_vessel_01 重建为动脉和静脉 GLB。
```

For the first request, Agnes should call `choose_dicom_folder` and wait for the user's selection. For the second, it should use the supplied path directly without opening a dialog.

## Safety boundary

- The server maps case IDs to local directories and rejects input outside configured roots.
- Candidate IDs are immutable.
- Only the three documented discrete tuning parameters are accepted.
- Subprocess commands use fixed executables and argument arrays; the model cannot provide shell text.
- `conclusion=pass` means technical mesh checks passed. It is not clinical validation, and the manifest retains `clinical_quality_review_required=true`.

## Long-running jobs

One artery/vein candidate normally takes about 20 minutes, and the first MRV Frangi calculation can take longer. `get_vessel_job` is a server-side long poll: each non-terminal call waits up to 55 seconds or returns early when status/phase changes. The 55-second cap leaves room before the current Agnes MCP SDK's 60-second per-call timeout. It returns authoritative `elapsed_seconds` and `elapsed_minutes`; the model must not derive elapsed time from timestamps.

- Call `get_vessel_job(wait_seconds=55)` for non-terminal work. The wait is enforced in the MCP process, preventing fast model loops from producing repeated payloads.
- Report unchanged progress to the user no more than every 2–4 minutes.
- Report state transitions, completion, cancellation, and failure immediately.
- A long unchanged `running` state is not itself a failure. Do not resubmit the same immutable candidate or launch a duplicate job.
- Running responses are compact and omit log paths and repeated notices. `phase` identifies DICOM conversion, artery reconstruction, vein reconstruction, and completion.

## Automatic parameter refinement

`evaluate_vessel_candidate` performs technical mesh checks, saves six fixed views per vessel, builds one artery montage and one vein montage, and returns both montage images to the conversation. Agnes classifies each montage as `good`, `too_dense`, `too_sparse`, or `uncertain`.

The local Agnes build must include the bounded MCP image policy in `packages/base/extensions/mcp-server/src/extension.ts` (two images per result, at most 1456² pixels and 2 MiB each). The current local Web was rebuilt and restarted on port 4177 with that policy. An older Agnes build will reject MCP image blocks even though the Python server successfully produced PNGs.

`suggest_vessel_parameters` converts that assessment into one untried change from the three discrete parameter allowlists. It changes only one parameter per candidate and never starts a long job itself. Agnes stops when a technical-QC-passing candidate is visually `good`, after six candidates, after two rounds without clear improvement, or when the preview is uncertain and needs human review. This is technical/visual optimization, not clinical validation.

If the selected model cannot inspect the returned images, Agnes must ask for human review instead of inventing a visual assessment. The native folder dialog is user-driven; if it is cancelled or selects a directory outside the configured input root, no case is registered.
