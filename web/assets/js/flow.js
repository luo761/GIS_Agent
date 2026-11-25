/* ============================================================
   执行流可视化：五阶段卡片 + DAG + 工具轨迹 + 播放控制
   任务台、执行流回放、评测报告共用
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;
  const F = (GIS.flow = GIS.flow || {});

  F.stages = [
    { key: "understand", no: "01", title: "任务理解", en: "Understand", desc: "领域识别 · 表结构检索 · skill 检索" },
    { key: "decompose", no: "02", title: "精炼与拆解", en: "Decompose", desc: "问题精炼 · 子任务拆分 · 能力路由" },
    { key: "plan", no: "03", title: "规划", en: "Plan", desc: "记忆/经验检索 · 计划 DAG" },
    { key: "execute", no: "04", title: "执行", en: "Execute", desc: "工具调用 · $ref 结果传递" },
    { key: "evaluate", no: "05", title: "评估与进化", en: "Evaluate", desc: "结果判定 · 能力向量更新" },
  ];

  function fmtDuration(ms) {
    if (ms == null) return "—";
    if (ms < 1000) return Math.round(ms) + " ms";
    return (ms / 1000).toFixed(1) + " s";
  }

  function agentRow(agentId) {
    const color = GIS.meta.agentColor(agentId);
    return "<span class='dot' style='background:" + color + "'></span>智能体 " + esc(GIS.meta.agentName(agentId));
  }

  function scoreList(routing) {
    if (!routing) return "";
    const scores = routing.scores || {};
    const winner = routing.agent_id;
    const rows = Object.keys(scores).sort().map((aid) => {
      const v = Number(scores[aid] || 0);
      return "<div class='routing-row " + (aid === winner ? "winner" : "") + "'>" +
        "<div class='routing-name'>" + agentRow(aid) + "</div>" +
        "<div class='routing-bar'><i style='width:" + Math.max(2, v * 100).toFixed(1) + "%'></i></div>" +
        "<div class='routing-score'>" + v.toFixed(3) + "</div></div>";
    }).join("");
    const tieNote = routing.random_pick
      ? "<div class='tiny muted' style='margin-top:6px'>" + esc((routing.tied || []).length + " 个智能体得分并列（容差 " + routing.epsilon + "），随机抽取 → 智能体 " + GIS.meta.agentName(winner)) + "</div>"
      : "<div class='tiny muted' style='margin-top:6px'>按能力向量最高分选中智能体 " + esc(GIS.meta.agentName(winner)) + "</div>";
    return "<div class='routing'>" + rows + "</div>" + tieNote;
  }

  function hitList(items, kind) {
    if (!items || !items.length) return "<div class='tiny muted'>未命中相关内容。</div>";
    return "<div class='hit-list'>" + items.slice(0, 6).map((item) => {
      const score = Number(item.score || 0);
      const title = kind === "table"
        ? "<span class='mono'>" + esc(item.name) + "</span>"
        : esc(item.name || item.task_signature || item.question_feat || "经验");
      const sub = kind === "table"
        ? esc(item.note || "")
        : (kind === "skill" ? esc(item.steps || item.desc || "") : esc(U.truncate(item.question_feat || item.error_lesson || "", 96)));
      return "<div class='hit'><div class='hit-main'><div class='hit-title'>" + title +
        "</div><div class='hit-sub'>" + sub + "</div></div>" +
        "<div class='score'>" + GIS.ui.scoreBar(score, 1) + "<b>" + score.toFixed(2) + "</b></div></div>";
    }).join("") + "</div>";
  }

  function dimChips(dims) {
    return (dims || []).map((d) =>
      "<span class='chip brand' title='" + esc(GIS.meta.dimGlossary(d)) + "'>" + esc(GIS.meta.dimLabel(d)) + "</span>").join("");
  }

  function briefChips(brief) {
    if (!brief) return "";
    const out = [];
    const push = (label, value, cls) => out.push("<span class='chip " + (cls || "") + "'>" + esc(label) + " <b class='mono'>" + esc(value) + "</b></span>");
    if (brief.feature_count != null) push("要素数", brief.feature_count);
    if (brief.distance_m != null) push("缓冲", brief.distance_m + " m");
    if (brief.radius_m != null) push("半径", brief.radius_m + " m");
    if (brief.value != null) push(brief.metric === "length" ? "长度" : "量测", Number(brief.value).toLocaleString("zh-CN") + " " + (brief.unit === "meter" ? "m" : brief.unit === "square_meter" ? "㎡" : brief.unit || ""));
    if (brief.percent != null) push("占比", brief.percent + "%", "warn");
    if (brief.geometry_type) push("几何", brief.geometry_type);
    if (brief.group_count != null) push("分组数", brief.group_count);
    if (brief.parts != null) push("部件", brief.parts);
    if (brief.groups && brief.groups.length) {
      brief.groups.slice(0, 3).forEach((g) => {
        const name = g.pressure_level || g.pipe_type || g.device_type || g.status || "组";
        push(name, g.value);
      });
      if (brief.groups.length > 3) out.push("<span class='chip muted'>+" + (brief.groups.length - 3) + " 组</span>");
    }
    return out.join("");
  }

  function traceHTML(traces) {
    if (!traces || !traces.length) return "<div class='tiny muted'>没有工具调用记录。</div>";
    return "<div class='trace'>" + traces.map((t) => {
      const ok = t.ok !== false;
      const tool = GIS.meta.tool(t.tool);
      const label = tool ? tool.label : "";
      const refs = (t.refs || []).map((r) => "<span class='ref-chip'>$ref " + esc(r) + "</span>").join(" ");
      const err = ok ? "" : "<div class='chip err' style='margin-top:5px'>" + esc(t.error || "执行失败") + "</div>";
      const args = t.args && Object.keys(t.args).length
        ? "<details class='trace-args'><summary>参数</summary>" + GIS.ui.codeBlock(JSON.stringify(t.args, null, 2), false, 160) + "</details>"
        : "";
      return "<div class='trace-item " + (ok ? "" : "failed") + "'>" +
        "<div class='trace-top'><span class='trace-step'>" + esc(t.step) + "</span>" +
        "<span class='trace-tool'>" + esc(t.tool) + "</span>" +
        (label ? "<span class='chip muted'>" + esc(label) + "</span>" : "") +
        "<span class='chip " + (ok ? "ok" : "err") + "'>" + (ok ? "成功" : "失败") + "</span>" +
        (t.elapsed_ms ? "<span class='trace-step'>" + fmtDuration(t.elapsed_ms) + "</span>" : "") +
        refs + "</div>" +
        (briefChips(t.brief) ? "<div class='trace-brief'>" + briefChips(t.brief) + "</div>" : "") +
        err + args + "</div>";
    }).join("") + "</div>";
  }

  function planHTML(item, idx) {
    const plan = item.plan || { nodes: [], edges: [] };
    const skill = item.skill;
    const mem = item.memory_hits || [];
    const exp = item.experience_hits || [];
    const memHTML = mem.length
      ? mem.map((m) => "<div class='hit'><div class='hit-main'><div class='hit-title'>" + esc(U.truncate(m.question_feat || "", 74)) +
        "</div><div class='hit-sub'>本人完成过 · " + esc(m.outcome || "") + " · " + esc(m.ts || "") + "</div></div>" +
        "<div class='score'><b>" + Number(m.score || 0).toFixed(2) + "</b></div></div>").join("")
      : "<div class='tiny muted'>该智能体暂无相似任务记忆。</div>";
    const expHTML = exp.length
      ? exp.map((m) => "<div class='hit'><div class='hit-main'><div class='hit-title'>" + esc(m.task_signature || "经验") +
        "</div><div class='hit-sub'>" + esc(U.truncate(m.question_feat || m.error_lesson || "", 90)) + "</div></div>" +
        "<div class='score'><b>" + Number(m.score || 0).toFixed(2) + "</b></div></div>").join("")
      : "<div class='tiny muted'>经验池暂无强相关经验。</div>";
    return "<div class='card' style='background:var(--panel-2);box-shadow:none'>" +
      "<div class='row between wrap' style='margin-bottom:9px'>" +
      "<div class='row'>" + GIS.ui.agentAvatar(item.agent_id, 28) +
      "<div><div class='strong small'>智能体 " + esc(item.agent_name || GIS.meta.agentName(item.agent_id)) + " · " + esc(item.subtask_id) + "</div>" +
      "<div class='tiny muted'>" + esc(item.capability_line || "") + "</div></div></div>" +
      (skill ? "<span class='chip brand' title='" + esc(skill.id || "") + "'>参考 skill： " + esc(skill.name) + " · " + Number(skill.score || 0).toFixed(2) + "</span>" : "") +
      "</div>" +
      (item.preferred_tools && item.preferred_tools.length
        ? "<div class='chip-row' style='margin-bottom:8px'><span class='tiny muted'>工具偏好</span>" +
          item.preferred_tools.map((t) => "<span class='op'>" + esc(t) + "</span>").join("") + "</div>"
        : "") +
      "<div class='dag-wrap'><canvas class='flow-dag' data-plan='" + idx + "' id='dag" + idx + "'></canvas></div>" +
      "<div class='row between' style='margin-top:6px'><div class='tiny muted'>点击节点查看参数 · 共 " + plan.nodes.length + " 个节点 / " + plan.edges.length + " 条依赖</div>" +
      "<button class='btn sm ghost' data-toggle-plan='" + idx + "'>计划 JSON</button></div>" +
      "<div class='plan-json' data-plan-json='" + idx + "' hidden>" + GIS.ui.codeBlock(JSON.stringify(plan, null, 2), false, 220) + "</div>" +
      "<div class='grid grid-2' style='margin-top:10px;gap:10px'>" +
      "<div><div class='tiny muted' style='margin-bottom:5px'>专属记忆检索</div>" + memHTML + "</div>" +
      "<div><div class='tiny muted' style='margin-bottom:5px'>共享经验检索</div>" + expHTML + "</div>" +
      "</div></div>";
  }

  F.verdict = function (stage) {
    const ev = String((stage && stage.evaluation) || "");
    if (ev === "clarification") return { key: "clarification", label: "问题不合法 · 待澄清", chip: "warn" };
    if (ev === "unknown") return { key: "unknown", label: "未判定", chip: "warn" };
    if (ev === "failed" || (stage && stage.correct === false)) return { key: "failed", label: "判定失败", chip: "err" };
    return { key: "success", label: "判定正确", chip: "ok" };
  };

  function evaluateHTML(stage, run) {
    const verdict = F.verdict(stage);
    const ok = verdict.key === "success";
    const unknown = verdict.key === "unknown";
    const clarify = verdict.key === "clarification";
    const changes = stage.changes || [];
    const changeRows = changes.map((c) => {
      const dims = c.dims || [];
      return "<div style='margin-bottom:10px'>" +
        "<div class='row between' style='margin-bottom:4px'>" + agentRow(c.agent_id) +
        "<span class='chip " + (c.outcome === "success" ? "ok" : "err") + "'>" + (c.outcome === "success" ? "成功经验" : "失败经验") + "</span></div>" +
        dims.map((d) => {
          const before = Number((c.before || {})[d] || 0);
          const after = Number((c.after || {})[d] || 0);
          const delta = Number((c.delta || {})[d] || 0);
          return "<div class='cap-delta-row'>" +
            "<div class='small muted'>" + esc(GIS.meta.dimLabel(d)) + "</div>" +
            "<div class='cap-delta-track'><div class='cap-delta-fill' style='width:" + (after * 100).toFixed(1) + "%'></div>" +
            "<div class='cap-delta-mark' style='left:" + (before * 100).toFixed(1) + "%'></div></div>" +
            "<div class='cap-delta-val'><b>" + before.toFixed(3) + " → " + after.toFixed(3) + "</b> <span class='delta " + GIS.ui.deltaClass(delta) + "'>" + U.signed(delta, 4) + "</span></div>" +
            "</div>";
        }).join("") + "</div>";
    }).join("");
    const answerLabel = clarify
      ? "需要用户补充信息 · 本次未执行"
      : unknown
        ? "最终答案 · 未判定（未提供参考答案）"
        : (ok ? "最终答案 · 判定正确"
          : ((stage.final_answer && !String(stage.final_answer).startsWith("执行失败")) ? "最终答案 · 判定未通过" : "执行失败 · 未生成答案"));
    const missing = stage.missing_info || [];
    return "<div class='stack'>" +
      "<div class='answer-box " + (clarify ? "unknown" : (unknown ? "unknown" : (ok ? "" : "fail"))) + "'>" +
      "<div class='ans-label'>" + answerLabel + "</div>" +
      "<pre>" + esc(stage.final_answer || "—") + "</pre></div>" +
      "<div class='kv-grid'>" +
      "<div class='kv'><dt>评估结论</dt><dd>" + esc(verdict.label) + "</dd></div>" +
      "<div class='kv'><dt>判定依据</dt><dd style='font-weight:500;font-size:11.5px'>" + esc(stage.reason || "—") + "</dd></div>" +
      "<div class='kv'><dt>结果类型</dt><dd>" + esc(stage.answer_kind || "—") + "</dd></div>" +
      "<div class='kv'><dt>能力更新</dt><dd>" + (clarify || unknown ? "无（未执行/未判定）" : changes.length + " 个智能体") + "</dd></div>" +
      "</div>" +
      (clarify
        ? "<div class='chip warn' style='white-space:normal;line-height:1.7'>问题被判定为「问题不合法」：本次没有拆解、规划、工具调用或数据库操作，能力向量保持不变。" +
          (missing.length ? " 需要补充：" + esc(missing.map((m) => m.name).join("、")) + "。" : "") + "</div>"
        : "") +
      (unknown
        ? "<div class='chip warn' style='white-space:normal;line-height:1.7'>未知结果：未提供参考答案，本次不写入成功/失败经验，能力向量保持不变。如需演示进化，可在判定方式中选择「判成功 / 判失败」，或填写参考答案。</div>"
        : "") +
      (changeRows ? "<div><div class='tiny muted' style='margin-bottom:7px'>能力向量变化（实线为更新后，竖线为更新前）</div><div class='cap-delta'>" + changeRows + "</div></div>" : "") +
      (changes.some((c) => c.note) ? "<div class='chip warn' style='white-space:normal;line-height:1.6'>" + esc(changes.filter((c) => c.note).map((c) => c.note).join("；")) + "</div>" : "") +
      "<div class='row'><a class='btn sm ghost' href='#/capability'>在能力进化中查看 <svg><use href='#i-arrow'></use></svg></a>" +
      "<button class='btn sm ghost' data-copy='" + esc(run ? run.run_id : "") + "'>复制运行 ID</button></div>" +
      "</div>";
  }

  F.render = function (flow, options) {
    const opt = options || {};
    const run = opt.run || null;
    const u = flow.understand || {};
    const dec = flow.decompose || {};
    const plan = flow.plan || {};
    const exec = flow.execute || {};
    const ev = flow.evaluate || {};

    const validity = u.validity || {};
    const permission = u.permission || {};
    const understandBody = "<div class='stack'>" +
      "<div class='kv-grid'>" +
      "<div class='kv'><dt>业务领域</dt><dd>" + esc(u.domain_label || u.domain || "—") + "</dd></div>" +
      "<div class='kv'><dt>任务类型</dt><dd>" + esc(u.task_type || "—") + "</dd></div>" +
      "<div class='kv'><dt>相关表</dt><dd>" + ((u.tables || []).length) + " 张</dd></div>" +
      "<div class='kv'><dt>相关 skill</dt><dd>" + ((u.skills || []).length) + " 个</dd></div>" +
      "</div>" +
      "<div class='kv-grid'>" +
      "<div class='kv'><dt>合法性判定</dt><dd>" +
      (u.is_valid === false
        ? "<span class='chip err'>问题不合法</span>"
        : "<span class='chip ok'>合法</span>") +
      " <span class='tiny muted'>来源 " + esc(validity.source || "rule") + "</span></dd></div>" +
      "<div class='kv'><dt>用户类别</dt><dd>" +
      esc(permission.role_name || "—") +
      (permission.role ? " <span class='mono tiny'>" + esc(permission.role) + "</span>" : "") + "</dd></div>" +
      "<div class='kv'><dt>可查询表</dt><dd>" + ((permission.allowed_tables || []).length) + " 张</dd></div>" +
      "<div class='kv'><dt>越权拦截</dt><dd>" + ((run && (run.permission_denials || []).length) || 0) + " 次</dd></div>" +
      "</div>" +
      (validity.is_valid === false
        ? "<div class='chip err' style='white-space:normal;line-height:1.7'>判定原因：" +
          esc((validity.reasons || []).join("；") || "信息不足") +
          (validity.missing_info && validity.missing_info.length
            ? " ｜ 缺少：" + esc(validity.missing_info.map((m) => m.name).join("、"))
            : "") + "</div>"
        : "") +
      "<div><div class='tiny muted' style='margin-bottom:4px'>专业形式精炼</div><div class='small'>" + esc(u.refined_question || "—") + "</div></div>" +
      "<div class='grid grid-2' style='gap:12px'>" +
      "<div><div class='tiny muted' style='margin-bottom:5px'>表结构检索（余弦相似度）</div>" + hitList(u.tables, "table") + "</div>" +
      "<div><div class='tiny muted' style='margin-bottom:5px'>任务级 skill 检索</div>" + hitList(u.skills, "skill") + "</div>" +
      "</div>" +
      (u.knowledge ? "<div><div class='tiny muted' style='margin-bottom:4px'>领域知识注入</div><div class='small' style='color:var(--ink-2)'>" + esc(u.knowledge) + "</div></div>" : "") +
      (u.context ? "<details><summary class='tiny muted' style='cursor:pointer'>查看注入上下文明细</summary>" + GIS.ui.codeBlock(u.context, true, 220) + "</details>" : "") +
      "</div>";

    const subCards = (dec.subtasks || []).map((s) =>
      "<div class='card' style='background:var(--panel-2);box-shadow:none'>" +
      "<div class='row between wrap' style='margin-bottom:8px'><div class='row'>" +
      "<span class='chip mono'>" + esc(s.subtask_id) + "</span>" +
      "<span class='strong small'>" + esc(U.truncate(s.question, 92)) + "</span></div>" +
      "<span class='chip " + ((s.routing || {}).random_pick ? "warn" : "brand") + "'>" +
      ((s.routing || {}).random_pick ? "并列随机" : "能力最高") + " → 智能体 " + esc(s.agent_name) + "</span></div>" +
      "<div class='chip-row' style='margin-bottom:9px'><span class='tiny muted'>所需能力</span>" + dimChips(s.required_capabilities) + "</div>" +
      scoreList(s.routing) + "</div>").join("") ||
      "<div class='tiny muted'>没有子任务。</div>";

    const decomposeBody = "<div class='stack'>" +
      "<div><div class='tiny muted' style='margin-bottom:4px'>精炼后的问题</div><div class='small'>" + esc(dec.refined_question || u.refined_question || "—") + "</div></div>" +
      subCards + "</div>";

    const planBody = "<div class='stack'>" + ((plan.subtasks || []).map((p, i) => planHTML(p, i)).join("") ||
      "<div class='tiny muted'>没有计划数据。</div>") + "</div>";

    const execBody = "<div class='stack'>" + ((exec.subtasks || []).map((s) =>
      "<div class='card' style='background:var(--panel-2);box-shadow:none'>" +
      "<div class='row between wrap' style='margin-bottom:8px'>" +
      "<div class='row'>" + GIS.ui.agentAvatar(s.agent_id, 26) +
      "<span class='strong small'>" + esc(s.subtask_id) + " · 智能体 " + esc(s.agent_name) + "</span>" +
      "<span class='chip " + (s.status === "success" ? "ok" : "err") + "'>" + (s.status === "success" ? "跑通" : "报错") + "</span></div>" +
      "<div class='chip-row'>" + (s.tools_used || []).map((t) => "<span class='op'>" + esc(t) + "</span>").join("") + "</div></div>" +
      traceHTML(s.trace) +
      (s.error ? "<div class='chip err' style='white-space:normal'>" + esc(s.error) + "</div>" : "") +
      "</div>").join("") + "</div>");

    const evaluateBody = evaluateHTML(ev, run);

    const bodies = [understandBody, decomposeBody, planBody, execBody, evaluateBody];
    const cards = F.stages.map((st, i) =>
      "<section class='stage-card' data-stage='" + i + "'>" +
      "<div class='stage-head' data-stage-toggle='" + i + "'>" +
      "<span class='stage-index'>" + st.no + "</span>" +
      "<div><h3>" + st.title + " <span class='desc'>" + st.en + "</span></h3>" +
      "<div class='tiny muted'>" + st.desc + "</div></div>" +
      "<span class='stage-time'>" + fmtDuration((flow[st.key] || {}).elapsed_ms) + "</span>" +
      "<span class='chip muted' style='margin-left:8px'>" + esc(U.truncate((flow[st.key] || {}).summary || "", 46)) + "</span>" +
      "<svg class='stage-chevron'><use href='#i-chevron'></use></svg>" +
      "</div><div class='stage-body'>" + bodies[i] + "</div></section>").join("");

    const rail = "<div class='stage-rail'>" + F.stages.map((st, i) =>
      "<div class='stage-node' data-node='" + i + "'><div class='stage-dot'>" + st.no +
      "</div><div class='sn'>" + st.title + "</div><div class='sm'>" + st.en + "</div></div>").join("") + "</div>";

    const log = opt.showLog === false ? "" :
      "<div class='card flush' style='margin-bottom:14px'><div class='card-head' style='padding:12px 15px;margin:0'>" +
      "<div><h3 style='font-size:12px'>运行时日志</h3><p class='sub'>按阶段回放本次执行的决策与工具调用</p></div>" +
      "<div class='right'><span class='chip mono' id='flowClock'>00:00.0</span></div></div>" +
      "<div id='flowLog' class='flow-log'></div></div>";

    return "<div class='flow-root'>" + rail + log +
      "<div class='row between wrap' style='margin-bottom:10px'>" +
      "<div class='playback'>" +
      "<button class='btn sm primary' data-play='toggle'>" + GIS.ui.icon("pause") + "暂停</button>" +
      "<button class='btn sm ghost' data-play='step'>下一步</button>" +
      "<button class='btn sm ghost' data-play='finish'>全部展开</button>" +
      "<span class='status' id='flowStatus'>准备就绪</span></div>" +
      "<div class='chip-row' id='flowMeta'>" +
      (run ? "<span class='chip mono'>" + esc(run.run_id || "") + "</span>" : "") +
      "<span class='chip'>" + esc((run && run.mode) || "demo") + "</span>" +
      "</div></div>" +
      "<div class='progress-line'><i id='flowProgress' style='width:0%'></i></div>" +
      "<div id='flowStages' style='margin-top:14px'>" + cards + "</div></div>";
  };

  F.mount = function (container, flow, options) {
    const opt = options || {};
    const root = container.querySelector(".flow-root");
    if (!root) return null;
    const cards = Array.from(root.querySelectorAll(".stage-card"));
    const nodes = Array.from(root.querySelectorAll(".stage-node"));
    const logBox = root.querySelector("#flowLog");
    const clock = root.querySelector("#flowClock");
    const status = root.querySelector("#flowStatus");
    const progress = root.querySelector("#flowProgress");
    const playBtn = root.querySelector("[data-play='toggle']");
    const timeline = (opt.run && opt.run.timeline) || [];
    let index = -1;
    let timer = null;
    let mounted = {};
    let elapsed = 0;
    let logIndex = 0;
    if (logBox && !timeline.length) {
      logBox.innerHTML = "<div class='log-line'><span class='log-t'>—</span><span class='log-i'>·</span>" +
        "<span class='log-m'>该记录未保存运行时日志（基准报告仅保留工具调用轨迹）</span></div>";
    }

    function logLine(entry) {
      if (!logBox) return;
      const kind = entry.kind || "info";
      const icon = kind === "error" ? "✕" : kind === "warn" ? "!" : kind === "ok" ? "✓" : "·";
      const el = document.createElement("div");
      el.className = "log-line " + kind;
      el.innerHTML = "<span class='log-t'>" + String(entry.at_ms || 0) + "ms</span>" +
        "<span class='log-i'>" + icon + "</span><span class='log-m'>" + esc(entry.title) +
        (entry.detail ? " <span class='log-d'>" + esc(entry.detail) + "</span>" : "") + "</span>";
      logBox.appendChild(el);
      logBox.scrollTop = logBox.scrollHeight;
    }

    function mountStage(i) {
      const key = F.stages[i] && F.stages[i].key;
      if (!key) return;
      if (key === "plan" && !mounted.plan) {
        mounted.plan = true;
        const stage = flow.plan || {};
        (stage.subtasks || []).forEach((item, idx) => {
          const canvas = root.querySelector(".flow-dag[data-plan='" + idx + "']");
          if (!canvas) return;
          const nodeClick = (node) => {
            GIS.ui.openDrawer("节点 " + node.id + " · " + node.action,
              "<div class='stack'><div class='kv-grid'>" +
              "<div class='kv'><dt>算子</dt><dd class='mono'>" + esc(node.action) + "</dd></div>" +
              "<div class='kv'><dt>说明</dt><dd>" + esc(node.label || "") + "</dd></div>" +
              "<div class='kv'><dt>依赖</dt><dd class='mono'>" + esc((node.depends_on || []).join(", ") || "无") + "</dd></div>" +
              "</div>" + GIS.ui.codeBlock(JSON.stringify(node.params || {}, null, 2), false, 320) + "</div>");
          };
          canvas._nodeClick = nodeClick;
          requestAnimationFrame(() => {
            GIS.charts.dag(canvas, item.plan || {}, { onNodeClick: nodeClick });
          });
        });
      }
    }

    function updateFocus() {
      cards.forEach((card, i) => {
        card.classList.toggle("open", i === index);
        card.classList.toggle("reveal", i <= index || index >= cards.length);
      });
      nodes.forEach((node, i) => {
        node.classList.toggle("active", i === index);
        node.classList.toggle("done", i < index || (index >= cards.length && i < cards.length));
      });
      const total = F.stages.length;
      if (progress) progress.style.width = Math.max(0, Math.min(1, (index + 1) / total)) * 100 + "%";
    }

    function reveal(i, opts) {
      index = Math.max(-1, Math.min(cards.length - 1, i));
      updateFocus();
      mountStage(index);
      // 日志推进
      const stageKey = F.stages[index] && F.stages[index].key;
      const stageEntries = timeline.filter((e) => e.stage === stageKey);
      if (logBox) {
        const all = timeline.slice(0, (() => {
          let last = 0;
          for (let k = 0; k <= index; k++) {
            const key = F.stages[k].key;
            timeline.forEach((e, ei) => { if (e.stage === key) last = Math.max(last, ei + 1); });
          }
          return last;
        })());
        logBox.innerHTML = "";
        all.forEach(logLine);
        logIndex = all.length;
      }
      if (clock) {
        const last = timeline.length ? timeline[timeline.length - 1].at_ms || 0 : 0;
        clock.textContent = last ? "+" + last + " ms" : "0 ms";
      }
      if (status) {
        const st = F.stages[index] || {};
        status.textContent = "阶段 " + st.no + " · " + st.title + " 已就绪";
      }
      if (index >= cards.length - 1 && timer) stop();
      if (opts && opts.scrollTo) {
        const card = cards[index];
        if (card) card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }

    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
      if (playBtn) playBtn.innerHTML = GIS.ui.icon("play") + "继续播放";
    }
    function play() {
      if (timer) { stop(); return; }
      if (index >= cards.length - 1) reveal(0);
      if (playBtn) playBtn.innerHTML = GIS.ui.icon("pause") + "暂停";
      timer = setInterval(() => {
        if (index >= cards.length - 1) { stop(); return; }
        reveal(index + 1);
      }, opt.speed || 1500);
    }

    root.querySelectorAll("[data-stage-toggle]").forEach((head) => {
      head.addEventListener("click", () => {
        const card = head.closest(".stage-card");
        const i = Number(head.dataset.stageToggle);
        if (index < i) reveal(i);
        else card.classList.toggle("open");
      });
    });
    root.querySelectorAll("[data-play]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.play;
        if (action === "toggle") play();
        else if (action === "step") { stop(); reveal(index + 1, { scrollTo: true }); }
        else if (action === "finish") { stop(); reveal(cards.length - 1); }
      });
    });
    root.querySelectorAll("[data-toggle-plan]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const box = root.querySelector("[data-plan-json='" + btn.dataset.togglePlan + "']");
        if (box) box.hidden = !box.hidden;
      });
    });
    root.querySelectorAll("[data-copy]").forEach((btn) => {
      btn.addEventListener("click", () => GIS.ui.copy(btn.dataset.copy, "运行 ID 已复制"));
    });

    // 初始：只展示第一阶段
    reveal(0);
    if (opt.autoplay === false) {
      stop();
      if (status) status.textContent = "已暂停 · 可单步查看";
    } else {
      timer = null;
      if (playBtn) playBtn.innerHTML = GIS.ui.icon("pause") + "暂停";
      timer = setInterval(() => {
        if (index >= cards.length - 1) { stop(); return; }
        reveal(index + 1);
      }, opt.speed || 1500);
    }

    // 尺寸变化时重绘 DAG
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => {
        if (!mounted.plan) return;
        const stage = flow.plan || {};
        (stage.subtasks || []).forEach((item, idx) => {
          const canvas = root.querySelector(".flow-dag[data-plan='" + idx + "']");
          if (canvas && canvas.clientWidth) {
            GIS.charts.dag(canvas, item.plan || {}, { onNodeClick: canvas._nodeClick });
          }
        });
      });
      ro.observe(root);
    }

    return {
      reveal,
      finish: () => { stop(); reveal(cards.length - 1); },
      stop,
      get index() { return index; },
    };
  };

  /* ---------------------------------------------------------- 基准报告适配 */
  F.fromBenchmark = function (item) {
    const dims = GIS.meta.dims();
    const routing = item.routing || {};
    const changes = item.capability_changes || [];
    const steps = item.steps || [];
    const agentId = item.agent || routing.agent_id || "agent_02";
    const agentName = item.agent_name || GIS.meta.agentName(agentId);
    const subtask = {
      subtask_id: "t1",
      question: item.question,
      required_capabilities: routing.required || dims,
      agent_id: agentId,
      agent_name: agentName,
      routing: routing,
    };
    const trace = steps.map((s) => ({
      step: s.step, tool: s.tool, args: s.args || {}, refs: [], ok: s.ok !== false,
      error: s.error || "", brief: s.brief || {},
    }));
    return {
      understand: {
        domain: "", domain_label: item.task_signature || "基准题",
        task_type: item.level || "", tables: [], skills: [],
        refined_question: item.question,
        summary: "基准报告未保存该阶段上下文，显示题目与路由结果",
        elapsed_ms: item.elapsed_s ? item.elapsed_s * 1000 : null,
      },
      decompose: {
        refined_question: item.question, subtasks: [subtask],
        summary: "题号 " + item.id + " · " + item.level,
        elapsed_ms: null,
      },
      plan: {
        subtasks: [{
          subtask_id: "t1", agent_id: agentId, agent_name: agentName,
          plan: { nodes: [], edges: [] }, skill: null, memory_hits: [], experience_hits: [],
          capability_line: "基准报告未保存规划 DAG；下方为实际工具调用轨迹",
        }],
        summary: "基准报告未保存计划 DAG",
        elapsed_ms: null,
      },
      execute: {
        subtasks: [{ subtask_id: "t1", agent_id: agentId, agent_name: agentName,
          status: item.error ? "failed" : "success", trace, tools_used: item.tools || [],
          error: item.error || "" }],
        summary: (item.tools || []).length + " 个工具 · " + steps.length + " 次调用",
        elapsed_ms: item.elapsed_s ? item.elapsed_s * 1000 : null,
      },
      evaluate: {
        evaluation: item.correct ? "success" : "failed",
        correct: !!item.correct,
        reason: item.failure_feedback || (item.diffs && item.diffs.length ? JSON.stringify(item.diffs) : (item.correct ? "与标准答案一致" : "与标准答案不符")),
        final_answer: item.answer_raw || JSON.stringify(item.answer || {}),
        answer: item.answer,
        answer_kind: "基准答案",
        changes: changes.map((c) => ({ ...c, subtask_id: c.subtask_id || "t1" })),
        summary: item.correct ? "判定通过" : "判定未通过",
        elapsed_ms: null,
      },
      history_meta: { id: item.id, level: item.level, elapsed_s: item.elapsed_s },
    };
  };
})();
