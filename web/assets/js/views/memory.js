/* ============================================================
   记忆库：智能体专属记忆（长期记录 + 短期缓存）+ 共享经验池
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;

  const S = {
    tab: "agent_02",
    search: "",
    retrieval: null,
    retrievalLoading: false,
    query: "",
  };

  function memory() { return (GIS.state.data || {}).memory || {}; }
  function agents() { return GIS.meta.agents(); }
  function recordsOf(agentId) { return ((memory()[agentId] || {}).records) || []; }
  function cacheOf(agentId) { return ((memory()[agentId] || {}).cache) || []; }

  function agentStatsHTML(agentId) {
    const stats = GIS.meta.agentStats(agentId);
    const recs = recordsOf(agentId);
    const cache = cacheOf(agentId);
    const agent = (GIS.state.data.capability.agents || {})[agentId] || {};
    const prefs = agent.preferred_tools || [];
    const prefText = prefs.length
      ? prefs.slice(0, 2).map((t) => "<span class='op'>" + esc(t) + "</span>").join("") +
        (prefs.length > 2 ? "<span class='chip muted'>+" + (prefs.length - 2) + "</span>" : "")
      : "<span class='muted small'>暂无</span>";
    return "<div class='grid grid-4' style='gap:12px'>" +
      "<div class='kv'><dt>长期任务记录</dt><dd class='mono'>" + recs.length + " 条</dd><div class='tiny faint'>容量上限 10 条</div></div>" +
      "<div class='kv'><dt>短期步骤缓存</dt><dd class='mono'>" + cache.length + " 条</dd><div class='tiny faint'>注入最近 3 条</div></div>" +
      "<div class='kv'><dt>能力统计（演示）</dt><dd class='mono'>" + (stats.attempts || 0) + " 尝试 · " + (stats.successes || 0) + " 成功</dd></div>" +
      "<div class='kv'><dt>工具偏好</dt><dd>" + prefText + "</dd></div>" +
      "</div>";
  }

  function planSummary(plan) {
    if (!plan) return "—";
    if (Array.isArray(plan.nodes)) return plan.nodes.map((n) => n.action || n.id).join(" → ");
    const parts = [];
    Object.keys(plan).forEach((k) => {
      const sub = plan[k];
      if (sub && Array.isArray(sub.nodes)) parts.push(k + ": " + sub.nodes.map((n) => n.action || n.id).join(" → "));
    });
    return parts.join("；") || "—";
  }

  function recordHTML(record) {
    const outcome = record.outcome === "success" ? "ok" : (record.outcome === "failed" ? "err" : "warn");
    const label = { success: "成功", failed: "失败", uncertain: "已确认存疑" }[record.outcome] || record.outcome || "未知";
    const planText = planSummary(record.plan);
    return "<div class='record-card' data-record='" + esc(record.id) + "'>" +
      "<div class='record-top'><span class='chip " + outcome + "'>" + esc(label) + "</span>" +
      "<span class='chip mono'>" + esc(record.id) + "</span>" +
      "<span class='record-meta' style='margin-left:auto'>" + esc(record.ts || record._mtime || "") + "</span></div>" +
      "<div class='record-q'>" + esc(U.truncate(record.question_feat || "", 180)) + "</div>" +
      (record.result_summary ? "<div class='tiny muted' style='overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>结果：" + esc(U.truncate(record.result_summary, 140)) + "</div>" : "") +
      (record.error ? "<div class='chip err' style='white-space:normal'>教训：" + esc(U.truncate(record.error, 160)) + "</div>" : "") +
      (planText !== "—" ? "<div class='record-plan'>" + esc(U.truncate(planText, 200)) + "</div>" : "") +
      "</div>";
  }

  function cacheQuestion(item) {
    return String(item.question || item.step_question || "").trim();
  }

  function cacheGroups(cache) {
    const groups = [];
    (cache || []).forEach((item) => {
      const question = cacheQuestion(item);
      const last = groups[groups.length - 1];
      if (last && last.question === question) last.items.push(item);
      else groups.push({ question, items: [item] });
    });
    return groups;
  }

  function noteInfo(item) {
    const note = String(item.note || "");
    const lower = note.toLowerCase();
    if (lower.includes("planned") || note.includes("计划")) {
      return { label: "规划", kind: "plan" };
    }
    if (lower.includes("executed") || note.includes("执行")) {
      const failed = item.outcome === "failed" || note.includes("失败");
      return { label: failed ? "执行 · 失败" : (item.outcome === "success" ? "执行 · 成功" : "执行"), kind: "exec" + (failed ? " failed" : "") };
    }
    return { label: note || item.lesson || "步骤", kind: "" };
  }

  function planNodeCount(plan) {
    if (!plan) return null;
    if (Array.isArray(plan.nodes)) return plan.nodes.length;
    let count = 0;
    Object.keys(plan).forEach((k) => {
      const sub = plan[k];
      if (sub && Array.isArray(sub.nodes)) count += sub.nodes.length;
    });
    return count || null;
  }

  function timeOnly(ts) {
    const m = String(ts || "").match(/(\d{2}:\d{2}:\d{2})/);
    return m ? m[1] : String(ts || "");
  }

  function cacheHTML(group, i) {
    const items = group.items || [];
    const planItem = items.find((it) => it.plan);
    const execItem = items.slice().reverse().find((it) =>
      it.outcome != null || String(it.note || "").toLowerCase().includes("executed") || String(it.note || "").includes("执行"));
    const stages = items.map((it) => {
      const info = noteInfo(it);
      return "<span class='cache-stage " + info.kind + "'>" + esc(info.label) +
        " <b>" + esc(timeOnly(it.ts)) + "</b></span>";
    }).join("<span class='cache-arrow'>→</span>");
    const planText = planItem ? planSummary(planItem.plan) : "—";
    const nodes = planItem ? planNodeCount(planItem.plan) : null;
    const outcomeChip = execItem && execItem.outcome
      ? "<span class='chip " + (execItem.outcome === "success" ? "ok" : "err") + "'>" +
        (execItem.outcome === "success" ? "成功" : "失败") + "</span>"
      : "";
    return "<div class='cache-item'><span class='cache-idx'>" + (i + 1) + "</span><div style='min-width:0;flex:1'>" +
      "<div class='cache-q'>" + esc(U.truncate(group.question || "（无问题文本）", 130)) + "</div>" +
      "<div class='cache-stages'>" + stages + outcomeChip + "</div>" +
      (planText && planText !== "—"
        ? "<div class='tiny faint' style='margin-top:3px'>计划" + (nodes ? "（" + nodes + " 个节点）" : "") +
          "：" + esc(U.truncate(planText, 110)) + "</div>"
        : "") +
      (execItem && execItem.error
        ? "<div class='tiny' style='color:var(--err);margin-top:2px'>教训：" + esc(U.truncate(execItem.error, 100)) + "</div>"
        : "") +
      "</div></div>";
  }

  function retrievalHTML(kind, agentId) {
    if (S.retrievalLoading) return "<div class='skeleton' style='height:54px'></div>";
    const payload = S.retrieval;
    if (!payload) return "<div class='tiny muted'>输入一个任务描述，看看该智能体自己的记忆里有没有相似案例。检索走余弦相似度。</div>";
    const items = payload.items || [];
    if (!items.length) return "<div class='tiny muted'>没有相似度大于 0 的记忆命中。</div>";
    const max = Math.max.apply(null, items.map((i) => Number(i.score || 0))) || 1;
    return "<div style='display:flex;flex-direction:column;gap:6px'>" + items.map((item) =>
      "<div class='hit'><div class='hit-main'><div class='hit-title'>" + esc(U.truncate(item.question_feat || "", 84)) +
      "</div><div class='hit-sub'>" + esc(item.ts || "") + " · " + esc(item.outcome || "") + "</div></div>" +
      "<div class='score'>" + GIS.ui.scoreBar(Number(item.score || 0) / max, 1) + "<b>" + Number(item.score || 0).toFixed(3) + "</b></div></div>").join("") + "</div>";
  }

  function agentBody(agentId) {
    const recs = recordsOf(agentId);
    const cache = cacheOf(agentId);
    const groups = cacheGroups(cache);
    const q = S.search.trim().toLowerCase();
    const list = q ? recs.filter((r) => ((r.question_feat || "") + " " + (r.result_summary || "") + " " + (r.error || "")).toLowerCase().includes(q)) : recs;
    return "<div class='stack-lg'>" + agentStatsHTML(agentId) +
      "<div class='grid' style='grid-template-columns:minmax(0,1.25fr) minmax(300px,.75fr);align-items:start'>" +
      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("memory") + "</span>" +
      "<div><h2>长期任务记录</h2><p class='sub'>该智能体完成过的完整案例；容量上限 10 条，FIFO 淘汰</p></div>" +
      "<div class='right'><span class='chip mono'>" + recs.length + "</span></div></div>" +
      "<div class='searchbar' style='margin-bottom:10px'>" + GIS.ui.icon("search") +
      "<input id='memSearch' placeholder='搜索本人完成过的任务…' value='" + esc(S.search) + "'></div>" +
      "<div class='stack' style='max-height:620px;overflow:auto;padding-right:4px'>" +
      (list.length ? list.map(recordHTML).join("") : GIS.ui.empty(q ? "没有匹配的记录" : "暂无长期记录", q ? "试试其他关键词。" : "该智能体还没有完成过结果明确的任务；初始状态下四个智能体完全相同。", "memory")) +
      "</div></div>" +

      "<div class='stack'>" +
      "<div class='card'><div class='card-head'><div><h3>短期步骤缓存</h3><p class='sub'>同一子任务在阶段③写入「规划」、阶段④写入「执行」，按子任务合并展示</p></div>" +
      "<div class='right'><span class='chip mono'>" + cache.length + " 条 / " + groups.length + " 组</span></div></div>" +
      (groups.length
        ? "<div class='tiny faint' style='margin:-2px 0 6px;line-height:1.65'>原始缓存按「规划 → 执行」成对出现；下方把同一子任务的两条上下文合并成一张卡片，计划和执行结果都能看到。</div>" +
          groups.slice(-5).reverse().map(cacheHTML).join("")
        : "<div class='tiny muted'>暂无缓存。</div>") + "</div>" +

      "<div class='card'><div class='card-head'><div><h3>记忆检索</h3><p class='sub'>仅检索该智能体自己的记录</p></div></div>" +
      "<div class='searchbar' style='margin-bottom:8px'>" + GIS.ui.icon("search") +
      "<input id='memQuery' placeholder='例如：施工区内的燃气管线长度' value='" + esc(S.query) + "'></div>" +
      "<button class='btn sm primary block' id='memQueryBtn'>" + GIS.ui.icon("search") + "检索专属记忆</button>" +
      "<div class='retrieval-result' id='memRetrieval'>" + retrievalHTML("memory", agentId) + "</div></div>" +
      "</div></div></div>";
  }

  function experienceHTML() {
    const experience = (GIS.state.data || {}).experience || [];
    const q = S.search.trim().toLowerCase();
    const list = q ? experience.filter((e) => ((e.question_feat || "") + " " + (e.task_signature || "") + " " + (e.error_lesson || "") + " " + (e.trace || "")).toLowerCase().includes(q)) : experience;
    const success = experience.filter((e) => e.outcome === "success").length;
    return "<div class='stack-lg'>" +
      "<div class='grid grid-4' style='gap:12px'>" +
      "<div class='kv'><dt>经验条目</dt><dd class='mono'>" + experience.length + "</dd></div>" +
      "<div class='kv'><dt>成功范例</dt><dd class='mono' style='color:var(--ok)'>" + success + "</dd></div>" +
      "<div class='kv'><dt>失败教训</dt><dd class='mono' style='color:var(--err)'>" + (experience.length - success) + "</dd></div>" +
      "<div class='kv'><dt>容量上限</dt><dd class='mono'>100</dd></div></div>" +
      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("book") + "</span>" +
      "<div><h2>共享经验池</h2><p class='sub'>跨智能体共享；同类任务只更新不新增，规划前按余弦相似度检索 top-3</p></div>" +
      "<div class='right'><span class='chip mono'>" + experience.length + " 条</span></div></div>" +
      "<div class='searchbar' style='margin-bottom:12px'>" + GIS.ui.icon("search") +
      "<input id='memSearch' placeholder='搜索任务签名、问题或教训…' value='" + esc(S.search) + "'></div>" +
      (list.length ? "<div class='grid grid-2'>" + list.map((e) => {
        const ok = e.outcome === "success";
        return "<div class='record-card'><div class='record-top'><span class='chip " + (ok ? "ok" : "err") + "'>" +
          (ok ? "成功范例" : "失败教训") + "</span><span class='chip mono'>" + esc(e.task_signature || "") + "</span>" +
          "<span class='tiny faint' style='margin-left:auto'>命中 " + (e.hits || 0) + " 次 · " + esc(e.updated_at || "") + "</span></div>" +
          "<div class='record-q'>" + esc(U.truncate(e.question_feat || "", 200)) + "</div>" +
          (e.trace ? "<div class='tiny muted' style='line-height:1.7'>轨迹：" + esc(U.truncate(e.trace, 220)) + "</div>" : "") +
          (e.error_lesson ? "<div class='chip err' style='white-space:normal'>教训：" + esc(U.truncate(e.error_lesson, 180)) + "</div>" : "") +
          "<div class='record-plan'>" + esc(U.truncate(planSummary(e.plan), 200)) + "</div></div>";
      }).join("") + "</div>" : GIS.ui.empty(q ? "没有匹配的经验" : "经验池为空", "执行任务后，阶段⑤会把轨迹压缩为经验写入。", "book")) +
      "</div></div>";
  }

  function render() {
    let tabs = agents().map((a) => {
      const key = "agent_" + a.id.replace("agent_", "");
      const count = recordsOf(a.id).length;
      return "<button class='mem-tab " + (S.tab === a.id ? "active" : "") + "' data-mem-tab='" + a.id + "'>" +
        "<span class='dot' style='background:" + GIS.meta.agentColor(a.id) + "'></span>智能体 " + esc(a.name) +
        "<span class='count'>" + count + " 条</span></button>";
    }).join("");
    const experienceCount = ((GIS.state.data || {}).experience || []).length;
    tabs += "<button class='mem-tab " + (S.tab === "experience" ? "active" : "") + "' data-mem-tab='experience'>" +
      "<span class='dot' style='background:var(--purple)'></span>共享经验池<span class='count'>" + experienceCount + " 条</span></button>";

    return "<div class='stack-lg'>" +
      "<div class='card' style='padding:14px 18px'><div class='row between wrap'>" +
      "<div class='memory-agent-tabs' style='margin:0'>" + tabs + "</div>" +
      "<div class='row' style='gap:6px'>" +
      "<span class='chip muted'>数据来自 data/memory 与 data/experience.json</span>" +
      "<button class='btn sm ghost' id='memRefresh'>" + GIS.ui.icon("refresh") + "刷新</button></div>" +
      "</div></div>" +
      "<div id='memBody'>" + (S.tab === "experience" ? experienceHTML() : agentBody(S.tab)) + "</div>" +
      "</div>";
  }

  function openRecord(id, agentId) {
    const record = recordsOf(agentId).find((r) => r.id === id);
    if (!record) return;
    const plan = record.plan;
    GIS.ui.openDrawer("记忆记录 · " + id,
      "<div class='stack'>" +
      "<div class='chip-row'><span class='chip " + (record.outcome === "success" ? "ok" : "err") + "'>" + esc(record.outcome || "") + "</span>" +
      "<span class='chip mono'>" + esc(id) + "</span><span class='chip'>" + esc(record.ts || "") + "</span></div>" +
      "<div><div class='tiny muted' style='margin-bottom:4px'>任务特征</div><div class='small' style='line-height:1.8'>" + esc(record.question_feat || "") + "</div></div>" +
      (record.result_summary ? "<div><div class='tiny muted' style='margin-bottom:4px'>结果摘要</div>" + GIS.ui.codeBlock(record.result_summary, true) + "</div>" : "") +
      (record.error ? "<div><div class='tiny muted' style='margin-bottom:4px'>教训</div><div class='chip err' style='white-space:normal'>" + esc(record.error) + "</div></div>" : "") +
      "<div><div class='tiny muted' style='margin-bottom:4px'>存档的计划</div>" + GIS.ui.codeBlock(JSON.stringify(plan || {}, null, 2), false, 340) + "</div>" +
      "</div>");
  }

  function bindBody() {
    document.querySelectorAll("[data-record]").forEach((el) => {
      el.addEventListener("click", () => openRecord(el.dataset.record, S.tab));
    });
    const search = document.getElementById("memSearch");
    if (search) {
      search.addEventListener("input", U.debounce(() => {
        S.search = search.value;
        const body = document.getElementById("memBody");
        if (body) {
          body.innerHTML = S.tab === "experience" ? experienceHTML() : agentBody(S.tab);
          bindBody();
        }
      }, 170));
    }
    const query = document.getElementById("memQuery");
    const btn = document.getElementById("memQueryBtn");
    const run = async () => {
      const q = (query ? query.value : "").trim();
      if (!q) { GIS.toast("请输入检索文本", "warn"); return; }
      if (GIS.state.mode === "static") { GIS.toast("静态预览模式无法调用检索服务", "warn"); return; }
      S.retrievalLoading = true;
      const box = document.getElementById("memRetrieval");
      if (box) box.innerHTML = "<div class='skeleton' style='height:54px'></div>";
      try {
        const payload = await GIS.api.retrieve(q, "memory", S.tab);
        S.retrieval = payload;
        S.query = q;
        S.retrievalLoading = false;
        if (box) box.innerHTML = retrievalHTML("memory", S.tab);
      } catch (err) {
        S.retrievalLoading = false;
        if (box) box.innerHTML = "<div class='chip err'>" + esc(err.message) + "</div>";
      }
    };
    if (btn) btn.addEventListener("click", run);
    if (query) query.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  }

  function mount() {
    document.querySelectorAll("[data-mem-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        S.tab = btn.dataset.memTab;
        S.search = "";
        S.retrieval = null;
        document.querySelectorAll("[data-mem-tab]").forEach((b) => b.classList.toggle("active", b === btn));
        const body = document.getElementById("memBody");
        if (body) {
          body.innerHTML = S.tab === "experience" ? experienceHTML() : agentBody(S.tab);
          bindBody();
        }
      });
    });
    bindBody();
    const refresh = document.getElementById("memRefresh");
    if (refresh) {
      refresh.addEventListener("click", async () => {
        if (GIS.state.mode === "static") { GIS.toast("静态预览模式无法刷新", "warn"); return; }
        refresh.disabled = true;
        try {
          const payload = await GIS.api.memory();
          GIS.state.data.memory = payload.memory;
          GIS.state.data.experience = payload.experience;
          GIS.state.data.counts.memory_records = Object.keys(payload.memory).reduce((s, k) => s + (payload.memory[k].records || []).length, 0);
          GIS.toast("记忆与经验已刷新", "ok");
          if (window.GIS.refreshView) window.GIS.refreshView();
        } catch (err) {
          GIS.toast(err.message || "刷新失败", "err");
        } finally { refresh.disabled = false; }
      });
    }
  }

  GIS.views.memory = {
    title: "记忆库",
    subtitle: "智能体专属记忆与共享经验池",
    render,
    mount,
    async before() { await GIS.api.bootstrap(); },
  };
})();
