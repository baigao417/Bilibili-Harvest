/* BilibiliHarvest Dashboard Control Panel */

const DEFAULT_TOKEN = "";
const DEFAULTS = {
  port: 16780,
  token: DEFAULT_TOKEN,
  paired: false,
  extension_id: "",
  archive_root: "",
  archive_label: "本地知识库",
  source_type: "auto",
  import_mode: "single",
  limit: 200,
  order: "pubdate_desc",
  save_selected: false
};

const $ = (id) => document.getElementById(id);

const ui = {
  // Workflow
  sourceType: $("sourceType"),
  sendCurrentBtn: $("sendCurrentBtn"),
  manualAddBtn: $("manualAddBtn"),
  clearMainBtn: $("clearMainBtn"),
  
  // Notebook
  notebookFilter: $("notebookFilter"),
  nlmNotebook: $("nlmNotebook"),
  nlmRefreshBtn: $("nlmRefreshBtn"),
  
  // Push & Create
  mainNlmBtn: $("mainNlmBtn"),
  mainShapeBtn: $("mainShapeBtn"),
  newNotebookName: $("newNotebookName"),
  nlmCreateBtn: $("nlmCreateBtn"),
  
  // Status
  statusCard: $("statusCard"),
  progressFill: $("progressFill"),
  progressText: $("progressText"),
  nlmSuccessPanel: $("nlmSuccessPanel"),
  nlmOpenBtn: $("nlmOpenBtn"),
  shapeSuccessPanel: $("shapeSuccessPanel"),
  shapeSuccessPath: $("shapeSuccessPath"),
  wizardPanel: $("wizardPanel"),
  wizardStepText: $("wizardStepText"),
  wizardStatus: $("wizardStatus"),
  wizardArchiveRow: $("wizardArchiveRow"),
  wizardArchiveRoot: $("wizardArchiveRoot"),
  wizardArchiveLabel: $("wizardArchiveLabel"),
  wizardPrimaryBtn: $("wizardPrimaryBtn"),
  wizardSecondaryBtn: $("wizardSecondaryBtn"),
  wizardSkipBtn: $("wizardSkipBtn"),
  offlinePanel: $("offlinePanel"),
  offlineRetryBtn: $("offlineRetryBtn"),
  offlineGuideBtn: $("offlineGuideBtn"),
  
  // Drawer
  advancedDrawer: $("advancedDrawer"),
  drawerOverlay: $("drawerOverlay"),
  closeDrawer: $("closeDrawer"),
  settingsToggle: $("settingsToggle"),
  
  // Drawer Content
  importMode: $("importMode"),
  limit: $("limit"),
  order: $("order"),
  urlInput: $("urlInput"),
  urlPreview: $("urlPreview"),
  selectAllShape: $("selectAllShape"),
  urlPreviewList: $("urlPreviewList"),
  urlPreviewCount: $("urlPreviewCount"),
  addBtn: $("addBtn"),
  
  // Export & Settings
  fmtSrt: $("fmtSrt"),
  fmtTxt: $("fmtTxt"),
  fmtMd: $("fmtMd"),
  fmtZip: $("fmtZip"),
  exportBtn: $("exportBtn"),
  startBtn: $("startBtn"),
  stopBtn: $("stopBtn"),
  clearBtn: $("clearBtn"),
  cfgPort: $("cfgPort"),
  cfgToken: $("cfgToken"),
  cfgArchiveLabel: $("cfgArchiveLabel"),
  cfgAutostart: $("cfgAutostart"),
  cfgSaveBtn: $("cfgSaveBtn"),
  cfgTestBtn: $("cfgTestBtn"),

  // Table
  taskTableBody: $("taskTableBody"),
  statusDot: document.querySelector(".status-dot"),
  statusLabel: document.querySelector(".status-label"),
  statusBar: $("statusBar"),
};

// State
let pollTimer = null;
let pollInFlight = false;
let workflowState = { running: false, step: null, target: null }; // target: 'nlm' or 'shape'
let cachedNotebooks = [];
let currentTasks = [];
let isBatchRunning = false;
let currentConfig = null;
let dashboardBootstrapped = false;
let wizardStep = 1;
let wizardScanResult = null;

/* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
   Initialization
   鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */

document.addEventListener("DOMContentLoaded", async () => {
  currentConfig = await loadConfig();
  ensureTaskTable();
  setupEventListeners();
  if (currentConfig && currentConfig.paired) {
    await bootstrapDashboard();
    return;
  }
  await showWizard();
});

function ensureTaskTable() {
  let table = document.querySelector("table");
  if (!table) {
    const card = document.createElement("div");
    card.className = "table-wrap";
    card.innerHTML = `
      <table>
        <thead>
          <tr>
            <th class="col-seq">#</th>
            <th class="col-bv">视频标题/BV号</th>
            <th class="col-status">状态</th>
            <th class="col-result">结果</th>
            <th style="width:40px;text-align:center">资料库</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody id="taskTableBody"></tbody>
      </table>
    `;
    const statusCard = document.getElementById("statusCard");
    if (statusCard) {
      statusCard.parentNode.insertBefore(card, statusCard.nextSibling);
    } else {
      document.body.appendChild(card);
    }
    ui.taskTableBody = $("taskTableBody");
  } else {
    ui.taskTableBody = table.querySelector("tbody");
  }
}

