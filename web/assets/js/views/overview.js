/* ============================================================
   总览：能力全景 / 智能体状态 / 最近进化 / 评测成绩
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;

  function avgCapability(agents, dims) {
    const ids = Object.keys(agents || {});
    if (!ids.length || !dims.length) return 0;
    let sum = 0;
    ids.forEach((id) => dims.forEach((d) => { sum += Number((agents[id].capabilities || {})[d] || 0); }));
    return sum / (ids.length * dims.length);
  }

  function evolutionSeries(history, agents, dims) {
    const values = [];
    const ids = Object.keys(agents || {}).sort();
    const current = {};
    ids.forEach((id) => {
      current[id] = {};
      dims.forEach((d) => { current[id][d] = Number((agents[id].capabilities || {})[d] || 0); });
    });
    // 从当前状态反推不现实，直接累计每帧平均：以初始值出发重放
    const init = Number((GIS.state.data || {}).initial_capability || 0.5);
    const state = {};
    ids.forEach((id) => { state[id] = {}; dims.forEach((d) => { state[id][d] = init; }); });
    (history || []).forEach((e) => {
      if (state[e.agent_id]) {
        dims.forEach((d) => {
          if (e.vector_after && e.vector_after[d] != null) state[e.agent_id][d] = Number(e.vector_after[d]);
        });
      }
      let sum = 0;
      ids.forEach((id) => dims.forEach((d) => { sum += state[id][d]; }));
      values.push(sum / (ids.length * dims.length));
    });
    return values;
  }

  function render() {
    const d = GIS.state.data;
    const cap = d.capability || {};
    const agents = cap.agents || {};
    const dims = d.dimensions || [];
    const history = cap.history || [];
    const reports = d.reports || [];
    const latestReport = reports.length ? reports[0] : null;
    const counts = d.counts || {};
    const avg = avgCapability(agents, dims);
    const runs = d.runs || [];

    const agentCards = Object.keys(agents).sort().map((id) => {
      const a = agents[id];
      const evoCount = history.filter((e) => e.agent_id === id).length;
      const bars = dims.map((dim) => {
        const v = Number((a.capabilities || {})[dim] || 0);
        return "<div class='mini-cap'><span>" + esc(GIS.meta.dimLabel(dim)) +
          "</span><span class='bar'><i style='width:" + (v * 100).toFixed(1) + "%;background:" + GIS.meta.agentColor(id) + "'></i></span>" +
          "<b>" + v.toFixed(3) + "</b></div>";
      }).join("");
      return "<div class='agent-card' data-agent='" + id + "' role='button' tabindex='0'>" +
        "<div class='agent-card-top'>" + GIS.ui.agentAvatar(id, 34) +
        "<div><div class='agent-name'>智能体 " + esc(a.name || id) + "</div>" +
        "<div class='agent-meta'>尝试 " + (a.stats.attempts || 0) + " · 成功 " + (a.stats.successes || 0) +
        " · 进化 " + evoCount + " 次</div></div>" +
        "<span class='chip " + (evoCount ? "brand" : "muted") + "' style='margin-left:auto'>" + (evoCount ? "已分化" : "均衡") + "</span></div>" +
        "<div class='agent-mini-bars'>" + bars + "</div>" +
        (a.preferred_tools && a.preferred_tools.length
          ? "<div class='chip-row' style='margin-top:8px'>" + a.preferred_tools.slice(0, 3).map((t) => "<span class='op'>" + esc(t) + "</span>").join("") +
            (a.preferred_tools.length > 3 ? "<span class='tiny muted'>+" + (a.preferred_tools.length - 3) + "</span>" : "") + "</div>"
          : "<div class='tiny muted' style='margin-top:8px'>尚无工具偏好</div>") +
        "</div>";
    }).join("");

    const evoRows = history.slice(-7).reverse().map((e) => {
      const deltaSum = Object.keys(e.delta || {}).reduce((s, k) => s + Number(e.delta[k] || 0), 0);
      const color = GIS.meta.agentColor(e.agent_id);
      return "<div class='event-row'>" +
        "<span class='event-badge' style='background:" + color + "'>" + esc(e.agent_name) + "</span>" +
        "<div class='event-body'><div class='event-title'>" +
        (e.outcome === "success" ? "成功经验" : "失败经验") +
        " <span>· " + (e.dims || []).map((x) => esc(GIS.meta.dimLabel(x))).join(" / ") + "</span></div>" +
        "<div class='event-sub'>" + esc(U.truncate(e.question || "", 74)) + "</div></div>" +
        "<span class='delta " + GIS.ui.deltaClass(deltaSum) + "'>" + U.signed(deltaSum, 4) + "</span></div>";
    }).join("") || GIS.ui.empty("还没有进化记录", "在任务台运行一次任务，成功或失败都会让能力向量发生变化。", "spark");

    const levelBars = latestReport ? Object.keys(latestReport.by_level || {}).sort().map((lv) => {
      const item = latestReport.by_level[lv];
      const ratio = item.total ? item.correct / item.total : 0;
      return "<div class='level-bar'><span class='mono tiny'>" + esc(lv) + "</span>" +
        "<span class='track'><i style='width:" + (ratio * 100).toFixed(1) + "%'></i></span>" +
        "<b>" + item.correct + "/" + item.total + "</b></div>";
    }).join("") : "";

    const recentRuns = runs.slice(0, 4).map((r) => {
      const v = GIS.ui.verdictInfo({ evaluation: r.evaluation });
      return "<div class='run-card' data-run='" + esc(r.run_id) + "'>" +
        "<div><div class='q'>" + esc(r.question) + "</div>" +
        "<div class='meta'><span>" + esc(r.domain_label || r.domain || "") + " / " + esc(r.task_type || "") + "</span>" +
        "<span>" + esc((r.metrics || {}).tool_calls || 0) + " 次工具调用</span>" +
        "<span>" + esc((r.metrics || {}).elapsed_ms || 0) + " ms</span>" +
        "<span>" + esc(r.created_at || "") + "</span></div></div>" +
        "<span class='chip " + v.chip + "'>" + v.short + "</span></div>";
    }).join("");

    const examples = (d.examples || []).slice(0, 3).map((q, i) =>
      "<button class='example-item' data-example='" + esc(q) + "'><b>DEMO " + (i + 1) + "</b>" + esc(q) + "</button>").join("");

    return "<div class='stack-lg'>" +
      "<section class='hero'><div class='hero-grid'><div>" +
      "<div class='hero-eyebrow'>能力进化版 · 五阶段多智能体架构</div>" +
      "<h2>智能体没有预设专长，<br>专长从每一次成功与失败中长出来。</h2>" +
      "<p class='lede'>领域识别 → 精炼拆解 → 能力路由 → DAG 规划 → 工具执行 → 评估进化。所有检索统一走余弦相似度，能力向量只随真实执行结果变化。</p>" +
      "<div class='hero-stats'>" +
      "<div class='hero-stat'><strong>" + Object.keys(agents).length + "</strong><span>编号智能体</span></div>" +
      "<div class='hero-stat'><strong>" + avg.toFixed(3) + "</strong><span>平均能力值</span></div>" +
      "<div class='hero-stat'><strong>" + history.length + "</strong><span>能力进化事件</span></div>" +
      "<div class='hero-stat'><strong>" + (counts.skills || 0) + "</strong><span>任务级 skill</span></div>" +
      "</div>" +
      "<div class='hero-actions'>" +
      "<a class='btn primary' href='#/workbench'>" + GIS.ui.icon("play") + "开始一次任务</a>" +
      "<a class='btn' href='#/capability'>" + GIS.ui.icon("radar") + "回放能力进化</a>" +
      "<a class='btn' href='#/benchmark'>" + GIS.ui.icon("check") + "查看评测</a>" +
      "</div></div>" +
      "<div class='hero-flow'>" +
      GIS.flow.stages.map((s) => "<div class='hero-flow-item'><b>" + s.no + "</b><span>" + s.title + "</span><em class='tiny' style='font-style:normal;color:#7f97b8;margin-left:auto'>" + s.en + "</em></div>").join("") +
      "</div></div></section>" +

      "<section class='grid grid-kpi'>" +
      "<div class='card kpi'><div class='kpi-label'>平均能力值 <span class='faint'>/ 1.0</span></div>" +
      "<div class='kpi-value'>" + avg.toFixed(3) + "</div>" +
      "<div class='kpi-sub'>" + (avg > 0.5 ? "高于初始均衡基线 0.500" : "处于初始均衡基线") + "</div>" +
      "<canvas class='kpi-spark' id='sparkAvg' style='width:78px;height:34px'></canvas></div>" +
      "<div class='card kpi'><div class='kpi-label'>能力进化事件</div>" +
      "<div class='kpi-value'>" + history.length + "</div>" +
      "<div class='kpi-sub'>" + (history.filter((e) => e.outcome === "success").length) + " 次成功 · " +
      (history.filter((e) => e.outcome !== "success").length) + " 次失败</div></div>" +
      "<div class='card kpi'><div class='kpi-label'>知识资产</div>" +
      "<div class='kpi-value'>" + (counts.skills || 0) + "<small>skill</small> " + (counts.tables || 0) + "<small>表</small></div>" +
      "<div class='kpi-sub'>" + (counts.tools || 0) + " 个 PostGIS 算子已绑定</div></div>" +
      "<div class='card kpi'><div class='kpi-label'>经验与记忆</div>" +
      "<div class='kpi-value'>" + (counts.experience || 0) + "<small>经验</small> " + (counts.memory_records || 0) + "<small>记忆</small></div>" +
      "<div class='kpi-sub'>共享经验池 + 智能体专属记忆</div></div>" +
      "</section>" +

      "<section class='grid' style='grid-template-columns:minmax(0,1.18fr) minmax(320px,.82fr);align-items:start'>" +
      "<div class='card'><div class='card-head'>" +
      "<span class='card-title-icon'>" + GIS.ui.icon("radar") + "</span>" +
      "<div><h2>当前能力向量</h2><p class='sub'>四个智能体在同一坐标系中的能力分布；能力维度与业务领域正交</p></div>" +
      "<div class='right'><span class='chip mono'>" + esc(cap.updated_at || "") + "</span></div></div>" +
      "<div class='radar-wrap'><canvas id='overviewRadar'></canvas></div>" +
      "<div class='radar-legend'>" + Object.keys(agents).sort().map((id) =>
        "<span><span class='dot' style='background:" + GIS.meta.agentColor(id) + "'></span>智能体 " + esc(agents[id].name || id) + "</span>").join("") + "</div>" +
      "<div class='hr-soft' style='margin-top:14px'></div>" +
      "<div class='grid grid-2' style='gap:9px 16px'>" + dims.map((dim, i) =>
        "<div><div class='row' style='gap:6px'><span class='mono tiny faint'>0" + (i + 1) + "</span>" +
        "<b class='small'>" + esc(GIS.meta.dimLabel(dim)) + "</b></div>" +
        "<div class='tiny muted'>" + esc(GIS.meta.dimGlossary(dim)) + "</div></div>").join("") + "</div>" +
      "</div>" +
      "<div class='card'><div class='card-head'>" + GIS.ui.icon("spark") +
      "<div><h3>智能体分化状态</h3><p class='sub'>编号本身不携带能力信息；点击查看进化轨迹</p></div>" +
      "<div class='right'><button class='btn sm danger' id='overviewResetCaps' title='将全部智能体能力向量恢复为初始 0.500'>" +
      GIS.ui.icon("reset") + "重置所有智能体</button></div></div>" +
      "<div class='stack'>" + agentCards + "</div></div>" +
      "</section>" +

      "<section class='grid grid-2'>" +
      "<div class='card'><div class='card-head'><div><h3>最近能力进化</h3><p class='sub'>成功提升、失败回落，只更新子任务所需维度</p></div>" +
      "<div class='right'><a class='btn sm ghost' href='#/capability'>全部记录</a></div></div>" + evoRows + "</div>" +
      "<div class='card'><div class='card-head'><div><h3>最新基准评测</h3><p class='sub'>" +
      (latestReport ? esc(latestReport.model || "") + " · " + esc(latestReport.started_at || "") : "暂无评测报告") +
      "</p></div><div class='right'><a class='btn sm ghost' href='#/benchmark'>查看报告</a></div></div>" +
      (latestReport
        ? "<div class='row' style='gap:22px;align-items:center'><div class='donut-wrap'><canvas id='benchDonut'></canvas>" +
          "<div class='donut-center'><strong>" + ((latestReport.accuracy || 0) * 100).toFixed(0) + "%</strong><span>准确率</span></div></div>" +
          "<div style='flex:1'><div class='level-bars'>" + levelBars + "</div>" +
          "<div class='tiny faint' style='margin-top:12px'>" + (latestReport.correct || 0) + " / " + (latestReport.total || 0) + " 题通过 · 平均 " +
          (latestReport.elapsed_s ? (latestReport.elapsed_s / Math.max(1, latestReport.total || 1)).toFixed(1) : "—") + " 秒/题</div></div></div>"
        : GIS.ui.empty("暂无评测数据", "运行 scripts/run_dev20_benchmark.py 生成报告。", "check")) +
      "</div></section>" +

      "<section class='grid grid-2'>" +
      "<div class='card'><div class='card-head'><div><h3>最近的演示执行</h3><p class='sub'>在任务台发起的运行会保存在 web/data/demo_runs.json</p></div>" +
      "<div class='right'><a class='btn sm ghost' href='#/history'>执行流历史</a></div></div>" +
      (recentRuns || GIS.ui.empty("还没有运行记录", "去任务台输入一个问题，观察五阶段执行流与能力变化。", "flow")) +
      "</div>" +
      "<div class='card'><div class='card-head'><div><h3>快速开始</h3><p class='sub'>选择一个示例问题直达任务台</p></div></div>" +
      "<div class='examples'>" + examples + "</div>" +
      "<div class='hr-soft'></div>" +
      "<div class='row between'><span class='tiny muted'>服务模式</span><span class='chip " + (GIS.state.mode === "live" ? "ok" : "warn") + "'>" +
      (GIS.state.mode === "live" ? "本地服务已连接" : "静态快照预览") + "</span></div></div>" +
      "</section>" +
      "</div>";
  }

  function mount() {
    const d = GIS.state.data;
    const cap = d.capability || {};
    const agents = cap.agents || {};
    const dims = d.dimensions || [];
    const agentList = Object.keys(agents).sort().map((id) => ({
      id, name: agents[id].name, color: GIS.meta.agentColor(id), values: agents[id].capabilities,
    }));

    const radar = document.getElementById("overviewRadar");
    if (radar) {
      const draw = () => GIS.charts.radar(radar, {
        dims, labels: d.labels, agents: agentList, showInitial: true,
        initial: d.initial_capability, pad: 58,
      });
      requestAnimationFrame(draw);
      radar.addEventListener("dblclick", () => { location.hash = "#/capability"; });
    }

    const spark = document.getElementById("sparkAvg");
    if (spark) {
      const series = evolutionSeries(cap.history, agents, dims);
      GIS.charts.sparkline(spark, series.slice(-24), GIS.meta.agentColor("agent_02"));
    }

    const donut = document.getElementById("benchDonut");
    const reports = d.reports || [];
    if (donut && reports.length) {
      requestAnimationFrame(() => GIS.charts.donut(donut, { ratio: reports[0].accuracy || 0 }));
    }

    document.querySelectorAll("[data-agent]").forEach((el) => {
      const go = () => { location.hash = "#/capability?agent=" + el.dataset.agent; };
      el.addEventListener("click", go);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });

    document.querySelectorAll("[data-example]").forEach((el) => {
      el.addEventListener("click", () => {
        try { sessionStorage.setItem("gis:prefill", el.dataset.example); } catch (e) { /* ignore */ }
        location.hash = "#/workbench";
      });
    });

    document.querySelectorAll("[data-run]").forEach((el) => {
      el.addEventListener("click", () => { location.hash = "#/history?run=" + encodeURIComponent(el.dataset.run); });
    });

    const resetBtn = document.getElementById("overviewResetCaps");
    if (resetBtn) resetBtn.addEventListener("click", () => GIS.ui.openCapabilityReset());
  }

  GIS.views.overview = {
    title: "总览",
    subtitle: "多智能体能力进化全景",
    render,
    mount,
    async before() { await GIS.api.bootstrap(); },
  };
})();
