/* ============================================================
   应用入口：引导 / 路由 / 导航 / 主题 / 全局交互
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;
  const KNOWN = ["overview", "workbench", "history", "capability", "skills", "knowledge", "memory", "benchmark", "admin"];

  function parseHash() {
    const raw = (location.hash || "").replace(/^#\/?/, "");
    const [name, qs] = raw.split("?");
    const query = {};
    new URLSearchParams(qs || "").forEach((v, k) => { query[k] = v; });
    return { name: KNOWN.indexOf(name) >= 0 ? name : "overview", query };
  }

  function setNav(route) {
    document.querySelectorAll(".nav-item").forEach((a) => {
      a.classList.toggle("active", a.dataset.route === route);
    });
  }

  function refreshNav() {
    const d = GIS.state.data;
    if (!d) return;
    const runs = (d.runs || []).length;
    const runCount = d.counts && d.counts.runs != null ? d.counts.runs : runs;
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set("navRunCount", runCount);
    set("navSkillCount", (d.counts || {}).skills || (d.skills || []).length);
    set("navMemoryCount", (d.memory ? Object.keys(d.memory).reduce((s, k) => s + (((d.memory[k] || {}).records) || []).length, 0) : 0));
    const updated = (d.capability || {}).updated_at || d.generated_at || "";
    set("sideUpdated", updated ? U.dateLabel(updated) : "—");
    const chip = document.getElementById("serverChip");
    const mode = document.getElementById("serverMode");
    if (mode) mode.textContent = GIS.state.mode === "live" ? "本地服务已连接" : "静态快照预览";
    if (chip) {
      const dot = chip.querySelector(".status-dot");
      if (dot) { dot.classList.toggle("warn", GIS.state.mode !== "live"); }
    }
    const health = d.health || {};
    const db = (health.database || {}).reachable;
    const llm = !!((health.llm || {}).key_present);
    const footer = document.getElementById("footerHealth");
    if (footer) {
      footer.textContent = "数据库端口 " + (db ? "可达" : "未检测") + " · LLM " + (llm ? "已配置" : "未配置") + " · 演示引擎";
    }
  }
  GIS.refreshNav = refreshNav;

  function applyMeta(view) {
    const title = document.getElementById("pageTitle");
    const sub = document.getElementById("pageSub");
    if (title) title.textContent = view.title || "总览";
    if (sub) sub.textContent = view.subtitle || "";
    document.title = (view.title || "总览") + " · GIS 多智能体控制台";
  }

  function errorHTML(message) {
    return "<div class='card'><div class='card-head'><span class='card-title-icon' style='background:var(--err-soft);color:var(--err)'>" +
      GIS.ui.icon("close") + "</span><div><h2>页面加载失败</h2><p class='sub'>" + esc(message) + "</p></div></div>" +
      "<div class='row'><button class='btn primary' id='retryView'>重新加载</button>" +
      "<a class='btn ghost' href='#/overview'>回到总览</a></div></div>";
  }

  let rendering = false;
  let pending = false;

  async function renderRoute(force) {
    if (rendering) { pending = true; return; }
    rendering = true;
    const { name, query } = parseHash();
    if (query.theme === "dark" || query.theme === "light") {
      if (GIS.state.theme !== query.theme) { GIS.ui.applyTheme(query.theme); }
    }
    GIS.state.route = name;
    GIS.state.query = query;
    setNav(name);
    const view = GIS.views[name] || GIS.views.overview;
    applyMeta(view);
    const container = document.getElementById("view");
    if (GIS.state.activeView && typeof GIS.state.activeView.unmount === "function") {
      try { GIS.state.activeView.unmount(); } catch (e) { /* ignore */ }
    }
    GIS.state.activeView = view;
    try {
      if (view.before) await view.before();
      const html = await view.render();
      if (container) {
        container.innerHTML = html;
        container.classList.remove("view-in");
        void container.offsetWidth;
        container.classList.add("view-in");
      }
      if (view.mount) await view.mount();
      if (name === "capability" && query.agent) {
        const btn = document.querySelector("[data-highlight='" + query.agent + "']");
        if (btn) btn.click();
      }
      refreshNav();
    } catch (err) {
      if (container) {
        container.innerHTML = errorHTML(err.message || "未知错误");
        const retry = document.getElementById("retryView");
        if (retry) retry.addEventListener("click", () => renderRoute(true));
      }
    } finally {
      rendering = false;
      if (pending) { pending = false; renderRoute(true); }
    }
  }
  GIS.renderRoute = renderRoute;
  GIS.refreshView = () => renderRoute(true);

  function hideBoot() {
    const boot = document.getElementById("boot");
    const app = document.getElementById("app");
    if (app) app.hidden = false;
    if (boot) {
      boot.classList.add("done");
      setTimeout(() => boot.remove(), 600);
    }
  }

  function bootError(err) {
    const boot = document.getElementById("boot");
    if (boot) {
      boot.innerHTML = "<div class='boot-title'>无法加载数据</div>" +
        "<div class='boot-sub' style='max-width:460px;text-align:center;line-height:1.8'>" + esc(err.message || err) +
        "<br><br>请通过 <code>python web/server/app.py --open</code> 启动本地服务。" +
        "<br>若仅需浏览，可先生成快照：<code>python web/server/data_source.py</code></div>" +
        "<button class='btn primary' style='margin-top:12px' onclick='location.reload()'>重新加载</button>";
    }
  }

  async function init() {
    try {
      await GIS.api.bootstrap();
    } catch (err) {
      bootError(err);
      return;
    }
    hideBoot();
    if (GIS.state.mode === "static") {
      const banner = document.getElementById("staticBanner");
      if (banner) banner.hidden = false;
    }
    refreshNav();
    await renderRoute(true);
  }

  /* ---------------------------------------------------------- 全局事件 */
  function bindShell() {
    window.addEventListener("hashchange", () => {
      document.body.classList.remove("nav-open");
      renderRoute();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });

    const themeBtn = document.getElementById("themeBtn");
    if (themeBtn) themeBtn.addEventListener("click", () => GIS.ui.toggleTheme());
    window.addEventListener("gis:theme", () => { renderRoute(true); });

    const refreshBtn = document.getElementById("refreshBtn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => {
        GIS.toast("正在重新加载数据…", "ok", "刷新");
        setTimeout(() => location.reload(), 120);
      });
    }

    const menu = document.getElementById("menuBtn");
    if (menu) {
      menu.addEventListener("click", () => document.body.classList.toggle("nav-open"));
    }
    document.addEventListener("click", (e) => {
      if (!document.body.classList.contains("nav-open")) return;
      if (e.target.closest("#sidebar") || e.target.closest("#menuBtn")) return;
      document.body.classList.remove("nav-open");
    });

    const search = document.getElementById("globalSearch");
    if (search) {
      search.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          GIS.ui.globalSearch(search.value);
          search.value = "";
        }
      });
      search.addEventListener("focus", () => { search.select(); });
    }
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        const input = document.getElementById("globalSearch");
        if (input) { input.focus(); input.select(); }
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindShell();
    init();
  });
})();
