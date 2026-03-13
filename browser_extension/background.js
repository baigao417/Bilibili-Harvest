const DEFAULT_TOKEN = "";

const DEFAULTS = {
  port: 16780,
  token: DEFAULT_TOKEN,
  paired: false,
  extension_id: "",
  archive_root: "",
  source_type: "auto",
  import_mode: "single",
  limit: 200,
  order: "pubdate_desc",
  save_selected: false,
  custom_url: ""
};

function normalizeConfig(data) {
  const merged = { ...DEFAULTS, ...(data || {}) };
  const allowedSourceTypes = ["single", "multi_p", "favorite", "collection", "series", "space_uploads", "auto"];
  const sourceType = String(merged.source_type || DEFAULTS.source_type).trim();
  const normalizedSourceType = allowedSourceTypes.includes(sourceType) ? sourceType : DEFAULTS.source_type;
  return {
    ...merged,
    port: Number(merged.port || DEFAULTS.port),
    token: String(merged.token || "").trim(),
    paired: Boolean(merged.paired),
    extension_id: String(merged.extension_id || "").trim(),
    archive_root: String(merged.archive_root || "").trim(),
    source_type: normalizedSourceType,
    import_mode: merged.import_mode || DEFAULTS.import_mode,
    limit: Number(merged.limit || DEFAULTS.limit),
    order: merged.order || DEFAULTS.order,
    save_selected: Boolean(merged.save_selected),
    custom_url: String(merged.custom_url || "").trim()
  };
}

function getConfig() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(DEFAULTS, (data) => resolve(normalizeConfig(data)));
  });
}

function saveConfig(payload) {
  const normalized = normalizeConfig(payload || {});
  return new Promise((resolve) => {
    chrome.storage.sync.set(normalized, () => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message || "save config failed" });
        return;
      }
      resolve({ ok: true });
    });
  });
}

function normalizeFetchError(err) {
  const text = String(err || "");
  if (text.includes("Failed to fetch")) {
    return "Cannot reach local service. Check service status, origin policy, and port.";
  }
  return text || "Request failed";
}

async function parseResponseBody(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch (_err) {
    return { raw: text };
  }
}

function classifyHttpError(status, detail) {
  if (status === 401) {
    return "Token mismatch. Update token in extension if you manually reset it in app.";
  }
  if (status === 403) {
    return "Origin blocked. Only localhost and browser extension origins are allowed.";
  }
  if (status >= 500) {
    return `Local service error (${status}): ${detail || "internal error"}`;
  }
  return `Request failed (${status}): ${detail || "unknown error"}`;
}

async function callApi(path, method, payload) {
  const cfg = await getConfig();
  const endpoint = `http://127.0.0.1:${Number(cfg.port || 16780)}${path}`;
  const init = {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-BilibiliHarvest-Token": cfg.token
    }
  };
  if (method !== "GET") {
    init.body = JSON.stringify(payload || {});
  }

  let response;
  try {
    response = await fetch(endpoint, init);
  } catch (err) {
    return { ok: false, error: normalizeFetchError(err) };
  }

  const body = await parseResponseBody(response);
  if (!response.ok) {
    const detail = body?.detail || body?.error || body?.raw || "";
    return {
      ok: false,
      status: response.status,
      error: classifyHttpError(response.status, detail),
      detail: detail || ""
    };
  }

  return { ok: true, data: body };
}

async function callHealth() {
  return callApi("/v1/health", "GET");
}

async function callPairingInfoOnPort(port) {
  const endpoint = `http://127.0.0.1:${Number(port || 16780)}/v1/pairing/info`;
  let response;
  try {
    response = await fetch(endpoint, { method: "GET" });
  } catch (err) {
    return { ok: false, error: normalizeFetchError(err), port: Number(port || 16780) };
  }

  const body = await parseResponseBody(response);
  if (!response.ok) {
    const detail = body?.detail || body?.error || body?.raw || "";
    return {
      ok: false,
      status: response.status,
      error: classifyHttpError(response.status, detail),
      detail: detail || "",
      port: Number(port || 16780),
    };
  }

  return { ok: true, data: body, port: Number(port || 16780) };
}

async function scanPairingPorts(startPort = 16780, endPort = 16800) {
  for (let port = Number(startPort); port <= Number(endPort); port += 1) {
    const resp = await callPairingInfoOnPort(port);
    if (resp.ok) {
      return resp;
    }
  }
  return { ok: false, error: "Desktop service not found in scan range." };
}

