const PATIENT_FIELDS = [
  ["patient_name", "patientName"],
  ["patient_id", "patientId"],
  ["sex", "patientSex"],
  ["age", "patientAge"],
  ["study_date", "studyDate"],
  ["notes", "patientNotes"],
];

const PATIENT_PATHS = {
  dicom_dir: "patient_input\\DICOM",
  t1_file: "patient_input\\T1.nii",
  dk_file: "SynthSeg_result\\T1_synthseg.nii",
  synthseg_robust_file: "SynthSeg_result\\T1_synthseg.nii",
  mra_file: "patient_input\\MRA.nii",
  mrv_file: "patient_input\\MRV.nii",
  dti_file: "patient_input\\DTI.nii.gz",
  dti_bvals_file: "patient_input\\DTI.bval",
  dti_bvecs_file: "patient_input\\DTI.bvec",
  mask_file: "patient_input\\c2T1.nii",
  gwi_atlas_file: "temp\\interface_atlas.nii.gz",
  fiber_gfa_cache_file: "temp\\gfa.nii",
  mrv_frangi_cache_file: "temp\\out_figma12_1000.nii",
  multiroi_file: "patient_input\\Segmentation_multilayer.nii",
  dki_file: "patient_input\\dki_4d.nii.gz",
  dki_bvals_file: "patient_input\\bvals.bval",
  dki_bvecs_file: "patient_input\\bvecs.bvec",
};

const PATH_FIELD_TYPES = new Set(["file", "directory", "folder", "file_or_directory"]);
const DICOM_SOURCE_PATH_FIELDS = new Set([
  "dicom_t1_source",
  "dicom_mra_source",
  "dicom_mrv_source",
  "dicom_dti_source",
]);
const PATH_INSPECT_DEBOUNCE_MS = 450;
const DICOM_DETECT_DEBOUNCE_MS = 650;
const DICOM_ROOT_FIELD = "dicom_dir";
const DICOM_KEYWORD_FIELDS = [
  "dicom_t1_keywords",
  "dicom_mra_keywords",
  "dicom_mrv_keywords",
  "dicom_dti_keywords",
];

const FINAL_STATUSES = new Set(["success", "failed", "cancelled"]);
const ACTIVE_STATUSES = new Set(["pending", "running"]);
const PATIENT_OUTPUT_CATEGORIES = new Set([
  "input",
  "segmentation",
  "final_model",
  "important_intermediate",
  "preview",
  "log",
  "metadata",
]);
const TEXT_PREVIEW_LIMIT = 240000;
const MODE_ESTIMATE_SECONDS = {
  dicom_convert: 20 * 60,
  synthseg_segmentation: 40 * 60,
  spm_segmentation: 30 * 60,
  gm_wm: 30 * 60,
  individual_regions: 30 * 60,
  lobes: 30 * 60,
  hemispheres: 30 * 60,
  ventricle: 30 * 60,
  multiroi: 30 * 60,
  tissue: 30 * 60,
  vessel: 10 * 60,
  mrv: 10 * 60,
  fiber_tracking: 60 * 60,
  fiber_tracking_region: 60 * 60,
  fiber_tracking_dki: 60 * 60,
};
const STAGE_LABELS = {
  Waiting: "等待中",
  "Running DICOM conversion": "运行 DICOM 转换",
  "Running SynthSeg": "运行 SynthSeg",
  "Running SPM segmentation": "运行 SPM 分割",
  "Generating brain tissue model": "生成灰白质模型",
  "Generating brain region models": "生成 DK 脑区模型",
  "Generating lobe models": "生成脑叶模型",
  "Generating hemisphere models": "生成半球模型",
  "Generating ventricle model": "生成脑室模型",
  "Generating ROI models": "生成 ROI 模型",
  "Generating tissue models": "生成组织模型",
  "Generating vessel model": "生成动脉模型",
  "Generating venous model": "生成静脉模型",
  "Running fiber tracking": "运行纤维束追踪",
  "Running processing pipeline": "运行处理流程",
  Completed: "完成",
  Cancelled: "已取消",
  Failed: "失败",
};

const MODEL_PRESETS = [
  { key: "dk_regions", label: "DK 脑区", groups: ["dk_regions"] },
  { key: "lobes", label: "脑叶", groups: ["lobes"] },
  { key: "hemispheres", label: "脑半球", groups: ["hemispheres"] },
  { key: "tissue", label: "组织", groups: ["tissue", "gm_wm", "ventricle", "multiroi", "roi"] },
  { key: "vascular", label: "血管", groups: ["vessel", "mrv", "vascular"] },
  { key: "fiber", label: "纤维束", groups: ["fiber_tracking", "fiber_tracking_region", "fiber_tracking_dki"] },
];

const state = {
  config: null,
  runtimeStatus: null,
  modes: [],
  currentMode: null,
  currentJobId: null,
  currentPatientApiId: "",
  currentPatientFolder: "",
  patients: [],
  patientOutputs: [],
  outputSourceLabel: "病人结果",
  selectedGlbKeys: new Set(),
  pollTimer: null,
  jobLocalStart: null,
  three: null,
  viewer: null,
  imageViewer: null,
};

const el = {
  connectionStatus: document.querySelector("#connectionStatus"),
  patientSelect: document.querySelector("#patientSelect"),
  patientName: document.querySelector("#patientName"),
  patientId: document.querySelector("#patientId"),
  patientSex: document.querySelector("#patientSex"),
  patientAge: document.querySelector("#patientAge"),
  studyDate: document.querySelector("#studyDate"),
  patientNotes: document.querySelector("#patientNotes"),
  patientFolder: document.querySelector("#patientFolder"),
  refreshPatientsButton: document.querySelector("#refreshPatientsButton"),
  savePatientButton: document.querySelector("#savePatientButton"),
  newPatientButton: document.querySelector("#newPatientButton"),
  runButton: document.querySelector("#runButton"),
  cancelButton: document.querySelector("#cancelButton"),
  modeSelect: document.querySelector("#modeSelect"),
  modeDescription: document.querySelector("#modeDescription"),
  parameterForm: document.querySelector("#parameterForm"),
  previewTitle: document.querySelector("#previewTitle"),
  previewMeta: document.querySelector("#previewMeta"),
  previewStage: document.querySelector("#previewStage"),
  resetViewButton: document.querySelector("#resetViewButton"),
  leftWorkspaceResizer: document.querySelector("#leftWorkspaceResizer"),
  rightWorkspaceResizer: document.querySelector("#rightWorkspaceResizer"),
  jobStatus: document.querySelector("#jobStatus"),
  jobStage: document.querySelector("#jobStage"),
  elapsedTime: document.querySelector("#elapsedTime"),
  remainingTime: document.querySelector("#remainingTime"),
  runtimeStatus: document.querySelector("#runtimeStatus"),
  progressBar: document.querySelector("#progressBar"),
  progressValue: document.querySelector("#progressValue"),
  activePatientHint: document.querySelector("#activePatientHint"),
  jobError: document.querySelector("#jobError"),
  outputsMeta: document.querySelector("#outputsMeta"),
  outputCount: document.querySelector("#outputCount"),
  outputSource: document.querySelector("#outputSource"),
  glbSelectionCount: document.querySelector("#glbSelectionCount"),
  selectAllGlbButton: document.querySelector("#selectAllGlbButton"),
  loadSelectedGlbButton: document.querySelector("#loadSelectedGlbButton"),
  clearGlbButton: document.querySelector("#clearGlbButton"),
  modelPresetList: document.querySelector("#modelPresetList"),
  modelLayerList: document.querySelector("#modelLayerList"),
  outputsList: document.querySelector("#outputsList"),
  logView: document.querySelector("#logView"),
  logSize: document.querySelector("#logSize"),
};

function setStatus(text) {
  el.connectionStatus.textContent = text;
}