function currentArchiveLabel() {
  return String((currentConfig && currentConfig.archive_label) || DEFAULTS.archive_label || "本地知识库").trim() || "本地知识库";
}

function applyArchiveLabel(label) {
  const archiveLabel = String(label || DEFAULTS.archive_label || "本地知识库").trim() || "本地知识库";
  if (ui.mainShapeBtn) {
    const textNode = ui.mainShapeBtn.querySelector(".btn-text");
    if (textNode) textNode.textContent = `保存到${archiveLabel}`;
  }
  if (ui.shapeSuccessPath && !(currentConfig && currentConfig.archive_root)) {
    ui.shapeSuccessPath.textContent = `已写入${archiveLabel}`;
  }
}

async function bootstrapDashboard() {
  if (dashboardBootstrapped) {
    return;
  }
  dashboardBootstrapped = true;
  if (ui.wizardPanel) ui.wizardPanel.style.display = "none";
  if (ui.offlinePanel) ui.offlinePanel.style.display = "none";
  currentConfig = await loadConfig();
  if (currentConfig && currentConfig.paired) {
    await syncRuntimeConfigFromService();
  }
  applyArchiveLabel(currentArchiveLabel());
  await checkConnection();
  startPolling();
  refreshNotebooks();
}

function setupEventListeners() {
  // Workflow
  ui.sendCurrentBtn.onclick = () => handleAddCurrent();
  ui.manualAddBtn.onclick = () => openDrawer();
  if (ui.clearMainBtn) ui.clearMainBtn.onclick = handleClearTasks;
  
  // Notebook
  ui.nlmRefreshBtn.onclick = refreshNotebooks;
  ui.notebookFilter.oninput = filterNotebooks;
  
  // Main Actions
  ui.mainNlmBtn.onclick = () => runWorkflow('nlm');
  ui.mainShapeBtn.onclick = () => runWorkflow('shape');
  ui.nlmCreateBtn.onclick = handleCreateNotebook;
  
  // Drawer
  if(ui.settingsToggle) ui.settingsToggle.onclick = toggleDrawer;
  if(ui.closeDrawer) ui.closeDrawer.onclick = closeDrawer;
  if(ui.drawerOverlay) ui.drawerOverlay.onclick = closeDrawer;
  
  // Drawer Actions
  ui.urlInput.oninput = renderUrlPreview;
  // ui.selectAllShape.onchange = toggleAllShapePreview; // mvp skip
  ui.addBtn.onclick = handleManualAdd;
  ui.clearBtn.onclick = handleClearTasks;
  
  if (ui.startBtn) ui.startBtn.onclick = () => sendMessage({ type: "start_batch" });
  if (ui.stopBtn) ui.stopBtn.onclick = () => sendMessage({ type: "stop_batch" });
  if (ui.exportBtn) ui.exportBtn.onclick = handleExport;
  
  // Settings
  ui.cfgSaveBtn.onclick = saveConfig;
  ui.cfgTestBtn.onclick = checkConnection;
  if (ui.offlineRetryBtn) ui.offlineRetryBtn.onclick = () => showWizard(true);
  if (ui.offlineGuideBtn) ui.offlineGuideBtn.onclick = showStartupGuide;
  if (ui.wizardPrimaryBtn) ui.wizardPrimaryBtn.onclick = handleWizardPrimary;
  if (ui.wizardSecondaryBtn) ui.wizardSecondaryBtn.onclick = handleWizardSecondary;
  if (ui.wizardSkipBtn) ui.wizardSkipBtn.onclick = handleWizardSkip;

  // Table row actions (avoid inline onclick handlers in extension context)
  if (ui.taskTableBody) {
    ui.taskTableBody.addEventListener("click", onTaskTableClick);
    ui.taskTableBody.addEventListener("change", onTaskTableChange);
  }
}

function setWizardStatus(text, level = "ok") {
  if (!ui.wizardStatus) return;
  ui.wizardStatus.textContent = text || "";
  ui.wizardStatus.className = "status-bar" + (text ? " " + level : "");
}

function showStartupGuide() {
  setStatusMessage("运行 PowerShell：powershell -ExecutionPolicy Bypass -File .\\scripts\\setup_windows.ps1", "warn");
}

