/* 服务状态监控 Page 逻辑：通过 window.AstrBotPluginPage bridge 与插件后端通信。 */

const bridge = window.AstrBotPluginPage;

const state = {
  status: null, // /status 响应
  services: null, // /services 响应
  autoRefresh: true,
  timer: null,
  refreshing: false,
};

const $ = (sel) => document.querySelector(sel);

// 远端 API 返回的描述文本不可信任，插入 innerHTML 前必须转义
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);

const t = (key, fallback) => {
  try {
    return bridge.t(`pages.dashboard.${key}`, fallback);
  } catch {
    return fallback;
  }
};

const TYPE_LABELS = {
  statuspage: "StatusPage",
  aliyun: "Aliyun",
  probe: "HTTP",
  rss: "RSS",
  steamstat: "Steam",
};

// indicator → 卡片样式类 + 图标
const INDICATOR_META = {
  none: { cls: "ok", emoji: "✅" },
  operational: { cls: "ok", emoji: "✅" },
  rss_new: { cls: "ok", emoji: "📝" },
  minor: { cls: "warn", emoji: "⚠️" },
  major: { cls: "err", emoji: "❌" },
  critical: { cls: "crit", emoji: "🚨" },
  maintenance: { cls: "warn", emoji: "🔧" },
};

function indicatorMeta(indicator) {
  return INDICATOR_META[indicator] || { cls: "", emoji: "📊" };
}

/* ---------- i18n ---------- */

function applyStaticI18n() {
  document.title = t("title", "服务状态监控");
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n, el.textContent);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder, el.placeholder);
  });
}

/* ---------- 概览 ---------- */

function summaryHTML(summary) {
  const stats = [
    { key: "statTotal", value: summary.total, cls: "" },
    { key: "statOk", value: summary.ok, cls: "ok" },
    { key: "statProblem", value: summary.problem, cls: "problem" },
    { key: "statError", value: summary.error, cls: "error" },
  ];
  return stats
    .map(
      (s) => `
      <div class="stat ${s.cls}">
        <span class="num">${s.value}</span>
        <span class="lbl">${esc(t(s.key, s.key))}</span>
      </div>`
    )
    .join("");
}

function cardMetaHTML(item) {
  const parts = [];
  if (item.uptime_7d != null) {
    parts.push(`${t("uptime7", "7天可用率")} ${item.uptime_7d}%`);
  }
  if (item.type === "statuspage") {
    parts.push(`${t("incidents", "活跃事件")}: ${item.incidents ?? 0}`);
    if (item.maintenances) parts.push(`${t("maintenances", "计划维护")}: ${item.maintenances}`);
  } else if (item.type === "probe") {
    if (item.http_status != null) {
      parts.push(`HTTP ${item.http_status}`);
      if (item.latency_ms != null) parts.push(`${item.latency_ms}ms`);
    } else if (item.error) {
      parts.push(esc(item.error));
    }
  } else if (item.type === "aliyun") {
    parts.push(`${t("activeEvents", "活跃事件")}: ${item.events ?? 0}`);
  }
  let html = parts.map(esc).join(" · ");
  const link = item.page_url || item.link;
  if (link) {
    const label = item.page_url ? t("monitorPage", "监控页") : t("openLink", "链接");
    html += ` · <a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
  }
  return html;
}

function cardHTML(item) {
  const typeLabel = TYPE_LABELS[item.type] || item.type;
  if (item.status !== "ok") {
    return `
      <div class="card crit" data-key="${esc(item.key)}">
        <div class="card-head">
          <span class="card-name" title="${esc(item.name)}">${esc(item.name)}</span>
          <span class="badge">${esc(typeLabel)}</span>
        </div>
        <div class="card-status">
          <span class="dot"></span>
          <span class="card-desc">${esc(t("fetchFailed", "获取失败"))}</span>
        </div>
        <div class="card-error-text">${esc(item.error || "-")}</div>
      </div>`;
  }

  const meta = indicatorMeta(item.indicator);
  return `
    <div class="card ${meta.cls}" data-key="${esc(item.key)}">
      <div class="card-head">
        <span class="card-name" title="${esc(item.name)}">${esc(item.name)}</span>
        <span class="badge">${esc(typeLabel)}</span>
      </div>
      <div class="card-status">
        <span class="dot"></span>
        <span class="card-desc">${meta.emoji} ${esc(item.description)}</span>
      </div>
      <div class="card-meta">${cardMetaHTML(item)}</div>
    </div>`;
}

function renderStatus() {
  const data = state.status;
  const grid = $("#status-grid");
  const summary = $("#summary");
  if (!data) return;

  summary.innerHTML = summaryHTML(data.summary || { total: 0, ok: 0, problem: 0, error: 0 });

  if (!data.services || data.services.length === 0) {
    grid.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📡</div>
        <p>${esc(t("emptyTitle", "暂无已启用的服务"))}</p>
        <p>${esc(t("emptyHintPrefix", "请前往"))}
          <a id="goto-manage">${esc(t("tabManage", "服务管理"))}</a>
          ${esc(t("emptyHintSuffix", "开启需要监控的服务"))}
        </p>
      </div>`;
    const goto = $("#goto-manage");
    if (goto) goto.addEventListener("click", () => switchTab("manage"));
    return;
  }

  grid.innerHTML = data.services.map(cardHTML).join("");

  if (data.checked_at) {
    $("#last-check").textContent = `${t("lastCheck", "最后检查")} ${fmtTime(new Date(data.checked_at * 1000))}`;
  }
}