async function callPairingClaim(port, extensionId) {
  const endpoint = `http://127.0.0.1:${Number(port || 16780)}/v1/pairing/claim`;
  let response;
  try {
    response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ extension_id: String(extensionId || "").trim() }),
    });
  } catch (err) {
    return { ok: false, error: normalizeFetchError(err) };
  }

  const body = await parseResponseBody(response);
  if (!response.ok) {
    const detail = body?.detail || body?.error || body?.raw || "";
    return {
      ok: false,
      status: response.status,
      error: classifyHttpError(response.status, detail),
      detail: detail || "",
    };
  }

  const data = body || {};
  const pairedConfig = normalizeConfig({
    ...(await getConfig()),
    port: Number(data.port || port || DEFAULTS.port),
    token: String(data.token || "").trim(),
    paired: true,
    extension_id: String(data.extension_id || extensionId || "").trim(),
    archive_root: String(data.archive_root || "").trim(),
  });
  await saveConfig(pairedConfig);
  return { ok: true, data };
}

async function callConfigGet() {
  return callApi("/v1/config", "GET");
}

async function callConfigPatch(payload) {
  return callApi("/v1/config", "PATCH", payload || {});
}

async function callWindowShow() {
  return callApi("/v1/window/show", "POST", {});
}

async function callAdd(payload) {
  return callApi("/v1/tasks/add", "POST", payload);
}

async function callAddPrefetched(payload) {
  return callApi("/v1/tasks/add_prefetched", "POST", payload);
}

async function callBindPrefetched(payload) {
  return callApi("/v1/tasks/bind_prefetched", "POST", payload);
}

async function callBulkAdd(payload) {
  return callApi("/v1/tasks/bulk_add", "POST", payload);
}

// 鈹€鈹€ Dashboard API calls 鈹€鈹€

async function callListTasks() {
  return callApi("/v1/tasks", "GET");
}

async function callBatchStatus() {
  return callApi("/v1/batch/status", "GET");
}

async function callBatchStart() {
  return callApi("/v1/batch/start", "POST", {});
}

async function callBatchStop() {
  return callApi("/v1/batch/stop", "POST", {});
}

async function callBatchExport(payload) {
  return callApi("/v1/batch/export", "POST", payload || {});
}

async function callDeleteTask(seq) {
  return callApi(`/v1/tasks/${seq}`, "DELETE");
}

async function callRetryTask(seq) {
  return callApi(`/v1/tasks/${seq}/retry`, "POST", {});
}

async function callClearTasks() {
  return callApi("/v1/tasks/clear", "DELETE");
}

async function callNlmStatus() {
  return callApi("/v1/notebooklm/status", "GET");
}

async function callNlmNotebooks() {
  return callApi("/v1/notebooklm/notebooks", "GET");
}

async function callNlmCreateNotebook(title) {
  return callApi("/v1/notebooklm/notebooks", "POST", { title });
}

async function callNlmPushStatus(jobId) {
  return callApi(`/v1/notebooklm/push/${jobId}`, "GET");
}

function extractBv(text) {
  const hit = String(text || "").match(/BV[0-9A-Za-z]{10}/i);
  return hit ? hit[0].toUpperCase() : "";
}

function normalizeUrlList(urls) {
  const seen = new Set();
  const result = [];
  for (const item of urls || []) {
    const raw = String(item || "").trim();
    if (!raw) {
      continue;
    }
    const key = extractBv(raw) || raw;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(raw);
  }
  return result;
}