async function showWizard(rescan = false) {
  dashboardBootstrapped = false;
  if (ui.wizardPanel) ui.wizardPanel.style.display = "block";
  if (ui.offlinePanel) ui.offlinePanel.style.display = "none";
  wizardStep = 1;
  wizardScanResult = null;
  if (ui.wizardArchiveRow) ui.wizardArchiveRow.style.display = "none";
  if (ui.wizardSkipBtn) ui.wizardSkipBtn.style.display = "none";
  if (ui.wizardSecondaryBtn) ui.wizardSecondaryBtn.style.display = "none";
  if (ui.wizardPrimaryBtn) ui.wizardPrimaryBtn.textContent = "重新扫描";
  if (ui.wizardStepText) ui.wizardStepText.textContent = "步骤 1/4：检测桌面后端";
  setWizardStatus("正在扫描 16780-16800 端口…", "warn");

  const scanResp = await sendMessage({ type: "pairing_scan", start_port: 16780, end_port: 16800 });
  if (!scanResp || !scanResp.ok) {
    setWizardStatus("未找到桌面端后台服务。请先运行 setup_windows.ps1。", "error");
    if (ui.offlinePanel) ui.offlinePanel.style.display = rescan ? "block" : "none";
    return;
  }

  wizardScanResult = scanResp;
  const payload = scanResp.data || {};
  if (ui.wizardPrimaryBtn) ui.wizardPrimaryBtn.textContent = "开始配对";
  setWizardStatus(`已发现桌面端：127.0.0.1:${scanResp.port || payload.port || 16780}`, "ok");
}

async function handleWizardPrimary() {
  if (wizardStep === 1) {
    if (!wizardScanResult || !wizardScanResult.ok) {
      await showWizard(true);
      return;
    }
    const resp = await sendMessage({
      type: "pairing_claim",
      port: wizardScanResult.port || 16780,
      extension_id: chrome.runtime.id || "",
    });
    if (!resp || !resp.ok) {
      setWizardStatus(responseError(resp, "配对失败"), "error");
      return;
    }
    currentConfig = await loadConfig();
    wizardStep = 2;
    if (ui.wizardStepText) ui.wizardStepText.textContent = "步骤 2/4：读取当前配置";
    setWizardStatus("配对成功，正在读取本地资料库配置…", "ok");
    const cfgResp = await sendMessage({ type: "runtime_config_get" });
    if (!cfgResp || !cfgResp.ok) {
      setWizardStatus(responseError(cfgResp, "读取配置失败"), "error");
      return;
    }
    const cfg = unwrapResponse(cfgResp);
    currentConfig = await persistConfig({ ...(currentConfig || {}), ...cfg });
    applyArchiveLabel(currentArchiveLabel());
    if (ui.wizardArchiveRow) ui.wizardArchiveRow.style.display = "block";
    if (ui.wizardArchiveRoot) ui.wizardArchiveRoot.value = String(cfg.archive_root || currentConfig.archive_root || "");
    if (ui.wizardArchiveLabel) ui.wizardArchiveLabel.value = String(cfg.archive_label || currentConfig.archive_label || DEFAULTS.archive_label);
    if (ui.cfgAutostart) ui.cfgAutostart.checked = Boolean(cfg.autostart_enabled);
    if (ui.wizardPrimaryBtn) ui.wizardPrimaryBtn.textContent = "保存目录并继续";
    if (ui.wizardSecondaryBtn) {
      ui.wizardSecondaryBtn.style.display = "inline-flex";
      ui.wizardSecondaryBtn.textContent = "显示诊断窗口";
    }
    return;
  }

  if (wizardStep === 2) {
    const archiveRoot = String((ui.wizardArchiveRoot && ui.wizardArchiveRoot.value) || "").trim();
    const archiveLabel = String((ui.wizardArchiveLabel && ui.wizardArchiveLabel.value) || DEFAULTS.archive_label).trim();
    const resp = await sendMessage({
      type: "runtime_config_patch",
      payload: { archive_root: archiveRoot, archive_label: archiveLabel },
    });
    if (!resp || !resp.ok) {
      setWizardStatus(responseError(resp, "保存目录失败"), "error");
      return;
    }
    currentConfig = await persistConfig({ ...(currentConfig || {}), ...unwrapResponse(resp) });
    applyArchiveLabel(currentArchiveLabel());
    wizardStep = 3;
    if (ui.wizardStepText) ui.wizardStepText.textContent = "步骤 3/4：可选登录 NotebookLM";
    setWizardStatus("本地资料库目录已保存。你现在可以选择登录 NotebookLM，或直接完成。", "ok");
    if (ui.wizardPrimaryBtn) ui.wizardPrimaryBtn.textContent = "打开 NotebookLM";
    if (ui.wizardSkipBtn) {
      ui.wizardSkipBtn.style.display = "inline-flex";
      ui.wizardSkipBtn.textContent = "跳过并完成";
    }
    return;
  }

  if (wizardStep === 3) {
    window.open("https://notebooklm.google.com/", "_blank", "noopener");
    wizardStep = 4;
    if (ui.wizardStepText) ui.wizardStepText.textContent = "步骤 4/4：完成";
    setWizardStatus("NotebookLM 已在新标签页打开。返回后点击“完成向导”开始使用。", "ok");
    if (ui.wizardPrimaryBtn) ui.wizardPrimaryBtn.textContent = "完成向导";
    return;
  }

  await bootstrapDashboard();
}

async function handleWizardSecondary() {
  if (wizardStep === 2) {
    await sendMessage({ type: "show_diagnostic_window" });
  }
}