function showError(message) {
  el.jobError.style.display = message ? "block" : "none";
  el.jobError.textContent = message || "";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || body.message || detail;
    } catch (_) {
      // Keep the HTTP status detail when the response is not JSON.
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function optionalApi(path, options = {}) {
  try {
    return await api(path, options);
  } catch (error) {
    if (error.status === 404 || error.status === 405) return null;
    throw error;
  }
}

function normalizeFields(mode) {
  return Array.isArray(mode?.fields) ? mode.fields : [];
}

function statusLabel(status) {
  return {
    pending: "等待中",
    running: "运行中",
    success: "成功",
    failed: "失败",
    cancelled: "已取消",
  }[status] || status || "未运行";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function runtimeItem(label, value, stateName, title = "") {
  return `<div class="runtime-item ${stateName}" title="${escapeHtml(title)}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function renderRuntimeStatus(status) {
  if (!el.runtimeStatus) return;
  if (!status) {
    el.runtimeStatus.innerHTML = runtimeItem("Python", "检查中", "warn") +
      runtimeItem("SPM", "检查中", "warn") +
      runtimeItem("工具", "检查中", "warn");
    return;
  }
  const python = status.python || {};
  const spm = status.spm || {};
  const tools = status.tools || {};
  const toolReady = Boolean(tools.dcm2niix && tools.dcmtk_dcmdjpeg);
  const pythonState = python.exists && !python.using_fallback ? "ready" : python.effective ? "warn" : "error";
  const spmInstallerReady = Boolean(spm.runtime_installer_exists);
  const spmState = spm.ready ? "ready" : spmInstallerReady ? "warn" : "error";
  const toolState = toolReady ? "ready" : "error";
  const backend = spm.selected_backend || spm.backend || "unknown";
  const spmReason = spm.reason || "";
  const spmValue = spm.ready
    ? `${backend} 就绪`
    : spmInstallerReady
      ? `${backend} 首次安装`
      : spmReason.includes("MATLAB Runtime")
      ? `${backend} MCR缺失`
      : `${backend} 缺失`;
  const spmTitle = [spmReason, spm.runtime_installer || "", spm.compiled_exe || spm.standalone_exe || spm.spm_dir || ""].filter(Boolean).join("\n");
  el.runtimeStatus.innerHTML =
    runtimeItem("Python", python.exists ? "就绪" : "回退", pythonState, python.effective || python.configured || "") +
    runtimeItem("SPM", spmValue, spmState, spmTitle) +
    runtimeItem("工具", toolReady ? "就绪" : "缺失", toolState, `dcm2niix=${tools.dcm2niix}; dcmdjpeg=${tools.dcmtk_dcmdjpeg}; docker=${tools.docker}`);
}

function stageLabel(stage) {
  const raw = String(stage || "").trim();
  return STAGE_LABELS[raw] || raw;
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(bytes) || 0;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "估算中";
  const total = Math.floor(seconds);
  if (total < 60) return `${total}秒`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return rest ? `${minutes}分${rest}秒` : `${minutes}分`;
  const hours = Math.floor(minutes / 60);
  const minuteRest = minutes % 60;
  return minuteRest ? `${hours}小时${minuteRest}分` : `${hours}小时`;
}

function clampPercent(value) {
  const number = typeof value === "string" ? Number.parseFloat(value) : Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, Math.round(number)));
}

function clampNumber(value, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return min;
  return Math.max(min, Math.min(max, number));
}

function escapeSelectorName(name) {
  if (window.CSS?.escape) return CSS.escape(name);
  return String(name).replace(/["\\]/g, "\\$&");
}

function sanitizeFolderPart(value) {
  return String(value || "")
    .trim()
    .replace(/[<>:"/\\|?*\x00-\x1F]/g, "_")
    .replace(/\s+/g, "_")
    .replace(/[. ]+$/g, "")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
}

function collectPatient() {
  const patient = {};
  for (const [key, id] of PATIENT_FIELDS) {
    patient[key] = el[id].value.trim();
  }
  return patient;
}

function patientFolderName(patient = collectPatient()) {
  const name = sanitizeFolderPart(patient.patient_name);
  const id = sanitizeFolderPart(patient.patient_id);
  if (name && id) return `${name}_${id}`;
  return name || id || "unknown";
}

function getWorkspaceRoot() {
  return state.config?.paths?.workspace_root || "workspace";
}

function isAbsolutePath(path) {
  return /^[A-Za-z]:[\\/]/.test(path) || path.startsWith("\\\\") || path.startsWith("/");
}

function joinPath(base, relative) {
  if (!base) return relative;
  const separator = base.includes("/") && !base.includes("\\") ? "/" : "\\";
  const cleanBase = base.replace(/[\\/]+$/g, "");
  const cleanRelative = String(relative || "").replace(/^[\\/]+/g, "").replace(/[\\/]+/g, separator);
  return `${cleanBase}${separator}${cleanRelative}`;
}

function currentPatientWorkspace() {
  const folder = state.currentPatientFolder || patientFolderName();
  if (isAbsolutePath(folder)) return folder;
  return joinPath(getWorkspaceRoot(), folder);
}

function endpointIdFromFolder(folder) {
  const parts = String(folder || "").split(/[\\/]+/).filter(Boolean);
  return parts.at(-1) || String(folder || "");
}

function updatePatientFolderDisplay() {
  const workspace = currentPatientWorkspace();
  el.patientFolder.textContent = workspace;
  const folder = state.currentPatientFolder ? endpointIdFromFolder(state.currentPatientFolder) : patientFolderName();
  el.activePatientHint.textContent = `当前病人：${folder}`;
}

function buildPatientPayload() {
  const patient = collectPatient();
  if (state.currentPatientApiId) patient.existing_patient_id = state.currentPatientApiId;
  if (state.currentPatientFolder) patient.patient_folder = state.currentPatientFolder;
  return patient;
}

function setPatientForm(patient, folder = "") {
  const source = patient || {};
  for (const [key, id] of PATIENT_FIELDS) {
    el[id].value = source[key] ?? "";
  }
  state.currentPatientFolder = folder || source.patient_folder || source.folder || source.workspace || "";
  updatePatientFolderDisplay();
}

function clearPatientSelection() {
  state.currentPatientApiId = "";
  state.currentPatientFolder = "";
  el.patientSelect.value = "";
  setPatientForm({}, "");
  state.selectedGlbKeys.clear();
  renderForm();
  renderOutputs([], "病人结果");
  clearModelComposition(true);
}

function patientLabel(patient) {
  const data = patient.patient || {};
  const name = data.patient_name || "未命名病人";
  const id = data.patient_id ? ` · ${data.patient_id}` : "";
  const folder = patient.folder ? ` · ${patient.folder}` : "";
  return `${name}${id}${folder}`;
}

function normalizePatientItem(item, index = 0) {
  const source = item?.patient && typeof item.patient === "object" ? item.patient : item || {};
  const folder = item?.patient_folder || item?.folder || item?.workspace || source.patient_folder || source.folder || source.workspace || "";
  const apiId =
    item?.id ||
    item?.patient_key ||
    item?.patient_folder ||
    source.id ||
    source.patient_key ||
    source.patient_folder ||
    source.folder ||
    source.patient_id ||
    folder ||
    `patient_${index}`;
  const patient = {};
  for (const [key] of PATIENT_FIELDS) {
    patient[key] = source[key] ?? "";
  }
  return {
    apiId: String(apiId),
    folder: String(folder || ""),
    patient,
    raw: item,
  };
}

function patientIdentityMatches(a, b) {
  if (!a || !b) return false;
  const aId = String(a.apiId || "");
  const bId = String(b.apiId || "");
  const aFolder = String(a.folder || "");
  const bFolder = String(b.folder || "");
  const aPatientId = String(a.patient?.patient_id || "");
  const bPatientId = String(b.patient?.patient_id || "");
  return Boolean(
    (aId && bId && aId === bId) ||
      (aFolder && bFolder && aFolder === bFolder) ||
      (aPatientId && bPatientId && aPatientId === bPatientId)
  );
}

function upsertPatient(patient) {
  const normalized = normalizePatientItem(patient, state.patients.length);
  state.patients = [normalized, ...state.patients.filter((item) => !patientIdentityMatches(item, normalized))];
  renderPatientSelect(normalized.apiId);
  return normalized;
}

function renderPatientSelect(selected = state.currentPatientApiId) {
  el.patientSelect.innerHTML = "";
  const fresh = document.createElement("option");
  fresh.value = "";
  fresh.textContent = "新建病人";
  el.patientSelect.appendChild(fresh);
  for (const patient of state.patients) {
    const option = document.createElement("option");
    option.value = patient.apiId;
    option.textContent = patientLabel(patient);
    el.patientSelect.appendChild(option);
  }
  el.patientSelect.value = selected;
}

async function loadPatients(selected = state.currentPatientApiId) {
  const response = await optionalApi("/api/patients");
  if (!response) {
    state.patients = [];
    renderPatientSelect(selected);
    el.outputsMeta.textContent = "等待病人接口";
    return;
  }
  const list = response.patients || response.items || response.results || (Array.isArray(response) ? response : []);
  state.patients = list.map((item, index) => normalizePatientItem(item, index));
  renderPatientSelect(selected);
}

async function selectPatient(apiId) {
  if (!apiId) {
    clearPatientSelection();
    return;
  }

  state.currentPatientApiId = apiId;
  const existing = state.patients.find((patient) => patient.apiId === apiId);
  let selected = existing;
  const detail = await optionalApi(`/api/patients/${encodeURIComponent(apiId)}`);
  if (detail) {
    selected = normalizePatientItem(detail.patient || detail, 0);
    selected.apiId = apiId;
  }

  if (selected) {
    setPatientForm(selected.patient, selected.folder);
  }
  state.selectedGlbKeys.clear();
  clearPreview("等待结果");
  renderForm();
  await refreshPatientOutputs();
}

async function savePatient() {
  showError("");
  const apiId = state.currentPatientApiId || endpointIdFromFolder(state.currentPatientFolder);
  const payload = { patient: buildPatientPayload() };
  const path = apiId ? `/api/patients/${encodeURIComponent(apiId)}` : "/api/patients";
  const method = apiId ? "PATCH" : "POST";

  try {
    const response = await api(path, {
      method,
      body: JSON.stringify(payload),
    });
    const saved = normalizePatientItem(response.patient || response, 0);
    state.currentPatientApiId = saved.apiId;
    state.currentPatientFolder = saved.folder;
    setPatientForm(saved.patient, saved.folder);
    upsertPatient(saved);
    await loadPatients(saved.apiId);
    const refreshed = state.patients.find((patient) => patientIdentityMatches(patient, saved));
    if (refreshed) {
      state.currentPatientApiId = refreshed.apiId;
      state.currentPatientFolder = refreshed.folder;
      setPatientForm(refreshed.patient, refreshed.folder);
    } else {
      upsertPatient(saved);
    }
    renderPatientSelect(state.currentPatientApiId);
    await refreshPatientOutputs();
    setStatus("病人已保存");
  } catch (error) {
    setStatus("保存失败");
    showError(error.message);
  }
}

function rawDefaultValue(field) {
  const modeDefault = state.currentMode?.defaults?.[field.name];
  if (modeDefault !== undefined && modeDefault !== null && modeDefault !== "") return modeDefault;
  if (field.default !== undefined && field.default !== null && field.default !== "") return field.default;
  if (field.default_path !== undefined && field.default_path !== null && field.default_path !== "") return field.default_path;
  if (PATIENT_PATHS[field.name]) return PATIENT_PATHS[field.name];
  if (modeDefault !== undefined && modeDefault !== null) return modeDefault;
  if (field.default !== undefined && field.default !== null) return field.default;
  if (field.default_path !== undefined && field.default_path !== null) return field.default_path;
  return "";
}

function looksLikePatientRelativePath(value) {
  const normalized = String(value || "").replace(/\\/g, "/");
  return /^(patient_input|SynthSeg_result|model_output|temp|previews|logs)\//.test(normalized);
}

function resolveDefaultPath(value) {
  if (Array.isArray(value)) return value.join(",");
  if (value === undefined || value === null) return "";
  if (typeof value !== "string") return String(value);

  const workspace = currentPatientWorkspace();
  let result = value
    .replaceAll("{patient_workspace}", workspace)
    .replaceAll("{case_workspace}", workspace);

  if (isAbsolutePath(result)) return result;

  const normalized = result.replace(/\\/g, "/");
  if (looksLikePatientRelativePath(normalized)) return joinPath(workspace, normalized);
  if (normalized.startsWith("template/")) {
    return joinPath(state.config?.paths?.mri2mr_root || "", normalized);
  }
  if (normalized.startsWith("scripts/")) {
    return joinPath(state.config?.paths?.mri2mr_root || "", normalized);
  }
  return result;
}

function fieldDefault(field) {
  return resolveDefaultPath(rawDefaultValue(field));
}

function isPatientPathField(field) {
  const raw = rawDefaultValue(field);
  return Boolean(
    PATIENT_PATHS[field.name] ||
      String(raw || "").includes("{patient_workspace}") ||
      String(raw || "").includes("{case_workspace}") ||
      looksLikePatientRelativePath(raw),
  );
}

function booleanDefault(field) {
  const value = rawDefaultValue(field);
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return Boolean(value);
  return ["1", "true", "yes", "on", "是"].includes(String(value).trim().toLowerCase());
}

function isPathField(field) {
  const type = String(field?.type || "").toLowerCase();
  return PATH_FIELD_TYPES.has(type) || DICOM_SOURCE_PATH_FIELDS.has(field?.name);
}

function pathSelectionKind(field) {
  const type = String(field?.type || "").toLowerCase();
  if (type === "file") return "file";
  if (type === "directory" || type === "folder" || type === "file_or_directory") return "directory";
  const dialogKind = String(field?.dialog?.kind || "").toLowerCase();
  if (dialogKind === "file") return "file";
  return "directory";
}

function pathSelectionTitle(field, kind) {
  const label = field?.label || field?.name || "路径";
  return kind === "file" ? `选择 ${label}` : `选择 ${label}`;
}

function pathSelectionPatterns(field, kind) {
  if (kind !== "file" || !Array.isArray(field?.accept) || !field.accept.length) return null;
  const patterns = field.accept
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .map((item) => (item.startsWith(".") ? `*${item}` : item));
  if (!patterns.length) return null;
  return [["支持的文件", patterns.join(" ")], ["All files", "*"]];
}

function pathParent(value) {
  const text = String(value || "").trim();
  const index = Math.max(text.lastIndexOf("\\"), text.lastIndexOf("/"));
  if (index < 0) return "";
  if (index === 2 && /^[A-Za-z]:[\\/]/.test(text)) return text.slice(0, 3);
  return text.slice(0, index);
}

function looksLikeFilePath(value) {
  const name = String(value || "").split(/[\\/]+/).pop() || "";
  return /\.[^.]+$/.test(name);
}

function initialDirectoryForSelection(value, kind) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (kind === "file" || looksLikeFilePath(text)) return pathParent(text);
  return text;
}

function fieldInput(name) {
  return el.parameterForm.querySelector(`[name="${escapeSelectorName(name)}"]`);
}

function fieldInputValue(name) {
  const input = fieldInput(name);
  if (!input || input.type === "checkbox") return "";
  return input.value.trim();
}

function compactObject(source) {
  const result = {};
  for (const [key, value] of Object.entries(source)) {
    if (value !== undefined && value !== null && String(value).trim()) result[key] = value;
  }
  return result;
}

function dtiRelatedForField(fieldName) {
  const dti = fieldInputValue("dti_file");
  const bval = fieldInputValue("dti_bvals_file");
  const bvec = fieldInputValue("dti_bvecs_file");
  if (fieldName === "dti_file") {
    return compactObject({ bval, bvec, dti_bvals_file: bval, dti_bvecs_file: bvec });
  }
  if (fieldName === "dti_bvals_file") {
    return compactObject({ dti, bvec, dti_file: dti, dti_bvecs_file: bvec });
  }
  if (fieldName === "dti_bvecs_file") {
    return compactObject({ dti, bval, dti_file: dti, dti_bvals_file: bval });
  }
  return {};
}

function fieldConfig(name) {
  return normalizeFields(state.currentMode).find((field) => field.name === name) || { name };
}

function isDicomConvertMode() {
  return state.currentMode?.mode === "dicom_convert";
}

function dicomDetectionKeywords() {
  const keywords = {};
  for (const name of DICOM_KEYWORD_FIELDS) {
    const value = fieldInputValue(name);
    if (value) keywords[name] = value;
  }
  return keywords;
}

function bumpDicomDetectRequest(input) {
  const next = Number(input.dataset.dicomDetectRequestId || "0") + 1;
  input.dataset.dicomDetectRequestId = String(next);
  return next;
}

function shouldApplyDetectedDicomSource(input) {
  return !input.value.trim() || input.dataset.autoDetected === "1" || input.dataset.userEdited !== "1";
}

function clearAutoDetectedDicomSources() {
  for (const name of DICOM_SOURCE_PATH_FIELDS) {
    const input = fieldInput(name);
    if (!input || input.dataset.autoDetected !== "1" || input.dataset.userEdited === "1") continue;
    input.value = "";
    input.dataset.autoDetected = "0";
    const note = input.closest(".field-row")?.querySelector(".field-note");
    schedulePathInspection(fieldConfig(name), input, note, { immediate: true });
  }
}

function applyDetectedDicomSources(response) {
  const selections = response?.details?.selections || {};
  for (const name of DICOM_SOURCE_PATH_FIELDS) {
    const input = fieldInput(name);
    if (!input || !shouldApplyDetectedDicomSource(input)) continue;

    const selected = selections[name];
    const selectedPath = String(selected?.path || "").trim();
    if (!selectedPath) {
      if (input.dataset.autoDetected === "1") {
        input.value = "";
        input.dataset.autoDetected = "0";
        const note = input.closest(".field-row")?.querySelector(".field-note");
        schedulePathInspection(fieldConfig(name), input, note, { immediate: true });
      }
      continue;
    }

    if (input.value.trim() === selectedPath && input.dataset.autoDetected === "1") continue;
    input.value = selectedPath;
    input.dataset.autoDetected = "1";
    input.dataset.userEdited = "0";
    const note = input.closest(".field-row")?.querySelector(".field-note");
    schedulePathInspection(fieldConfig(name), input, note, { immediate: true });
  }
}

async function detectDicomSeriesForDir(field, input, note) {
  if (!isDicomConvertMode()) return;

  const path = input.value.trim();
  if (!path) {
    bumpDicomDetectRequest(input);
    input.dataset.dicomDetectionSummary = "";
    clearAutoDetectedDicomSources();
    clearFieldNote(note);
    return;
  }

  const requestId = bumpDicomDetectRequest(input);
  input.dataset.dicomDetectionSummary = "";
  setFieldNote(note, "正在自动检测 DICOM 序列...");

  try {
    const response = await optionalApi("/api/detect-dicom-series", {
      method: "POST",
      body: JSON.stringify({
        path,
        keywords: dicomDetectionKeywords(),
      }),
    });
    if (input.dataset.dicomDetectRequestId !== String(requestId) || input.value.trim() !== path) return;
    if (!response) {
      clearFieldNote(note);
      return;
    }

    const summary = pathInspectionSummary(response);
    input.dataset.dicomDetectionSummary = summary || "";
    setFieldNote(note, summary, noteStatusFromInspection(response));
    if (response.ok === false) {
      clearAutoDetectedDicomSources();
      return;
    }
    applyDetectedDicomSources(response);
  } catch (error) {
    if (input.dataset.dicomDetectRequestId !== String(requestId) || input.value.trim() !== path) return;
    input.dataset.dicomDetectionSummary = "";
    setFieldNote(note, `DICOM 自动检测失败：${error.message}`, "error");
  }
}

function scheduleDicomSeriesDetection(field, input, note, { immediate = false } = {}) {
  if (!isDicomConvertMode() || field?.name !== DICOM_ROOT_FIELD) return;
  if (input.dicomDetectTimer) clearTimeout(input.dicomDetectTimer);
  input.dicomDetectTimer = window.setTimeout(
    () => detectDicomSeriesForDir(field, input, note),
    immediate ? 0 : DICOM_DETECT_DEBOUNCE_MS
  );
}

function scheduleDicomDetectionFromCurrentRoot({ immediate = false } = {}) {
  if (!isDicomConvertMode()) return;
  const input = fieldInput(DICOM_ROOT_FIELD);
  if (!input) return;
  const note = input.closest(".field-row")?.querySelector(".field-note");
  scheduleDicomSeriesDetection(fieldConfig(DICOM_ROOT_FIELD), input, note, { immediate });
}

function clearFieldNote(note) {
  if (!note) return;
  note.hidden = true;
  note.textContent = "";
  note.className = "field-note";
}

function setFieldNote(note, text, status = "") {
  if (!note) return;
  note.hidden = !text;
  note.textContent = text || "";
  note.className = "field-note";
  if (status) note.classList.add(status);
}

function pathInspectionSummary(info) {
  if (!info) return "";
  if (info.summary) return String(info.summary);
  if (info.message) return String(info.message);
  if (info.error) return String(info.error);
  if (info.warning) return String(info.warning);

  const parts = [];
  if (info.exists === false) parts.push("路径不存在");
  if (info.type) parts.push(String(info.type));
  if (Array.isArray(info.shape) && info.shape.length) parts.push(`shape ${info.shape.join("x")}`);
  if (Array.isArray(info.voxel_size_mm) && info.voxel_size_mm.length) {
    parts.push(`voxel ${info.voxel_size_mm.join("x")} mm`);
  }
  if (info.volume_count) parts.push(`${info.volume_count} volumes`);
  return parts.join(" · ");
}

function noteStatusFromInspection(info) {
  if (!info) return "";
  if (info.error || String(info.status || "").toLowerCase() === "error") return "error";
  if (info.warning || info.ok === false) return "warning";
  return "";
}

function bumpPathInspectRequest(input) {
  const next = Number(input.dataset.inspectRequestId || "0") + 1;
  input.dataset.inspectRequestId = String(next);
  return next;
}

async function inspectPathField(field, input, note) {
  const path = input.value.trim();
  if (!path) {
    bumpPathInspectRequest(input);
    clearFieldNote(note);
    return;
  }

  const requestId = bumpPathInspectRequest(input);
  setFieldNote(note, "检查中...");

  try {
    const related = dtiRelatedForField(field.name);
    const payload = {
      path,
      field: field.name,
    };
    if (Object.keys(related).length) payload.related = related;
    const response = await optionalApi("/api/inspect-path", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (input.dataset.inspectRequestId !== String(requestId) || input.value.trim() !== path) return;
    if (!response) {
      clearFieldNote(note);
      return;
    }
    setFieldNote(note, pathInspectionSummary(response), noteStatusFromInspection(response));
  } catch (error) {
    if (input.dataset.inspectRequestId !== String(requestId) || input.value.trim() !== path) return;
    setFieldNote(note, `路径检查失败：${error.message}`, "error");
  }
}

function schedulePathInspection(field, input, note, { immediate = false } = {}) {
  if (input.pathInspectTimer) clearTimeout(input.pathInspectTimer);
  if (!input.value.trim()) {
    bumpPathInspectRequest(input);
    clearFieldNote(note);
    return;
  }
  input.pathInspectTimer = window.setTimeout(
    () => inspectPathField(field, input, note),
    immediate ? 0 : PATH_INSPECT_DEBOUNCE_MS
  );
}

async function selectPathForField(field, input, note, button) {
  const kind = pathSelectionKind(field);
  const payload = {
    kind,
    title: pathSelectionTitle(field, kind),
  };
  const initialDir = initialDirectoryForSelection(input.value, kind);
  const patterns = pathSelectionPatterns(field, kind);
  if (initialDir) payload.initial_dir = initialDir;
  if (patterns) payload.patterns = patterns;

  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "选择中";
  showError("");
  try {
    const response = await api("/api/select-path", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const selectedPath = response?.path || "";
    if (!selectedPath) {
      setStatus("未选择路径");
      return;
    }
    input.value = selectedPath;
    input.dataset.userEdited = "1";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    if (field.name === DICOM_ROOT_FIELD && isDicomConvertMode()) {
      scheduleDicomSeriesDetection(field, input, note, { immediate: true });
    } else {
      schedulePathInspection(field, input, note, { immediate: true });
    }
    setStatus("路径已选择");
  } catch (error) {
    setStatus("路径选择失败");
    showError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function createField(field) {
  if (field.type === "boolean") {
    const row = document.createElement("label");
    row.className = "field-row check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = field.name;
    input.checked = booleanDefault(field);
    input.dataset.userEdited = "0";
    input.addEventListener("change", () => {
      input.dataset.userEdited = "1";
    });
    const text = document.createElement("span");
    text.textContent = field.label || field.name;
    row.append(input, text);
    return row;
  }

  const pathField = isPathField(field);
  const row = document.createElement(pathField ? "div" : "label");
  row.className = "field-row";
  const title = document.createElement("span");
  title.textContent = field.label || field.name;
  if (field.required) {
    const mark = document.createElement("span");
    mark.className = "required-mark";
    mark.textContent = " *";
    title.appendChild(mark);
  }

  const defaultValue = fieldDefault(field);
  const input = field.options ? document.createElement("select") : document.createElement("input");
  input.name = field.name;
  input.dataset.autoValue = defaultValue;
  input.dataset.userEdited = "0";

  if (field.options) {
    for (const optionInfo of field.options) {
      const option = document.createElement("option");
      option.value = optionInfo.value ?? optionInfo;
      option.textContent = optionInfo.label ?? optionInfo.value ?? optionInfo;
      input.appendChild(option);
    }
    input.value = defaultValue;
  } else {
    input.value = defaultValue;
    input.placeholder = field.required ? "必填" : "";
    input.spellcheck = false;
    if (field.type === "number") {
      input.type = "number";
      input.step = "any";
    } else {
      input.type = "text";
    }
  }

  input.addEventListener("input", () => {
    input.dataset.userEdited = "1";
    if (DICOM_SOURCE_PATH_FIELDS.has(field.name)) input.dataset.autoDetected = "0";
    if (pathField) {
      const note = row.querySelector(".field-note");
      if (field.name === DICOM_ROOT_FIELD && isDicomConvertMode()) {
        scheduleDicomSeriesDetection(field, input, note);
      } else {
        schedulePathInspection(field, input, note);
      }
    } else if (DICOM_KEYWORD_FIELDS.includes(field.name)) {
      scheduleDicomDetectionFromCurrentRoot();
    }
  });
  input.addEventListener("change", () => {
    input.dataset.userEdited = "1";
    if (DICOM_SOURCE_PATH_FIELDS.has(field.name)) input.dataset.autoDetected = "0";
    if (pathField) {
      const note = row.querySelector(".field-note");
      if (field.name === DICOM_ROOT_FIELD && isDicomConvertMode()) {
        scheduleDicomSeriesDetection(field, input, note);
      } else {
        schedulePathInspection(field, input, note);
      }
    } else if (DICOM_KEYWORD_FIELDS.includes(field.name)) {
      scheduleDicomDetectionFromCurrentRoot();
    }
  });

  row.appendChild(title);
  if (pathField && !field.options) {
    const group = document.createElement("div");
    group.className = "path-input-group";
    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.textContent = "选择";
    const note = document.createElement("div");
    note.className = "field-note";
    note.dataset.field = field.name;
    note.hidden = true;
    selectButton.addEventListener("click", () => {
      selectPathForField(field, input, note, selectButton);
    });
    group.append(input, selectButton);
    row.append(group, note);
    if (field.name === DICOM_ROOT_FIELD && isDicomConvertMode()) {
      scheduleDicomSeriesDetection(field, input, note);
    } else {
      schedulePathInspection(field, input, note);
    }
  } else {
    row.appendChild(input);
  }
  if (field.help) {
    const help = document.createElement("div");
    help.className = "field-help";
    help.textContent = field.help;
    row.appendChild(help);
  }
  return row;
}

function applyPatientDefaults({ respectManual = false } = {}) {
  for (const field of normalizeFields(state.currentMode)) {
    if (!field.name || !isPatientPathField(field)) continue;
    const input = el.parameterForm.querySelector(`[name="${escapeSelectorName(field.name)}"]`);
    if (!input || input.type === "checkbox") continue;
    if (respectManual && input.dataset.userEdited === "1") continue;
    const value = fieldDefault(field);
    input.value = value;
    input.dataset.autoValue = value;
    input.dataset.userEdited = "0";
    const note = input.closest(".field-row")?.querySelector(".field-note");
    if (note) {
      if (field.name === DICOM_ROOT_FIELD && isDicomConvertMode()) {
        scheduleDicomSeriesDetection(field, input, note);
      } else {
        schedulePathInspection(field, input, note);
      }
    }
  }
}

function renderForm() {
  const mode = state.currentMode;
  el.parameterForm.innerHTML = "";
  if (!mode) {
    el.modeDescription.textContent = "";
    return;
  }

  el.modeDescription.textContent = mode.description || "";
  const fields = normalizeFields(mode);
  const basic = fields.filter((field) => !field.advanced);
  const advanced = fields.filter((field) => field.advanced);

  for (const field of basic) {
    el.parameterForm.appendChild(createField(field));
  }

  if (advanced.length) {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "advanced-toggle";
    toggle.textContent = "高级参数";
    const wrap = document.createElement("div");
    wrap.className = "advanced-fields";
    for (const field of advanced) {
      wrap.appendChild(createField(field));
    }
    toggle.addEventListener("click", () => wrap.classList.toggle("open"));
    el.parameterForm.append(toggle, wrap);
  }
}

function renderModes() {
  el.modeSelect.innerHTML = "";
  for (const mode of state.modes) {
    const option = document.createElement("option");
    option.value = mode.mode;
    option.textContent = mode.label || mode.mode;
    el.modeSelect.appendChild(option);
  }
  state.currentMode = state.modes.find((mode) => mode.mode === "dicom_convert") || state.modes[0] || null;
  if (state.currentMode) el.modeSelect.value = state.currentMode.mode;
  renderForm();
}

function collectParameters() {
  const params = {};
  for (const field of normalizeFields(state.currentMode)) {
    if (!field.name || !field.cli) continue;
    const input = el.parameterForm.querySelector(`[name="${escapeSelectorName(field.name)}"]`);
    if (!input) continue;
    if (field.type === "boolean") {
      params[field.name] = input.checked;
    } else {
      params[field.name] = input.value.trim();
    }
  }
  return params;
}

function validateRequiredFields() {
  const mode = state.currentMode;
  const requiredNames = new Set(Array.isArray(mode?.required_fields) ? mode.required_fields : []);
  const missing = [];

  for (const field of normalizeFields(mode)) {
    const required = field.required || requiredNames.has(field.name);
    if (!required) continue;
    const input = el.parameterForm.querySelector(`[name="${escapeSelectorName(field.name)}"]`);
    if (!input) continue;
    const empty = input.type === "checkbox" ? !input.checked : !input.value.trim();
    if (empty) missing.push(field.label || field.name);
  }

  if (missing.length) {
    showError(`请填写 ${missing.join("、")}`);
    setStatus("参数缺失");
    return false;
  }
  return true;
}

function estimatedTotalSeconds(mode) {
  const name = mode?.mode || "";
  const category = mode?.category || "";
  if (MODE_ESTIMATE_SECONDS[name]) return MODE_ESTIMATE_SECONDS[name];
  if (category === "fiber" || name.includes("fiber")) return 3600;
  if (category === "model") return 1800;
  return null;
}

function elapsedSecondsForJob(job) {
  if (Number(job?.elapsed_seconds) > 0) return Number(job.elapsed_seconds);
  if (job?.started_at) {
    const startedAt = Date.parse(job.started_at);
    if (Number.isFinite(startedAt) && ACTIVE_STATUSES.has(job.status)) {
      return Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    }
  }
  if (state.jobLocalStart && ACTIVE_STATUSES.has(job?.status)) {
    return Math.max(0, Math.floor((Date.now() - state.jobLocalStart) / 1000));
  }
  return 0;
}

function updateJobPanel(job) {
  const status = job?.status || "";
  const elapsed = elapsedSecondsForJob(job);
  const total = estimatedTotalSeconds(state.currentMode);
  const progress =
    job?.progress !== undefined
      ? clampPercent(job.progress)
      : status === "success"
        ? 100
        : ACTIVE_STATUSES.has(status) && total
          ? Math.min(92, clampPercent((elapsed / total) * 100))
          : 0;
  const remaining =
    Number.isFinite(Number(job?.estimated_remaining_seconds)) && Number(job.estimated_remaining_seconds) >= 0
      ? Number(job.estimated_remaining_seconds)
      : ACTIVE_STATUSES.has(status) && total
        ? Math.max(0, total - elapsed)
        : null;

  el.jobStatus.textContent = statusLabel(status);
  el.jobStage.textContent = stageLabel(job?.stage) || (status ? statusLabel(status) : "等待任务");
  el.elapsedTime.textContent = formatDuration(elapsed);
  el.remainingTime.textContent = remaining === null ? "估算中" : formatDuration(remaining);
  el.progressBar.style.width = `${progress}%`;
  el.progressValue.textContent = `${progress}%`;
  el.progressBar.parentElement?.setAttribute("aria-valuenow", String(progress));
  el.progressBar.parentElement?.setAttribute("aria-valuemin", "0");
  el.progressBar.parentElement?.setAttribute("aria-valuemax", "100");
  el.cancelButton.disabled = !job || !ACTIVE_STATUSES.has(status);
  el.runButton.disabled = Boolean(job && ACTIVE_STATUSES.has(status));

  if (job?.error) showError(job.error);
  else showError("");
}

function fileTypeFromName(name) {
  const lower = String(name || "").toLowerCase();
  if (lower.endsWith(".nii") || lower.endsWith(".nii.gz")) return "nifti";
  if (lower.endsWith(".glb")) return "glb";
  if (/\.(png|jpe?g|webp)$/.test(lower)) return "image";
  if (lower.endsWith(".log") || lower.endsWith(".txt")) return "text";
  if (lower.endsWith(".json")) return "json";
  return lower.split(".").pop() || "file";
}

function normalizeOutputsResponse(response) {
  const list = response?.outputs || response?.files || response?.items || (Array.isArray(response) ? response : []);
  return list.map((file, index) => {
    const name = file.name || file.filename || file.path || file.relative_path || `file_${index}`;
    const relativePath = file.relative_path || file.relpath || file.path || name;
    const type = String(file.type || file.file_type || fileTypeFromName(name)).toLowerCase();
    const category = String(file.category || "output").toLowerCase();
    const url = file.url || file.download_url || file.href || "";
    const previewUrl = file.preview_url || file.previewUrl || file.preview || "";
    return {
      ...file,
      key: file.key || relativePath || url || `${name}_${index}`,
      name,
      relative_path: relativePath,
      type,
      category,
      size: file.size || 0,
      url,
      preview_url: previewUrl,
      previewable: Boolean(file.previewable || previewUrl || type === "image" || type === "glb"),
    };
  });
}

function isImportantOutput(file) {
  const rel = String(file.relative_path || file.name || "").replace(/\\/g, "/");
  const lowerRel = rel.toLowerCase();
  const lowerName = String(file.name || "").toLowerCase();
  if (lowerRel.includes("temp/dicom2niix_output/")) return false;
  if (lowerRel.includes("temp/dicom_dcmtk_decompressed/")) return false;
  if (PATIENT_OUTPUT_CATEGORIES.has(file.category)) return true;
  if (/^(patient_input|synthseg_result|model_output|previews|logs)\//i.test(rel)) return true;
  if (file.type === "glb" || file.type === "image" || file.type === "text") return true;
  if (file.type === "json") return ["job.json", "patient.json"].includes(lowerName);
  if (!lowerRel.startsWith("temp/")) return file.type === "nifti";
  return (
    lowerName.includes("gfa") ||
    lowerName.includes("frangi") ||
    lowerName.includes("figma") ||
    lowerName.includes("atlas") ||
    lowerName.includes("mask") ||
    lowerName.includes("synthseg") ||
    lowerName.includes("seg")
  );
}

function outputPatientLabel() {
  const patient = collectPatient();
  if (!state.currentPatientApiId && !state.currentPatientFolder && !patient.patient_name && !patient.patient_id) {
    return "尚未选择病人";
  }
  const label = patient.patient_name || patient.patient_id || patientFolderName(patient);
  return label || "未命名病人";
}

function renderOutputs(outputs, sourceLabel = state.outputSourceLabel) {
  state.outputSourceLabel = sourceLabel;
  state.patientOutputs = outputs;
  const outputKeys = new Set(outputs.map((file) => file.key));
  for (const key of [...state.selectedGlbKeys]) {
    if (!outputKeys.has(key)) state.selectedGlbKeys.delete(key);
  }
  el.outputsList.innerHTML = "";
  el.outputCount.textContent = `${outputs.length} 个文件`;
  el.outputsMeta.textContent = outputPatientLabel();
  el.outputSource.textContent = sourceLabel;

  if (!outputs.length) {
    const empty = document.createElement("div");
    empty.className = "output-item";
    const spacer = document.createElement("span");
    const text = document.createElement("span");
    text.textContent = "暂无文件";
    empty.append(spacer, text, document.createElement("span"));
    el.outputsList.appendChild(empty);
    renderModelPresets();
    updateGlbControls();
    return;
  }

  for (const file of outputs) {
    const item = document.createElement("div");
    item.className = "output-item";
    if (file.previewable || file.url) item.classList.add("is-clickable");
    if (state.selectedGlbKeys.has(file.key)) item.classList.add("selected");

    const picker = document.createElement("span");
    if (file.type === "glb") {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.selectedGlbKeys.has(file.key);
      checkbox.title = "选择用于组合展示";
      checkbox.addEventListener("click", (event) => event.stopPropagation());
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.selectedGlbKeys.add(file.key);
        else state.selectedGlbKeys.delete(file.key);
        renderOutputs(state.patientOutputs, state.outputSourceLabel);
      });
      picker.appendChild(checkbox);
    }

    const main = document.createElement("div");
    main.className = "file-main";
    const name = document.createElement("strong");
    name.textContent = file.name;
    const meta = document.createElement("span");
    const groupLabel = file.type === "glb" ? `${modelGroupLabel(file)} · ` : "";
    meta.textContent = `${groupLabel}${file.category || "output"} · ${formatBytes(file.size)}`;
    main.append(name, meta);

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = file.type;
    item.append(picker, main, badge);
    item.addEventListener("click", () => previewFile(file));
    el.outputsList.appendChild(item);
  }
  renderModelPresets();
  updateGlbControls();
}

async function refreshPatientOutputs({ fallbackToJob = false } = {}) {
  let response = null;
  let sourceLabel = "病人结果";
  const patientId = state.currentPatientApiId || endpointIdFromFolder(state.currentPatientFolder);

  if (patientId) {
    response = await optionalApi(`/api/patients/${encodeURIComponent(patientId)}/outputs`);
  }

  if (!response && fallbackToJob && state.currentJobId) {
    response = await optionalApi(`/api/jobs/${encodeURIComponent(state.currentJobId)}/outputs`);
    sourceLabel = response ? "当前任务回退" : sourceLabel;
  }

  const outputs = normalizeOutputsResponse(response).filter(isImportantOutput);
  renderOutputs(outputs, sourceLabel);
}

function glbFiles() {
  return state.patientOutputs.filter((file) => file.type === "glb");
}

function modelGroupForFile(file) {
  if (file.model_group) return String(file.model_group);
  const rel = String(file.relative_path || file.name || "").replace(/\\/g, "/").toLowerCase();
  const match = rel.match(/^model_output\/([^/]+)\//);
  if (!match) return "models";
  const group = match[1];
  if (group === "individual_regions") return "dk_regions";
  return group;
}

function modelGroupLabel(file) {
  if (file.model_group_label) return String(file.model_group_label);
  const group = modelGroupForFile(file);
  const preset = MODEL_PRESETS.find((item) => item.groups.includes(group));
  return preset?.label || group;
}

function presetFiles(preset) {
  return glbFiles().filter((file) => preset.groups.includes(modelGroupForFile(file)));
}

function renderModelPresets() {
  el.modelPresetList.innerHTML = "";
  const presets = MODEL_PRESETS.map((preset) => ({ ...preset, files: presetFiles(preset) })).filter(
    (preset) => preset.files.length,
  );

  if (!presets.length) {
    const empty = document.createElement("div");
    empty.className = "model-preset-empty";
    empty.textContent = "暂无组合预设";
    el.modelPresetList.appendChild(empty);
    return;
  }

  for (const preset of presets) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${preset.label} (${preset.files.length})`;
    button.addEventListener("click", async () => {
      state.selectedGlbKeys = new Set(preset.files.map((file) => file.key));
      renderOutputs(state.patientOutputs, state.outputSourceLabel);
      await showGlbCombination(preset.files);
    });
    el.modelPresetList.appendChild(button);
  }
}

function updateGlbControls() {
  const glbs = glbFiles();
  const selected = glbs.filter((file) => state.selectedGlbKeys.has(file.key));
  el.glbSelectionCount.textContent = selected.length ? `已选 ${selected.length}` : "未选择";
  el.selectAllGlbButton.disabled = !glbs.length;
  el.loadSelectedGlbButton.disabled = !selected.length;
  el.clearGlbButton.disabled = !selected.length && !state.viewer?.models?.length;
}

function selectAllGlb() {
  for (const file of glbFiles()) {
    state.selectedGlbKeys.add(file.key);
  }
  renderOutputs(state.patientOutputs, state.outputSourceLabel);
}

function renderModelLayerList(models = state.viewer?.models || []) {
  el.modelLayerList.innerHTML = "";
  if (!models.length) {
    const empty = document.createElement("div");
    empty.className = "model-layer-empty";
    empty.textContent = "未加载组合模型";
    el.modelLayerList.appendChild(empty);
    updateGlbControls();
    return;
  }

  for (const model of models) {
    const row = document.createElement("label");
    row.className = "model-layer-item";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = model.object.visible;
    checkbox.addEventListener("change", () => {
      model.object.visible = checkbox.checked;
    });
    const text = document.createElement("span");
    text.textContent = model.name;
    row.append(checkbox, text);
    el.modelLayerList.appendChild(row);
  }
  updateGlbControls();
}

function clearPreview(message = "等待结果") {
  disposeImageViewer();
  disposeViewer();
  el.previewStage.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = message;
  el.previewStage.appendChild(empty);
  el.resetViewButton.disabled = true;
  el.resetViewButton.onclick = null;
  el.previewTitle.textContent = "预览";
  el.previewMeta.textContent = "";
  renderModelLayerList([]);
}

function clearModelComposition(clearSelection = false) {
  if (clearSelection) state.selectedGlbKeys.clear();
  clearPreview("等待结果");
  renderOutputs(state.patientOutputs, state.outputSourceLabel);
}

function outputApiBase(file) {
  const url = String(file.url || file.preview_url || "");
  const match = url.match(/^(\/api\/(?:patients|jobs)\/[^/?#]+)/);
  if (match) return match[1];
  const patientId = state.currentPatientApiId || endpointIdFromFolder(state.currentPatientFolder);
  return patientId ? `/api/patients/${encodeURIComponent(patientId)}` : "";
}

function endpointWithQuery(base, params) {
  return `${base}?${new URLSearchParams(params).toString()}`;
}

function loadImage(url, { signal } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const image = new Image();
    const cleanup = () => {
      signal?.removeEventListener("abort", abort);
      image.onload = null;
      image.onerror = null;
    };
    const abort = () => {
      cleanup();
      image.src = "";
      reject(new DOMException("Aborted", "AbortError"));
    };
    image.onload = () => {
      cleanup();
      resolve(image);
    };
    image.onerror = () => {
      cleanup();
      reject(new Error("预览图不可用"));
    };
    signal?.addEventListener("abort", abort, { once: true });
    image.src = url;
  });
}

async function loadFetchedImage(url, { signal } = {}) {
  const response = await fetch(url, { cache: "no-store", signal });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const image = await loadImage(objectUrl, { signal });
    return { image, objectUrl };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

function disposeImageViewer() {
  const viewer = state.imageViewer;
  if (!viewer) return;
  window.removeEventListener("resize", viewer.resize);
  if (viewer.objectUrl) URL.revokeObjectURL(viewer.objectUrl);
  state.imageViewer = null;
}

function createCanvasImageViewer({ controls = null, onSliceWheel = null } = {}) {
  disposeImageViewer();
  el.previewStage.innerHTML = "";
  const canvas = document.createElement("canvas");
  canvas.className = "preview-canvas";
  el.previewStage.appendChild(canvas);
  if (controls) el.previewStage.appendChild(controls);

  const context = canvas.getContext("2d");
  const viewer = {
    image: null,
    scale: 1,
    minScale: 0.02,
    maxScale: 32,
    panX: 0,
    panY: 0,
    dragging: false,
    objectUrl: "",
    resize: () => {
      const rect = el.previewStage.getBoundingClientRect();
      const width = Math.max(1, rect.width);
      const height = Math.max(1, rect.height);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      viewer.draw();
    },
    fit: () => {
      if (!viewer.image) return;
      const rect = canvas.getBoundingClientRect();
      const fitScale = Math.min(
        rect.width / Math.max(viewer.image.naturalWidth || viewer.image.width, 1),
        rect.height / Math.max(viewer.image.naturalHeight || viewer.image.height, 1)
      );
      viewer.scale = clampNumber(fitScale || 1, viewer.minScale, viewer.maxScale);
      viewer.panX = 0;
      viewer.panY = 0;
    },
    reset: () => {
      viewer.fit();
      viewer.draw();
    },
    setImage: (image, { reset = false } = {}) => {
      viewer.image = image;
      if (reset || !viewer.scale) viewer.fit();
      viewer.draw();
    },
    draw: () => {
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(1, rect.width);
      const height = Math.max(1, rect.height);
      context.clearRect(0, 0, width, height);
      context.fillStyle = "#0b1015";
      context.fillRect(0, 0, width, height);
      if (!viewer.image) return;
      const imageWidth = viewer.image.naturalWidth || viewer.image.width;
      const imageHeight = viewer.image.naturalHeight || viewer.image.height;
      const drawWidth = imageWidth * viewer.scale;
      const drawHeight = imageHeight * viewer.scale;
      const x = width / 2 - drawWidth / 2 + viewer.panX;
      const y = height / 2 - drawHeight / 2 + viewer.panY;
      context.imageSmoothingEnabled = false;
      context.drawImage(viewer.image, x, y, drawWidth, drawHeight);
    },
  };

  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      if (event.shiftKey && onSliceWheel) {
        onSliceWheel(event.deltaY > 0 ? 1 : -1);
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const localX = event.clientX - rect.left - rect.width / 2;
      const localY = event.clientY - rect.top - rect.height / 2;
      const oldScale = viewer.scale;
      const factor = event.deltaY < 0 ? 1.12 : 0.88;
      const nextScale = clampNumber(oldScale * factor, viewer.minScale, viewer.maxScale);
      if (nextScale === oldScale) return;
      const ratio = nextScale / oldScale;
      viewer.panX = localX - (localX - viewer.panX) * ratio;
      viewer.panY = localY - (localY - viewer.panY) * ratio;
      viewer.scale = nextScale;
      viewer.draw();
    },
    { passive: false }
  );

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 && event.button !== 1) return;
    event.preventDefault();
    viewer.dragging = true;
    viewer.startX = event.clientX;
    viewer.startY = event.clientY;
    viewer.startPanX = viewer.panX;
    viewer.startPanY = viewer.panY;
    canvas.classList.add("is-dragging");
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!viewer.dragging) return;
    viewer.panX = viewer.startPanX + event.clientX - viewer.startX;
    viewer.panY = viewer.startPanY + event.clientY - viewer.startY;
    viewer.draw();
  });

  const stopDrag = (event) => {
    viewer.dragging = false;
    canvas.classList.remove("is-dragging");
    if (event?.pointerId !== undefined && canvas.hasPointerCapture(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId);
    }
  };
  canvas.addEventListener("pointerup", stopDrag);
  canvas.addEventListener("pointercancel", stopDrag);
  canvas.addEventListener("auxclick", (event) => event.preventDefault());

  window.addEventListener("resize", viewer.resize);
  state.imageViewer = viewer;
  viewer.resize();
  el.resetViewButton.disabled = false;
  el.resetViewButton.onclick = viewer.reset;
  return viewer;
}