/* ---------- 详情弹窗 ---------- */

const locale = () => {
  try {
    return (bridge.getLocale?.() || "zh-CN").toLowerCase();
  } catch {
    return "zh-CN";
  }
};
const isZh = () => locale().startsWith("zh");

const STATUS_ZH = {
  investigating: "调查中",
  identified: "已定位",
  monitoring: "监控中",
  resolved: "已解决",
  postmortem: "复盘中",
  scheduled: "已排期",
  in_progress: "进行中",
  verifying: "验证中",
  completed: "已完成",
};

const IMPACT_ZH = {
  none: "正常",
  minor: "轻微",
  major: "严重",
  critical: "致命",
  maintenance: "维护",
};

function statusLabel(value) {
  if (!value) return "-";
  if (!isZh()) return String(value);
  return STATUS_ZH[String(value).toLowerCase()] || String(value);
}

function impactLabel(value) {
  if (!value) return "-";
  if (!isZh()) return String(value);
  return IMPACT_ZH[String(value).toLowerCase()] || String(value);
}

function pillClass(value) {
  const v = String(value || "").toLowerCase();
  if (["resolved", "completed", "operational", "none"].includes(v)) return "good";
  if (["critical", "major"].includes(v)) return "bad";
  if (["minor", "investigating", "scheduled", "in_progress", "verifying", "maintenance"].includes(v)) return "warn";
  return "";
}

function tzLabel(d) {
  const totalMinutes = -d.getTimezoneOffset();
  const sign = totalMinutes >= 0 ? "+" : "-";
  const abs = Math.abs(totalMinutes);
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  return `UTC${sign}${h}${m ? ":" + String(m).padStart(2, "0") : ""}`;
}

function fmtTime(value) {
  if (!value) return "-";
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())} (${tzLabel(d)})`;
}

const stripTags = (s) => String(s ?? "").replace(/<[^>]+>/g, " ");

function linkHTML(url, label) {
  if (!url) return "";
  return `<a class="incident-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label || t("openLink", "链接"))}</a>`;
}

function timelineHTML(updates) {
  if (!updates || !updates.length) return "";
  const items = updates.map((u) => `
    <div class="tl-item">
      <div class="tl-dot"></div>
      <div class="tl-content">
        <div class="tl-head">
          <span class="pill ${pillClass(u.status)}">${esc(statusLabel(u.status))}</span>
          <span class="tl-time">${esc(fmtTime(u.created_at))}</span>
        </div>
        ${u.body ? `<div class="tl-body">${esc(stripTags(u.body))}</div>` : ""}
      </div>
    </div>`).join("");
  // 默认折叠，点击展开
  return `
    <details class="tl-collapse">
      <summary>
        <span class="tl-chevron">▸</span>
        <span>${esc(t("timelineToggle", "更新时间线"))} (${updates.length})</span>
      </summary>
      <div class="timeline">${items}</div>
    </details>`;
}