async function handleWizardSkip() {
  await bootstrapDashboard();
}

function parseTaskSeq(value) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : 0;
}

async function deleteTaskBySeq(seq) {
  if (!seq) {
    setStatusMessage("删除失败：无效任务编号", "error");
    return;
  }
  const resp = await sendMessage({ type: "delete_task", seq });
  if (!isResponseOk(resp)) {
    setStatusMessage(responseError(resp, "删除失败"), "error");
    return;
  }
  setStatusMessage(`已删除任务 #${seq}`, "ok");
  await pollStatus();
}

async function updateTaskShapeFlag(seq, checked) {
  if (!seq) {
    setStatusMessage("更新失败：无效任务编号", "error");
    return;
  }
  const resp = await sendMessage({
    type: "update_task_flag",
    seq,
    flag: "save_selected",
    value: checked,
  });
  if (!isResponseOk(resp)) {
    setStatusMessage(responseError(resp, "更新资料库保存标记失败"), "error");
  }
}

function onTaskTableClick(event) {
  const btn = event.target.closest("button[data-action='delete-task']");
  if (!btn) return;
  if (btn.disabled) return;
  const seq = parseTaskSeq(btn.dataset.seq);
  void deleteTaskBySeq(seq);
}

function onTaskTableChange(event) {
  const checkbox = event.target.closest("input[data-action='toggle-shape']");
  if (!checkbox) return;
  const seq = parseTaskSeq(checkbox.dataset.seq);
  void updateTaskShapeFlag(seq, Boolean(checkbox.checked));
}

/* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
   Workflow Logic
   鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */

async function runWorkflow(target) {
  if (workflowState.running) return;

  if (target === "nlm" && !ui.nlmNotebook.value) {
    alert("请先选择一个 Notebook。");
    return;
  }

  const hasRows = Array.isArray(currentTasks) && currentTasks.length > 0;
  if (!hasRows) {
    const ok = confirm(`当前列表中没有任务。\n是否获取当前浏览器标签页的视频，并自动${target === "nlm" ? "推送到 NotebookLM" : `保存到${currentArchiveLabel()}`}？`);
    if (!ok) return;

    workflowState = { running: true, step: "adding", target };
    updateStatusUI("正在获取视频信息...", 10);
    try {
      await handleAddCurrent(target === "shape");
    } catch (e) {
      finishWorkflow("fail", `获取视频失败: ${e && e.message ? e.message : e}`);
      return;
    }

    setTimeout(async () => {
      const startResp = await sendMessage({ type: "start_batch" });
      if (!isResponseOk(startResp)) {
        finishWorkflow("fail", responseError(startResp, "启动批处理失败"));
      }
    }, 500);
    return;
  }

  const resp = await sendMessage({ type: "get_status" });
  if (!isResponseOk(resp)) {
    finishWorkflow("fail", responseError(resp, "读取任务状态失败"));
    return;
  }

  const tasks = Array.isArray(resp.tasks) ? resp.tasks : [];
  const allFinished = tasks.length > 0 && tasks.every((t) => {
    const s = String(t.status || "").toLowerCase();
    return s.startsWith("completed_") || s === "failed";
  });

  if (allFinished) {
    if (target === "nlm") {
      workflowState = { running: true, step: "pushing", target };
      updateStatusUI("正在推送到 NotebookLM...", 90);
      await pushToNotebookLM();
    } else {
      workflowState = { running: true, step: "exporting", target };
      updateStatusUI(`正在保存到${currentArchiveLabel()}...`, 92);
      await markTasksForShape(tasks);
      await exportToShape();
    }
    return;
  }

  if (target === "shape") {
    await markTasksForShape(tasks);
  }
  workflowState = { running: true, step: "processing", target };
  updateStatusUI("开始处理任务...", 20);
  const startResp = await sendMessage({ type: "start_batch" });
  if (!isResponseOk(startResp)) {
    finishWorkflow("fail", responseError(startResp, "启动批处理失败"));
  }
}

async function handleWorkflowStep(status) {
  if (!workflowState.running) return;

  const tasks = Array.isArray(status.tasks) ? status.tasks : [];
  const allFinished = tasks.length > 0 && tasks.every((t) => {
    const s = String(t.status || "").toLowerCase();
    return s.startsWith("completed_") || s === "failed";
  });
  const hasSuccess = tasks.some((t) => String(t.status || "").toLowerCase().startsWith("completed_"));

  if (status.is_running) {
    const progress = Math.floor((Number(status.progress || 0)) * 100);
    if (workflowState.step !== "pushing" && workflowState.step !== "exporting") {
      updateStatusUI(`处理中... ${progress}%`, 20 + (progress * 0.6));
    }
    return;
  }

  if (!allFinished || workflowState.step === "pushing" || workflowState.step === "exporting") {
    return;
  }

  if (!hasSuccess) {
    finishWorkflow("fail", "没有成功任务");
    return;
  }

  if (workflowState.target === "nlm") {
    workflowState.step = "pushing";
    updateStatusUI("正在推送到 NotebookLM...", 90);
    await pushToNotebookLM();
    return;
  }

  workflowState.step = "exporting";
  updateStatusUI(`正在保存到${currentArchiveLabel()}...`, 92);
  await markTasksForShape(tasks);
  await exportToShape();
}