function createSliceControls(info, onAxisChange) {
  const root = document.createElement("div");
  root.className = "slice-controls";
  const buttons = {};
  for (const axis of ["x", "y", "z"]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = axis.toUpperCase();
    button.title = `${axis.toUpperCase()} 轴`;
    button.addEventListener("click", () => onAxisChange(axis));
    buttons[axis] = button;
    root.appendChild(button);
  }
  const index = document.createElement("span");
  index.className = "slice-index";
  root.appendChild(index);
  return {
    root,
    update(axis, sliceIndex) {
      for (const [key, button] of Object.entries(buttons)) {
        button.classList.toggle("active", key === axis);
      }
      const size = info.axes?.[axis]?.size || 1;
      index.textContent = `${sliceIndex + 1}/${size}`;
    },
  };
}

function resizeActivePreview() {
  state.viewer?.resize?.();
  state.imageViewer?.resize?.();
}

function setupWorkspaceResizer(handle, side) {
  if (!handle) return;
  let active = null;
  const leftPanel = document.querySelector(".left-panel");
  const rightPanel = document.querySelector(".right-panel");
  const workspace = document.querySelector(".workspace");
  const minLeft = 280;
  const minRight = 290;
  const minPreview = 420;
  const splitterWidth = 14;

  handle.addEventListener("pointerdown", (event) => {
    if (window.matchMedia("(max-width: 1180px)").matches) return;
    event.preventDefault();
    active = {
      startX: event.clientX,
      leftWidth: leftPanel.getBoundingClientRect().width,
      rightWidth: rightPanel.getBoundingClientRect().width,
      workspaceWidth: workspace.getBoundingClientRect().width,
    };
    document.body.classList.add("is-resizing");
    handle.setPointerCapture(event.pointerId);
  });

  handle.addEventListener("pointermove", (event) => {
    if (!active) return;
    const dx = event.clientX - active.startX;
    if (side === "left") {
      const maxLeft = Math.max(minLeft, active.workspaceWidth - active.rightWidth - minPreview - splitterWidth);
      const nextLeft = clampNumber(active.leftWidth + dx, minLeft, maxLeft);
      document.documentElement.style.setProperty("--left-panel-width", `${nextLeft}px`);
    } else {
      const maxRight = Math.max(minRight, active.workspaceWidth - active.leftWidth - minPreview - splitterWidth);
      const nextRight = clampNumber(active.rightWidth - dx, minRight, maxRight);
      document.documentElement.style.setProperty("--right-panel-width", `${nextRight}px`);
    }
    resizeActivePreview();
  });

  const stop = (event) => {
    if (!active) return;
    active = null;
    document.body.classList.remove("is-resizing");
    if (event?.pointerId !== undefined && handle.hasPointerCapture(event.pointerId)) {
      handle.releasePointerCapture(event.pointerId);
    }
    resizeActivePreview();
  };

  handle.addEventListener("pointerup", stop);
  handle.addEventListener("pointercancel", stop);
  handle.addEventListener("dblclick", () => {
    document.documentElement.style.removeProperty(side === "left" ? "--left-panel-width" : "--right-panel-width");
    resizeActivePreview();
  });
}

