/* ============================================================
   核心：命名空间 / 工具函数 / API / 主题 / 浮层 / 全局检索
   ============================================================ */
(function () {
  "use strict";

  const GIS = (window.GIS = window.GIS || {});
  GIS.state = {
    data: null,
    mode: "live",          // live | static
    theme: "light",
    route: "overview",
    lastRun: null,
    activeView: null,
  };
  GIS.views = {};
  GIS.apiBase = "";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  GIS.$ = $;
  GIS.$$ = $$;

  /* ---------------------------------------------------------- 文本与数值 */
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function attr(value) { return esc(value); }
  function nl2br(value) { return esc(value).replace(/\n/g, "<br>"); }
  function num(value, digits) {
    const n = Number(value);
    if (!isFinite(n)) return "—";
    const d = digits == null ? 2 : digits;
    return n.toFixed(d);
  }
  function pct(value, digits) {
    const n = Number(value);
    if (!isFinite(n)) return "—";
    return (n * 100).toFixed(digits == null ? 1 : digits) + "%";
  }
  function signed(value, digits) {
    const n = Number(value);
    if (!isFinite(n)) return "—";
    return (n >= 0 ? "+" : "") + n.toFixed(digits == null ? 3 : digits);
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function truncate(text, n) {
    const s = String(text == null ? "" : text);
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }
  function jsonText(value, indent) {
    try { return JSON.stringify(value, null, indent == null ? 2 : indent); }
    catch (e) { return String(value); }
  }
  function dateLabel(value) {
    if (!value) return "—";
    return String(value).replace(/^\d{4}-/, "").replace(/:00$/, "");
  }
  function timeAgo(value) {
    if (!value) return "—";
    const t = Date.parse(String(value).replace(" ", "T"));
    if (!isFinite(t)) return String(value);
    const diff = (Date.now() - t) / 1000;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
    if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
    return Math.floor(diff / 86400) + " 天前";
  }
  function debounce(fn, wait) {
    let timer = null;
    return function () {
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), wait || 220);
    };
  }
  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
  GIS.util = { esc, attr, nl2br, num, pct, signed, clamp, truncate, jsonText, dateLabel, timeAgo, debounce, sleep };

  /* ---------------------------------------------------------- 项目字段映射 */
  function data() { return GIS.state.data || {}; }
  GIS.meta = {
    agentColor(agentId) {
      const colors = (data().colors || {});
      if (colors[agentId]) return colors[agentId];
      const idx = Object.keys((data().capability || {}).agents || {}).sort().indexOf(agentId);
      const fallback = ["#2563eb", "#e11d48", "#059669", "#d97706", "#7c3aed", "#0891b2"];
      return fallback[(idx < 0 ? 0 : idx) % fallback.length];
    },
    agentName(agentId) {
      const agents = ((data().capability || {}).agents || {});
      return (agents[agentId] && agents[agentId].name) || String(agentId).replace("agent_", "");
    },
    agents() {
      const agents = ((data().capability || {}).agents || {});
      return Object.keys(agents).sort().map((id) => ({ id, ...agents[id] }));
    },
    dims() { return data().dimensions || []; },
    dimLabel(dim) { return (data().labels || {})[dim] || dim; },
    dimGlossary(dim) { return (data().glossary || {})[dim] || ""; },
    skill(id) { return (data().skills || []).find((s) => s.id === id) || null; },
    tool(name) { return (data().tools || []).find((t) => t.name === name) || null; },
    agentStats(agentId) {
      const agents = ((data().capability || {}).agents || {});
      return (agents[agentId] && agents[agentId].stats) || { attempts: 0, successes: 0, failures: 0 };
    },
  };

  /* ---------------------------------------------------------- API */
  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status || 0;
    }
  }
  GIS.ApiError = ApiError;

  async function request(path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json; charset=utf-8";
      opts.body = JSON.stringify(opts.body);
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), opts.timeout || 12000);
    try {
      const res = await fetch(GIS.apiBase + path, { ...opts, signal: controller.signal });
      const text = await res.text();
      let payload = null;
      try { payload = text ? JSON.parse(text) : null; } catch (e) { payload = { raw: text }; }
      if (!res.ok) {
        throw new ApiError((payload && (payload.error || payload.message)) || ("HTTP " + res.status), res.status);
      }
      return payload;
    } catch (err) {
      if (err.name === "AbortError") throw new ApiError("请求超时，请稍后重试", 0);
      throw err;
    } finally {
      clearTimeout(timeout);
    }
  }

  GIS.api = {
    get(path, options) { return request(path, Object.assign({ method: "GET" }, options || {})); },
    post(path, body, options) {
      return request(path, Object.assign({ method: "POST", body: body || {} }, options || {}));
    },
    del(path) { return request(path, { method: "DELETE" }); },
    async bootstrap(force) {
      if (GIS.state.data && !force) return GIS.state.data;
      try {
        const payload = await request("/api/bootstrap", { timeout: 15000 });
        GIS.state.data = payload;
        GIS.state.mode = "live";
        return payload;
      } catch (err) {
        if (window.__GIS_SNAPSHOT__) {
          GIS.state.data = window.__GIS_SNAPSHOT__;
          GIS.state.mode = "static";
          return GIS.state.data;
        }
        throw err;
      }
    },
    run(question, truth, verdict) {
      return request("/api/run", {
        method: "POST",
        body: { question, truth, verdict },
        timeout: 45000,
      });
    },
    capability(source) {
      return request("/api/capability?source=" + encodeURIComponent(source || "demo"), { timeout: 10000 });
    },
    resetCapability(seed, clearRuns) {
      return request("/api/capability/reset", {
        method: "POST",
        body: { confirm: true, seed: seed || "initial", clear_runs: !!clearRuns },
      });
    },
    retrieve(query, kind, agent) {
      return request("/api/retrieve", {
        method: "POST",
        body: { query, kind, agent },
        timeout: 15000,
      });
    },
    admin() { return request("/api/admin", { timeout: 15000 }); },
    resetRealCapability() {
      return request("/api/admin/capability/reset", {
        method: "POST",
        body: { confirm: true },
        timeout: 20000,
      });
    },
    updateTieEpsilon(value) {
      return request("/api/admin/routing", {
        method: "POST",
        body: { confirm: true, tie_epsilon: value },
        timeout: 15000,
      });
    },
    memoryAction(agentId, scope, mode) {
      return request("/api/admin/memory", {
        method: "POST",
        body: { confirm: true, agent_id: agentId, scope, mode },
        timeout: 20000,
      });
    },
    reports() { return request("/api/reports"); },
    report(name) { return request("/api/reports/" + encodeURIComponent(name), { timeout: 20000 }); },
    runs() { return request("/api/runs"); },
    runById(id) { return request("/api/runs/" + encodeURIComponent(id)); },
    clearRuns() { return request("/api/runs", { method: "DELETE" }); },
    memory() { return request("/api/memory"); },
  };

  /* ---------------------------------------------------------- 主题 / 导航 */
  function applyTheme(theme) {
    const next = theme === "dark" ? "dark" : "light";
    GIS.state.theme = next;
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("gis-theme", next); } catch (e) { /* ignore */ }
    window.dispatchEvent(new CustomEvent("gis:theme", { detail: next }));
  }
  GIS.ui = {
    applyTheme,
    toggleTheme() { applyTheme(GIS.state.theme === "dark" ? "light" : "dark"); },
  };

  /* ---------------------------------------------------------- Toast */
  function toast(message, kind, title) {
    const box = document.getElementById("toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = "toast " + (kind || "");
    const label = { ok: "完成", err: "错误", warn: "注意" }[kind] || "提示";
    el.innerHTML = "<div><strong>" + esc(title || label) + "</strong><div class='small'>" + esc(message) + "</div></div>";
    box.appendChild(el);
    setTimeout(() => {
      el.classList.add("out");
      setTimeout(() => el.remove(), 320);
    }, kind === "err" ? 5200 : 3400);
  }
  GIS.toast = toast;

  /* ---------------------------------------------------------- Confirm */
  let confirmResolver = null;
  function confirmDialog(title, text, okLabel) {
    const modal = document.getElementById("confirm");
    document.getElementById("confirmTitle").textContent = title || "确认操作";
    document.getElementById("confirmText").textContent = text || "";
    const ok = document.getElementById("confirmOk");
    ok.textContent = okLabel || "确认";
    modal.hidden = false;
    return new Promise((resolve) => { confirmResolver = resolve; });
  }
  function closeConfirm(result) {
    const modal = document.getElementById("confirm");
    modal.hidden = true;
    if (confirmResolver) { confirmResolver(result); confirmResolver = null; }
  }
  GIS.confirm = confirmDialog;
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-close='confirm']")) closeConfirm(false);
    if (e.target.closest("#confirmOk")) closeConfirm(true);
    if (e.target.closest("#confirmCancel")) closeConfirm(false);
    if (e.target.closest("[data-close='capreset']")) closeCapReset();
    if (e.target.closest("[data-close='drawer']")) GIS.ui.closeDrawer();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!document.getElementById("confirm").hidden) closeConfirm(false);
      else if (!document.getElementById("capResetModal").hidden) closeCapReset();
      else GIS.ui.closeDrawer();
    }
  });

  /* ---------------------------------------------------------- Drawer */
  GIS.ui.openDrawer = function (title, html) {
    const drawer = document.getElementById("drawer");
    document.getElementById("drawerTitle").textContent = title || "详情";
    document.getElementById("drawerBody").innerHTML = html || "";
    drawer.hidden = false;
    document.body.style.overflow = "hidden";
  };
  GIS.ui.closeDrawer = function () {
    const drawer = document.getElementById("drawer");
    if (!drawer || drawer.hidden) return;
    drawer.hidden = true;
    document.body.style.overflow = "";
    document.getElementById("drawerBody").innerHTML = "";
  };

  /* ---------------------------------------------------------- 复制 / 下载 */
  GIS.ui.copy = async function (text, message) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      toast(message || "已复制到剪贴板", "ok");
    } catch (e) {
      toast("复制失败，请手动选择文本", "err");
    }
  };
  GIS.ui.download = function (filename, content, type) {
    const blob = new Blob([content], { type: type || "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  /* ---------------------------------------------------------- 小工具 */
  GIS.ui.verdictInfo = function (stage) {
    const ev = String((stage && stage.evaluation) || "");
    if (ev === "unknown") return { key: "unknown", label: "未判定", short: "未判定", chip: "warn" };
    if (ev === "failed" || (stage && stage.correct === false)) {
      return { key: "failed", label: "判定失败", short: "失败", chip: "err" };
    }
    if (ev === "success" || (stage && stage.correct === true)) {
      return { key: "success", label: "判定正确", short: "成功", chip: "ok" };
    }
    return { key: "unknown", label: "未判定", short: "未判定", chip: "warn" };
  };
  GIS.ui.verdictChip = function (stage, short) {
    const v = GIS.ui.verdictInfo(stage);
    return "<span class='chip " + v.chip + "'>" + (short ? v.short : v.label) + "</span>";
  };
  GIS.ui.icon = function (name, cls) {
    return "<svg class='" + (cls || "") + "' aria-hidden='true'><use href='#i-" + name + "'></use></svg>";
  };
  GIS.ui.deltaClass = (v) => (Number(v) > 0 ? "up" : (Number(v) < 0 ? "down" : ""));
  GIS.ui.scoreBar = function (score, max) {
    const p = clamp(Number(score) / (max || 1), 0, 1) * 100;
    return "<span class='score-bar'><i style='width:" + p.toFixed(1) + "%'></i></span>";
  };
  GIS.ui.agentAvatar = function (agentId, size) {
    const name = GIS.meta.agentName(agentId);
    const color = GIS.meta.agentColor(agentId);
    const s = size || 32;
    return "<span class='agent-avatar' style='width:" + s + "px;height:" + s + "px;background:" + color + ";font-size:" + Math.round(s * 0.38) + "px'>" + esc(name) + "</span>";
  };
  GIS.ui.empty = function (title, hint, icon) {
    return "<div class='empty'>" + GIS.ui.icon(icon || "search") +
      "<strong>" + esc(title || "暂无数据") + "</strong><span>" + esc(hint || "") + "</span></div>";
  };
  GIS.ui.skeleton = function (height, width) {
    return "<div class='skeleton' style='height:" + (height || 16) + "px;width:" + (width || "100%") + "'></div>";
  };
  GIS.ui.chip = function (text, cls, title) {
    return "<span class='chip " + (cls || "") + "'" + (title ? " title='" + attr(title) + "'" : "") + ">" + esc(text) + "</span>";
  };
  GIS.ui.codeBlock = function (text, light, maxHeight) {
    return "<pre class='code-block " + (light ? "light" : "") + "'" +
      (maxHeight ? " style='max-height:" + maxHeight + "px'" : "") + ">" + esc(text) + "</pre>";
  };

  /* ---------------------------------------------------------- 全局检索 */
  GIS.ui.globalSearch = function (query) {
    const q = String(query || "").trim();
    if (!q) return;
    const d = data();
    const hay = (s) => String(s || "").toLowerCase().includes(q.toLowerCase());
    const skills = (d.skills || []).filter((s) => hay(s.name) || hay(s.desc) || hay(s.steps) || (s.operators || []).some(hay));
    const tables = ((d.schema || {}).tables || []).filter((t) => hay(t.name) || hay(t.note) || (t.fields || []).some((f) => hay(f.name) || hay(f.note)));
    const mem = [];
    Object.keys(d.memory || {}).forEach((aid) => {
      ((d.memory[aid] || {}).records || []).forEach((r) => { if (hay(r.question_feat)) mem.push({ agent: aid, record: r }); });
    });
    const blocks = [];
    if (skills.length) {
      blocks.push("<div class='card-head'><h3>技能库 · " + skills.length + " 条</h3></div><div class='stack'>" +
        skills.slice(0, 6).map((s) =>
          "<div class='hit'><div class='hit-main'><div class='hit-title'>" + esc(s.name) +
          "</div><div class='hit-sub'>" + esc(s.desc) + "</div></div>" +
          "<button class='btn sm ghost' data-go='skills'>查看</button></div>").join("") + "</div>");
    }
    if (tables.length) {
      blocks.push("<div class='hr-soft'></div><div class='card-head'><h3>知识库 · " + tables.length + " 张表</h3></div><div class='stack'>" +
        tables.slice(0, 6).map((t) =>
          "<div class='hit'><div class='hit-main'><div class='hit-title mono'>" + esc(t.name) +
          "</div><div class='hit-sub'>" + esc(t.note) + "</div></div>" +
          "<button class='btn sm ghost' data-go='knowledge'>查看</button></div>").join("") + "</div>");
    }
    if (mem.length) {
      blocks.push("<div class='hr-soft'></div><div class='card-head'><h3>记忆库 · " + mem.length + " 条记录</h3></div><div class='stack'>" +
        mem.slice(0, 6).map((m) =>
          "<div class='hit'><div class='hit-main'><div class='hit-title'>智能体 " + esc(GIS.meta.agentName(m.agent)) +
          "</div><div class='hit-sub'>" + esc(m.record.question_feat) + "</div></div></div>").join("") + "</div>");
    }
    GIS.ui.openDrawer("检索“" + q + "”", blocks.length ? blocks.join("") : GIS.ui.empty("未检索到匹配内容", "试试技能名称、表名或记忆中的关键词。"));
    document.querySelectorAll("[data-go]").forEach((btn) => {
      btn.addEventListener("click", () => {
        GIS.ui.closeDrawer();
        location.hash = "#/" + btn.dataset.go;
      });
    });
  };

  /* ---------------------------------------------------------- 重置所有智能体 */
  let capResetBound = false;
  let capResetBusy = false;

  function closeCapReset() {
    const modal = document.getElementById("capResetModal");
    if (modal) modal.hidden = true;
  }

  function bindCapReset() {
    if (capResetBound) return;
    capResetBound = true;
    const ok = document.getElementById("capResetOk");
    const cancel = document.getElementById("capResetCancel");
    if (cancel) cancel.addEventListener("click", closeCapReset);
    if (ok) ok.addEventListener("click", async () => {
      if (capResetBusy) return;
      capResetBusy = true;
      const old = ok.innerHTML;
      ok.disabled = true;
      ok.textContent = "重置中…";
      const clearRuns = !!(document.getElementById("capResetRuns") || {}).checked;
      try {
        const payload = await GIS.api.resetCapability("initial", clearRuns);
        if (payload && payload.capability) {
          GIS.state.data.capability = payload.capability;
          GIS.state.data.counts = GIS.state.data.counts || {};
          GIS.state.data.counts.evolution_events = 0;
          if (clearRuns) {
            GIS.state.data.runs = [];
            GIS.state.data.counts.runs = 0;
          }
          if (GIS.views.capability && typeof GIS.views.capability.forceSource === "function") {
            GIS.views.capability.forceSource("demo");
          }
        }
        closeCapReset();
        toast("已将 " + (payload.agent_count || Object.keys((GIS.state.data.capability || {}).agents || {}).length) +
          " 个智能体的能力向量重置为 " + Number(payload.initial_capability || 0.5).toFixed(3), "ok", "重置完成");
        if (window.GIS.refreshNav) window.GIS.refreshNav();
        if (window.GIS.refreshView) window.GIS.refreshView();
      } catch (err) {
        toast(err.message || "重置失败", "err", "重置失败");
      } finally {
        capResetBusy = false;
        ok.disabled = false;
        ok.innerHTML = old;
      }
    });
  }

  GIS.ui.openCapabilityReset = function () {
    if (GIS.state.mode === "static") {
      toast("静态预览模式无法重置能力向量，请先启动本地服务", "warn");
      return;
    }
    const cap = (GIS.state.data && GIS.state.data.capability) || {};
    const agents = cap.agents || {};
    const dims = cap.dimensions || (GIS.state.data || {}).dimensions || [];
    const labels = (GIS.state.data || {}).labels || {};
    const target = Number(cap.initial_capability != null ? cap.initial_capability : 0.5);
    const ids = Object.keys(agents).sort();
    bindCapReset();

    const head = "<tr><th>智能体</th>" + dims.map((d) =>
      "<th title='" + attr((GIS.state.data.glossary || {})[d] || "") + "'>" + esc(labels[d] || d) + "</th>").join("") + "</tr>";
    const rows = ids.map((id) => {
      const caps = agents[id].capabilities || {};
      return "<tr><td><div class='agent-cell'><span class='dot' style='background:" +
        GIS.meta.agentColor(id) + "'></span>智能体 " + esc((agents[id] || {}).name || id) + "</div></td>" +
        dims.map((d) => {
          const v = Number(caps[d] || 0);
          const hot = v > target + 1e-9;
          return "<td class='v " + (hot ? "hot" : "") + "' title='" + (hot ? "高于初始值 " + (v - target).toFixed(4) : "已处于初始值") + "'>" +
            v.toFixed(4) + "</td>";
        }).join("") + "</tr>";
    }).join("");

    const preview = document.getElementById("capResetPreview");
    if (preview) {
      preview.innerHTML = "<div class='tiny muted' style='padding:7px 10px 5px;border-bottom:1px solid var(--line)'>当前能力向量（红色为高于初始值的维度）</div>" +
        "<table class='reset-table'><thead>" + head + "</thead><tbody>" + rows + "</tbody></table>";
    }
    const targetEl = document.getElementById("capResetTarget");
    if (targetEl) targetEl.textContent = target.toFixed(3);
    const runCount = (GIS.state.data.counts || {}).runs != null
      ? GIS.state.data.counts.runs : (GIS.state.data.runs || []).length;
    const runCountEl = document.getElementById("capResetRunCount");
    if (runCountEl) runCountEl.textContent = runCount;
    const runsBox = document.getElementById("capResetRuns");
    if (runsBox) { runsBox.checked = false; runsBox.disabled = !runCount; }
    const modal = document.getElementById("capResetModal");
    if (modal) modal.hidden = false;
  };

  /* ---------------------------------------------------------- 主题初始化 */
  try {
    const saved = localStorage.getItem("gis-theme");
    GIS.state.theme = saved === "dark" ? "dark" : "light";
  } catch (e) { /* ignore */ }
  document.documentElement.setAttribute("data-theme", GIS.state.theme);
})();