async function pushToNotebookLM() {
  const notebookId = ui.nlmNotebook.value;
  const resp = await sendMessage({ type: "upload_to_notebooklm", notebookId });
  if (isResponseOk(resp)) {
    finishWorkflow("success-nlm");
  } else {
    finishWorkflow("fail", responseError(resp, "推送失败"));
  }
}

function finishWorkflow(result, msg) {
  workflowState = { running: false, step: null, target: null };
  resetStatusUI();

  if (result === "success-nlm") {
    ui.statusCard.style.display = "block";
    if (ui.nlmSuccessPanel) ui.nlmSuccessPanel.style.display = "flex";
    ui.progressText.textContent = "完成";
    ui.progressFill.style.width = "100%";
    ui.progressFill.className = "progress-fill done";
    const notebookId = ui.nlmNotebook.value;
    if (ui.nlmOpenBtn) ui.nlmOpenBtn.href = `https://notebooklm.google.com/notebook/${encodeURIComponent(notebookId)}`;
    return;
  }

  if (result === "success-shape") {
    ui.statusCard.style.display = "block";
    if (ui.shapeSuccessPanel) ui.shapeSuccessPanel.style.display = "flex";
    if (ui.shapeSuccessPath) {
      ui.shapeSuccessPath.textContent = currentConfig && currentConfig.archive_root
        ? `已写入 ${currentConfig.archive_root}`
        : `已写入${currentArchiveLabel()}`;
    }
    ui.progressText.textContent = "完成";
    ui.progressFill.style.width = "100%";
    ui.progressFill.className = "progress-fill done";
    return;
  }

  ui.statusCard.style.display = "block";
  ui.progressText.textContent = msg || "失败";
  ui.progressFill.className = "progress-fill error";
}

function resetStatusUI() {
  ui.statusCard.style.display = "none";
  if (ui.nlmSuccessPanel) ui.nlmSuccessPanel.style.display = "none";
  if (ui.shapeSuccessPanel) ui.shapeSuccessPanel.style.display = "none";
  ui.progressFill.className = "progress-fill";
}

function updateStatusUI(text, percent) {
  ui.statusCard.style.display = "block";
  if (ui.nlmSuccessPanel) ui.nlmSuccessPanel.style.display = "none";
  if (ui.shapeSuccessPanel) ui.shapeSuccessPanel.style.display = "none";
  ui.progressText.textContent = text;
  ui.progressFill.style.width = `${percent}%`;
  ui.progressFill.className = "progress-fill";
}

function setStatusMessage(text, level = "ok") {
  if (!ui.statusBar) return;
  ui.statusBar.textContent = text || "";
  ui.statusBar.className = `status-bar ${level}`.trim();
}

function unwrapResponse(resp) {
  if (resp && typeof resp === "object" && resp.data && typeof resp.data === "object") {
    return resp.data;
  }
  return resp || {};
}

function isResponseOk(resp) {
  if (!resp || resp.ok !== true) return false;
  const body = unwrapResponse(resp);
  if (typeof body.ok === "boolean") {
    return body.ok;
  }
  return true;
}

function responseError(resp, fallback = "操作失败") {
  const body = unwrapResponse(resp);
  return body.error || body.detail || body.reason || (resp && resp.error) || fallback;
}

function responsePrefetchHint(resp) {
  const reason = String(resp?.prefetch_local_reason || "").trim();
  return reason ? ` | prefetch=${reason}` : "";
}

async function markTasksForShape(tasks) {
  const candidates = (tasks || []).filter((t) => String(t.status || "").toLowerCase() !== "failed");
  await Promise.all(candidates.map((t) => sendMessage({
    type: "update_task_flag",
    seq: t.seq,
    flag: "save_selected",
    value: true,
  })));
}

async function exportToShape() {
  const resp = await sendMessage({
    type: "export_subtitles",
    payload: {
      formats: { md: true },
    },
  });
  if (!isResponseOk(resp)) {
    finishWorkflow("fail", responseError(resp, `保存到${currentArchiveLabel()}失败`));
    return;
  }

  const body = unwrapResponse(resp);
  const saved = Number(body.shape_saved_count || 0);
  if (saved > 0) {
    finishWorkflow("success-shape");
    return;
  }
  finishWorkflow("fail", `未检测到已保存文件，请确认任务的${currentArchiveLabel()}保存标记后重试。`);
}

async function handleAddCurrent(forceShape = false) {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs || !tabs.length) return;

  const tab = tabs[0];
  const url = tab && tab.url ? tab.url : "";
  const tabId = tab && Number.isFinite(tab.id) ? tab.id : null;
  if (!url) {
    throw new Error("当前标签页没有可用 URL");
  }
  const payload = {
    urls: [url],
    tab_id: tabId,
    source_type: ui.sourceType.value,
    import_mode: ui.importMode.value,
    limit: Number(ui.limit.value),
    order: ui.order.value,
    save_selected: forceShape || false,
  };

  const resp = await sendMessage({ type: "add_task", payload });
  const prefetchHint = responsePrefetchHint(resp);
  if (!isResponseOk(resp)) {
    throw new Error(`${responseError(resp, "请求失败")}${prefetchHint}`);
  }
  setStatusMessage(`已添加任务${prefetchHint}`, "ok");
}