function chunkArray(arr, size) {
  const chunks = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

const ALLOWED_SOURCE_TYPES = new Set([
  "single",
  "multi_p",
  "favorite",
  "collection",
  "series",
  "space_uploads",
  "auto"
]);

const ALLOWED_IMPORT_MODES = new Set(["single", "all_pages"]);

function normalizeBulkDefaults(rawDefaults, cfg) {
  const defaults = (rawDefaults && typeof rawDefaults === "object") ? rawDefaults : {};
  const options = (defaults.options && typeof defaults.options === "object") ? defaults.options : {};

  const rawSourceType = String(defaults.source_type || cfg.source_type || "auto").trim();
  const source_type = ALLOWED_SOURCE_TYPES.has(rawSourceType) ? rawSourceType : "auto";

  const rawImportMode = String(options.import_mode || cfg.import_mode || "single").trim().toLowerCase();
  const import_mode = ALLOWED_IMPORT_MODES.has(rawImportMode) ? rawImportMode : "single";

  const parsedLimit = Number(options.limit ?? cfg.limit ?? 200);
  const limit = Number.isFinite(parsedLimit)
    ? Math.max(1, Math.min(Math.trunc(parsedLimit), 2000))
    : 200;

  const order = String(options.order || cfg.order || "pubdate_desc").trim() || "pubdate_desc";
  const cookie_header = options.cookie_header == null ? null : String(options.cookie_header).trim();
  const save_selected = defaults.save_selected == null ? Boolean(cfg.save_selected) : Boolean(defaults.save_selected);

  return {
    source_type,
    options: {
      import_mode,
      limit,
      order,
      cookie_header
    },
    save_selected
  };
}

function _toSingleTaskPayload(cfg, input, rawOverrides = null) {
  const overrides = (rawOverrides && typeof rawOverrides === "object") ? rawOverrides : {};
  const hasOwn = (key) => Object.prototype.hasOwnProperty.call(overrides, key);

  const rawSourceType = String(overrides.source_type || "single").trim();
  const source_type = ALLOWED_SOURCE_TYPES.has(rawSourceType) ? rawSourceType : "single";

  const rawImportMode = String(overrides.import_mode || "single").trim().toLowerCase();
  const import_mode = ALLOWED_IMPORT_MODES.has(rawImportMode) ? rawImportMode : "single";

  const parsedLimit = Number(hasOwn("limit") ? overrides.limit : (cfg.limit ?? 200));
  const limit = Number.isFinite(parsedLimit)
    ? Math.max(1, Math.min(Math.trunc(parsedLimit), 2000))
    : 200;

  const order = String(overrides.order || cfg.order || "pubdate_desc").trim() || "pubdate_desc";

  let cookie_header = null;
  if (hasOwn("cookie_header")) {
    cookie_header = overrides.cookie_header == null ? null : String(overrides.cookie_header).trim() || null;
  }

  const save_selected = hasOwn("save_selected")
    ? Boolean(overrides.save_selected)
    : Boolean(cfg.save_selected);

  return {
    source_type,
    input,
    options: {
      import_mode,
      limit,
      order,
      cookie_header
    },
    save_selected
  };
}

async function collectNativeSubtitleFromTab(tabId, { maxRetries = 5, retryDelayMs = 2000 } = {}) {
  if (!tabId || !chrome.scripting || typeof chrome.scripting.executeScript !== "function") {
    return { ok: false, error: "scripting unavailable or tab missing" };
  }

  let scriptResult;
  try {
    const injected = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      args: [maxRetries, retryDelayMs],
      func: async (MAX_RETRIES, RETRY_DELAY_MS) => {
        const toAbsUrl = (rawUrl) => {
          const text = String(rawUrl || "").trim();
          if (!text) return "";
          if (text.startsWith("//")) return `https:${text}`;
          if (text.startsWith("http://") || text.startsWith("https://")) return text;
          if (text.startsWith("/")) return `https://api.bilibili.com${text}`;
          return `https://${text.replace(/^\/+/, "")}`;
        };

        const extractBv = (text) => {
          const hit = String(text || "").match(/BV[0-9A-Za-z]{10}/i);
          return hit ? hit[0].toUpperCase() : "";
        };

        const normalizeSegments = (payload) => {
          const body = payload && Array.isArray(payload.body) ? payload.body : [];
          const segments = [];
          for (const row of body) {
            if (!row || typeof row !== "object") continue;
            const text = String(row.content || row.text || "").trim();
            const fromRaw = row.from ?? row.start;
            const toRaw = row.to ?? row.end ?? fromRaw;
            const from = Number(fromRaw);
            const to = Number(toRaw);
            if (!text) continue;
            if (!Number.isFinite(from) || !Number.isFinite(to)) continue;
            if (from < 0 || to < from) continue;
            segments.push({ start_sec: from, end_sec: to, text });
          }
          return segments;
        };

        const langRank = (lang, trackType) => {
          const key = String(lang || "").toLowerCase();
          if (key === "zh-cn") return 0;
          if (key === "zh-hans") return 1;
          if (key === "zh") return 2;
          if (key.startsWith("ai-zh")) return 3;
          if (trackType === "uploader") return 4;
          return 5;
        };

        const parseCurrentPage = () => {
          const p = Number(new URL(location.href).searchParams.get("p") || "1");
          return Number.isFinite(p) && p > 0 ? Math.trunc(p) : 1;
        };

        // 从页面内嵌数据读取 aid/cid，兼容普通视频和合集/剧集
        // window.__INITIAL_STATE__ 由 B站注入，不需要额外网络请求
        const _readPageAidCid = () => {
          try {
            const st = window.__INITIAL_STATE__;
            if (!st) return null;
            // 普通视频
            const vd = st.videoData || st;
            const aid = Number(vd.aid || st.aid || 0) || null;
            // cid：优先当前分P
            let cid = null;
            const pages = Array.isArray(vd.pages) ? vd.pages : [];
            if (pages.length > 0) {
              const p = parseCurrentPage();
              const hit = pages.find(pg => Number(pg && pg.page) === p) || pages[0];
              cid = Number((hit && hit.cid) || 0) || null;
            }
            if (!cid) cid = Number(vd.cid || st.cid || 0) || null;
            return (aid && cid) ? { aid, cid } : null;
          } catch (e) { return null; }
        };

        // 从播放器实例( window.player / __biliPlayer )读取 cid
        const _readPlayerCid = () => {
          try {
            const p = window.player || window.__biliPlayer;
            if (p && typeof p.getCid === "function") return Number(p.getCid()) || null;
            if (p && p.config && p.config.cid) return Number(p.config.cid) || null;
          } catch (e) {}
          return null;
        };

        try {
          const url = new URL(location.href);
          const bvid = extractBv(url.searchParams.get("bvid") || "") || extractBv(url.pathname);
          if (!bvid) {
            console.error("[bili2text] 注入脚本失败: bvid_not_found, href=", location.href);
            return { ok: false, error: "bvid_not_found" };
          }
          console.log("[bili2text] 注入脚本开始, bvid=", bvid);

          // ① 优先读页面内嵌数据（无需网络，支持合集/剧集）
          let aid = null, cid = null;
          const pageData = _readPageAidCid();
          if (pageData) {
            aid = pageData.aid;
            cid = pageData.cid;
            console.log("[bili2text] 从 __INITIAL_STATE__ 读取: aid=", aid, "cid=", cid);
          }

          // ② 兜底：调用 view API（普通视频可用，合集/剧集可能 -404）
          if (!aid || !cid) {
            console.log("[bili2text] __INITIAL_STATE__ 不可用，改用 view API");
            const viewResp = await fetch(`https://api.bilibili.com/x/web-interface/view?bvid=${encodeURIComponent(bvid)}`, {
              credentials: "include",
            });
            const viewPayload = await viewResp.json();
            console.log("[bili2text] view API: code=", viewPayload && viewPayload.code, "aid=", viewPayload && viewPayload.data && viewPayload.data.aid);
            if (viewPayload && viewPayload.code === 0) {
              const vd = viewPayload.data || {};
              aid = Number(vd.aid || 0) || null;
              const pages = Array.isArray(vd.pages) ? vd.pages : [];
              const p = parseCurrentPage();
              const hit = pages.find(pg => Number(pg && pg.page) === p) || pages[0] || null;
              cid = Number((hit && hit.cid) || vd.cid || 0) || null;
            }
          }

          // ③ 再兜底：从播放器实例读 cid（合集切集后最准确）
          if (aid && !cid) {
            cid = _readPlayerCid();
            if (cid) console.log("[bili2text] 从播放器实例读 cid=", cid);
          }

          console.log("[bili2text] 最终: aid=", aid, "cid=", cid);
          if (!aid || !cid) {
            console.error("[bili2text] 注入脚本失败: aid_or_cid_missing. __INITIAL_STATE__ keys=",
              window.__INITIAL_STATE__ ? Object.keys(window.__INITIAL_STATE__) : "undefined");
            return { ok: false, error: "aid_or_cid_missing" };
          }

          // ── 重试循环：B站 AI 字幕异步生成，需等待后端就绪 ──
          const _sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const _mapTrack = (track) => {
            const lan = String((track || {}).lan || "").trim();
            const subtitleUrl = toAbsUrl((track || {}).subtitle_url || "");
            if (!lan || !subtitleUrl) return null;
            if (lan.toLowerCase() === "danmaku") return null;
            if (subtitleUrl.toLowerCase().endsWith(".xml")) return null;
            const trackType = (lan.toLowerCase().startsWith("ai-") || Boolean((track || {}).ai_type)) ? "ai" : "uploader";
            return { lan, subtitle_url: subtitleUrl, track_type: trackType };
          };

          let usableTracks = [];
          for (let _i = 0; _i < MAX_RETRIES; _i++) {
            if (_i > 0) {
              console.debug(`[bili2text] wbi/v2 字幕重试 ${_i}/${MAX_RETRIES - 1}`);  
              await _sleep(RETRY_DELAY_MS);
            }
            const playerResp = await fetch(`https://api.bilibili.com/x/player/wbi/v2?aid=${aid}&cid=${cid}`, {
              credentials: "include",
            });
            const playerPayload = await playerResp.json();
            if (!playerPayload || playerPayload.code !== 0) {
              console.error("[bili2text] wbi/v2 失败: code=", playerPayload && playerPayload.code, playerPayload && playerPayload.message);
              return { ok: false, error: "player_wbi_v2_failed", detail: playerPayload && playerPayload.code };
            }
            const subtitleRoot = ((playerPayload.data || {}).subtitle || {});
            const subtitleItems = Array.isArray(subtitleRoot.subtitles) ? subtitleRoot.subtitles : [];
            console.log(`[bili2text] wbi/v2 subtitles count: ${subtitleItems.length}`, subtitleItems.map(t => t && t.lan));
            usableTracks = subtitleItems.map(_mapTrack).filter(Boolean);
            if (usableTracks.length > 0) break;
          }

          if (!usableTracks.length) {
            console.error("[bili2text] 没有可用字幕轨道（重试全部失败）");
            return { ok: false, error: "no_usable_track" };
          }

          usableTracks.sort((a, b) => {
            const ar = langRank(a.lan, a.track_type);
            const br = langRank(b.lan, b.track_type);
            if (ar !== br) return ar - br;
            if (a.track_type !== b.track_type) return a.track_type === "uploader" ? -1 : 1;
            return a.lan.localeCompare(b.lan);
          });

          const selected = usableTracks[0];
          // 字幕 JSON 在 CDN（aisubtitle.hdslb.com），返回 CORS: *，不能带 credentials
          const subtitleResp = await fetch(selected.subtitle_url, { credentials: "omit" });
          const subtitlePayload = await subtitleResp.json();
          const segments = normalizeSegments(subtitlePayload);
          if (!segments.length) {
            return { ok: false, error: "subtitle_segments_empty" };
          }

          return {
            ok: true,
            prefetched_subtitle: {
              aid,
              cid,
              lang: selected.lan,
              track_type: selected.track_type,
              subtitle_url: selected.subtitle_url,
              segments,
              collected_at: new Date().toISOString(),
            },
          };
        } catch (err) {
          return { ok: false, error: `prefetch_exception:${String(err || "")}` };
        }
      },
    });
    scriptResult = injected && injected[0] ? injected[0].result : null;
  } catch (err) {
    return { ok: false, error: normalizeFetchError(err) };
  }

  if (!scriptResult || !scriptResult.ok || !scriptResult.prefetched_subtitle) {
    return { ok: false, error: (scriptResult && scriptResult.error) || "prefetch_failed" };
  }
  return { ok: true, prefetched_subtitle: scriptResult.prefetched_subtitle };
}