function previewFile(file) {
  if (!file.previewable && !file.preview_url && !file.url) return;
  const url = file.preview_url || file.url;
  el.previewTitle.textContent = file.name;
  el.previewMeta.textContent = file.type;

  if (file.type === "glb") {
    showGlbCombination([file]);
  } else if (file.type === "nifti" && file.url) {
    showNiftiViewer(file).catch(() => {
      if (file.preview_url) showImage(file.preview_url);
      else clearPreview("NIfTI 预览不可用");
    });
  } else if (file.preview_url || file.type === "image") {
    showImage(url);
  } else if ((file.type === "text" || file.type === "json") && file.url) {
    showTextPreview(file.url, file.type).catch((error) => {
      el.previewMeta.textContent = error.message;
      if (file.url) window.open(file.url, "_blank");
    });
  } else if (file.url) {
    window.open(file.url, "_blank");
  }
}

function showImage(url) {
  disposeImageViewer();
  disposeViewer();
  renderModelLayerList([]);
  el.resetViewButton.disabled = false;
  el.previewStage.innerHTML = "";
  const loading = document.createElement("div");
  loading.className = "empty-state";
  loading.textContent = "加载预览";
  el.previewStage.appendChild(loading);
  const viewer = createCanvasImageViewer();
  loadImage(url)
    .then((image) => {
      if (state.imageViewer !== viewer) return;
      viewer.setImage(image, { reset: true });
    })
    .catch(() => {
      if (state.imageViewer === viewer) clearPreview("预览图不可用");
    });
}