async function handleManualAdd() {
  const raw = ui.urlInput.value;
  const lines = raw.split(/\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return;

  const payload = {
    urls: lines,
    source_type: "auto",
    import_mode: ui.importMode.value,
    limit: Number(ui.limit.value),
    save_selected: false,
  };

  const resp = await sendMessage({ type: "add_task", payload });
  if (!isResponseOk(resp)) {
    setStatusMessage(responseError(resp, "添加任务失败"), "error");
    return;
  }

  ui.urlInput.value = "";
  renderUrlPreview();
  closeDrawer();
  setStatusMessage("已添加任务", "ok");
  await pollStatus();
}

async function handleClearTasks() {
  const taskCount = currentTasks.length;
  if (taskCount <= 0) {
    setStatusMessage("当前表格已为空", "warn");
    return;
  }

  if (!confirm(`确定清空当前 ${taskCount} 条任务吗？`)) {
    return;
  }

  const resp = await sendMessage({ type: "clear_tasks" });
  if (!isResponseOk(resp)) {
    setStatusMessage(responseError(resp, "清空失败"), "error");
    return;
  }

  setStatusMessage("已清空表格", "ok");
  await pollStatus();
}

async function handleExport() {
  const flags = {
    srt: ui.fmtSrt.checked,
    txt: ui.fmtTxt.checked,
    md: ui.fmtMd.checked,
    zip: ui.fmtZip.checked,
  };
  if (!Object.values(flags).some(Boolean)) {
    alert("请至少选择一种导出格式");
    return;
  }

  const resp = await sendMessage({ type: "export_subtitles", formats: flags });
  if (!isResponseOk(resp)) {
    setStatusMessage(responseError(resp, "导出请求失败"), "error");
    return;
  }
  setStatusMessage("导出请求已提交", "ok");
}

async function refreshNotebooks() {
  ui.nlmRefreshBtn.classList.add("loading");
  const resp = await sendMessage({ type: "get_notebooks" });
  ui.nlmRefreshBtn.classList.remove("loading");
  
  if (resp && resp.ok && resp.notebooks) {
    cachedNotebooks = resp.notebooks;
    renderNotebookOptions(resp.notebooks);
  }
}

function renderNotebookOptions(list) {
  const filter = ui.notebookFilter.value.toLowerCase();
  ui.nlmNotebook.innerHTML = '<option value="">选择 Notebook</option>';
  
  if(!list) return;

  list.forEach(nb => {
    if (!filter || (nb.title || nb.name || "").toLowerCase().includes(filter)) {
      const opt = document.createElement("option");
      opt.value = nb.id || nb.notebook_id || "";
      opt.textContent = nb.title || nb.name || "(Untitled)";
      ui.nlmNotebook.appendChild(opt);
    }
  });
}

function filterNotebooks() {
  renderNotebookOptions(cachedNotebooks);
}

async function handleCreateNotebook() {
  const name = ui.newNotebookName.value.trim();
  if (!name) {
    ui.newNotebookName.focus();
    return;
  }
  
  ui.nlmCreateBtn.classList.add("loading");
  const resp = await sendMessage({ type: "create_notebook", name });
  ui.nlmCreateBtn.classList.remove("loading");
  
  if (resp && resp.ok) {
    ui.newNotebookName.value = "";
    // Refresh list and auto-select the new notebook
    await refreshNotebooks();
    if (resp.notebook && resp.notebook.id) {
      ui.nlmNotebook.value = resp.notebook.id;
    }
    // Show inline success panel instead of alert
    const panel = document.getElementById('notebookCreateSuccess');
    const link = document.getElementById('notebookOpenBtn');
    const nameSpan = document.getElementById('notebookCreateName');
    if (panel) {
      if (nameSpan) nameSpan.textContent = resp.notebook.title || "";
      if (link && resp.notebook.id) {
        link.href = `https://notebooklm.google.com/notebook/${encodeURIComponent(resp.notebook.id)}`;
      }
      panel.style.display = 'flex';
      setTimeout(() => { panel.style.display = 'none'; }, 8000);
    }
  } else {
    alert("创建失败: " + (resp.error || "unknown"));
  }
}

/* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
   Drawer & UI
   鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */

function openDrawer() {
  ui.advancedDrawer.classList.add("open");
  ui.drawerOverlay.classList.add("open");
}
function closeDrawer() {
  ui.advancedDrawer.classList.remove("open");
  ui.drawerOverlay.classList.remove("open");
}
function toggleDrawer() {
  if (ui.advancedDrawer.classList.contains("open")) closeDrawer();
  else openDrawer();
}

function renderUrlPreview() {
  const raw = ui.urlInput.value || "";
  const lines = raw.split(/\n/).map((l) => l.trim()).filter((l) => l);
  if (ui.urlPreviewCount) ui.urlPreviewCount.textContent = `共 ${lines.length} 条`;

  if (lines.length < 2) {
    ui.urlPreview.style.display = "none";
    return;
  }
  ui.urlPreview.style.display = "block";
  ui.urlPreviewList.innerHTML = lines.map((l) => `
    <div class="url-preview-item">
      <span class="url-label">${l}</span>
    </div>
  `).join("");
}

/* 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
   Polling & Table
   鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollStatus, 1000);
  pollStatus();
}

async function pollStatus() {
  if (pollInFlight) return;
  pollInFlight = true;

  try {
    const resp = await sendMessage({ type: "get_status" });
    if (resp && resp.ok) {
      const tasks = Array.isArray(resp.tasks) ? resp.tasks : [];
      currentTasks = tasks;
      isBatchRunning = Boolean(resp.is_running);
      renderTable(tasks, isBatchRunning);

      if (ui.startBtn) ui.startBtn.disabled = resp.is_running;
      if (ui.stopBtn) ui.stopBtn.disabled = !resp.is_running;
      if (ui.clearBtn) ui.clearBtn.disabled = resp.is_running;
      if (ui.clearMainBtn) ui.clearMainBtn.disabled = resp.is_running;

      if (ui.statusDot) ui.statusDot.className = "status-dot connected";
      if (ui.statusLabel) {
        ui.statusLabel.textContent = "已连接";
        ui.statusLabel.className = "status-label connected";
      }

      handleWorkflowStep(resp);
    } else {
      currentTasks = [];
      isBatchRunning = false;
      if (ui.statusDot) ui.statusDot.className = "status-dot error";
      if (ui.statusLabel) {
        ui.statusLabel.textContent = "未连接";
        ui.statusLabel.className = "status-label error";
      }
    }
  } catch (e) {
    console.error(e);
    setStatusMessage(String(e && e.message ? e.message : e || "状态读取失败"), "error");
  } finally {
    pollInFlight = false;
  }
}

function renderTable(tasks, running = false) {
  if (!ui.taskTableBody) return;
  const emptyState = document.getElementById("emptyState");

  if (!tasks.length) {
    ui.taskTableBody.innerHTML = "";
    if (emptyState) emptyState.style.display = "flex";
    return;
  }

  if (emptyState) emptyState.style.display = "none";

  ui.taskTableBody.innerHTML = tasks.map((t) => `
    <tr>
      <td class="col-seq">${t.seq}</td>
      <td>
        <div class="title-text" title="${t.title || t.bv_id}">${t.title || t.bv_id}</div>
      </td>
      <td class="col-status">
        <span class="badge badge-${getStatusClass(t.status)}">${getStatusLabel(t.status)}</span>
        ${t.progress > 0 && t.status === "processing" ? `<span style="font-size:10px;color:#888;margin-left:2px">${Math.floor(t.progress * 100)}%</span>` : ""}
      </td>
      <td class="col-result">
        ${t.result_info ? `<span title="${t.result_info}" style="font-size:10px;color:#888">${t.result_info.slice(0, 10)}...</span>` : "-"}
      </td>
      <td style="text-align:center">
        <input
          type="checkbox"
          data-action="toggle-shape"
          data-seq="${t.seq}"
          ${t.save_selected ? "checked" : ""}
          ${running ? "disabled" : ""}
        >
      </td>
      <td class="col-actions">
        <button
          class="act-btn delete"
          data-action="delete-task"
          data-seq="${t.seq}"
          ${running ? "disabled" : ""}
        >×</button>
      </td>
    </tr>
  `).join("");
}

function getStatusClass(status) {
  if (!status) return 'queued';
  const s = status.toLowerCase();
  if (s === 'queued') return 'queued';
  if (s === 'failed') return 'failed';
  if (s.startsWith('completed_')) return 'success';
  // All intermediate states: resolving_tracks, downloading_track, transcribing_asr
  return 'processing';
}

function getStatusLabel(status) {
  if (!status) return '未知';
  const s = status.toLowerCase();
  if (s === 'queued') return '排队中';
  if (s === 'failed') return '失败';
  if (s.startsWith('completed_')) return '完成';
  if (s === 'resolving_tracks') return '解析中';
  if (s === 'downloading_track') return '下载中';
  if (s === 'transcribing_asr') return '转录中';
  return '处理中';
}

// Backward-compatible globals (in case older injected DOM still calls them)
window.deleteTask = async (seq) => {
  await deleteTaskBySeq(parseTaskSeq(seq));
};
window.toggleTaskShape = async (seq, checked) => {
  await updateTaskShapeFlag(parseTaskSeq(seq), Boolean(checked));
};

/* Config Loader */
function normalizeStoredConfig(cfg) {
  const merged = { ...DEFAULTS, ...(cfg || {}) };
  return {
    ...merged,
    port: Number(merged.port || DEFAULTS.port),
    token: String(merged.token || "").trim(),
    paired: Boolean(merged.paired),
    extension_id: String(merged.extension_id || "").trim(),
    archive_root: String(merged.archive_root || "").trim(),
    archive_label: String(merged.archive_label || DEFAULTS.archive_label).trim() || DEFAULTS.archive_label,
    autostart_enabled: Boolean(merged.autostart_enabled),
    source_type: String(merged.source_type || DEFAULTS.source_type).trim() || DEFAULTS.source_type,
    import_mode: merged.import_mode || DEFAULTS.import_mode,
    limit: Number(merged.limit || DEFAULTS.limit),
    order: merged.order || DEFAULTS.order,
    save_selected: Boolean(merged.save_selected),
  };
}

async function persistConfig(cfg) {
  const normalized = normalizeStoredConfig(cfg);
  return new Promise((resolve) => {
    chrome.storage.sync.set(normalized, () => {
      currentConfig = normalized;
      resolve(normalized);
    });
  });
}

async function syncRuntimeConfigFromService() {
  const cfgResp = await sendMessage({ type: "runtime_config_get" });
  if (!cfgResp || !cfgResp.ok) {
    return { ok: false, error: responseError(cfgResp, "读取配置失败") };
  }

  const cfg = unwrapResponse(cfgResp);
  const merged = await persistConfig({ ...(currentConfig || {}), ...cfg });
  applyArchiveLabel(String(merged.archive_label || DEFAULTS.archive_label));
  return { ok: true, config: merged };
}

async function loadConfig() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(DEFAULTS, (cfg) => {
      const normalized = normalizeStoredConfig(cfg);
      ui.cfgPort.value = normalized.port;
      ui.cfgToken.value = normalized.token;
      if (ui.cfgArchiveLabel) ui.cfgArchiveLabel.value = normalized.archive_label;
      if (ui.cfgAutostart) ui.cfgAutostart.checked = Boolean(normalized.autostart_enabled);
      ui.sourceType.value = normalized.source_type;
      ui.importMode.value = normalized.import_mode;
      ui.limit.value = normalized.limit;
      ui.order.value = normalized.order;
      currentConfig = normalized;
      resolve(normalized);
    });
  });
}