function resolveTabIdForSend(message, sender) {
  const msgTabId = Number((message && message.tab_id) ?? NaN);
  if (Number.isFinite(msgTabId) && msgTabId > 0) {
    return Math.trunc(msgTabId);
  }

  const senderTabId = Number((sender && sender.tab && sender.tab.id) ?? NaN);
  if (Number.isFinite(senderTabId) && senderTabId > 0) {
    return Math.trunc(senderTabId);
  }

  return null;
}

function withPrefetchMeta(response, attempted, reason) {
  const normalized = (response && typeof response === "object")
    ? { ...response }
    : { ok: false, error: "invalid response" };
  normalized.prefetch_attempted = Boolean(attempted);
  normalized.prefetch_local_reason = String(reason || "").trim() || "fallback_add";
  return normalized;
}

async function sendSingle(url, tabId, payloadOverrides = null) {
  const cfg = await getConfig();
  const input = String(url || "").trim();
  if (!input) {
    return { ok: false, error: "Missing URL to send." };
  }

  const basePayload = _toSingleTaskPayload(cfg, input, payloadOverrides);

  if (!tabId) {
    const fallbackResp = await callAdd(basePayload);
    return withPrefetchMeta(fallbackResp, false, "tab_missing");
  }

  const prefetched = await collectNativeSubtitleFromTab(tabId);
  if (!prefetched.ok || !prefetched.prefetched_subtitle) {
    const fallbackResp = await callAdd(basePayload);
    // 延迟绑定：异步地继续轮询字幕，一旦就绪就推送给已入队任务
    if (tabId && fallbackResp.ok) {
      // 每 1 分钟重试一次（alarms 最小间隔），最多 4 次（约 4 分钟）
      scheduleDelayedBinding(input, tabId, 1, 4, 60000);
    }
    return withPrefetchMeta(fallbackResp, true, "collect_failed");
  }

  const prefetchedResp = await callAddPrefetched({
    ...basePayload,
    prefetched_subtitle: prefetched.prefetched_subtitle,
  });
  if (prefetchedResp.ok) {
    const bound = Boolean(prefetchedResp?.data?.prefetch_bound);
    return withPrefetchMeta(prefetchedResp, true, bound ? "api_bound" : "fallback_add");
  }

  const fallbackResp = await callAdd(basePayload);
  return withPrefetchMeta(fallbackResp, true, "api_rejected");
}