async function showNiftiViewer(file) {
  disposeImageViewer();
  disposeViewer();
  renderModelLayerList([]);
  el.previewStage.innerHTML = "";
  const loading = document.createElement("div");
  loading.className = "empty-state";
  loading.textContent = "加载切片";
  el.previewStage.appendChild(loading);

  const base = outputApiBase(file);
  if (!base || !file.relative_path) throw new Error("NIfTI 文件地址不可用");

  const info = await api(endpointWithQuery(`${base}/nifti-info`, { path: file.relative_path }));
  const indices = {};
  for (const axis of ["x", "y", "z"]) {
    indices[axis] = Number(info.axes?.[axis]?.default_index || 0);
  }
  const sliceState = {
    axis: info.default_axis || "z",
    requestId: 0,
    timer: 0,
    abortController: null,
    resetNext: false,
  };

  const controls = createSliceControls(info, (axis) => {
    if (sliceState.axis === axis) return;
    sliceState.axis = axis;
    scheduleSliceLoad({ reset: true, immediate: true });
  });
  const viewer = createCanvasImageViewer({
    controls: controls.root,
    onSliceWheel: (direction) => {
      const axisInfo = info.axes?.[sliceState.axis] || { size: 1 };
      const nextIndex = clampNumber(indices[sliceState.axis] + direction, 0, Math.max(0, axisInfo.size - 1));
      if (nextIndex === indices[sliceState.axis]) return;
      indices[sliceState.axis] = nextIndex;
      scheduleSliceLoad({ reset: false });
    },
  });

  function updateSliceUi(axis = sliceState.axis, index = indices[axis]) {
    controls.update(axis, index);
    el.previewMeta.textContent = `nifti · ${axis.toUpperCase()} ${index + 1}/${info.axes?.[axis]?.size || 1}`;
  }

  function scheduleSliceLoad({ reset = false, immediate = false } = {}) {
    sliceState.resetNext = sliceState.resetNext || reset;
    updateSliceUi();
    if (sliceState.timer) clearTimeout(sliceState.timer);
    const run = (bubbleError = false) => {
      sliceState.timer = 0;
      const shouldReset = sliceState.resetNext;
      sliceState.resetNext = false;
      return loadSlice({ reset: shouldReset }).catch((error) => {
        if (!isAbortError(error)) el.previewMeta.textContent = error.message;
        if (bubbleError) throw error;
      });
    };
    if (immediate) {
      sliceState.abortController?.abort();
      return run(true);
    }
    sliceState.timer = window.setTimeout(() => run(false), 70);
    return Promise.resolve();
  }

  async function loadSlice({ reset = false } = {}) {
    const axis = sliceState.axis;
    const index = indices[axis];
    const requestId = ++sliceState.requestId;
    sliceState.abortController?.abort();
    const abortController = new AbortController();
    sliceState.abortController = abortController;
    updateSliceUi(axis, index);
    const url = endpointWithQuery(`${base}/nifti-slice`, {
      path: file.relative_path,
      axis,
      index: String(index),
      t: String(Date.now()),
    });
    const { image, objectUrl } = await loadFetchedImage(url, { signal: abortController.signal });
    if (
      state.imageViewer !== viewer ||
      requestId !== sliceState.requestId ||
      axis !== sliceState.axis ||
      index !== indices[axis]
    ) {
      URL.revokeObjectURL(objectUrl);
      return;
    }
    if (viewer.objectUrl) URL.revokeObjectURL(viewer.objectUrl);
    viewer.objectUrl = objectUrl;
    viewer.setImage(image, { reset: reset || !viewer.image });
    updateSliceUi(axis, index);
  }

  try {
    await scheduleSliceLoad({ reset: true, immediate: true });
  } catch (error) {
    if (!isAbortError(error)) throw error;
  }
}