function collectConfig() {
  return {
    port: Number(ui.cfgPort.value),
    token: (ui.cfgToken.value || "").trim(),
    paired: Boolean(currentConfig && currentConfig.paired),
    extension_id: String((currentConfig && currentConfig.extension_id) || "").trim(),
    archive_root: String((currentConfig && currentConfig.archive_root) || "").trim(),
    archive_label: String((ui.cfgArchiveLabel && ui.cfgArchiveLabel.value) || (currentConfig && currentConfig.archive_label) || DEFAULTS.archive_label).trim() || DEFAULTS.archive_label,
    autostart_enabled: Boolean(ui.cfgAutostart && ui.cfgAutostart.checked),
    source_type: ui.sourceType.value || DEFAULTS.source_type,
    import_mode: ui.importMode.value || DEFAULTS.import_mode,
    limit: Number(ui.limit.value || DEFAULTS.limit),
    order: ui.order.value || DEFAULTS.order,
    save_selected: DEFAULTS.save_selected,
  };
}

async function saveConfig() {
  const cfg = collectConfig();
  const patchResp = await sendMessage({
    type: "runtime_config_patch",
    payload: {
      archive_root: cfg.archive_root,
      archive_label: cfg.archive_label,
      autostart_enabled: cfg.autostart_enabled,
    },
  });
  if (!patchResp || !patchResp.ok) {
    setStatusMessage(responseError(patchResp, "配置保存失败"), "error");
    return;
  }
  const merged = { ...cfg, ...unwrapResponse(patchResp) };
  await persistConfig(merged);
  await sendMessage({ type: "save_config", payload: merged });
  applyArchiveLabel(currentArchiveLabel());
  setStatusMessage("配置已保存", "ok");
}

async function checkConnection() {
  const resp = await sendMessage({ type: "test_connection" });
  if (resp && resp.ok) {
    if(ui.statusDot) ui.statusDot.className = "status-dot connected";
    if(ui.statusLabel) ui.statusLabel.textContent = "已连接";
    if (ui.offlinePanel) ui.offlinePanel.style.display = "none";
    setStatusMessage("连接成功", "ok");
  } else {
    if(ui.statusDot) ui.statusDot.className = "status-dot error";
    if(ui.statusLabel) ui.statusLabel.textContent = "未连接";
    if (currentConfig && currentConfig.paired && ui.offlinePanel) ui.offlinePanel.style.display = "block";
    setStatusMessage(responseError(resp, "连接失败"), "error");
  }
}

function sendMessage(payload) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(payload, (resp) => {
        if (chrome.runtime.lastError) {
          // console.warn("Runtime error:", chrome.runtime.lastError);
          resolve({ ok: false, error: "Connection error" });
        } else {
          resolve(resp || { ok: false, error: "no response" });
        }
      });
    } catch(e) {
      resolve({ ok: false, error: e.message });
    }
  });
}