// ── 延迟绑定：使用 chrome.alarms 解决 MV3 Service Worker 休眠问题 ──
// SW 空闲 5 秒即被休眠，setTimeout 回调不会触发；alarms 会唤醒 SW
const BINDING_ALARM_PREFIX = "bili2text_bind_";

async function _getPendingBindings() {
  return new Promise((resolve) => {
    try {
      chrome.storage.session.get("_pendingBindings", (data) => {
        resolve((data && data._pendingBindings) || {});
      });
    } catch (e) { resolve({}); }
  });
}

async function _setPendingBindings(map) {
  return new Promise((resolve) => {
    try {
      chrome.storage.session.set({ _pendingBindings: map }, resolve);
    } catch (e) { resolve(); }
  });
}

async function scheduleDelayedBinding(url, tabId, attempt, maxAttempts, intervalMs) {
  if (attempt > maxAttempts || !tabId) return;
  const alarmName = `${BINDING_ALARM_PREFIX}${tabId}_${attempt}`;
  const bindings = await _getPendingBindings();
  bindings[alarmName] = { url, tabId, attempt, maxAttempts, intervalMs };
  await _setPendingBindings(bindings);
  // chrome.alarms 生产环境最小延迟 1 分钟，确保兼容
  const delayMins = Math.max(1, intervalMs / 60000);
  chrome.alarms.create(alarmName, { delayInMinutes: delayMins });
  console.debug(`[bili2text] 延迟绑定已调度 alarm=${alarmName}, 约${delayMins}分钟后`);
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm || !alarm.name.startsWith(BINDING_ALARM_PREFIX)) return;
  const bindings = await _getPendingBindings();
  const job = bindings[alarm.name];
  if (!job) return;
  delete bindings[alarm.name];
  await _setPendingBindings(bindings);

  const { url, tabId, attempt, maxAttempts, intervalMs } = job;
  try {
    console.debug(`[bili2text] 延迟绑定字幕 尝试 ${attempt}/${maxAttempts}: ${url}`);
    const result = await collectNativeSubtitleFromTab(tabId, { maxRetries: 1, retryDelayMs: 0 });
    if (result.ok && result.prefetched_subtitle) {
      const resp = await callBindPrefetched({ input: url, prefetched_subtitle: result.prefetched_subtitle });
      if (resp.ok && resp.data && resp.data.prefetch_bound) {
        console.debug(`[bili2text] 延迟绑定成功！尝试 ${attempt}, url=${url}`);
        return; // 绑定成功，停止轮询
      }
    }
  } catch (e) {
    console.debug(`[bili2text] 延迟绑定异常: ${e}`);
  }
  // 未成功，调度下一次
  await scheduleDelayedBinding(url, tabId, attempt + 1, maxAttempts, intervalMs);
});

