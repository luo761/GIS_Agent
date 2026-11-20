/* ============================================================
   知识库：PostGIS 表结构 / 领域知识 / 上下文注入检索
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;

  const S = { query: "", open: {}, results: null };

  function fieldsHTML(table) {
    return (table.fields || []).map((f) =>
      "<div class='field-row'><div class='field-name'>" + esc(f.name) + "</div>" +
      "<div class='field-type'>" + esc(f.type) + "</div>" +
      "<div><span class='small'>" + esc(f.note) + "</span>" +
      ((f.samples || []).length ? "<div style='margin-top:2px'>" + f.samples.map((v) => "<span class='sample'>" + esc(v) + "</span>").join("") + "</div>" : "") +
      "</div></div>").join("");
  }

  function tablesHTML() {
    const d = GIS.state.data;
    const tables = ((d.schema || {}).tables) || [];
    const q = S.query.trim().toLowerCase();
    const list = q ? tables.filter((t) =>
      (t.name + " " + t.note + " " + (t.fields || []).map((f) => f.name + f.note + (f.samples || []).join("")).join(" ")).toLowerCase().includes(q)) : tables;
    if (!list.length) return "<div class='card'>" + GIS.ui.empty("没有匹配的表", "换一个关键词试试。", "db") + "</div>";
    return "<div class='stack'>" + list.map((t, i) => {
      const open = S.open[t.name] != null ? S.open[t.name] : (i === 0 && !q);
      return "<div class='card flush table-card " + (open ? "open" : "") + "' data-table-card='" + esc(t.name) + "'>" +
        "<div class='table-card-head' data-table-head='" + esc(t.name) + "'>" +
        "<span class='card-title-icon' style='width:30px;height:30px'>" + GIS.ui.icon("db") + "</span>" +
        "<div><div class='table-name'>" + esc(t.name) + "</div><div class='tiny muted'>" + esc(t.note) + "</div></div>" +
        "<span class='chip muted' style='margin-left:auto'>" + (t.fields || []).length + " 字段</span>" +
        "<svg class='chev'><use href='#i-chevron'></use></svg></div>" +
        "<div class='table-fields'>" + fieldsHTML(t) + "</div></div>";
    }).join("") + "</div>";
  }

  function knowledgeHTML() {
    const d = GIS.state.data;
    const knowledge = d.domain_knowledge || {};
    const domains = d.domains || {};
    const names = d.domain_names || {};
    const keys = Object.keys(domains).length ? Object.keys(domains) : Object.keys(knowledge);
    return "<div class='grid grid-2'>" + keys.map((key) => {
      const domain = domains[key] || {};
      return "<div class='card knowledge-card'><div class='card-head'>" +
        "<div><span class='knowledge-key'>" + esc(key.toUpperCase()) + "</span>" +
        "<h3 style='margin:2px 0 0'>" + esc(names[key] || key) + "</h3>" +
        "<p class='sub'>" + esc((domain.keywords || []).join(" / ")) + "</p></div>" +
        "<div class='right'><span class='chip muted'>" + esc((domain.typical_tables || []).length) + " 个典型表</span></div></div>" +
        "<div class='small' style='line-height:1.8;color:var(--ink-2)'>" + esc(knowledge[key] || "暂无领域知识条目（该领域在示例库中没有对应图层）。") + "</div>" +
        ((domain.typical_tables || []).length
          ? "<div class='chip-row' style='margin-top:9px'>" + domain.typical_tables.map((t) => "<span class='op'>" + esc(t) + "</span>").join("") + "</div>"
          : "") + "</div>";
    }).join("") + "</div>";
  }

  function renderResults(payload) {
    const items = payload.items || [];
    if (!items.length) return "<div class='tiny muted' style='margin-top:8px'>没有相似度大于 0 的命中。</div>";
    const max = Math.max.apply(null, items.map((i) => Number(i.score || 0))) || 1;
    const context = ["【数据库相关表结构（按余弦相似度检索）】"].concat(items.map((t) =>
      "\n表 " + t.name + "（" + (t.note || "") + "）:\n" + (t.fields || []).map((f) => "  - " + f.name + ": " + f.note).join("\n"))).join("\n");
    return "<div style='margin-top:10px;display:flex;flex-direction:column;gap:6px'>" + items.map((i) =>
      "<div class='hit'><div class='hit-main'><div class='hit-title mono'>" + esc(i.name) +
      "</div><div class='hit-sub'>" + esc(i.note) + "</div></div>" +
      "<div class='score'>" + GIS.ui.scoreBar(Number(i.score || 0) / max, 1) + "<b>" + Number(i.score || 0).toFixed(3) + "</b></div></div>").join("") +
      "</div><div class='code-head'><span>将要注入规划/拆解 prompt 的表结构上下文</span>" +
      "<button class='btn sm ghost' data-copy-context>复制上下文</button></div>" +
      GIS.ui.codeBlock(context, false, 220);
  }

  function render() {
    const d = GIS.state.data;
    const schema = d.schema || {};
    const health = d.health || {};
    const db = health.database || {};
    const tables = schema.tables || [];
    const totalFields = tables.reduce((s, t) => s + (t.fields || []).length, 0);
    return "<div class='stack-lg'>" +
      "<div class='card' style='border-left:3px solid var(--brand)'>" +
      "<div class='row between wrap'>" +
      "<div><h2 style='font-size:16px'>PostGIS 表结构知识</h2>" +
      "<p class='small muted' style='margin:4px 0 0'>阶段①按问题检索最相关的表与字段，作为上下文注入提示词，避免把整库 schema 塞进模型。</p></div>" +
      "<div class='chip-row'>" +
      "<span class='chip " + (db.reachable ? "ok" : "warn") + "'>数据库端口 " + (db.reachable ? "可达" : "未检测到") + "</span>" +
      "<span class='chip muted'>网页使用" + esc(schema.source_label || "内置示例") + "</span></div></div>" +
      "<div class='hr-soft'></div>" +
      "<div class='row wrap' style='gap:22px'>" +
      "<div><div class='tiny faint'>表数量</div><div class='mono strong'>" + tables.length + "</div></div>" +
      "<div><div class='tiny faint'>字段数量</div><div class='mono strong'>" + totalFields + "</div></div>" +
      "<div><div class='tiny faint'>坐标系</div><div class='mono strong'>EPSG:3857</div></div>" +
      "<div><div class='tiny faint'>长度 / 面积单位</div><div class='mono strong'>meter / ㎡</div></div>" +
      "<div class='spacer'></div>" +
      "<div class='tiny muted' style='max-width:420px;line-height:1.65'>" +
      "真实链路会从 <span class='mono'>information_schema</span> 现场读取表、字段并采样真实取值；此页面在未安装 psycopg 时展示项目内置示例。" +
      "</div></div></div>" +

      "<div class='grid' style='grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);align-items:start'>" +
      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("db") + "</span>" +
      "<div><h2>数据表与字段</h2><p class='sub'>点击表头展开/收起字段明细</p></div>" +
      "<div class='right'><span class='chip mono'>" + tables.length + " tables</span></div></div>" +
      "<div class='searchbar' style='margin-bottom:12px'>" + GIS.ui.icon("search") +
      "<input id='tableSearch' placeholder='搜索表名、字段或样例值…' value='" + esc(S.query) + "'></div>" +
      "<div id='tableList'>" + tablesHTML() + "</div></div>" +

      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("search") + "</span>" +
      "<div><h2>表结构检索演示</h2><p class='sub'>用真实 TF-IDF 余弦检索挑出相关表</p></div></div>" +
      "<div class='searchbar' style='margin-bottom:8px'>" + GIS.ui.icon("search") +
      "<input id='tableRetrievalInput' placeholder='例如：施工区内高压燃气管线长度'></div>" +
      "<button class='btn primary block' id='tableRetrievalBtn'>" + GIS.ui.icon("search") + "检索相关表</button>" +
      "<div class='retrieval-result' id='tableRetrievalResult'>" +
      (S.results ? renderResults(S.results) : "<div class='tiny muted' style='margin-top:8px'>检索后展示相关度与注入上下文。</div>") + "</div>" +
      "<div class='hr-soft'></div><div class='tiny muted' style='line-height:1.75'>top-5 命中后按最高分 × 0.4 做相对截断，低相关表不会进入上下文。</div>" +
      "<div class='hr-soft'></div><div class='tiny muted' style='margin-bottom:6px'>示例查询</div>" +
      "<div class='stack' style='gap:5px'>" + [
        "施工区 A001 内的燃气设备数量",
        "燃气管线裁剪后按压力等级汇总长度",
        "水管在施工区 A003 内的总长度",
        "缓冲区与施工区求交后的面积",
      ].map((q) => "<button class='example-item' data-kb-example='" + esc(q) + "' style='padding:7px 9px;font-size:11px'>" + esc(q) + "</button>").join("") + "</div>" +
      "</div></div>" +

      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("book") + "</span>" +
      "<div><h2>领域知识</h2><p class='sub'>业务语义与编码约定（不含题目答案），由检索决定注入哪一条</p></div></div>" +
      knowledgeHTML() + "</div>" +
      "</div>";
  }

  function bindTableHeads() {
    document.querySelectorAll("[data-table-head]").forEach((head) => {
      if (head._bound) return;
      head._bound = true;
      head.addEventListener("click", () => {
        const name = head.dataset.tableHead;
        const card = head.closest(".table-card");
        const open = !card.classList.contains("open");
        card.classList.toggle("open", open);
        S.open[name] = open;
      });
    });
  }

  function bind() {
    bindTableHeads();
    const search = document.getElementById("tableSearch");
    if (search) {
      search.addEventListener("input", U.debounce(() => {
        S.query = search.value;
        const list = document.getElementById("tableList");
        if (list) { list.innerHTML = tablesHTML(); bindTableHeads(); }
      }, 160));
    }
    const btn = document.getElementById("tableRetrievalBtn");
    const input = document.getElementById("tableRetrievalInput");
    const run = async () => {
      const q = (input ? input.value : "").trim();
      if (!q) { GIS.toast("请输入检索文本", "warn"); return; }
      if (GIS.state.mode === "static") { GIS.toast("静态预览模式无法调用检索服务", "warn"); return; }
      const box = document.getElementById("tableRetrievalResult");
      if (box) box.innerHTML = "<div class='skeleton' style='height:52px'></div>";
      try {
        const payload = await GIS.api.retrieve(q, "tables");
        S.results = payload;
        if (box) {
          box.innerHTML = renderResults(payload);
          const copy = box.querySelector("[data-copy-context]");
          if (copy) copy.addEventListener("click", () => {
            const items = payload.items || [];
            const context = ["【数据库相关表结构（按余弦相似度检索）】"].concat(items.map((t) =>
              "\n表 " + t.name + "（" + (t.note || "") + "）:\n" + (t.fields || []).map((f) => "  - " + f.name + ": " + f.note).join("\n"))).join("\n");
            GIS.ui.copy(context, "上下文已复制");
          });
        }
      } catch (err) {
        if (box) box.innerHTML = "<div class='chip err'>" + esc(err.message) + "</div>";
      }
    };
    if (btn) btn.addEventListener("click", run);
    if (input) input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
    document.querySelectorAll("[data-kb-example]").forEach((ex) => {
      ex.addEventListener("click", () => {
        if (input) input.value = ex.dataset.kbExample;
        run();
      });
    });
  }

  GIS.views.knowledge = {
    title: "知识库",
    subtitle: "PostGIS 表结构、领域知识与检索注入",
    render,
    mount: bind,
    async before() { await GIS.api.bootstrap(); },
  };
})();
