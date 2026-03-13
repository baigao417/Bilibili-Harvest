(function () {
  const ROOT_ID   = "bh-floating-root";
  const TOGGLE_ID = "bh-floating-toggle";
  const PANEL_ID  = "bh-floating-panel";
  const TOAST_ID  = "bh-floating-toast";
  const STYLE_ID  = "bh-injected-styles";

  /* ═══ Utility: BV extraction (unchanged logic) ═══ */

  function extractBv(text) {
    const hit = String(text || "").match(/BV[0-9A-Za-z]{10}/i);
    return hit ? hit[0].toUpperCase() : "";
  }

  function normalizeVideoUrl(rawUrl, dataBvid) {
    if (dataBvid) {
      const bv = extractBv(dataBvid);
      if (bv) return { bv, url: `https://www.bilibili.com/video/${bv}` };
    }
    const text = String(rawUrl || "").trim();
    if (!text) return null;
    let urlObj;
    try { urlObj = new URL(text, window.location.origin); } catch (_) { return null; }
    const fromQuery = extractBv(urlObj.searchParams.get("bvid") || "");
    if (fromQuery) return { bv: fromQuery, url: `https://www.bilibili.com/video/${fromQuery}` };
    const fromHref = extractBv(urlObj.href);
    if (fromHref) return { bv: fromHref, url: `https://www.bilibili.com/video/${fromHref}` };
    return null;
  }

  function collectVisibleVideoUrls() {
    const elements = document.querySelectorAll('a[href], [data-bvid], a[href*="bvid="], a[href*="/video/av"]');
    const byBv = new Map();
    let skippedAvOnly = 0;
    for (const node of elements) {
      if (!(node instanceof Element)) continue;
      const dataBvid = node.getAttribute("data-bvid") || "";
      const href = node.getAttribute("href") || "";
      const resolved = normalizeVideoUrl(href, dataBvid);
      if (resolved && resolved.bv) {
        if (!byBv.has(resolved.bv)) byBv.set(resolved.bv, resolved.url);
        continue;
      }
      if (/\/video\/av[0-9]+/i.test(href)) skippedAvOnly += 1;
    }
    const urls = Array.from(byBv.values());
    const warnings = [];
    if (skippedAvOnly > 0) warnings.push(`跳过 ${skippedAvOnly} 条仅 av 链接（无法稳定提取 BV）`);
    return { urls, warnings };
  }

  function summarizeSendResult(resp) {
    if (!resp || !resp.ok) {
      return { text: `发送失败：${resp?.error || "unknown error"}`, type: "error" };
    }
    const data = resp.data || resp;
    const accepted = Number(data.accepted || 0);
    const duplicates = Number(data.duplicates || 0);
    const failed = Number(data.failed || 0);
    if (failed <= 0) return { text: `已入队 ${accepted} 条，重复 ${duplicates} 条`, type: "ok" };
    if (accepted > 0 || duplicates > 0) return { text: `已入队 ${accepted} 条，重复 ${duplicates} 条，失败 ${failed} 条`, type: "warn" };
    return { text: `发送失败：${failed} 条失败`, type: "error" };
  }

  /* ═══ Inject Stylesheet ═══ */

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      /* ── Root container ── */
      #${ROOT_ID} {
        position: fixed;
        right: 18px;
        bottom: 18px;
        z-index: 2147483647;
        font-family: "Microsoft YaHei UI", "Segoe UI", system-ui, -apple-system, sans-serif;
        line-height: 1.5;
      }

      /* ── Toggle button ── */
      #${TOGGLE_ID} {
        width: 48px;
        height: 48px;
        border: none;
        border-radius: 50%;
        background: linear-gradient(135deg, #23c9ed 0%, #00a1d6 100%);
        color: #fff;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 4px 18px rgba(0, 161, 214, 0.35),
                    0 0 0 0 rgba(0, 161, 214, 0);
        transition: transform 0.22s cubic-bezier(.4,0,.2,1),
                    box-shadow 0.22s cubic-bezier(.4,0,.2,1);
        outline: none;
      }
      #${TOGGLE_ID}:hover {
        transform: scale(1.1);
        box-shadow: 0 6px 24px rgba(0, 161, 214, 0.45),
                    0 0 0 4px rgba(0, 161, 214, 0.12);
      }
      #${TOGGLE_ID}:active {
        transform: scale(0.93);
      }
      #${TOGGLE_ID} svg {
        pointer-events: none;
      }

      /* ── Panel ── */
      #${PANEL_ID} {
        width: 208px;
        margin-top: 10px;
        padding: 16px;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.82);
        backdrop-filter: blur(24px) saturate(180%);
        -webkit-backdrop-filter: blur(24px) saturate(180%);
        border: 1px solid rgba(0, 0, 0, 0.06);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.10),
                    0 1px 3px rgba(0, 0, 0, 0.04);
        transform-origin: bottom right;
      }
      #${PANEL_ID}.bh-panel-show {
        display: block;
        animation: bh-panelIn 0.25s cubic-bezier(.4,0,.2,1) both;
      }
      #${PANEL_ID}.bh-panel-hide {
        display: none;
      }

      .bh-panel-title {
        font-size: 13px;
        font-weight: 700;
        color: #1a1f2e;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 7px;
      }
      .bh-panel-title svg {
        flex-shrink: 0;
        opacity: 0.6;
      }

      /* ── Panel buttons ── */
      .bh-btn {
        width: 100%;
        padding: 9px 12px;
        border: none;
        border-radius: 9px;
        color: #fff;
        font-size: 12px;
        font-weight: 600;
        font-family: inherit;
        cursor: pointer;
        transition: transform 0.15s, box-shadow 0.15s, opacity 0.15s;
        margin-bottom: 7px;
        outline: none;
      }
      .bh-btn:last-child { margin-bottom: 0; }
      .bh-btn:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.14);
      }
      .bh-btn:active {
        transform: scale(0.97);
      }

      .bh-btn-primary {
        background: linear-gradient(135deg, #23c9ed 0%, #00a1d6 100%);
        box-shadow: 0 2px 8px rgba(0, 161, 214, 0.25);
      }
      .bh-btn-success {
        background: linear-gradient(135deg, #34d399 0%, #12b886 100%);
        box-shadow: 0 2px 8px rgba(18, 184, 134, 0.2);
      }

      /* ── Toast ── */
      #${TOAST_ID} {
        position: fixed;
        right: 18px;
        bottom: 84px;
        z-index: 2147483647;
        max-width: 340px;
        padding: 10px 14px;
        border-radius: 10px;
        font-size: 12px;
        line-height: 1.5;
        font-family: "Microsoft YaHei UI", "Segoe UI", system-ui, sans-serif;
        color: #fff;
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        box-shadow: 0 8px 28px rgba(0, 0, 0, 0.16);
        pointer-events: none;
      }
      #${TOAST_ID}.bh-toast-in {
        animation: bh-slideIn 0.3s cubic-bezier(.4,0,.2,1) both;
      }
      #${TOAST_ID}.bh-toast-out {
        animation: bh-slideOut 0.28s cubic-bezier(.4,0,.2,1) both;
      }

      .bh-toast-ok    { background: rgba(18, 184, 134, 0.92); }
      .bh-toast-warn  { background: rgba(232, 133, 12, 0.92); }
      .bh-toast-error { background: rgba(224, 49, 49, 0.92); }

      /* ── Dark mode ── */
      @media (prefers-color-scheme: dark) {
        #${PANEL_ID} {
          background: rgba(28, 31, 42, 0.85);
          border-color: rgba(255, 255, 255, 0.07);
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35),
                      0 1px 3px rgba(0, 0, 0, 0.15);
        }
        .bh-panel-title { color: #e0e4ed; }
      }

      /* ── Animations ── */
      @keyframes bh-panelIn {
        from { opacity: 0; transform: scale(0.9) translateY(8px); }
        to   { opacity: 1; transform: scale(1)   translateY(0); }
      }
      @keyframes bh-slideIn {
        from { opacity: 0; transform: translateX(50px); }
        to   { opacity: 1; transform: translateX(0); }
      }
      @keyframes bh-slideOut {
        from { opacity: 1; transform: translateX(0); }
        to   { opacity: 0; transform: translateX(50px); }
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  /* ═══ Toast ═══ */

  function showToast(text, type) {
    let node = document.getElementById(TOAST_ID);
    if (!node) {
      node = document.createElement("div");
      node.id = TOAST_ID;
      document.body.appendChild(node);
    }

    clearTimeout(node.__hideTimer);
    clearTimeout(node.__removeTimer);

    node.textContent = text;
    node.className = `bh-toast-${type || "error"} bh-toast-in`;
    node.style.display = "block";

    node.__hideTimer = setTimeout(() => {
      node.className = `bh-toast-${type || "error"} bh-toast-out`;
      node.__removeTimer = setTimeout(() => {
        node.style.display = "none";
      }, 300);
    }, 3800);
  }

  /* ═══ Build UI ═══ */

  function createUi() {
    if (document.getElementById(ROOT_ID)) return;

    injectStyles();

    const root = document.createElement("div");
    root.id = ROOT_ID;

    /* ── Toggle button with inline SVG icon ── */
    const toggle = document.createElement("button");
    toggle.id = TOGGLE_ID;
    toggle.title = "BilibiliHarvest";
    toggle.innerHTML = `<svg width="24" height="24" viewBox="0 0 128 128" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="16" y="34" width="96" height="66" rx="14" fill="white"/>
      <rect x="30" y="14" width="6" height="26" rx="3" fill="white" transform="rotate(-18 33 27)"/>
      <rect x="92" y="14" width="6" height="26" rx="3" fill="white" transform="rotate(18 95 27)"/>
      <ellipse cx="44" cy="62" rx="6" ry="7" fill="#00a1d6"/>
      <ellipse cx="84" cy="62" rx="6" ry="7" fill="#00a1d6"/>
      <path d="M52 78 Q64 86 76 78" fill="none" stroke="#00a1d6" stroke-width="3.5" stroke-linecap="round"/>
    </svg>`;

    /* ── Panel ── */
    const panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.className = "bh-panel-hide";

    const title = document.createElement("div");
    title.className = "bh-panel-title";
    title.innerHTML = `<svg width="16" height="16" viewBox="0 0 128 128" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="128" height="128" rx="28" fill="#00a1d6"/>
      <rect x="24" y="38" width="80" height="58" rx="12" fill="white"/>
      <rect x="36" y="18" width="6" height="26" rx="3" fill="white" transform="rotate(-18 39 31)"/>
      <rect x="86" y="18" width="6" height="26" rx="3" fill="white" transform="rotate(18 89 31)"/>
      <ellipse cx="47" cy="62" rx="5" ry="6" fill="#00a1d6"/>
      <ellipse cx="81" cy="62" rx="5" ry="6" fill="#00a1d6"/>
    </svg>BilibiliHarvest`;
    panel.appendChild(title);

    const btnSendCurrent = document.createElement("button");
    btnSendCurrent.textContent = "发送当前页";
    btnSendCurrent.className = "bh-btn bh-btn-primary";

    const btnSendBulk = document.createElement("button");
    btnSendBulk.textContent = "批量发送可见视频";
    btnSendBulk.className = "bh-btn bh-btn-success";

    panel.appendChild(btnSendCurrent);
    panel.appendChild(btnSendBulk);
    root.appendChild(toggle);
    root.appendChild(panel);
    document.body.appendChild(root);

    /* ── Toggle panel visibility ── */
    toggle.addEventListener("click", () => {
      const isHidden = panel.classList.contains("bh-panel-hide");
      panel.className = isHidden ? "bh-panel-show" : "bh-panel-hide";
    });

    /* ── Send current page ── */
    btnSendCurrent.addEventListener("click", () => {
      chrome.runtime.sendMessage(
        { type: "send_to_harvest", url: window.location.href },
        (resp) => {
          if (chrome.runtime.lastError) {
            showToast(`发送失败：${chrome.runtime.lastError.message}`, "error");
            return;
          }
          const summary = summarizeSendResult(resp);
          showToast(summary.text, summary.type);
        }
      );
    });

    /* ── Bulk send visible videos ── */
    btnSendBulk.addEventListener("click", () => {
      const extracted = collectVisibleVideoUrls();
      if (!extracted.urls.length) {
        showToast("未发现可见视频链接", "error");
        return;
      }
      chrome.runtime.sendMessage(
        { type: "bulk_send_to_harvest", urls: extracted.urls },
        (resp) => {
          if (chrome.runtime.lastError) {
            showToast(`发送失败：${chrome.runtime.lastError.message}`, "error");
            return;
          }
          const summary = summarizeSendResult(resp);
          const warningText = extracted.warnings.length ? `；${extracted.warnings.join("；")}` : "";
          showToast(`${summary.text}${warningText}`, summary.type);
        }
      );
    });
  }

  /* ═══ Mount Guard ═══ */

  function ensureUiMounted() {
    if (!document.body) return;
    if (!document.getElementById(ROOT_ID)) createUi();
  }

  ensureUiMounted();
  const observer = new MutationObserver(() => ensureUiMounted());
  if (document.documentElement) {
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }
  setInterval(ensureUiMounted, 3000);
})();