async function showTextPreview(url, type) {
  disposeImageViewer();
  disposeViewer();
  renderModelLayerList([]);
  el.resetViewButton.disabled = true;
  el.resetViewButton.onclick = null;
  el.previewStage.innerHTML = "";
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  let text = await response.text();
  if (text.length > TEXT_PREVIEW_LIMIT) {
    text = `${text.slice(0, TEXT_PREVIEW_LIMIT)}\n\n... 内容过长，已截断预览`;
  }
  const pre = document.createElement("pre");
  pre.className = "text-preview";
  pre.textContent = type === "json" ? formatJsonPreview(text) : text;
  el.previewStage.appendChild(pre);
}

function formatJsonPreview(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch (_) {
    return text;
  }
}

async function loadThree() {
  if (state.three) return state.three;
  const [three, loaderModule, controlsModule] = await Promise.all([
    import("three"),
    import("three/addons/loaders/GLTFLoader.js"),
    import("three/addons/controls/OrbitControls.js"),
  ]);
  state.three = {
    THREE: three,
    GLTFLoader: loaderModule.GLTFLoader,
    OrbitControls: controlsModule.OrbitControls,
  };
  return state.three;
}

function disposeObject3D(object) {
  object.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    for (const material of materials) {
      if (!material) continue;
      for (const value of Object.values(material)) {
        if (value?.isTexture) value.dispose();
      }
      material.dispose();
    }
  });
}

