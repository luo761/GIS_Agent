/* ============================================================
   系统管理：真实能力向量重置 / 路由平局容差 / 智能体记忆空间
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;

  let memorySource = "real";

  function data() { return GIS.state.data || {}; }
  function realCap() { return data().real_capability || {}; }
  function memory() {
    return (memorySource === "demo" ? data().demo_memory : data().memory) || {};
  }
  function isStatic() { return GIS.state.mode === "static"; }

  function bytes(n) {
    const v = Number(n || 0);
    if (v < 1024) return v + " B";
    if (v < 1024 * 1024) return (v / 1024).toFixed(1) + " KB";
    return (v / 1024 / 1024).toFixed(2) + " MB";
  }

  function agentIds() {
    return Object.keys(realCap().agents || {}).sort();
  }

  function capabilityCard() {
    const cap = realCap();
    const agents = cap.agents || {};
    const dims = cap.dimensions || data().dimensions || [];
    const labels = data().labels || {};
    const glossary = data().glossary || {};
    const initial = Number(cap.initial_capability != null ? cap.initial_capability : 0.5);
    const ids = Object.keys(agents).sort();
    let best = 0;
    ids.forEach((id) => {
      dims.forEach((dim) => {
        const value = Number((agents[id].capabilities || {})[dim] || 0);
        if (value > initial + 1e-9) best += 1;
      });
    });
    const head = "<tr><th>智能体</th>" + dims.map((dim) =>
      "<th title='" + esc(glossary[dim] || "") + "'>" + esc(labels[dim] || dim) + "</th>").join("") +
      "<th>尝试</th></tr>";
    const rows = ids.length ? ids.map((id) => {
      const stats = agents[id].stats || {};
      return "<tr><td><div class='agent-cell'><span class='dot' style='background:" +
        GIS.meta.agentColor(id) + "'></span>智能体 " + esc(agents[id].name || id) + "</div></td>" +
        dims.map((dim) => {
          const value = Number((agents[id].capabilities || {})[dim] || 0);
          const hot = value > initial + 1e-9;
          return "<td class='v " + (hot ? "hot" : "") + "'>" + value.toFixed(4) + "</td>";
        }).join("") +
        "<td class='v'>" + (stats.attempts || 0) + "</td></tr>";
    }).join("") : "<tr><td colspan='" + (dims.length + 2) + "' class='v'>暂无能力数据</td></tr>";

    return "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("radar") + "</span>" +
      "<div><h2>能力向量表（项目真实）</h2><p class='sub'>直接读写 <span class='mono'>" +
      esc(data().admin && data().admin.capability_path || "data/agent_capabilities.json") +
      "</span>；红色表示当前值高于初始值</p></div>" +
      "<div class='right'><span class='chip " + (best ? "warn" : "ok") + "'>" +
      (best ? best + " 个维度已进化" : "全部均衡") + "</span></div></div>" +

      "<div class='kv-grid' style='margin-bottom:12px'>" +
      "<div class='kv'><dt>智能体</dt><dd class='mono'>" + ids.length + " 个</dd></div>" +
      "<div class='kv'><dt>能力维度</dt><dd class='mono'>" + dims.length + " 个</dd></div>" +
      "<div class='kv'><dt>初始目标值</dt><dd class='mono'>" + initial.toFixed(3) + "</dd></div>" +
      "<div class='kv'><dt>进化事件</dt><dd class='mono'>" + (cap.history || []).length + " 次</dd></div>" +
      "</div>" +

      "<div class='reset-preview' style='margin-top:0;max-height:300px'><table class='reset-table'><thead>" +
      head + "</thead><tbody>" + rows + "</tbody></table></div>" +

      "<div class='reset-note' style='margin-top:12px'>重置会把全部智能体的所有能力维度写回 <b class='mono'>" +
      initial.toFixed(3) + "</b>，并同时清空进化历史、执行统计与工具偏好。该操作直接修改项目文件，<b>不可撤销</b>。</div>" +
      "<div class='row' style='margin-top:12px;justify-content:flex-end'>" +
      "<button class='btn danger' id='adminResetCap'>" + GIS.ui.icon("reset") + "重置全部能力为 " + initial.toFixed(3) + "</button></div></div>";
  }

  function routingCard() {
    const routing = data().routing || {};
    const epsilon = Number(routing.tie_epsilon != null ? routing.tie_epsilon : 0.1);
    return "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("flow") + "</span>" +
      "<div><h2>路由平局容差 tie_epsilon</h2><p class='sub'>配置文件 <span class='mono'>" +
      esc(data().admin && data().admin.routing_path || "config/agents_capability.yaml") + "</span></p></div>" +
      "<div class='right'><span class='chip mono'>routing.tie_epsilon</span></div></div>" +

      "<div class='grid' style='grid-template-columns:minmax(0,1fr) minmax(240px,.7fr);align-items:start;gap:16px'>" +
      "<div><div class='row wrap' style='gap:12px;align-items:flex-end'>" +
      "<div class='field' style='width:190px'><label>当前生效值</label>" +
      "<input id='adminTieInput' type='number' min='0' max='1' step='0.01' value='" + epsilon + "'></div>" +
      "<button class='btn primary' id='adminTieSave'>" + GIS.ui.icon("check") + "保存参数</button>" +
      "<button class='btn ghost' id='adminTieReset'>恢复 0.10</button></div>" +
      "<div class='tiny muted' style='margin-top:9px;line-height:1.75'>取值范围 0–1。保存后立即重新读取 YAML，后续能力路由、并列随机抽取和演示运行都会使用新值；已写入的进化历史不回溯。</div></div>" +
      "<div class='kv'><dt>判定规则</dt><dd class='small' style='font-weight:400;line-height:1.8'>" +
      "最高分与其他智能体得分相差 ≤ <b class='mono'>" + epsilon.toFixed(3) + "</b> 时视为能力并列，在并列组内随机抽取；" +
      "容差越大，平局越容易发生。</dd></div></div></div>" +
      "</div>";
  }

  function outcomeLabel(outcome) {
    return { success: "成功", failed: "失败", uncertain: "已确认存疑" }[outcome] || outcome || "未知";
  }

  function recordRows(agentId, item) {
    const records = item.records || [];
    if (!records.length) return "<div class='tiny muted' style='padding:7px 0'>暂无长期记录。</div>";
    return records.map((record) => {
      const rid = record.id || record._file || "";
      return "<div class='admin-item'>" +
        "<div class='admin-item-main'>" +
        "<div class='admin-item-title'>" + esc(U.truncate(record.question_feat || "（无问题文本）", 150)) + "</div>" +
        "<div class='tiny faint mono'>" + esc(rid) + " · " + esc(record.ts || record._mtime || "") +
        " · " + esc(outcomeLabel(record.outcome)) + "</div></div>" +
        "<button class='btn sm danger' data-del-record data-agent='" + esc(agentId) +
        "' data-record-id='" + esc(rid) + "'>" + GIS.ui.icon("trash") + "删除</button></div>";
    }).join("");
  }

  function cacheRows(agentId, item) {
    const cache = item.cache || [];
    if (!cache.length) return "<div class='tiny muted' style='padding:7px 0'>暂无短期缓存。</div>";
    return cache.map((entry, index) => {
      const question = entry.question || entry.step_question || "（无步骤文本）";
      const rawNote = entry.note || entry.lesson || "";
      const note = rawNote === "unjudged" ? "未判定" : rawNote;
      return "<div class='admin-item'>" +
        "<span class='cache-idx'>" + (index + 1) + "</span>" +
        "<div class='admin-item-main'>" +
        "<div class='admin-item-title'>" + esc(U.truncate(question, 130)) + "</div>" +
        "<div class='tiny faint mono'>[" + index + "] · " + esc(entry.ts || "") +
        (note ? " · " + esc(note) : "") + "</div></div>" +
        "<button class='btn sm danger' data-del-cache data-agent='" + esc(agentId) +
        "' data-index='" + index + "'>" + GIS.ui.icon("trash") + "删除</button></div>";
    }).join("");
  }

  function memoryCard() {
    const mem = memory();
    const ids = Object.keys(mem).sort();
    const cards = ids.map((id) => {
      const item = mem[id] || {};
      const records = item.records_total || 0;
      const cache = item.cache_total || 0;
      const root = item.root || ("data/memory/" + id);
      return "<div class='admin-mem-card'>" +
        "<div class='row between wrap' style='gap:8px'>" +
        "<div class='agent-cell'><span class='dot' style='background:" + GIS.meta.agentColor(id) + "'></span>" +
        "<b>智能体 " + esc(item.name || id) + "</b><span class='chip mono'>" + esc(root) + "</span></div>" +
        "<div class='chip-row'>" +
        "<span class='chip " + (records ? "brand" : "muted") + "'>长期 " + records + " 条 · " + bytes(item.records_bytes) + "</span>" +
        "<span class='chip " + (cache ? "brand" : "muted") + "'>缓存 " + cache + " 条 · " + bytes(item.cache_bytes) + "</span>" +
        "</div></div>" +

        "<div class='grid grid-2' style='gap:10px;margin-top:11px'>" +
        "<div class='kv'><dt>长期任务记录</dt><dd class='small'>" +
        "目录 <span class='mono'>record/</span>" +
        "<div class='tiny faint' style='margin-top:3px'>上限 " + (item.record_max != null ? item.record_max : 10) + " 条，FIFO 淘汰</div></dd>" +
        "<div class='row wrap' style='gap:6px;margin-top:8px'>" +
        "<button class='btn sm' data-mem-action data-agent='" + esc(id) + "' data-scope='records' data-mode='clear'>清空记录</button>" +
        "<button class='btn sm danger' data-mem-action data-agent='" + esc(id) + "' data-scope='records' data-mode='delete'>删除记录目录</button>" +
        "</div></div>" +
        "<div class='kv'><dt>短期步骤缓存</dt><dd class='small'>" +
        "文件 <span class='mono'>cache.json</span>" +
        "<div class='tiny faint' style='margin-top:3px'>上限 " + (item.cache_max != null ? item.cache_max : 5) + " 条，注入最近 " +
        (item.cache_top_k != null ? item.cache_top_k : 3) + " 条</div></dd>" +
        "<div class='row wrap' style='gap:6px;margin-top:8px'>" +
        "<button class='btn sm' data-mem-action data-agent='" + esc(id) + "' data-scope='cache' data-mode='clear'>清空缓存</button>" +
        "<button class='btn sm danger' data-mem-action data-agent='" + esc(id) + "' data-scope='cache' data-mode='delete'>删除缓存文件</button>" +
        "</div></div></div>" +

        "<details class='admin-mem-details'>" +
        "<summary>单条长期记录 <span class='chip mono'>" + records + " 条</span></summary>" +
        "<div class='admin-item-list'>" + recordRows(id, item) + "</div></details>" +
        "<details class='admin-mem-details'>" +
        "<summary>单条短期缓存 <span class='chip mono'>" + cache + " 条</span></summary>" +
        "<div class='admin-item-list'>" + cacheRows(id, item) + "</div></details>" +

        "<div class='row' style='margin-top:10px;justify-content:flex-end'>" +
        "<button class='btn sm danger' data-mem-action data-agent='" + esc(id) + "' data-scope='all' data-mode='clear'>" +
        GIS.ui.icon("reset") + "重置该智能体全部记忆</button></div>" +
        "</div>";
    }).join("");

    return "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("memory") + "</span>" +
      "<div><h2>智能体记忆空间</h2><p class='sub'>长期记录与短期缓存分别管理；清空保留容器，删除会移除目录/文件本身</p></div>" +
      "<div class='right wrap' style='justify-content:flex-end'>" +
      "<div class='segmented' id='adminMemSource'>" +
      "<button data-admin-mem-source='real' class='" + (memorySource === "real" ? "active" : "") + "'>真实记忆</button>" +
      "<button data-admin-mem-source='demo' class='" + (memorySource === "demo" ? "active" : "") + "'>演示记忆</button></div>" +
      "<span class='chip mono'>" + (memorySource === "real" ? "data/memory" : "web/data/memory") + "</span>" +
      "</div></div>" +
      "<div class='stack-lg'>" + (cards || GIS.ui.empty("没有可管理的智能体", "请检查 config/agents_capability.yaml。", "memory")) + "</div>" +
      "</div>";
  }

  function render() {
    return "<div class='stack-lg' id='adminView'>" +
      "<div class='card' style='padding:13px 18px'><div class='row between wrap'>" +
      "<div><b>系统管理</b><span class='small muted' style='margin-left:8px'>直接管理项目运行期的能力、路由与记忆文件</span></div>" +
      "<div class='row' style='gap:6px'>" +
      "<span class='chip warn'>危险操作需二次确认</span>" +
      "<button class='btn sm ghost' id='adminRefresh'>" + GIS.ui.icon("refresh") + "重新读取</button></div>" +
      "</div></div>" +
      capabilityCard() + routingCard() + memoryCard() +
      "</div>";
  }

  async function reloadAll() {
    await GIS.api.bootstrap(true);
    try {
      const admin = await GIS.api.admin();
      GIS.state.data.real_capability = admin.capability;
      GIS.state.data.routing = admin.routing;
      GIS.state.data.memory = admin.memory;
      GIS.state.data.demo_memory = admin.demo_memory || admin.memory;
      GIS.state.data.admin = admin;
    } catch (e) { /* 管理页仍可使用已刷新的 bootstrap 数据 */ }
    const mem = GIS.state.data.memory || {};
    const demoMem = GIS.state.data.demo_memory || {};
    GIS.state.data.counts = GIS.state.data.counts || {};
    GIS.state.data.counts.memory_records = Object.keys(mem).reduce((s, k) => s + ((mem[k].records || []).length), 0);
    GIS.state.data.counts.memory_cache = Object.keys(mem).reduce((s, k) => s + ((mem[k].cache || []).length), 0);
    GIS.state.data.counts.demo_memory_records = Object.keys(demoMem).reduce((s, k) => s + ((demoMem[k].records || []).length), 0);
    GIS.state.data.counts.demo_memory_cache = Object.keys(demoMem).reduce((s, k) => s + ((demoMem[k].cache || []).length), 0);
    if (GIS.refreshNav) GIS.refreshNav();
    GIS.refreshView();
  }

  async function resetCapability(btn) {
    if (isStatic()) { GIS.toast("静态预览模式无法修改项目文件", "warn"); return; }
    const initial = Number(realCap().initial_capability != null ? realCap().initial_capability : 0.5);
    const ok = await GIS.confirm(
      "重置项目真实能力向量",
      "将把全部智能体的所有能力维度写回 " + initial.toFixed(3) + "，并清空进化历史、执行统计与工具偏好。\n" +
      "目标文件：data/agent_capabilities.json。该操作不可撤销。",
      "确认重置"
    );
    if (!ok) return;
    btn.disabled = true;
    const old = btn.innerHTML;
    btn.textContent = "重置中…";
    try {
      const payload = await GIS.api.resetRealCapability();
      GIS.toast("已将 " + (payload.agent_count || 0) + " 个智能体的能力向量重置为 " +
        Number(payload.initial_capability || initial).toFixed(3), "ok", "能力向量已重置");
      await reloadAll();
    } catch (err) {
      GIS.toast(err.message || "重置失败", "err", "重置失败");
      btn.disabled = false;
      btn.innerHTML = old;
    }
  }

  async function saveTie(input, btn) {
    if (isStatic()) { GIS.toast("静态预览模式无法修改项目文件", "warn"); return; }
    if (!input) return;
    const value = Number(input.value);
    if (!isFinite(value) || value < 0 || value > 1) {
      GIS.toast("tie_epsilon 必须是 0 到 1 之间的数字", "warn");
      input.focus();
      return;
    }
    btn.disabled = true;
    btn.textContent = "保存中…";
    try {
      const payload = await GIS.api.updateTieEpsilon(value);
      GIS.state.data.routing = payload.routing;
      GIS.toast("tie_epsilon 已更新为 " + Number(payload.tie_epsilon).toFixed(3), "ok", "路由参数已保存");
      await reloadAll();
    } catch (err) {
      GIS.toast(err.message || "保存失败", "err", "保存失败");
      btn.disabled = false;
      btn.innerHTML = GIS.ui.icon("check") + "保存参数";
    }
  }

  function actionText(scope, mode) {
    const scopeLabel = { records: "长期记录", cache: "短期缓存", all: "全部记忆" }[scope] || scope;
    const verb = mode === "delete" ? "删除" : "清空";
    return { title: verb + "智能体" + scopeLabel, verb, scopeLabel };
  }

  async function memoryAction(btn) {
    if (isStatic()) { GIS.toast("静态预览模式无法修改项目文件", "warn"); return; }
    const agentId = btn.dataset.agent;
    const scope = btn.dataset.scope;
    const mode = btn.dataset.mode;
    const info = actionText(scope, mode);
    const name = GIS.meta.agentName(agentId);
    const extra = mode === "delete"
      ? "会删除对应的目录/文件本身，项目下次写入时会重新创建。"
      : "只清空内容，保留目录/文件容器。";
    const ok = await GIS.confirm(
      info.title,
      "智能体 " + name + "：" + info.verb + info.scopeLabel + "。\n" + extra + "该操作不可撤销。",
      "确认" + info.verb
    );
    if (!ok) return;
    const buttons = document.querySelectorAll("[data-mem-action]");
    buttons.forEach((b) => { b.disabled = true; });
    try {
      const payload = await GIS.api.memoryAction(agentId, scope, mode, memorySource);
      const parts = [];
      if (scope === "records" || scope === "all") parts.push((payload.removed_records || 0) + " 条记录");
      if (scope === "cache" || scope === "all") parts.push((payload.removed_cache_entries || 0) + " 条缓存");
      GIS.toast("智能体 " + name + "：" + info.verb + " " + (parts.join(" · ") || "0 条") +
        "，释放 " + bytes(payload.freed_bytes), "ok", info.title + "完成");
      await reloadAll();
    } catch (err) {
      GIS.toast(err.message || "操作失败", "err", "操作失败");
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  async function deleteRecord(btn) {
    if (isStatic()) { GIS.toast("静态预览模式无法修改项目文件", "warn"); return; }
    const agentId = btn.dataset.agent;
    const recordId = btn.dataset.recordId;
    const name = GIS.meta.agentName(agentId);
    const ok = await GIS.confirm(
      "删除单条长期记录",
      "智能体 " + name + "：将永久删除记录 " + recordId + "。该操作不可撤销。",
      "确认删除"
    );
    if (!ok) return;
    btn.disabled = true;
    try {
      const payload = await GIS.api.deleteMemoryRecord(agentId, recordId, memorySource);
      GIS.toast("已删除记录 " + recordId + "，释放 " + bytes(payload.freed_bytes), "ok", "单条记录已删除");
      await reloadAll();
    } catch (err) {
      GIS.toast(err.message || "删除失败", "err", "删除失败");
      btn.disabled = false;
    }
  }

  async function deleteCache(btn) {
    if (isStatic()) { GIS.toast("静态预览模式无法修改项目文件", "warn"); return; }
    const agentId = btn.dataset.agent;
    const index = Number(btn.dataset.index);
    const name = GIS.meta.agentName(agentId);
    const ok = await GIS.confirm(
      "删除单条短期缓存",
      "智能体 " + name + "：将永久删除缓存条目 [" + index + "]。该操作不可撤销。",
      "确认删除"
    );
    if (!ok) return;
    btn.disabled = true;
    try {
      const payload = await GIS.api.deleteMemoryCache(agentId, index, memorySource);
      GIS.toast("已删除缓存条目 [" + index + "]，剩余 " + (payload.cache_total || 0) + " 条", "ok", "单条缓存已删除");
      await reloadAll();
    } catch (err) {
      GIS.toast(err.message || "删除失败", "err", "删除失败");
      btn.disabled = false;
    }
  }

  function mount() {
    const reset = document.getElementById("adminResetCap");
    if (reset) reset.addEventListener("click", () => resetCapability(reset));

    const input = document.getElementById("adminTieInput");
    const save = document.getElementById("adminTieSave");
    if (save) save.addEventListener("click", () => saveTie(input, save));
    const resetTie = document.getElementById("adminTieReset");
    if (resetTie) resetTie.addEventListener("click", () => {
      if (input) input.value = "0.1";
      if (save) saveTie(input, save);
    });
    if (input) input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && save) saveTie(input, save);
    });

    document.querySelectorAll("[data-mem-action]").forEach((btn) => {
      btn.addEventListener("click", () => memoryAction(btn));
    });
    document.querySelectorAll("[data-del-record]").forEach((btn) => {
      btn.addEventListener("click", () => deleteRecord(btn));
    });
    document.querySelectorAll("[data-del-cache]").forEach((btn) => {
      btn.addEventListener("click", () => deleteCache(btn));
    });
    document.querySelectorAll("[data-admin-mem-source]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const next = btn.dataset.adminMemSource === "demo" ? "demo" : "real";
        if (next === memorySource) return;
        memorySource = next;
        GIS.toast(next === "demo" ? "已切换到演示记忆 web/data/memory" : "已切换到真实记忆 data/memory", "ok");
        await reloadAll();
      });
    });

    const refresh = document.getElementById("adminRefresh");
    if (refresh) refresh.addEventListener("click", async () => {
      refresh.disabled = true;
      try {
        await reloadAll();
        GIS.toast("已重新读取项目文件", "ok");
      } catch (err) {
        GIS.toast(err.message || "刷新失败", "err");
      } finally {
        refresh.disabled = false;
      }
    });
  }

  GIS.views.admin = {
    title: "系统管理",
    subtitle: "能力向量 · 路由容差 · 记忆空间",
    render,
    mount,
    async before() {
      await GIS.api.bootstrap();
      if (isStatic()) return;
      try {
        const admin = await GIS.api.admin();
        GIS.state.data.admin = admin;
        GIS.state.data.real_capability = admin.capability;
        GIS.state.data.routing = admin.routing;
        GIS.state.data.memory = admin.memory;
        GIS.state.data.demo_memory = admin.demo_memory || admin.memory;
      } catch (e) { /* 回退到 bootstrap 数据 */ }
    },
  };
})();