function incidentHTML(i) {
  const updates = i.updates || [];
  return `
    <div class="incident">
      <div class="incident-head">
        <span class="incident-title">${esc(i.title)}</span>
        <span class="pill ${pillClass(i.impact)}">${esc(impactLabel(i.impact))}</span>
        <span class="pill ${pillClass(i.status)}">${esc(statusLabel(i.status))}</span>
      </div>
      <div class="incident-meta">${esc(t("startedAt", "开始"))}: ${esc(fmtTime(i.created_at))} · ${esc(t("lastUpdate", "最新更新"))}: ${esc(fmtTime(i.updated_at))}</div>
      ${timelineHTML(updates)}
      ${!updates.length && i.summary ? `<div class="incident-summary">${esc(stripTags(i.summary))}</div>` : ""}
      ${linkHTML(i.link)}
    </div>`;
}

function maintenanceHTML(m) {
  const updates = m.updates || [];
  return `
    <div class="incident">
      <div class="incident-head">
        <span class="incident-title">${esc(m.title)}</span>
        <span class="pill ${pillClass(m.status)}">${esc(statusLabel(m.status))}</span>
      </div>
      <div class="incident-meta">${esc(t("scheduledFor", "计划时间"))}: ${esc(fmtTime(m.scheduled_for))}</div>
      ${timelineHTML(updates)}
      ${linkHTML(m.link)}
    </div>`;
}

function eventHTML(e) {
  return `
    <div class="incident">
      <div class="incident-head">
        <span class="incident-title">${esc(e.title)}</span>
        <span class="pill ${pillClass(e.severity)}">${esc(e.severity)}</span>
        <span class="pill">${esc(e.status)}</span>
      </div>
      <div class="incident-meta">${esc(t("startedAt", "开始"))} ${esc(fmtTime(e.started_at))} · ${esc(t("lastUpdate", "最新更新"))} ${esc(fmtTime(e.updated_at))}</div>
      ${linkHTML(e.link)}
    </div>`;
}

function truncationNote(count, items) {
  return count > items.length
    ? `<p class="hint">${esc(t("truncated", "仅显示前 20 项"))}</p>`
    : "";
}

function uptimeSectionHTML(item) {
  if (item.uptime_7d == null && item.uptime_30d == null) return "";
  return `<div class="modal-section"><div class="kv">
    <span class="k">${esc(t("uptime7", "7 天可用率"))}</span><span>${item.uptime_7d != null ? esc(String(item.uptime_7d)) + "%" : "-"}</span>
    <span class="k">${esc(t("uptime30", "30 天可用率"))}</span><span>${item.uptime_30d != null ? esc(String(item.uptime_30d)) + "%" : "-"}</span>
  </div></div>`;
}

function renderDetailBody(item) {
  if (item.status !== "ok") {
    return `<p class="modal-empty">${esc(t("fetchFailed", "获取失败"))}: ${esc(item.error || "-")}</p>`;
  }

  if (item.type === "statuspage") {
    const incidents = item.incident_items || [];
    const maintenances = item.maintenance_items || [];
    let html = uptimeSectionHTML(item) + `<div class="modal-section">
      <h3>${esc(t("incidents", "活跃事件"))} (${item.incidents ?? incidents.length})</h3>
      ${incidents.length ? incidents.map(incidentHTML).join("") : `<p class="modal-empty">${esc(t("noIncidents", "无活跃事件"))}</p>`}
      ${truncationNote(item.incidents ?? 0, incidents)}
    </div>`;
    html += `<div class="modal-section">
      <h3>${esc(t("maintenances", "计划维护"))} (${item.maintenances ?? maintenances.length})</h3>
      ${maintenances.length ? maintenances.map(maintenanceHTML).join("") : `<p class="modal-empty">${esc(t("noMaintenances", "无计划维护"))}</p>`}
      ${truncationNote(item.maintenances ?? 0, maintenances)}
    </div>`;
    if (item.page_url) {
      html += `<div class="modal-section">${linkHTML(item.page_url, t("monitorPage", "监控页"))}</div>`;
    }
    return html;
  }

  if (item.type === "probe") {
    return uptimeSectionHTML(item) + `<div class="modal-section"><div class="kv">
      <span class="k">${esc(t("target", "探测目标"))}</span><span>${esc(item.target || "-")}</span>
      <span class="k">${esc(t("httpStatus", "HTTP 状态码"))}</span><span>${item.http_status != null ? esc(String(item.http_status)) : "-"}</span>
      <span class="k">${esc(t("latencyLabel", "延迟"))}</span><span>${item.latency_ms != null ? esc(String(item.latency_ms)) + "ms" : "-"}</span>
      ${item.error ? `<span class="k">${esc(t("errorLabel", "错误"))}</span><span>${esc(item.error)}</span>` : ""}
    </div></div>`;
  }

  if (item.type === "aliyun") {
    const events = item.event_items || [];
    return uptimeSectionHTML(item) + `<div class="modal-section">
      <h3>${esc(t("activeEvents", "活跃事件"))} (${item.events ?? events.length})</h3>
      ${events.length ? events.map(eventHTML).join("") : `<p class="modal-empty">${esc(t("noIncidents", "无活跃事件"))}</p>`}
    </div>`;
  }

  if (item.type === "rss") {
    const entry = item.entry || {};
    return uptimeSectionHTML(item) + `<div class="modal-section"><div class="kv">
      <span class="k">${esc(t("rssLatest", "最新动态"))}</span><span>${esc(entry.title || "-")}</span>
      <span class="k">${esc(t("publishedAt", "发布时间"))}</span><span>${esc(fmtTime(entry.published))}</span>
      <span class="k">${esc(t("author", "作者"))}</span><span>${esc(entry.author || "-")}</span>
    </div>
    ${entry.summary ? `<div class="incident-summary">${esc(stripTags(entry.summary))}</div>` : ""}
    ${linkHTML(item.link)}
    </div>`;
  }

  return `<p class="modal-empty">${esc(item.description || "-")}</p>`;
}

