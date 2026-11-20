/* ============================================================
   评测报告：dev20 基准成绩、逐题明细与执行流回放
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;

  const S = {
    reportName: null,
    report: null,
    loading: false,
    filter: "all",
    level: "all",
  };

  function reports() { return (GIS.state.data || {}).reports || []; }

  function summaryOf(report) {
    return (report && report.summary) || {};
  }

  function filteredResults() {
    const results = (S.report && S.report.results) || [];
    return results.filter((r) => {
      if (S.filter === "pass" && !r.correct) return false;
      if (S.filter === "fail" && r.correct) return false;
      if (S.level !== "all" && r.level !== S.level) return false;
      return true;
    });
  }

  function summaryHTML(report) {
    const summary = summaryOf(report);
    const meta = (report && report.meta) || {};
    const byLevel = summary.by_level || {};
    const levels = Object.keys(byLevel).sort();
    const accuracy = Number(summary.accuracy || 0);
    return "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("check") + "</span>" +
      "<div><h2>评测总览</h2><p class='sub'>" + esc(meta.suite || "dev20") + " · " + esc(meta.model || "—") +
      " · " + esc(meta.started_at || "—") + "</p></div>" +
      "<div class='right'><span class='chip " + (accuracy >= 0.9 ? "ok" : "warn") + "'>" + (accuracy * 100).toFixed(0) + "%</span></div></div>" +
      "<div class='row' style='gap:26px;align-items:center;flex-wrap:wrap'>" +
      "<div class='donut-wrap' style='width:160px;height:160px;margin:0'><canvas id='benchBigDonut'></canvas>" +
      "<div class='donut-center'><strong>" + (summary.correct || 0) + "/" + (summary.total || 0) + "</strong><span>通过 / 总数</span></div></div>" +
      "<div style='flex:1;min-width:210px'>" +
      "<div class='level-bars'>" + levels.map((lv) => {
        const item = byLevel[lv] || {};
        const ratio = item.total ? item.correct / item.total : 0;
        return "<div class='level-bar'><span class='mono tiny'>" + esc(lv) + "</span>" +
          "<span class='track'><i style='width:" + (ratio * 100).toFixed(1) + "%'></i></span>" +
          "<b>" + (item.correct || 0) + "/" + (item.total || 0) + "</b></div>";
      }).join("") + "</div>" +
      "<div class='kv-grid' style='margin-top:12px'>" +
      "<div class='kv'><dt>平均耗时</dt><dd class='mono'>" + (summary.elapsed_avg || 0) + " s</dd></div>" +
      "<div class='kv'><dt>工具调用</dt><dd class='mono'>" + (summary.tool_calls_total || 0) + " 次</dd></div>" +
      "<div class='kv'><dt>平均调用</dt><dd class='mono'>" + (summary.tool_calls_avg || 0) + " / 题</dd></div>" +
      "<div class='kv'><dt>随机路由</dt><dd class='mono'>" + (summary.random_routed || 0) + " 题</dd></div>" +
      "</div></div></div>" +
      "<div class='hr-soft'></div>" +
      "<div class='row between wrap tiny muted'><span>数据库 " + esc(meta.database || "—") + " · 每题作答 " + esc(meta.max_replans != null ? meta.max_replans : "—") + " 次重规划</span>" +
      "<span>错误 " + (summary.errors || 0) + " · 解析失败 " + (summary.no_json || 0) + "</span></div></div>";
  }

  function caseHTML(r) {
    const routing = r.routing || {};
    return "<div class='bench-case' data-case='" + esc(r.id) + "'>" +
      "<span class='case-id'>" + esc(r.id) + "</span>" +
      "<span class='level case-level'>" + esc(r.level) + "</span>" +
      "<span class='case-q'>" + esc(r.question) + "</span>" +
      "<span class='tiny muted mono'>" + esc(r.agent_name ? "agent " + r.agent_name : "") + "</span>" +
      "<span class='case-verdict'><span class='chip " + (r.correct ? "ok" : "err") + "'>" + (r.correct ? "通过" : "未通过") + "</span></span>" +
      "</div>";
  }

  function render() {
    const list = reports();
    if (!S.reportName && list.length) S.reportName = list[0].name;
    const entry = list.find((x) => x.name === S.reportName) || list[0];
    const report = S.report || {
      meta: entry ? {
        suite: "postgis_dev20_v1", model: entry.model, started_at: entry.started_at,
        database: entry.database, case_count: entry.case_count,
        total_elapsed_s: entry.elapsed_s,
      } : {},
      summary: (entry && entry.summary) || entry || {},
      results: [],
    };
    const results = filteredResults();
    const levels = Object.keys(summaryOf(report).by_level || (entry && entry.by_level) || {}).sort();

    return "<div class='stack-lg'>" +
      "<div class='card' style='padding:14px 18px'><div class='row between wrap'>" +
      "<div class='row wrap' style='gap:8px'>" +
      "<select id='reportSelect' class='field' style='height:36px;border:1px solid var(--line);border-radius:9px;background:var(--panel-2);padding:0 10px;font-size:12px;min-width:250px'>" +
      list.map((r) => "<option value='" + esc(r.name) + "' " + (r.name === S.reportName ? "selected" : "") + ">" +
        esc(r.name) + (r.latest ? " · 最新" : "") + " · " + ((r.accuracy || 0) * 100).toFixed(0) + "%</option>").join("") +
      "</select>" +
      "<span class='chip mono'>" + esc((report.meta || {}).model || "") + "</span>" +
      "<span class='chip'>" + (report.results || []).length + " 题</span>" +
      "</div>" +
      "<div class='row' style='gap:6px'>" +
      "<a class='btn sm ghost' href='/artifact/report.md' target='_blank' rel='noopener'>" + GIS.ui.icon("book") + "Markdown 报告</a>" +
      "<button class='btn sm ghost' data-download-report>" + GIS.ui.icon("download") + "导出 JSON</button></div>" +
      "</div></div>" +

      summaryHTML(report) +

      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("check") + "</span>" +
      "<div><h2>逐题结果</h2><p class='sub'>点击任意题目查看路由、工具轨迹、判定结果与能力变化</p></div>" +
      "<div class='right'><span class='chip mono'>" + results.length + " / " + ((report.results || []).length) + "</span></div></div>" +
      "<div class='toolbar'>" +
      "<div class='segmented' id='benchFilter'>" +
      "<button data-filter='all' class='" + (S.filter === "all" ? "active" : "") + "'>全部</button>" +
      "<button data-filter='pass' class='" + (S.filter === "pass" ? "active" : "") + "'>通过</button>" +
      "<button data-filter='fail' class='" + (S.filter === "fail" ? "active" : "") + "'>未通过</button></div>" +
      "<span class='divider' style='width:1px;height:18px;margin:0'></span>" +
      "<button class='filter-pill " + (S.level === "all" ? "active" : "") + "' data-level='all'>全部难度</button>" +
      levels.map((lv) => "<button class='filter-pill " + (S.level === lv ? "active" : "") + "' data-level='" + esc(lv) + "'>" + esc(lv) + "</button>").join("") +
      "</div>" +
      (S.loading ? "<div class='skeleton' style='height:120px'></div>" :
        ((report.results || []).length
          ? "<div id='benchCases'>" + (results.length ? results.map(caseHTML).join("") : GIS.ui.empty("没有匹配的题目", "调整筛选条件试试。", "search")) + "</div>"
          : GIS.ui.empty("静态预览模式", "报告明细需要连接本地服务后读取 reports/dev20/*.json。", "check"))) +
      "</div>" +

      (report.meta && report.meta.final_capabilities
        ? "<div class='card'><div class='card-head'><div><h3>评测结束时的能力向量</h3><p class='sub'>20 题连续执行后的能力分布</p></div></div>" +
          "<div class='grid grid-4' style='gap:12px'>" + report.meta.final_capabilities.map((a) =>
            "<div class='agent-card'><div class='agent-card-top'>" + GIS.ui.agentAvatar(a.agent, 30) +
            "<div><div class='agent-name'>智能体 " + esc(a.name) + "</div><div class='agent-meta'>尝试 " + ((a.stats || {}).attempts || 0) +
            " · 成功 " + ((a.stats || {}).successes || 0) + "</div></div></div>" +
            "<div class='agent-mini-bars'>" + GIS.meta.dims().map((dim, i) =>
              "<div class='mini-cap'><span>" + esc(GIS.meta.dimLabel(dim)) + "</span><span class='bar'><i style='width:" +
              (Number(a.vector[i] || 0) * 100).toFixed(1) + "%;background:" + GIS.meta.agentColor(a.agent) + "'></i></span><b>" +
              Number(a.vector[i] || 0).toFixed(3) + "</b></div>").join("") + "</div></div>").join("") + "</div></div>"
        : "") +
      "</div>";
  }

  function openCase(id) {
    const r = ((S.report || {}).results || []).find((x) => x.id === id);
    if (!r) return;
    const routing = r.routing || {};
    const routingRows = Object.keys(routing.scores || {}).sort().map((aid) =>
      "<div class='routing-row " + (aid === routing.agent_id ? "winner" : "") + "'>" +
      "<div class='routing-name'><span class='dot' style='background:" + GIS.meta.agentColor(aid) + "'></span>智能体 " + esc(GIS.meta.agentName(aid)) + "</div>" +
      "<div class='routing-bar'><i style='width:" + (Number(routing.scores[aid] || 0) * 100).toFixed(1) + "%'></i></div>" +
      "<div class='routing-score'>" + Number(routing.scores[aid] || 0).toFixed(3) + "</div></div>").join("");
    const diffs = (r.diffs || []).length
      ? "<div class='chip err' style='white-space:normal;line-height:1.7'>" + r.diffs.map((d) => esc(typeof d === "string" ? d : JSON.stringify(d))).join("<br>") + "</div>"
      : "";
    const flow = GIS.flow.fromBenchmark(r);
    GIS.ui.openDrawer("题目 " + r.id + " · " + (r.correct ? "通过" : "未通过"),
      "<div class='stack'>" +
      "<div class='chip-row'><span class='chip " + (r.correct ? "ok" : "err") + "'>" + (r.correct ? "判定通过" : "判定未通过") + "</span>" +
      "<span class='chip mono'>" + esc(r.level) + "</span><span class='chip mono'>" + esc(r.elapsed_s || 0) + " s</span>" +
      "<span class='chip'>智能体 " + esc(r.agent_name || "") + "</span>" +
      "<span class='chip'>" + (r.tools || []).length + " 个算子</span></div>" +
      "<div class='small' style='line-height:1.8'>" + esc(r.question) + "</div>" +
      "<div class='grid grid-2' style='gap:10px'>" +
      "<div class='kv'><dt>期望答案</dt><dd class='mono' style='white-space:pre-wrap'>" + esc(JSON.stringify(r.expected)) + "</dd></div>" +
      "<div class='kv'><dt>模型答案</dt><dd class='mono' style='white-space:pre-wrap'>" + esc(JSON.stringify(r.answer)) + "</dd></div></div>" +
      diffs +
      "<div><div class='tiny muted' style='margin-bottom:4px'>能力路由</div><div class='routing'>" + routingRows + "</div>" +
      "<div class='tiny faint' style='margin-top:4px'>" + (routing.random_pick ? "得分并列 → 随机抽取" : "按能力最高分选中") + "</div></div>" +
      "<div class='hr-soft'></div>" +
      "<div class='card' style='padding:12px;background:var(--panel-2);box-shadow:none'>" +
      GIS.flow.render(flow, { run: { run_id: r.id, mode: "benchmark", timeline: [] }, showLog: false }) + "</div>" +
      "</div>");
    const body = document.getElementById("drawerBody");
    if (body) GIS.flow.mount(body, flow, { run: { run_id: r.id, mode: "benchmark", timeline: [] }, autoplay: false, showLog: false });
  }

  function drawSummary() {
    const canvas = document.getElementById("benchBigDonut");
    if (!canvas) return;
    const report = S.report || {};
    const summary = summaryOf(report);
    requestAnimationFrame(() => GIS.charts.donut(canvas, { ratio: Number(summary.accuracy || 0) }));
  }

  function bind() {
    drawSummary();
    const select = document.getElementById("reportSelect");
    if (select) {
      select.addEventListener("change", async () => {
        S.reportName = select.value;
        S.report = null;
        S.loading = true;
        await loadReport(S.reportName);
        GIS.refreshView();
      });
    }
    document.querySelectorAll("[data-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        S.filter = btn.dataset.filter;
        const box = document.getElementById("benchCases");
        if (box) {
          const list = filteredResults();
          box.innerHTML = list.length ? list.map(caseHTML).join("") : GIS.ui.empty("没有匹配的题目", "调整筛选条件试试。", "search");
          bindCases();
        }
        document.querySelectorAll("[data-filter]").forEach((b) => b.classList.toggle("active", b === btn));
      });
    });
    document.querySelectorAll("[data-level]").forEach((btn) => {
      btn.addEventListener("click", () => {
        S.level = btn.dataset.level;
        document.querySelectorAll("[data-level]").forEach((b) => b.classList.toggle("active", b === btn));
        const box = document.getElementById("benchCases");
        if (box) {
          const list = filteredResults();
          box.innerHTML = list.length ? list.map(caseHTML).join("") : GIS.ui.empty("没有匹配的题目", "调整筛选条件试试。", "search");
          bindCases();
        }
      });
    });
    bindCases();
    const download = document.querySelector("[data-download-report]");
    if (download) download.addEventListener("click", () => {
      if (!S.report) { GIS.toast("报告明细尚未加载", "warn"); return; }
      GIS.ui.download(S.reportName || "report.json", JSON.stringify(S.report, null, 2));
    });
    const caseId = GIS.state.query && GIS.state.query.case;
    if (caseId && S.report) setTimeout(() => openCase(caseId), 120);
  }

  function bindCases() {
    document.querySelectorAll("[data-case]").forEach((el) => {
      if (el._bound) return;
      el._bound = true;
      el.addEventListener("click", () => openCase(el.dataset.case));
    });
  }

  async function loadReport(name) {
    if (GIS.state.mode === "static") { S.loading = false; return; }
    try {
      S.report = await GIS.api.report(name);
    } catch (err) {
      GIS.toast(err.message || "加载报告失败", "err");
    } finally {
      S.loading = false;
    }
  }

  GIS.views.benchmark = {
    title: "评测报告",
    subtitle: "dev20 基准 · 逐题回放执行流",
    render,
    mount: bind,
    async before() {
      await GIS.api.bootstrap();
      if (!S.reportName && reports().length) S.reportName = reports()[0].name;
      if (!S.report && S.reportName) await loadReport(S.reportName);
    },
  };
})();
