/* ============================================================
   任务台：提问 → 五阶段执行流 → 能力变化
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;

  const VIEW = {
    title: "任务台",
    subtitle: "提问 · 观察五阶段执行流与能力演化",
    question: "",
    truth: "",
    verdict: "auto",
    memoryTarget: "demo",
    role: "analyst",
    running: false,
    lastRun: null,
    player: null,
    timers: [],
  };

  function examples() {
    return (GIS.state.data && GIS.state.data.examples) || [];
  }

  function roleList() {
    const list = (GIS.state.data && GIS.state.data.roles) || [];
    return list.length ? list : [
      { key: "admin", name: "系统管理员" },
      { key: "analyst", name: "业务分析员" },
      { key: "operator", name: "运维操作员" },
      { key: "viewer", name: "访客（只读）" },
    ];
  }

  function roleField() {
    const list = roleList();
    const current = list.some((r) => r.key === VIEW.role) ? VIEW.role : list[0].key;
    const item = list.find((r) => r.key === current) || {};
    return "<div class='field role-field'><label>用户类别（数据权限）</label>" +
      "<select id='roleSelect'>" + list.map((r) =>
        "<option value='" + esc(r.key) + "'" + (r.key === current ? " selected" : "") + ">" +
        esc(r.name) + "（" + esc(r.key) + "）</option>").join("") + "</select>" +
      "<div class='tiny faint' style='margin-top:5px'>" + esc(item.description || "权限来自 config/user_permissions.yaml。") +
      " 决定可查询的表与增删改查范围，越权调用会被拦截并审计。</div></div>";
  }

  function render() {
    const d = GIS.state.data || {};
    const staticMode = GIS.state.mode === "static";
    const ex = examples();
    const agents = GIS.meta.agents();
    return "<div class='workbench-grid'>" +
      "<div class='stack-lg'>" +
      "<section class='card ask-card'>" +
      "<div class='row between wrap' style='margin-bottom:10px'>" +
      "<div><h2 style='font-size:16px'>描述你的 GIS 任务</h2>" +
      "<p class='small muted' style='margin:3px 0 0'>用日常语言即可，系统会自动识别领域、拆解子任务并按能力向量路由。</p></div>" +
      "<span class='chip " + (staticMode ? "warn" : "ok") + "'>" + (staticMode ? "静态预览" : "演示会话 · 本地模拟执行") + "</span></div>" +
      "<div class='ask-label'>问题</div>" +
      "<div class='ask-input-wrap'>" +
      "<textarea id='askInput' class='ask-input' placeholder='例如：统计严格位于施工区 A001 内、状态为正常的燃气设备数量，边界上的设备不计入。'>" + esc(VIEW.question) + "</textarea>" +
      "<div class='ask-toolbar'>" +
      "<span class='ask-hint'>" + GIS.ui.icon("bolt") + "Enter 换行 · Ctrl/⌘ + Enter 运行</span>" +
      "<span class='spacer'></span>" +
      "<span class='ask-hint' id='askCount'>0 / 2000</span>" +
      "<button class='btn sm ghost' id='clearAsk'>清空</button>" +
      "<button class='btn sm primary' id='runBtn' " + (staticMode || VIEW.running ? "disabled" : "") + ">" +
      GIS.ui.icon("play") + (VIEW.running ? "执行中…" : "运行任务") + "</button>" +
      "</div></div>" +
      "<div class='ask-options'>" +
      "<div class='field'><label>参考答案（可选，自动判定用）</label>" +
      "<input id='truthInput' placeholder='例如 {\"count\": 2} 或 2' value='" + esc(VIEW.truth) + "'></div>" +
      "<div class='field'><label>判定方式</label>" +
      "<div class='segmented' id='verdictGroup'>" +
      "<button data-verdict='auto' class='" + (VIEW.verdict === "auto" ? "active" : "") + "'>自动</button>" +
      "<button data-verdict='success' class='" + (VIEW.verdict === "success" ? "active" : "") + "'>判成功</button>" +
      "<button data-verdict='failure' class='" + (VIEW.verdict === "failure" ? "active" : "") + "'>判失败</button>" +
      "</div>" +
      "<div class='tiny faint' style='margin-top:5px'>自动模式未填参考答案时按「未知」处理，不更新能力；判成功/判失败会直接驱动进化。</div></div>" +
      "<div class='field memory-field'><label>记忆写入</label>" +
      "<div class='segmented' id='memoryTargetGroup'>" +
      "<button data-memory-target='demo' class='" + (VIEW.memoryTarget === "demo" ? "active" : "") + "'>演示记忆</button>" +
      "<button data-memory-target='real' class='" + (VIEW.memoryTarget === "real" ? "active" : "") + "'>真实记忆</button>" +
      "</div>" +
      "<div class='tiny faint' style='margin-top:5px'>演示记忆写 <span class='mono'>web/data/memory</span>；真实记忆写 <span class='mono'>data/memory</span>。运行后可在记忆库切换来源查看。</div></div>" +
      roleField() +
      "</div>" +
      "<div class='notice-line'>" + GIS.ui.chip("不调用 LLM", "muted") +
      GIS.ui.chip("记忆写入可选", "muted") +
      GIS.ui.chip("检索与进化公式来自项目真实实现", "muted") + "</div>" +
      "</section>" +
      "<section id='runOutput'>" + emptyOutput() + "</section>" +
      "</div>" +

      "<aside class='stack-lg'>" +
      "<section class='card'><div class='card-head'><div><h3>示例任务</h3><p class='sub'>点击填入，可直接运行</p></div></div>" +
      "<div class='examples'>" + ex.slice(0, 5).map((q, i) =>
        "<button class='example-item' data-fill='" + esc(q) + "'><b>EXAMPLE " + (i + 1) + "</b>" + esc(q) + "</button>").join("") +
      "</div></section>" +

      "<section class='card'><div class='card-head'><div><h3>当前能力向量</h3><p class='sub'>路由得分 = 所需维度能力均值</p></div>" +
      "<div class='right'><a class='btn sm ghost' href='#/capability'>详情</a></div></div>" +
      "<div class='stack'>" + agents.map((a) => {
        const dims = GIS.meta.dims();
        const sum = dims.reduce((s, dim) => s + Number((a.capabilities || {})[dim] || 0), 0);
        const avg = sum / Math.max(1, dims.length);
        return "<div class='row' style='gap:9px' data-side-agent='" + a.id + "'>" + GIS.ui.agentAvatar(a.id, 28) +
          "<div style='flex:1;min-width:0'><div class='row between'><span class='small strong'>智能体 " + esc(a.name) + "</span>" +
          "<span class='mono tiny side-avg'>" + avg.toFixed(3) + "</span></div>" +
          "<span class='cap-heat' style='margin-top:3px'><i style='width:" + (avg * 100).toFixed(1) + "%;background:" + GIS.meta.agentColor(a.id) + "'></i></span></div></div>";
      }).join("") + "</div></section>" +

      "<section class='card'><div class='card-head'><div><h3>演示说明</h3></div></div>" +
      "<div class='small muted' style='line-height:1.8'>" +
      "执行流由本地模拟引擎生成，但以下环节直接复用项目实现：<br>" +
      "· 表结构 / skill / 经验 / 记忆的 TF-IDF 余弦检索<br>" +
      "· 能力路由得分与并列随机抽取<br>" +
      "· 能力进化公式与边界值（来自 agents_capability.yaml）<br><br>" +
      "执行流与能力状态默认写入 <span class='mono'>web/data/</span>；记忆位置由上方「记忆写入」选项决定。" +
      "</div></section>" +
      "</aside></div>";
  }

  function emptyOutput() {
    return "<div class='card' style='padding:0'><div class='empty' style='padding:56px 24px'>" +
      "<div class='stage-rail' style='width:100%;max-width:560px;margin-bottom:18px'>" +
      GIS.flow.stages.map((s) => "<div class='stage-node'><div class='stage-dot'>" + s.no + "</div><div class='sn'>" + s.title + "</div></div>").join("") +
      "</div>" +
      "<strong style='font-size:14px'>运行后在这里查看完整执行流</strong>" +
      "<span>依次展开：任务理解 → 精炼拆解 → 规划 DAG → 工具调用 → 评估与能力进化。左侧示例可直接填入。</span>" +
      "</div></div>";
  }

  function runningOutput() {
    return "<div class='card'><div class='running-box'>" +
      "<div class='run-rings'><span></span><span></span><span></span><i></i></div>" +
      "<div style='flex:1'><div class='strong'>正在执行五阶段流水线…</div>" +
      "<div class='small muted' id='runningStage'>① 任务理解 · 领域识别与知识检索</div>" +
      "<div class='progress-line' style='margin-top:10px'><i id='runningProgress' style='width:6%'></i></div></div></div></div>";
  }

  function errorOutput(message) {
    return "<div class='card'><div class='card-head'><span class='card-title-icon' style='background:var(--err-soft);color:var(--err)'>" +
      GIS.ui.icon("close") + "</span><div><h3>执行失败</h3><p class='sub'>" + esc(message) + "</p></div></div>" +
      "<button class='btn sm ghost' id='retryRun'>重新运行</button></div>";
  }

  function outputForRun(run) {
    const ev = run.flow.evaluate || {};
    const verdict = GIS.flow.verdict(ev);
    const chipCls = verdict.key === "success" ? "ok" : (verdict.key === "failed" ? "err" : "warn");
    const meta = run.metrics || {};
    const actions = "<div class='row between wrap' style='margin-bottom:12px'>" +
      "<div class='row wrap' style='gap:6px'>" +
      "<span class='chip " + chipCls + "'>" + verdict.label + "</span>" +
      "<span class='chip mono'>" + esc(run.run_id) + "</span>" +
      "<span class='chip'>" + esc(run.domain_label || run.domain) + " / " + esc(run.task_type) + "</span>" +
      "<span class='chip'>用户：" + esc(run.role_name || run.role || "—") + "</span>" +
      (run.is_valid === false ? "<span class='chip err'>问题不合法</span>" : "") +
      ((run.permission_denials || []).length
        ? "<span class='chip err'>越权拦截 " + run.permission_denials.length + " 次</span>" : "") +
      "<span class='chip'>" + (meta.tool_calls || 0) + " 次工具调用</span>" +
      "<span class='chip'>" + (meta.subtasks || 1) + " 个子任务</span>" +
      "<span class='chip " + (run.memory_target === "real" ? "warn" : "") + "'>记忆：" +
      (run.memory_target === "real" ? "真实" : "演示") + "</span>" +
      "<span class='chip mono'>" + (meta.elapsed_ms || 0) + " ms</span>" +
      "</div>" +
      "<div class='row' style='gap:6px'>" +
      "<button class='btn sm ghost' data-copy-answer>" + GIS.ui.icon("copy") + "复制答案</button>" +
      "<button class='btn sm ghost' data-export-run>" + GIS.ui.icon("download") + "导出运行</button>" +
      "<button class='btn sm ghost' data-rerun>" + GIS.ui.icon("refresh") + "再运行</button>" +
      "</div></div>";
    return "<div class='card' style='padding:16px 18px'>" +
      "<div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("play") + "</span>" +
      "<div><h2>执行结果</h2><p class='sub'>" + esc(run.question) + "</p></div>" +
      "<div class='right'><span class='chip " + (GIS.state.mode === "live" ? "ok" : "warn") + "'>" +
      (GIS.state.mode === "live" ? "本地演示引擎" : "静态快照") + "</span></div></div>" +
      actions +
      GIS.flow.render(run.flow, { run }) +
      "</div>";
  }

  function refreshSideCapability() {
    const agents = (GIS.state.data.capability || {}).agents || {};
    const dims = GIS.meta.dims();
    Object.keys(agents).forEach((id) => {
      const row = document.querySelector("[data-side-agent='" + id + "']");
      if (!row) return;
      const caps = agents[id].capabilities || {};
      const avg = dims.reduce((s, d) => s + Number(caps[d] || 0), 0) / Math.max(1, dims.length);
      const val = row.querySelector(".side-avg");
      if (val) val.textContent = avg.toFixed(3);
      const bar = row.querySelector(".cap-heat i");
      if (bar) bar.style.width = (avg * 100).toFixed(1) + "%";
    });
  }

  function refreshCapability() {
    if (GIS.state.mode === "static") return Promise.resolve();
    return GIS.api.capability("demo").then((payload) => {
      if (!payload) return;
      GIS.state.data.capability = payload;
      if (payload.history) GIS.state.data.counts.evolution_events = payload.history.length;
      if (payload.runs) {
        GIS.state.data.runs = payload.runs;
        GIS.state.data.counts.runs = payload.runs.length;
      }
      refreshSideCapability();
      if (window.GIS.refreshNav) window.GIS.refreshNav();
    }).catch(() => { /* 静默 */ });
  }

  function refreshMemory(source) {
    if (GIS.state.mode === "static") return Promise.resolve();
    return GIS.api.memory(source).then((payload) => {
      if (!payload) return;
      if (source === "demo") GIS.state.data.demo_memory = payload.memory;
      else GIS.state.data.memory = payload.memory;
      const total = Object.keys(payload.memory).reduce((s, k) => s + ((payload.memory[k].records || []).length), 0);
      GIS.state.data.counts = GIS.state.data.counts || {};
      GIS.state.data.counts[source === "demo" ? "demo_memory_records" : "memory_records"] = total;
      if (window.GIS.refreshNav) window.GIS.refreshNav();
    }).catch(() => { /* 静默 */ });
  }

  function setRunningUI(on) {
    const btn = document.getElementById("runBtn");
    if (btn) {
      btn.disabled = on || GIS.state.mode === "static";
      btn.innerHTML = GIS.ui.icon("play") + (on ? "执行中…" : "运行任务");
    }
  }

  async function run() {
    if (VIEW.running) return;
    const input = document.getElementById("askInput");
    const truthInput = document.getElementById("truthInput");
    const question = (input ? input.value : VIEW.question).trim();
    if (!question) { GIS.toast("请先输入问题", "warn"); if (input) input.focus(); return; }
    VIEW.question = question;
    VIEW.truth = truthInput ? truthInput.value.trim() : "";
    VIEW.running = true;
    setRunningUI(true);
    const out = document.getElementById("runOutput");
    out.innerHTML = runningOutput();
    const stageEl = document.getElementById("runningStage");
    const progEl = document.getElementById("runningProgress");
    const stageLabels = [
      "① 任务理解 · 领域识别与知识检索",
      "② 精炼与拆解 · 标注能力维度并按能力路由",
      "③ 规划 · 专属记忆 + 共享经验 → 计划 DAG",
      "④ 执行 · 绑定算子调用与 $ref 结果传递",
      "⑤ 评估与沉淀 · 判定结果并更新能力向量",
    ];
    let step = 0;
    VIEW.timers.forEach(clearInterval);
    VIEW.timers = [setInterval(() => {
      step = (step + 1) % stageLabels.length;
      if (stageEl) stageEl.textContent = stageLabels[step];
      if (progEl) progEl.style.width = Math.min(94, 8 + step * 22) + "%";
    }, 760)];
    try {
      const result = await GIS.api.run(question, VIEW.truth, VIEW.verdict, VIEW.memoryTarget, VIEW.role);
      VIEW.lastRun = result;
      GIS.state.lastRun = result;
      VIEW.timers.forEach(clearInterval);
      VIEW.timers = [];
      out.innerHTML = outputForRun(result);
      const player = GIS.flow.mount(out, result.flow, { run: result, speed: 1650 });
      VIEW.player = player;
      bindOutput(result);
      if (result.is_valid === false) {
        GIS.toast("问题被判定为「问题不合法」：本次未执行，请按追问补充信息后重跑", "warn",
          "已中止 · 需要补充信息");
      } else if ((result.permission_denials || []).length) {
        GIS.toast("有 " + result.permission_denials.length + " 次工具调用因权限不足被拦截", "warn", "越权拦截");
      }
      refreshCapability();
      refreshMemory(result.memory_target === "real" ? "real" : "demo");
      const verdict = GIS.flow.verdict(result.flow.evaluate);
      if (verdict.key === "unknown") {
        GIS.toast("执行完成 · 未提供参考答案，按未知处理，能力向量保持不变", "warn", "结果未判定");
      } else if (verdict.key === "clarification") {
        GIS.toast("问题不合法：未执行任何算子，请按追问补充信息后重新提交", "warn", "需要补充信息");
      } else if (verdict.key === "success") {
        GIS.toast("执行完成 · 能力向量已更新", "ok", "任务完成");
      } else {
        GIS.toast("执行完成 · 判定失败，能力向量按失败经验回落", "err", "任务完成");
      }
      const writes = (result.memory_writes || []).length;
      if (writes) {
        GIS.toast("已写入" + (result.memory_target === "real" ? "真实记忆" : "演示记忆") +
          " " + writes + " 条", "ok", "记忆已更新");
      }
      if ((result.memory_errors || []).length) {
        GIS.toast(result.memory_errors[0], "warn", "部分记忆写入失败");
      }
      out.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      VIEW.timers.forEach(clearInterval);
      VIEW.timers = [];
      out.innerHTML = errorOutput(err.message || "未知错误");
      const retry = document.getElementById("retryRun");
      if (retry) retry.addEventListener("click", run);
      GIS.toast(err.message || "执行失败", "err");
    } finally {
      VIEW.running = false;
      setRunningUI(false);
    }
  }

  function bindOutput(run) {
    const out = document.getElementById("runOutput");
    if (!out) return;
    out.querySelectorAll("[data-copy-answer]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const answer = run.flow.evaluate.final_answer || "";
        GIS.ui.copy(answer, "答案已复制");
      });
    });
    out.querySelectorAll("[data-export-run]").forEach((btn) => {
      btn.addEventListener("click", () => {
        GIS.ui.download(run.run_id + ".json", JSON.stringify(run, null, 2));
      });
    });
    out.querySelectorAll("[data-rerun]").forEach((btn) => {
      btn.addEventListener("click", run);
    });
  }

  function mount() {
    let prefill = "";
    try { prefill = sessionStorage.getItem("gis:prefill") || ""; } catch (e) { /* ignore */ }
    const qp = GIS.state.query || {};
    if (qp.q && !VIEW.question) { VIEW.question = qp.q; prefill = qp.q; }
    if (prefill && !VIEW.question) {
      VIEW.question = prefill;
      try { sessionStorage.removeItem("gis:prefill"); } catch (e) { /* ignore */ }
      const input = document.getElementById("askInput");
      if (input) input.value = prefill;
    }
    const input = document.getElementById("askInput");
    if (input) {
      const count = document.getElementById("askCount");
      const updateCount = () => { if (count) count.textContent = input.value.length + " / 2000"; };
      updateCount();
      input.addEventListener("input", () => {
        VIEW.question = input.value;
        updateCount();
      });
      input.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); }
      });
    }
    const clear = document.getElementById("clearAsk");
    if (clear) clear.addEventListener("click", () => {
      VIEW.question = "";
      if (input) { input.value = ""; input.focus(); }
      const count = document.getElementById("askCount");
      if (count) count.textContent = "0 / 2000";
    });
    const runBtn = document.getElementById("runBtn");
    if (runBtn) runBtn.addEventListener("click", run);
    const truth = document.getElementById("truthInput");
    if (truth) truth.addEventListener("input", () => { VIEW.truth = truth.value; });
    document.querySelectorAll("#verdictGroup [data-verdict]").forEach((btn) => {
      btn.addEventListener("click", () => {
        VIEW.verdict = btn.dataset.verdict;
        document.querySelectorAll("#verdictGroup [data-verdict]").forEach((b) => b.classList.toggle("active", b === btn));
      });
    });
    document.querySelectorAll("#memoryTargetGroup [data-memory-target]").forEach((btn) => {
      btn.addEventListener("click", () => {
        VIEW.memoryTarget = btn.dataset.memoryTarget === "real" ? "real" : "demo";
        document.querySelectorAll("#memoryTargetGroup [data-memory-target]").forEach((b) =>
          b.classList.toggle("active", b === btn));
        GIS.toast(
          VIEW.memoryTarget === "real"
            ? "后续运行会写入项目真实记忆 data/memory"
            : "后续运行会写入演示记忆 web/data/memory",
          VIEW.memoryTarget === "real" ? "warn" : "ok",
          "记忆写入位置"
        );
      });
    });
    const roleSelect = document.getElementById("roleSelect");
    if (roleSelect) {
      roleSelect.addEventListener("change", () => {
        VIEW.role = roleSelect.value;
        const item = roleList().find((r) => r.key === VIEW.role) || {};
        GIS.toast((item.description || "已切换用户类别") + " 可查询表：" +
          Object.keys(item.tables || {}).filter((t) => (item.tables[t] || []).indexOf("select") >= 0).length + " 张",
          "ok", "用户类别：" + (item.name || VIEW.role));
      });
    }
    document.querySelectorAll("[data-fill]").forEach((btn) => {
      btn.addEventListener("click", () => {
        VIEW.question = btn.dataset.fill;
        if (input) { input.value = VIEW.question; input.focus(); }
        const count = document.getElementById("askCount");
        if (count) count.textContent = VIEW.question.length + " / 2000";
      });
    });
    if (VIEW.lastRun) {
      const out = document.getElementById("runOutput");
      if (out) {
        out.innerHTML = outputForRun(VIEW.lastRun);
        const player = GIS.flow.mount(out, VIEW.lastRun.flow, { run: VIEW.lastRun, autoplay: false });
        VIEW.player = player;
        bindOutput(VIEW.lastRun);
      }
    }
    if (qp.q && !VIEW.autoStarted && GIS.state.mode === "live" && qp.autorun === "1") {
      VIEW.autoStarted = true;
      const input2 = document.getElementById("askInput");
      if (input2) input2.value = qp.q;
      setTimeout(run, 600);
    }
    if (GIS.state.mode === "static") {
      GIS.toast("当前为静态预览：请运行 python web/server/app.py 启用交互", "warn", "未连接服务");
    }
  }

  function unmount() {
    VIEW.timers.forEach(clearInterval);
    VIEW.timers = [];
    if (VIEW.player && typeof VIEW.player.stop === "function") VIEW.player.stop();
  }

  GIS.views.workbench = {
    title: VIEW.title,
    subtitle: VIEW.subtitle,
    render,
    mount,
    unmount,
    async before() {
      await GIS.api.bootstrap();
      const qp = GIS.state.query || {};
      if (qp.verdict === "success" || qp.verdict === "failure" || qp.verdict === "auto") VIEW.verdict = qp.verdict;
      if (qp.truth) VIEW.truth = qp.truth;
      if (qp.q) VIEW.question = qp.q;
    },
  };
})();
