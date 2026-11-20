/* ============================================================
   技能库：任务级 skill + PostGIS 工具目录 + 余弦检索演示
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;

  const S = { query: "", group: "全部", results: null, loading: false };

  const GROUPS = ["全部", "空间", "统计", "属性", "比例", "去重", "综合"];

  function renderSkills() {
    const d = GIS.state.data;
    const all = d.skills || [];
    const q = S.query.trim().toLowerCase();
    let list = all.filter((s) => S.group === "全部" || s.group === S.group);
    if (q) {
      list = list.filter((s) => {
        const hay = [s.name, s.desc, s.steps, s.scenes, s.id, (s.operators || []).join(" ")].join(" ").toLowerCase();
        return hay.includes(q);
      });
    }
    if (!list.length) {
      return "<div class='card'>" + GIS.ui.empty("没有匹配的 skill", "换个关键词，或把分组切换为「全部」。", "tools") + "</div>";
    }
    return "<div class='grid grid-3'>" + list.map((s) =>
      "<article class='skill-card' data-skill='" + esc(s.id) + "' tabindex='0'>" +
      "<div class='skill-top'><span class='chip brand'>" + esc(s.group) + "</span><h3>" + esc(s.name) + "</h3>" +
      "<span class='skill-id' style='margin-left:auto'>" + esc(s.id) + "</span></div>" +
      "<p class='skill-desc'>" + esc(s.desc) + "</p>" +
      "<div class='ops'>" + (s.operators || []).map((op, i) =>
        (i ? "<span class='op-arrow'>→</span>" : "") + "<span class='op'>" + esc(op) + "</span>").join("") + "</div>" +
      "<div class='skill-steps'>" + esc(s.steps) + "</div>" +
      "<div class='row between'><span class='skill-scenes'>" + esc(s.scenes) + "</span>" +
      "<span class='tiny faint'>" + (s.operators || []).length + " 算子</span></div>" +
      "</article>").join("") + "</div>";
  }

  function renderTools() {
    const tools = GIS.state.data.tools || [];
    const groups = {};
    tools.forEach((t) => { (groups[t.category] = groups[t.category] || []).push(t); });
    return Object.keys(groups).map((cat) =>
      "<div style='margin-bottom:14px'><div class='row' style='margin-bottom:7px'><span class='chip muted'>" + esc(cat) + "</span>" +
      "<span class='tiny faint'>" + groups[cat].length + " 个算子 · 启动时通过 bind_tools 绑定到模型</span></div>" +
      "<div class='grid grid-3'>" + groups[cat].map((t) =>
        "<div class='tool-card'><h4><span class='dot' style='background:var(--brand)'></span>" + esc(t.name) + "</h4>" +
        "<p>" + esc(t.description) + "</p>" +
        "<div class='params'>" + esc(t.params) + "</div></div>").join("") + "</div></div>"
    ).join("");
  }

  function renderRetrieval() {
    return "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("search") + "</span>" +
      "<div><h2>skill 余弦检索</h2><p class='sub'>输入问题，查看 TF-IDF + 余弦相似度命中的 skill（与项目内检索实现一致）</p></div></div>" +
      "<div class='row wrap' style='gap:8px'>" +
      "<div class='searchbar' style='flex:1;min-width:260px'>" + GIS.ui.icon("search") +
      "<input id='skillRetrievalInput' placeholder='例如：统计施工区内管线长度并按压力等级分组' value='" + esc(S.query) + "'></div>" +
      "<button class='btn primary' id='skillRetrievalBtn'>" + GIS.ui.icon("search") + "计算相关度</button></div>" +
      "<div class='retrieval-result' id='skillRetrievalResult'>" +
      (S.results ? renderResults(S.results) : "<div class='tiny muted' style='margin-top:8px'>尚未检索。检索会调用 /api/retrieve（静态模式下不可用）。</div>") +
      "</div></div>";
  }

  function renderResults(payload) {
    const items = payload.items || [];
    if (!items.length) return "<div class='tiny muted' style='margin-top:8px'>没有相似度大于 0 的命中。</div>";
    const max = Math.max.apply(null, items.map((i) => Number(i.score || 0))) || 1;
    return "<div style='margin-top:10px;display:flex;flex-direction:column;gap:6px'>" + items.map((i, idx) =>
      "<div class='hit'><div class='hit-main'><div class='hit-title'>" +
      "<span class='mono tiny faint'>#" + (idx + 1) + "</span> " + esc(i.name) +
      " <span class='chip muted'>" + esc(i.group || "") + "</span></div>" +
      "<div class='hit-sub'>" + esc(i.steps || i.desc || "") + "</div></div>" +
      "<div class='score'>" + GIS.ui.scoreBar(Number(i.score || 0) / max, 1) +
      "<b>" + Number(i.score || 0).toFixed(3) + "</b></div></div>").join("") + "</div>" +
      "<div class='tiny faint' style='margin-top:7px'>相对截断：只保留相似度 ≥ 最高分 × 0.4 的命中。</div>";
  }

  function render() {
    const d = GIS.state.data;
    const skills = d.skills || [];
    const tools = d.tools || [];
    return "<div class='stack-lg'>" +
      "<div class='grid grid-kpi'>" +
      "<div class='card kpi'><div class='kpi-label'>任务级 skill</div><div class='kpi-value'>" + skills.length + "</div><div class='kpi-sub'>单算子到多算子串联</div></div>" +
      "<div class='card kpi'><div class='kpi-label'>已绑定算子</div><div class='kpi-value'>" + tools.length + "</div><div class='kpi-sub'>PostGIS 工具集 · 启动时绑定</div></div>" +
      "<div class='card kpi'><div class='kpi-label'>覆盖分组</div><div class='kpi-value'>" + new Set(skills.map((s) => s.group)).size + "</div><div class='kpi-sub'>空间 / 统计 / 属性 / 比例 / 去重 / 综合</div></div>" +
      "<div class='card kpi'><div class='kpi-label'>检索方式</div><div class='kpi-value' style='font-size:16px'>TF-IDF 余弦</div><div class='kpi-sub'>top-4 + 相对截断</div></div>" +
      "</div>" +

      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("tools") + "</span>" +
      "<div><h2>任务级 skill 库</h2><p class='sub'>skill 描述“这类问题通常怎么做、按什么顺序做”，规划阶段据此组织 DAG</p></div></div>" +
      "<div class='toolbar'>" +
      "<div class='searchbar' style='flex:1;min-width:230px'>" + GIS.ui.icon("search") +
      "<input id='skillSearch' placeholder='搜索名称、做法、算子…' value='" + esc(S.query) + "'></div>" +
      GROUPS.map((g) => "<button class='filter-pill " + (S.group === g ? "active" : "") + "' data-group='" + esc(g) + "'>" + esc(g) + "</button>").join("") +
      "</div>" +
      "<div id='skillGrid'>" + renderSkills() + "</div></div>" +

      "<div class='grid grid-2'>" +
      renderRetrieval() +
      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("bolt") + "</span>" +
      "<div><h2>skill 与算子的关系</h2><p class='sub'>skill 不是算子手册，而是问题到算子序列的套路</p></div></div>" +
      "<div class='small' style='color:var(--ink-2);line-height:1.9'>" +
      "<p style='margin:0 0 8px'><b>单算子小任务</b>：例如「空间范围筛选计数」→ <span class='op'>query_features</span>（带 target + relation）。</p>" +
      "<p style='margin:0 0 8px'><b>典型多算子任务</b>：例如「裁剪后量测」→ <span class='op'>query_features</span> → <span class='op'>clip_features</span> → <span class='op'>measure_features</span>。</p>" +
      "<p style='margin:0 0 8px'><b>缓冲合并后裁剪</b>：设备批量缓冲 → 合并去重 → 裁剪到施工区 → 量测覆盖面积或管线长度。</p>" +
      "<p style='margin:0'>规划阶段检索 top-4 skill 作为参考，最终 DAG 由模型结合能力向量、专属记忆与共享经验生成。</p></div></div>" +
      "</div>" +

      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("bolt") + "</span>" +
      "<div><h2>PostGIS 工具目录</h2><p class='sub'>10 个算子由 tools/postgis_tools.py 适配外部工具集，参数 schema 直接交给模型</p></div></div>" +
      renderTools() + "</div>" +
      "</div>";
  }

  function openSkill(id) {
    const s = (GIS.state.data.skills || []).find((x) => x.id === id);
    if (!s) return;
    const tools = GIS.state.data.tools || [];
    const opRows = (s.operators || []).map((op) => {
      const t = tools.find((x) => x.name === op);
      return "<div class='hit'><div class='hit-main'><div class='hit-title mono'>" + esc(op) +
        "</div><div class='hit-sub'>" + esc(t ? t.description : "工具目录中未找到该算子") + "</div></div>" +
        (t ? "<span class='chip muted'>" + esc(t.category) + "</span>" : "") + "</div>";
    }).join("");
    GIS.ui.openDrawer("skill · " + s.name,
      "<div class='stack'>" +
      "<div class='chip-row'><span class='chip brand'>" + esc(s.group) + "</span><span class='chip mono'>" + esc(s.id) + "</span>" +
      "<button class='btn sm ghost' data-try-skill='" + esc(s.scenes) + "'>去任务台试用</button></div>" +
      "<div class='small' style='line-height:1.8'>" + esc(s.desc) + "</div>" +
      "<div><div class='tiny muted' style='margin-bottom:4px'>典型步骤</div>" + GIS.ui.codeBlock(s.steps, true) + "</div>" +
      "<div><div class='tiny muted' style='margin-bottom:4px'>适用场景</div><div class='small'>" + esc(s.scenes) + "</div></div>" +
      "<div><div class='tiny muted' style='margin-bottom:4px'>涉及的算子</div><div class='stack' style='gap:6px'>" + opRows + "</div></div>" +
      "</div>");
    document.querySelectorAll("[data-try-skill]").forEach((btn) => {
      btn.addEventListener("click", () => {
        try { sessionStorage.setItem("gis:prefill", btn.dataset.trySkill); } catch (e) { /* ignore */ }
        GIS.ui.closeDrawer();
        location.hash = "#/workbench";
      });
    });
  }

  function bind() {
    const search = document.getElementById("skillSearch");
    const redraw = () => {
      const grid = document.getElementById("skillGrid");
      if (grid) grid.innerHTML = renderSkills();
      const retrievalInput = document.getElementById("skillRetrievalInput");
      if (retrievalInput) retrievalInput.value = S.query;
      bindCards();
    };
    if (search) {
      search.addEventListener("input", U.debounce(() => { S.query = search.value; redraw(); }, 180));
    }
    document.querySelectorAll("[data-group]").forEach((btn) => {
      btn.addEventListener("click", () => {
        S.group = btn.dataset.group;
        document.querySelectorAll("[data-group]").forEach((b) => b.classList.toggle("active", b === btn));
        redraw();
      });
    });
    bindCards();

    const retrievalBtn = document.getElementById("skillRetrievalBtn");
    const retrievalInput = document.getElementById("skillRetrievalInput");
    const runRetrieval = async () => {
      const q = (retrievalInput ? retrievalInput.value : "").trim();
      if (!q) { GIS.toast("请输入检索文本", "warn"); return; }
      if (GIS.state.mode === "static") { GIS.toast("静态预览模式无法调用检索服务", "warn"); return; }
      const box = document.getElementById("skillRetrievalResult");
      if (box) box.innerHTML = "<div class='skeleton' style='height:52px'></div>";
      try {
        const payload = await GIS.api.retrieve(q, "skills");
        S.results = payload;
        if (box) box.innerHTML = renderResults(payload);
      } catch (err) {
        if (box) box.innerHTML = "<div class='chip err'>" + esc(err.message) + "</div>";
      }
    };
    if (retrievalBtn) retrievalBtn.addEventListener("click", runRetrieval);
    if (retrievalInput) retrievalInput.addEventListener("keydown", (e) => { if (e.key === "Enter") runRetrieval(); });
  }

  function bindCards() {
    document.querySelectorAll("[data-skill]").forEach((card) => {
      if (card._bound) return;
      card._bound = true;
      const open = () => openSkill(card.dataset.skill);
      card.addEventListener("click", open);
      card.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    });
  }

  GIS.views.skills = {
    title: "技能库",
    subtitle: "任务级套路与 PostGIS 算子",
    render,
    mount: bind,
    async before() { await GIS.api.bootstrap(); },
  };
})();