function disposeViewer() {
  if (!state.viewer) return;
  window.removeEventListener("resize", state.viewer.resize);
  if (state.viewer.frame) cancelAnimationFrame(state.viewer.frame);
  if (state.viewer.scene) disposeObject3D(state.viewer.scene);
  state.viewer.controls?.dispose();
  state.viewer.renderer?.dispose();
  state.viewer = null;
}

function resetGlbView() {
  const viewer = state.viewer;
  if (!viewer) return;
  viewer.camera.position.copy(viewer.defaultCameraPosition);
  viewer.camera.near = viewer.defaultNear;
  viewer.camera.far = viewer.defaultFar;
  viewer.camera.updateProjectionMatrix();
  viewer.controls.target.set(0, 0, 0);
  viewer.controls.update();
}

async function showGlbCombination(files) {
  disposeImageViewer();
  disposeViewer();
  el.previewStage.innerHTML = "";
  const loading = document.createElement("div");
  loading.className = "empty-state";
  loading.textContent = files.length > 1 ? "加载组合模型" : "加载模型";
  el.previewStage.appendChild(loading);
  el.resetViewButton.disabled = true;
  el.previewTitle.textContent = files.length > 1 ? `组合模型（${files.length}）` : files[0]?.name || "GLB 模型";
  el.previewMeta.textContent = "glb";

  try {
    const { THREE, GLTFLoader, OrbitControls } = await loadThree();
    el.previewStage.innerHTML = "";

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b1015);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.001, 1000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.previewStage.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 2.6));
    const key = new THREE.DirectionalLight(0xffffff, 2.0);
    key.position.set(3, 4, 5);
    scene.add(key);

    const group = new THREE.Group();
    scene.add(group);
    const loader = new GLTFLoader();
    const models = [];
    const loadFailures = [];

    for (const file of files) {
      const url = file.preview_url || file.url;
      if (!url) {
        loadFailures.push(file.name);
        continue;
      }
      try {
        const gltf = await loader.loadAsync(url);
        const object = gltf.scene;
        object.name = file.name;
        group.add(object);
        models.push({ key: file.key, name: file.name, object });
      } catch (_) {
        loadFailures.push(file.name);
      }
    }

    if (!models.length) throw new Error("没有可加载的 GLB 地址");

    const box = new THREE.Box3().setFromObject(group);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    group.position.sub(center);
    const radius = Math.max(size.x, size.y, size.z) || 1;
    const defaultCameraPosition = new THREE.Vector3(radius * 1.4, radius * 1.1, radius * 1.7);
    camera.position.copy(defaultCameraPosition);
    camera.near = radius / 100;
    camera.far = radius * 100;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.update();

    const resize = () => {
      const rect = el.previewStage.getBoundingClientRect();
      renderer.setSize(rect.width, rect.height, false);
      camera.aspect = rect.width / Math.max(rect.height, 1);
      camera.updateProjectionMatrix();
    };

    state.viewer = {
      scene,
      renderer,
      controls,
      resize,
      frame: 0,
      camera,
      models,
      defaultCameraPosition,
      defaultNear: camera.near,
      defaultFar: camera.far,
    };

    const animate = () => {
      if (!state.viewer) return;
      controls.update();
      renderer.render(scene, camera);
      state.viewer.frame = requestAnimationFrame(animate);
    };

    window.addEventListener("resize", resize);
    resize();
    animate();
    renderModelLayerList(models);
    el.resetViewButton.disabled = false;
    el.resetViewButton.onclick = resetGlbView;
    if (loadFailures.length) {
      el.previewMeta.textContent = `glb · 已加载 ${models.length}，失败 ${loadFailures.length}`;
    }
    updateGlbControls();
  } catch (error) {
    clearPreview("模型预览不可用");
    el.previewTitle.textContent = files.length > 1 ? "组合模型" : files[0]?.name || "GLB 模型";
    el.previewMeta.textContent = error.message;
  }
}