function shouldUseAddTaskSinglePrefetch(payload) {
  const p = (payload && typeof payload === "object") ? payload : {};
  const urls = Array.isArray(p.urls) ? p.urls : [];
  if (urls.length !== 1) {
    return false;
  }

  const tabId = Number(p.tab_id ?? NaN);
  if (!Number.isFinite(tabId) || tabId <= 0) {
    return false;
  }

  const sourceType = String(p.source_type || "auto").trim();
  if (!["auto", "single", "multi_p"].includes(sourceType)) {
    return false;
  }

  const importMode = String(p.import_mode || "single").trim().toLowerCase();
  return importMode === "single";
}

async function sendBulk(input, rawDefaults = null) {
  const cfg = await getConfig();
  const bulkDefaults = normalizeBulkDefaults(rawDefaults, cfg);

  // input can be an array of strings (urls) or {url, save_selected} objects
  const isItemFormat = Array.isArray(input) && input.length > 0 && typeof input[0] === "object";
  const rawItems = isItemFormat
    ? input.map(it => ({ url: String(it.url || "").trim(), save_selected: Boolean(it.save_selected) }))
    : (input || []).map(url => ({ url: String(url || "").trim(), save_selected: bulkDefaults.save_selected }));

  // Deduplicate by BV or raw URL
  const seen = new Set();
  const dedupedItems = [];
  for (const item of rawItems) {
    if (!item.url) continue;
    const key = extractBv(item.url) || item.url;
    if (seen.has(key)) continue;
    seen.add(key);
    dedupedItems.push(item);
  }

  if (!dedupedItems.length) {
    return { ok: false, error: "No valid video URLs found." };
  }

  const chunks = chunkArray(dedupedItems, 100);
  let accepted = 0;
  let duplicates = 0;
  let failed = 0;
  const warnings = [];
  let successChunks = 0;
  let failedChunks = 0;

  for (let i = 0; i < chunks.length; i += 1) {
    const block = chunks[i];
    const payload = {
      defaults: {
        source_type: bulkDefaults.source_type,
        options: bulkDefaults.options,
        save_selected: bulkDefaults.save_selected
      },
      items: block.map(item => ({
        input: item.url,
        ...(isItemFormat ? { save_selected: Boolean(item.save_selected) } : {})
      }))
    };

    const resp = await callBulkAdd(payload);
    if (!resp.ok) {
      failed += block.length;
      failedChunks += 1;
      warnings.push(`chunk ${i + 1}: ${resp.error || "bulk add failed"}`);
      continue;
    }

    successChunks += 1;
    const data = resp.data || {};
    accepted += Number(data.accepted || 0);
    duplicates += Number(data.duplicates || 0);
    failed += Number(data.failed || 0);
    for (const msg of data.warnings || []) {
      const text = String(msg || "").trim();
      if (text) {
        warnings.push(text);
      }
    }
  }

  const partial = (accepted > 0 || duplicates > 0) && failed > 0;
  const ok = failed === 0 && (accepted > 0 || duplicates > 0);
  return {
    ok,
    partial,
    accepted,
    duplicates,
    failed,
    warnings,
    chunks: {
      total: chunks.length,
      succeeded: successChunks,
      failed: failedChunks
    }
  };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== "object") {
    return false;
  }

  const done = (result) => sendResponse(result);
  const fail = (err) => sendResponse({ ok: false, error: normalizeFetchError(err) });

  if (message.type === "save_config") {
    saveConfig(message.payload || {}).then(done).catch(fail);
    return true;
  }

  if (message.type === "test_connection") {
    getConfig()
      .then((cfg) => (cfg && cfg.paired ? callHealth() : scanPairingPorts()))
      .then(done)
      .catch(fail);
    return true;
  }

  if (message.type === "pairing_scan") {
    scanPairingPorts(message.start_port || 16780, message.end_port || 16800).then(done).catch(fail);
    return true;
  }

  if (message.type === "pairing_claim") {
    callPairingClaim(message.port || DEFAULTS.port, message.extension_id || chrome.runtime.id || "").then(done).catch(fail);
    return true;
  }

  if (message.type === "runtime_config_get") {
    callConfigGet().then(done).catch(fail);
    return true;
  }

  if (message.type === "runtime_config_patch") {
    callConfigPatch(message.payload || {}).then(done).catch(fail);
    return true;
  }

  if (message.type === "show_diagnostic_window") {
    callWindowShow().then(done).catch(fail);
    return true;
  }

  if (message.type === "send_to_harvest") {
    const tabId = resolveTabIdForSend(message, sender);
    sendSingle(message.url || "", tabId).then(done).catch(fail);
    return true;
  }

  if (message.type === "bulk_send_to_harvest") {
    // Support both items format [{url, save_selected}] and legacy urls format [string]
    const input = message.items || message.urls || [];
    sendBulk(input).then(done).catch(fail);
    return true;
  }

  // 鈹€鈹€ Dashboard message handlers 鈹€鈹€

  if (message.type === "harvest_list_tasks") {
    callListTasks().then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_batch_status") {
    callBatchStatus().then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_batch_start") {
    callBatchStart().then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_batch_stop") {
    callBatchStop().then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_batch_export") {
    callBatchExport(message.payload || {}).then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_delete_task") {
    callDeleteTask(message.seq).then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_retry_task") {
    callRetryTask(message.seq).then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_clear_tasks") {
    callClearTasks().then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_nlm_status") {
    callNlmStatus().then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_nlm_notebooks") {
    callNlmNotebooks().then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_nlm_create_notebook") {
    callNlmCreateNotebook(message.title || "Untitled").then(done).catch(fail);
    return true;
  }

  if (message.type === "harvest_nlm_push_status") {
    callNlmPushStatus(message.job_id || "").then(done).catch(fail);
    return true;
  }

  /* ── New Dashboard Protocol ── */

  if (message.type === "get_status") {
    // Merge batch status + task list into one flat response
    Promise.all([callBatchStatus(), callListTasks()])
      .then(([batchResp, tasksResp]) => {
        const batch = (batchResp.ok && batchResp.data) ? batchResp.data : {};
        const tasksList = (tasksResp.ok && tasksResp.data && tasksResp.data.tasks) ? tasksResp.data.tasks : [];
        done({
          ok: batchResp.ok,
          is_running: Boolean(batch.is_running),
          total_count: batch.total_count || 0,
          done_count: batch.done_count || 0,
          success_count: batch.success_count || 0,
          failed_count: batch.failed_count || 0,
          tasks: tasksList,
          progress: batch.total_count > 0 ? (batch.done_count / batch.total_count) : 0,
        });
      })
      .catch(fail);
    return true;
  }

  if (message.type === "start_batch") {
    callBatchStart().then(done).catch(fail);
    return true;
  }

  if (message.type === "stop_batch") {
    callBatchStop().then(done).catch(fail);
    return true;
  }

  if (message.type === "add_task") {
    const p = message.payload || {};
    const urls = Array.isArray(p.urls) ? p.urls : [];
    if (urls.length > 0) {
      if (shouldUseAddTaskSinglePrefetch(p)) {
        const tabId = resolveTabIdForSend({ tab_id: p.tab_id }, sender);
        sendSingle(String(urls[0] || "").trim(), tabId, {
          source_type: p.source_type,
          import_mode: p.import_mode,
          limit: p.limit,
          order: p.order,
          cookie_header: p.cookie_header,
          save_selected: p.save_selected,
        }).then(done).catch(fail);
        return true;
      }

      const items = urls.map(u => ({ url: u, save_selected: p.save_selected }));
      sendBulk(items, {
        source_type: p.source_type,
        options: {
          import_mode: p.import_mode,
          limit: p.limit,
          order: p.order,
          cookie_header: p.cookie_header
        },
        save_selected: p.save_selected
      }).then(done).catch(fail);
    } else {
      fail("No URLs provided");
    }
    return true;
  }

  if (message.type === "delete_task") {
    callDeleteTask(message.seq).then(done).catch(fail);
    return true;
  }

  if (message.type === "clear_tasks") {
    callClearTasks().then(done).catch(fail);
    return true;
  }

  if (message.type === "get_notebooks") {
    callNlmNotebooks()
      .then(resp => {
        if (!resp.ok) return done({ ok: false, error: resp.error || "failed" });
        const data = resp.data || {};
        const notebooks = data.notebooks || [];
        done({ ok: true, notebooks });
      })
      .catch(fail);
    return true;
  }

  if (message.type === "create_notebook") {
    callNlmCreateNotebook(message.name)
      .then(resp => {
        if (!resp.ok) return done({ ok: false, error: resp.error || "failed" });
        const data = resp.data || {};
        const notebook = data.notebook || {};
        done({ ok: true, notebook: { id: notebook.id || notebook.notebook_id || "", title: notebook.title || message.name } });
      })
      .catch(fail);
    return true;
  }

  if (message.type === "upload_to_notebooklm") {
    // callBatchExport with upload_to_notebooklm=true? 
    // Wait, the backend endpoint for pure "push" might be 'export' with options.
    // Let's check local_api_server.py
    // Actually typically we use "harvest_batch_export" with target
    // We need to implement callBatchExport properly
    callBatchExport({ 
        notebook_id: message.notebookId,
        upload_to_notebooklm: true
    }).then(done).catch(fail);
    return true;
  }

  if (message.type === "export_subtitles") {
    callBatchExport(message.formats || {}).then(done).catch(fail);
    return true;
  }

  if (message.type === "update_task_flag") {
    // New endpoint support
    callUpdateTaskFlag(message.seq, message.flag, message.value).then(done).catch(fail);
    return true;
  }

  return false;
});

// ── Helpers for new protocol ──

async function callUpdateTaskFlag(seq, flag, value) {
  const payload = { flag, value };
  if (String(flag || "").trim() === "save_selected") {
    payload.save_selected = Boolean(value);
  }
  return callApi(`/v1/tasks/${seq}/update_flag`, "POST", payload);
}


// 鈹€鈹€ Click extension icon 鈫?open side panel 鈹€鈹€

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
  .catch((e) => console.warn("setPanelBehavior failed:", e));