let currentDetailKey = null;

function openDetail(key) {
  const item = state.status?.services?.find((s) => s.key === key);
  if (!item) return;
  currentDetailKey = key;
  const meta = indicatorMeta(item.indicator);
  $("#detail-title").textContent = `${meta.emoji} ${item.name}`;
  $("#detail-type").textContent = TYPE_LABELS[item.type] || item.type;
  $("#detail-body").innerHTML = renderDetailBody(item);
  $("#detail-modal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeDetail() {
  currentDetailKey = null;
  $("#detail-modal").hidden = true;
  document.body.style.overflow = "";
}

/* ---------- 服务管理 ---------- */

// 运行时配置只有分组 id，组名优先从 i18n 取（如 group_china_services）
function groupLabel(group) {
  return t(`group_${group.id}`, group.description || group.id);
}

function renderServices() {
  const data = state.services;
  if (!data) return;

  const container = $("#manage-groups");
  const byKey = new Map(data.services.map((s) => [s.key, s]));
  const grouped = new Set();

  const groupHTML = (title, keys) => {
    const rows = keys
      .map((key) => byKey.get(key))
      .filter(Boolean)
      .map((s) => {
        grouped.add(s.key);
        return `
          <label class="service-row ${s.enabled ? "" : "off"}">
            <input type="checkbox" data-key="${esc(s.key)}" ${s.enabled ? "checked" : ""} />
            <span class="name" title="${esc(s.name)}">${esc(s.name)}</span>
            <span class="badge">${esc(TYPE_LABELS[s.type] || s.type)}</span>
          </label>`;
      })
      .join("");
    if (!rows) return "";
    return `
      <div class="manage-group">
        <div class="group-title">${esc(title)}</div>
        <div class="service-list">${rows}</div>
      </div>`;
  };

  let html = (data.groups || [])
    .map((g) => groupHTML(groupLabel(g), g.keys || []))
    .join("");

  const others = data.services.filter((s) => !grouped.has(s.key)).map((s) => s.key);
  html += groupHTML(t("groupOther", "其他"), others);

  container.innerHTML = html || `<p class="hint">${esc(t("noServices", "没有可用的服务定义"))}</p>`;

  container.querySelectorAll(".service-row input").forEach((input) => {
    input.addEventListener("change", () => {
      input.closest(".service-row").classList.toggle("off", !input.checked);
    });
  });
}

function fillSettings() {
  const data = state.services;
  if (!data) return;
  $("#input-interval").value = data.check_interval ?? 60;
  $("#input-targets").value = (data.notify_targets || []).join("\n");
}

/* ---------- 数据加载 ---------- */

async function refreshStatus({ silent = false } = {}) {
  if (state.refreshing) return;
  state.refreshing = true;
  const icon = $("#refresh-icon");
  if (!silent) icon.classList.add("spinning");
  try {
    state.status = await bridge.apiGet("status");
    renderStatus();
  } catch (e) {
    if (!silent) toast(`${t("loadFailed", "加载失败")}: ${e.message}`, "error");
  } finally {
    state.refreshing = false;
    icon.classList.remove("spinning");
  }
}

async function loadServices() {
  try {
    state.services = await bridge.apiGet("services");
    renderServices();
    fillSettings();
  } catch (e) {
    toast(`${t("loadFailed", "加载失败")}: ${e.message}`, "error");
  }
}

/* ---------- 操作 ---------- */

async function saveEnabledServices() {
  const enabled = {};
  $("#manage-groups").querySelectorAll(".service-row input").forEach((input) => {
    enabled[input.dataset.key] = input.checked;
  });
  const btn = $("#btn-save-services");
  btn.disabled = true;
  try {
    const res = await bridge.apiPost("config", { enabled });
    toast(`${t("saved", "已保存")} · ${t("enabledCount", "已启用")} ${res.enabled_count ?? 0}`,
      "success");
    await Promise.all([loadServices(), refreshStatus({ silent: true })]);
  } catch (e) {
    toast(`${t("saveFailed", "保存失败")}: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}

async function saveGeneralSettings() {
  const interval = parseInt($("#input-interval").value, 10);
  const targets = $("#input-targets")
    .value.split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (Number.isNaN(interval) || interval < 10) {
    toast(t("intervalInvalid", "检查间隔必须是不小于 10 的整数"), "error");
    return;
  }

  const btn = $("#btn-save-settings");
  btn.disabled = true;
  try {
    await bridge.apiPost("config", { check_interval: interval, notify_targets: targets });
    toast(t("saved", "已保存"), "success");
    scheduleTimer();
  } catch (e) {
    toast(`${t("saveFailed", "保存失败")}: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}

/* ---------- 定时刷新 ---------- */

function scheduleTimer() {
  if (state.timer) clearInterval(state.timer);
  if (!state.autoRefresh) return;
  // 跟随后端检查间隔轮询，前端最短 15 秒
  const seconds = Math.max(15, Number(state.status?.check_interval) || 60);
  state.timer = setInterval(() => {
    if (document.visibilityState === "visible") refreshStatus({ silent: true });
  }, seconds * 1000);
}

/* ---------- UI 杂项 ---------- */

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === name);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${name}`);
  });
}

let toastTimer = null;
function toast(message, kind = "") {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

function bindEvents() {
  $("#tabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".tab");
    if (tab) switchTab(tab.dataset.tab);
  });

  $("#btn-refresh").addEventListener("click", () => refreshStatus());

  $("#auto-refresh").addEventListener("change", (e) => {
    state.autoRefresh = e.target.checked;
    scheduleTimer();
  });

  // 卡片点击 → 详情弹窗（链接放行，由浏览器处理）
  $("#status-grid").addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const card = e.target.closest(".card[data-key]");
    if (card) openDetail(card.dataset.key);
  });

  // 详情弹窗关闭
  $("#detail-close").addEventListener("click", closeDetail);
  $("#detail-modal").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeDetail();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#detail-modal").hidden) closeDetail();
  });

  $("#btn-save-services").addEventListener("click", saveEnabledServices);
  $("#btn-save-settings").addEventListener("click", saveGeneralSettings);
}

function renderFromState() {
  renderStatus();
  renderServices();
  fillSettings();
}

/* ---------- 入口 ---------- */

async function init() {
  if (!bridge) {
    const grid = $("#status-grid");
    grid.innerHTML = `<div class="fatal">${esc("AstrBotPluginPage bridge 不可用，请通过 AstrBot WebUI 打开此页面。")}</div>`;
    return;
  }

  await bridge.ready();
  applyStaticI18n();
  bindEvents();

  await Promise.all([refreshStatus(), loadServices()]);
  scheduleTimer();

  // 语言/主题切换时重渲染（主题 data-theme 由 bridge SDK 自动维护）
  bridge.onContext(() => {
    applyStaticI18n();
    renderFromState();
  });
}

init().catch((e) => {
  const grid = $("#status-grid");
  if (grid) grid.innerHTML = `<div class="fatal">${esc(`${t("loadFailed", "加载失败")}: ${e.message}`)}</div>`;
});
