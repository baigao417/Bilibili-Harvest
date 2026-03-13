const $ = (id) => document.getElementById(id);

const ui = {
  status: $("status"),
  statusDot: $("statusDot"),
  statusLabel: $("statusLabel"),
  openDashboardBtn: $("openDashboardBtn"),
  showWindowBtn: $("showWindowBtn"),
  retryBtn: $("retryBtn"),
};

function setStatus(text, level = "ok") {
  if (ui.status) {
    ui.status.textContent = text || "";
    ui.status.className = "status-bar" + (text ? " " + level : "");
  }
}

function setConnectionState(connected) {
  if (ui.statusDot) ui.statusDot.className = "status-dot" + (connected ? " connected" : " error");
  if (ui.statusLabel) ui.statusLabel.textContent = connected ? "已连接" : "未连接";
}

function sendMessage(payload) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(payload, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message || "runtime error" });
        return;
      }
      resolve(resp || { ok: false, error: "empty response" });
    });
  });
}

async function refreshConnection() {
  const resp = await sendMessage({ type: "test_connection" });
  if (resp && resp.ok) {
    setConnectionState(true);
    setStatus("桌面端已连接，点击 Dashboard 开始使用。", "ok");
    return;
  }
  setConnectionState(false);
  setStatus("未连接桌面端，请先打开 Dashboard 完成自动配对。", "warn");
}

function openDashboard() {
  chrome.tabs.create({ url: chrome.runtime.getURL("dashboard.html") });
  window.close();
}

async function showDiagnosticWindow() {
  const resp = await sendMessage({ type: "show_diagnostic_window" });
  if (!resp || !resp.ok) {
    setStatus((resp && (resp.error || resp.detail)) || "无法显示诊断窗口", "error");
    return;
  }
  setStatus("诊断窗口已显示。", "ok");
}

async function init() {
  ui.openDashboardBtn.addEventListener("click", openDashboard);
  ui.showWindowBtn.addEventListener("click", showDiagnosticWindow);
  ui.retryBtn.addEventListener("click", refreshConnection);
  await refreshConnection();
}

init();