async function loadSelectedGlb() {
  const selected = state.patientOutputs.filter((file) => file.type === "glb" && state.selectedGlbKeys.has(file.key));
  if (!selected.length) return;
  await showGlbCombination(selected);
}

function isPreviewReady(file) {
  return Boolean(file?.previewable || file?.preview_url || file?.url);
}

function fileModifiedAtMs(file) {
  const seconds = Number(file?.modified_at);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 0;
}

function outputsUpdatedByJob(job) {
  const startedAt = Date.parse(job?.started_at || job?.created_at || "");
  const finishedAt = Date.parse(job?.finished_at || "");
  if (!Number.isFinite(startedAt)) return [];

  // Filesystems commonly store modification times with less precision than
  // the job timestamps, so allow a small margin around the job interval.
  const earliest = startedAt - 2_000;
  const latest = Number.isFinite(finishedAt) ? finishedAt + 10_000 : Infinity;
  return state.patientOutputs.filter((file) => {
    const modifiedAt = fileModifiedAtMs(file);
    return isPreviewReady(file) && modifiedAt >= earliest && modifiedAt <= latest;
  });
}

function firstMatchingFile(files, predicate) {
  return files.find((file) => isPreviewReady(file) && predicate(file));
}

function preferredAutoPreview(job) {
  const all = state.patientOutputs.filter(isPreviewReady);
  const updated = outputsUpdatedByJob(job);
  const mode = String(job?.mode || "").toLowerCase();
  const isModelMode = new Set([
    "gm_wm",
    "individual_regions",
    "lobes",
    "hemispheres",
    "ventricle",
    "multiroi",
    "tissue",
    "vessel",
    "mrv",
    "fiber_tracking",
    "fiber_tracking_region",
    "fiber_tracking_dki",
  ]);

  if (mode === "synthseg_segmentation") {
    return (
      firstMatchingFile(updated, (file) => file.category === "segmentation") ||
      firstMatchingFile(all, (file) => file.category === "segmentation") ||
      updated[0] ||
      all[0]
    );
  }

  if (mode === "spm_segmentation") {
    const spmOutput = (files) =>
      firstMatchingFile(files, (file) => {
        const path = String(file.relative_path || "").toLowerCase();
        return path.endsWith("/c1t1.nii") || path.endsWith("/c1t1.nii.gz") || path.endsWith("/c2t1.nii") || path.endsWith("/c2t1.nii.gz");
      }) ||
      firstMatchingFile(files, (file) => {
        const path = String(file.relative_path || "").toLowerCase();
        return path.endsWith("/mt1.nii") || path.endsWith("/mt1.nii.gz");
      });
    return spmOutput(updated) || spmOutput(all) || updated[0] || all[0];
  }

  if (isModelMode.has(mode)) {
    return firstMatchingFile(updated, (file) => file.type === "glb") || updated[0] || firstMatchingFile(all, (file) => file.type === "glb") || all[0];
  }

  if (mode === "dicom_convert") {
    return (
      firstMatchingFile(updated, (file) => {
        const path = String(file.relative_path || "").toLowerCase();
        return path.endsWith("/t1.nii") || path.endsWith("/t1.nii.gz");
      }) ||
      firstMatchingFile(updated, (file) => file.type === "nifti") ||
      updated[0] ||
      all[0]
    );
  }

  return firstMatchingFile(updated, (file) => file.type === "glb") || firstMatchingFile(updated, (file) => file.type === "nifti") || updated[0] || all[0];
}

async function refreshJob() {
  if (!state.currentJobId) return;
  const [{ job }, logs] = await Promise.all([
    api(`/api/jobs/${encodeURIComponent(state.currentJobId)}`),
    optionalApi(`/api/jobs/${encodeURIComponent(state.currentJobId)}/logs`),
  ]);

  updateJobPanel(job);
  if (logs) {
    el.logView.textContent = logs.text || "";
    el.logSize.textContent = formatBytes(logs.size || 0);
    el.logView.scrollTop = el.logView.scrollHeight;
  }

  if (FINAL_STATUSES.has(job.status)) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    state.jobLocalStart = null;
    setStatus(statusLabel(job.status));
    await loadPatients().catch(() => {});
    await refreshPatientOutputs({ fallbackToJob: true });
    const firstPreview = preferredAutoPreview(job);
    if (firstPreview && !el.previewStage.dataset.autoShown) {
      previewFile(firstPreview);
      el.previewStage.dataset.autoShown = "1";
    }
  }
}

function applyJobResponse(response) {
  const job = response.job || response;
  const patient = response.patient || job.patient;
  const folder =
    response.patient_folder ||
    job.patient_folder ||
    patient?.patient_folder ||
    patient?.folder ||
    patient?.workspace ||
    "";
  const apiId =
    response.patient_id ||
    response.patient_key ||
    response.id ||
    patient?.id ||
    patient?.patient_key ||
    patient?.patient_folder ||
    endpointIdFromFolder(folder) ||
    "";

  if (patient) setPatientForm({ ...collectPatient(), ...patient }, folder || state.currentPatientFolder);
  else if (folder) {
    state.currentPatientFolder = folder;
    updatePatientFolderDisplay();
  }
  if (apiId && !state.currentPatientApiId) state.currentPatientApiId = String(apiId);
  if (state.currentPatientApiId) el.patientSelect.value = state.currentPatientApiId;
  return job;
}

async function runJob() {
  if (!state.currentMode) return;
  showError("");
  if (!validateRequiredFields()) return;

  const parameters = collectParameters();
  const payload = {
    patient: buildPatientPayload(),
    mode: state.currentMode.mode,
    parameters,
  };

  el.previewStage.dataset.autoShown = "";
  clearPreview("任务运行中");

  try {
    const response = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const job = applyJobResponse(response);
    state.currentJobId = job.job_id || job.id;
    state.jobLocalStart = Date.now();
    updateJobPanel(job);
    setStatus("运行中");
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(() => refreshJob().catch((error) => setStatus(error.message)), 1500);
    await refreshJob();
  } catch (error) {
    setStatus("提交失败");
    showError(error.message);
    updateJobPanel(null);
  }
}

async function cancelJob() {
  if (!state.currentJobId) return;
  try {
    const { job } = await api(`/api/jobs/${encodeURIComponent(state.currentJobId)}/cancel`, { method: "POST" });
    updateJobPanel(job);
    await refreshJob();
  } catch (error) {
    showError(error.message);
  }
}

async function init() {
  try {
    renderRuntimeStatus(null);
    const [config, modesResponse, runtimeStatus] = await Promise.all([
      api("/api/config"),
      api("/api/modes"),
      optionalApi("/api/runtime-status"),
    ]);
    state.config = config;
    state.runtimeStatus = runtimeStatus;
    state.modes = modesResponse.modes || [];
    renderRuntimeStatus(runtimeStatus);
    renderModes();
    updatePatientFolderDisplay();
    updateJobPanel(null);
    renderOutputs([], "病人结果");
    renderModelLayerList([]);
    await loadPatients();
    setStatus("就绪");
  } catch (error) {
    setStatus("初始化失败");
    showError(error.message);
  }
}

el.modeSelect.addEventListener("change", () => {
  state.currentMode = state.modes.find((mode) => mode.mode === el.modeSelect.value) || null;
  renderForm();
});

for (const [, id] of PATIENT_FIELDS) {
  el[id].addEventListener("input", () => {
    updatePatientFolderDisplay();
    applyPatientDefaults({ respectManual: true });
  });
  el[id].addEventListener("change", () => {
    updatePatientFolderDisplay();
    applyPatientDefaults({ respectManual: true });
  });
}

el.patientSelect.addEventListener("change", () => {
  selectPatient(el.patientSelect.value).catch((error) => showError(error.message));
});
el.refreshPatientsButton.addEventListener("click", () => {
  loadPatients().catch((error) => showError(error.message));
});
el.savePatientButton.addEventListener("click", savePatient);
el.newPatientButton.addEventListener("click", clearPatientSelection);
el.runButton.addEventListener("click", runJob);
el.cancelButton.addEventListener("click", cancelJob);
el.selectAllGlbButton.addEventListener("click", selectAllGlb);
el.loadSelectedGlbButton.addEventListener("click", () => loadSelectedGlb().catch((error) => showError(error.message)));
el.clearGlbButton.addEventListener("click", () => clearModelComposition(true));
setupWorkspaceResizer(el.leftWorkspaceResizer, "left");
setupWorkspaceResizer(el.rightWorkspaceResizer, "right");

init();
