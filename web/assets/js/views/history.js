/* ============================================================
   执行流历史：演示运行列表与完整回放
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;

  const S = { runs: [], loaded: false, loading: false, current: null, currentId: null, search: "", detailError: "" };

  function slim(run) {
    const flow = run.flow || {};
    return {
      run_id: run.run_id,
      created_at: run.created_at,
      question: run.question,
      domain: run.domain,
      domain_label: run.domain_label,
      task_type: run.task_type,
      metrics: run.metrics,
      evaluation: (flow.evaluate || {}).evaluation,
      agent_names: (run.subtasks || []).map((s) => s.agent_name),
      verdict_mode: run.verdict_mode,
    };
  }

  async function loadRuns() {
    if (S.loading) return;
    S.loading = true;
    try {
      if (GIS.state.mode === "live") {
        const payload = await GIS.api.runs();
        S.runs = payload.runs || [];
      } else {
        S.runs = (GIS.state.data.runs || []).map(slim);
      }
      S.loaded = true;
    } catch (err) {
      GIS.toast(err.message || "加载运行记录失败", "err");
    } finally {
      S.loading = false;
    }
  }

  function listHTML() {
    const q = S.search.trim().toLowerCase();
    const list = q ? S.runs.filter((r) => ((r.question || "") + " " + (r.domain_label || "") + " " + (r.task_type || "")).toLowerCase().includes(q)) : S.runs;
    if (S.loading) return "<div class='skeleton' style='height:120px;margin-bottom:10px'></div><div class='skeleton' style='height:120px'></div>";
    if (!list.length) {
      return "<div class='card'>" + GIS.ui.empty(q ? "没有匹配的运行" : "还没有运行记录",
        q ? "试试其他关键词。" : "去任务台运行一次任务，完整执行流会保存在 web/data/demo_runs.json。", "flow") +
        "<div style='text-align:center'><a class='btn primary' href='#/workbench'>" + GIS.ui.icon("play") + "去任务台</a></div></div>";
    }
    return list.map((r) => {
      const v = GIS.ui.verdictInfo({ evaluation: r.evaluation });
      return "<article class='run-card' data-open-run='" + esc(r.run_id) + "'>" +
        "<div><div class='q'>" + esc(r.question) + "</div>" +
        "<div class='meta'>" +
        "<span class='chip mono'>" + esc(r.run_id) + "</span>" +
        "<span>" + esc(r.created_at || "") + "</span>" +
        "<span>" + esc(r.domain_label || r.domain || "") + " / " + esc(r.task_type || "") + "</span>" +
        "<span>" + ((r.metrics || {}).tool_calls || 0) + " 次工具</span>" +
        "<span>" + ((r.metrics || {}).elapsed_ms || 0) + " ms</span>" +
        "<span>智能体 " + esc((r.agent_names || []).join("、") || "—") + "</span>" +
        "</div></div>" +
        "<span class='chip " + v.chip + "'>" + v.short + "</span>" +
        "</article>";
    }).join("");
  }

  function detailHTML(run) {
    const meta = run.metrics || {};
    const v = GIS.ui.verdictInfo(run.flow.evaluate);
    return "<div class='stack-lg'>" +
      "<div class='row between wrap'>" +
      "<div class='row'><a class='btn sm ghost' href='#/history'>← 返回列表</a>" +
      "<span class='chip " + v.chip + "'>" + v.label + "</span>" +
      "<span class='chip mono'>" + esc(run.run_id) + "</span></div>" +
      "<div class='row' style='gap:6px'>" +
      "<button class='btn sm ghost' data-copy-run>" + GIS.ui.icon("copy") + "复制 JSON</button>" +
      "<button class='btn sm ghost' data-export-run>" + GIS.ui.icon("download") + "导出</button></div></div>" +
      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("flow") + "</span>" +
      "<div><h2>执行流回放</h2><p class='sub'>" + esc(run.question) + "</p></div></div>" +
      "<div class='chip-row' style='margin-bottom:12px'>" +
      "<span class='chip'>" + esc(run.domain_label || run.domain) + " / " + esc(run.task_type) + "</span>" +
      "<span class='chip'>" + (meta.subtasks || 1) + " 个子任务</span>" +
      "<span class='chip'>" + (meta.tool_calls || 0) + " 次工具调用</span>" +
      "<span class='chip mono'>" + (meta.elapsed_ms || 0) + " ms</span>" +
      "<span class='chip mono'>" + esc(run.created_at || "") + "</span>" +
      "<span class='chip " + (run.verdict_mode === "auto" ? "muted" : "warn") + "'>判定：" + esc(run.verdict_mode || "auto") + "</span>" +
      "</div>" +
      GIS.flow.render(run.flow, { run }) + "</div></div>";
  }

  function render() {
    const detailId = GIS.state.query && GIS.state.query.run;
    if (detailId) {
      if (S.detailError) {
        return "<div class='card'>" + GIS.ui.empty("找不到这次运行", S.detailError, "flow") +
          "<div style='text-align:center'><a class='btn primary' href='#/history'>" + GIS.ui.icon("arrow") + "返回执行流列表</a></div></div>";
      }
      if (!S.current || S.current.run_id !== detailId) {
        return "<div class='card'>" + GIS.ui.skeleton(200) + "</div>";
      }
      if (!S.current.flow) {
        return "<div class='card'>" + GIS.ui.empty("该记录只包含摘要", "完整执行流需要连接本地服务读取 web/data/demo_runs.json。", "flow") +
          "<div style='text-align:center'><a class='btn primary' href='#/history'>返回列表</a></div></div>";
      }
      return detailHTML(S.current);
    }
    const ok = S.runs.filter((r) => r.evaluation === "success").length;
    const failed = S.runs.filter((r) => r.evaluation === "failed").length;
    const unknown = S.runs.length - ok - failed;
    const latest = S.runs.length ? S.runs[0].created_at : "—";
    return "<div class='stack-lg'>" +
      "<div class='grid grid-kpi'>" +
      "<div class='card kpi'><div class='kpi-label'>运行记录</div><div class='kpi-value'>" + S.runs.length + "</div><div class='kpi-sub'>最近 " + esc(latest) + " · 最多 40 条</div></div>" +
      "<div class='card kpi'><div class='kpi-label'>判定成功</div><div class='kpi-value'>" + ok + "</div><div class='kpi-sub'>成功经验驱动能力上升</div></div>" +
      "<div class='card kpi'><div class='kpi-label'>判定失败</div><div class='kpi-value'>" + failed + "</div><div class='kpi-sub'>失败经验让能力回落</div></div>" +
      "<div class='card kpi'><div class='kpi-label'>未判定</div><div class='kpi-value'>" + unknown + "</div><div class='kpi-sub'>未提供参考答案 · 能力不变</div></div>" +
      "</div>" +
      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("flow") + "</span>" +
      "<div><h2>执行流历史</h2><p class='sub'>每次演示运行都保存完整的五阶段流程，可随时回放</p></div>" +
      "<div class='right'>" +
      "<button class='btn sm ghost' data-clear-runs>" + GIS.ui.icon("trash") + "清空记录</button></div></div>" +
      "<div class='row wrap' style='margin-bottom:12px;gap:8px'>" +
      "<div class='searchbar' style='flex:1;min-width:240px'>" + GIS.ui.icon("search") +
      "<input id='runSearch' placeholder='搜索问题、领域或任务类型…' value='" + esc(S.search) + "'></div>" +
      "<a class='btn sm primary' href='#/workbench'>" + GIS.ui.icon("play") + "新建运行</a>" +
      "</div>" +
      "<div id='runList'>" + listHTML() + "</div></div></div>";
  }

  function bindDetail() {
    const run = S.current;
    if (!run) return;
    document.querySelectorAll("[data-copy-run]").forEach((btn) => btn.addEventListener("click", () =>
      GIS.ui.copy(JSON.stringify(run, null, 2), "运行 JSON 已复制")));
    document.querySelectorAll("[data-export-run]").forEach((btn) => btn.addEventListener("click", () =>
      GIS.ui.download(run.run_id + ".json", JSON.stringify(run, null, 2))));
    GIS.flow.mount(document.getElementById("view"), run.flow, { run, autoplay: false });
  }

  function mount() {
    const detailId = GIS.state.query && GIS.state.query.run;
    if (detailId) { bindDetail(); return; }
    const search = document.getElementById("runSearch");
    if (search) {
      search.addEventListener("input", U.debounce(() => {
        S.search = search.value;
        const list = document.getElementById("runList");
        if (list) { list.innerHTML = listHTML(); bindList(); }
      }, 170));
    }
    bindList();
    const clear = document.querySelector("[data-clear-runs]");
    if (clear) {
      clear.addEventListener("click", async () => {
        if (!S.runs.length) return;
        const ok = await GIS.confirm("清空执行流记录", "将删除 web/data/demo_runs.json 中的全部演示运行记录，不影响能力向量与项目数据。", "清空");
        if (!ok) return;
        try {
          await GIS.api.clearRuns();
          S.runs = [];
          if (GIS.state.data.counts) GIS.state.data.counts.runs = 0;
          GIS.state.data.runs = [];
          GIS.toast("运行记录已清空", "ok");
          if (window.GIS.refreshNav) window.GIS.refreshNav();
          if (window.GIS.refreshView) window.GIS.refreshView();
        } catch (err) { GIS.toast(err.message || "清空失败", "err"); }
      });
    }
  }

  function bindList() {
    document.querySelectorAll("[data-open-run]").forEach((el) => {
      if (el._bound) return;
      el._bound = true;
      el.addEventListener("click", () => { location.hash = "#/history?run=" + encodeURIComponent(el.dataset.openRun); });
    });
  }

  GIS.views.history = {
    title: "执行流",
    subtitle: "回放每一次运行的完整轨迹",
    render,
    mount,
    async before() {
      await GIS.api.bootstrap();
      const detailId = GIS.state.query && GIS.state.query.run;
      if (detailId) {
        S.detailError = "";
        if (GIS.state.mode === "live") {
          try {
            S.current = await GIS.api.runById(detailId);
          } catch (err) {
            S.current = null;
            S.detailError = "运行记录不存在或已被清空。";
          }
        } else {
          S.current = (GIS.state.data.runs || []).find((r) => r.run_id === detailId) || null;
          if (!S.current) S.detailError = "静态快照中没有这次运行。";
        }
        return;
      }
      if (!S.loaded) await loadRuns();
      else if (GIS.state.mode === "live") await loadRuns();
    },
  };
})();
