/* ============================================================
   能力进化：雷达回放 / 能力矩阵 / 逐维趋势 / 进化事件
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const U = GIS.util;
  const esc = U.esc;

  const S = {
    source: "demo",
    frames: [],
    frame: 0,
    playing: false,
    timer: null,
    anim: null,
    highlight: null,
    dim: null,
    display: {},
  };

  function capData() {
    const d = GIS.state.data || {};
    return S.source === "real" ? (d.real_capability || d.capability) : d.capability;
  }

  function buildFrames(cap) {
    const dims = (cap && cap.dimensions) || (GIS.state.data || {}).dimensions || [];
    const agents = (cap && cap.agents) || {};
    const ids = Object.keys(agents).sort();
    const init = Number((cap && cap.initial_capability) != null ? cap.initial_capability : 0.5);
    const zeroStats = () => {
      const out = {};
      ids.forEach((id) => { out[id] = { attempts: 0, successes: 0, failures: 0 }; });
      return out;
    };
    const initVectors = () => {
      const out = {};
      ids.forEach((id) => {
        out[id] = {};
        dims.forEach((dim) => { out[id][dim] = init; });
      });
      return out;
    };
    const clone = (obj) => JSON.parse(JSON.stringify(obj));
    const frames = [];
    const vectors = initVectors();
    const stats = zeroStats();
    frames.push({
      label: "初始状态：所有智能体、所有维度均为 " + init.toFixed(2) + "，能力完全均衡",
      ts: "", vectors: clone(vectors), stats: clone(stats), agent: null, dims: [], question: "",
    });
    (cap.history || []).forEach((e) => {
      if (!vectors[e.agent_id]) return;
      dims.forEach((dim) => {
        if (e.vector_after && e.vector_after[dim] != null) vectors[e.agent_id][dim] = Number(e.vector_after[dim]);
      });
      const st = stats[e.agent_id];
      st.attempts += 1;
      if (e.outcome === "success") st.successes += 1; else st.failures += 1;
      frames.push({
        label: (e.ts || "") + " · 智能体 " + (e.agent_name || GIS.meta.agentName(e.agent_id)) +
          (e.outcome === "success" ? " 成功" : " 失败") + " · " +
          (e.dims || []).map((dim) => GIS.meta.dimLabel(dim)).join(" / "),
        ts: e.ts, vectors: clone(vectors), stats: clone(stats),
        agent: e.agent_id, dims: e.dims || [], question: e.question || "", event: e,
      });
    });
    const current = {};
    ids.forEach((id) => {
      current[id] = {};
      dims.forEach((dim) => { current[id][dim] = Number((agents[id].capabilities || {})[dim] || init); });
    });
    const last = frames[frames.length - 1];
    if (JSON.stringify(current) !== JSON.stringify(last.vectors)) {
      frames.push({
        label: "当前状态 · " + (cap.updated_at || ""), ts: cap.updated_at || "",
        vectors: current, stats: clone((() => {
          const out = {};
          ids.forEach((id) => { out[id] = agents[id].stats || { attempts: 0, successes: 0, failures: 0 }; });
          return out;
        })()), agent: null, dims: [], question: "",
      });
    } else if (frames.length > 1) {
      last.stats = clone((() => {
        const out = {};
        ids.forEach((id) => { out[id] = agents[id].stats || { attempts: 0, successes: 0, failures: 0 }; });
        return out;
      })());
    }
    return frames;
  }

  function currentFrame() { return S.frames[S.frame] || { vectors: {}, stats: {} }; }

  function frameCaption(frame) {
    const dims = (capData() || {}).dimensions || [];
    const detail = (frame.dims || []).map((dim) => {
      const before = frame.event && frame.event.before ? frame.event.before[dim] : null;
      const after = frame.event && frame.event.after ? frame.event.after[dim] : null;
      return GIS.meta.dimLabel(dim) + (before != null && after != null ? " " + Number(before).toFixed(3) + " → " + Number(after).toFixed(3) : "");
    }).join("、");
    return "<div class='row between wrap' style='gap:6px'><span>第 <b class='mono'>" + S.frame + "</b> / " + (S.frames.length - 1) +
      " 帧 · " + esc(frame.label) + (detail ? " · " + esc(detail) : "") + "</span>" +
      (frame.ts ? "<span class='chip mono'>" + esc(frame.ts) + "</span>" : "") + "</div>" +
      (frame.question ? "<div class='tiny faint' style='margin-top:4px'>" + esc(U.truncate(frame.question, 130)) + "</div>" : "");
  }

  function radarAgents() {
    const cap = capData() || {};
    const dims = cap.dimensions || [];
    const frame = currentFrame();
    return Object.keys(cap.agents || {}).sort().map((id) => ({
      id,
      name: (cap.agents[id] || {}).name,
      color: GIS.meta.agentColor(id),
      values: frame.vectors[id] || {},
    }));
  }

  function drawRadar() {
    const canvas = document.getElementById("capRadar");
    if (!canvas) return;
    const cap = capData() || {};
    const frame = currentFrame();
    const target = radarAgents();
    // 从上一帧平滑过渡
    const from = S.display;
    const to = {};
    target.forEach((a) => { to[a.id] = {}; (cap.dimensions || []).forEach((d) => { to[a.id][d] = Number((a.values || {})[d] || 0); }); });
    const start = performance.now();
    const fromValues = {};
    target.forEach((a) => {
      fromValues[a.id] = {};
      (cap.dimensions || []).forEach((d) => {
        fromValues[a.id][d] = from[a.id] && from[a.id][d] != null ? Number(from[a.id][d]) : Number((a.values || {})[d] || 0);
      });
    });
    if (S.anim) cancelAnimationFrame(S.anim);
    const step = (now) => {
      const t = Math.min(1, (now - start) / 420);
      const ease = 1 - Math.pow(1 - t, 3);
      const agentsNow = target.map((a) => {
        const vals = {};
        (cap.dimensions || []).forEach((d) => {
          vals[d] = fromValues[a.id][d] + (to[a.id][d] - fromValues[a.id][d]) * ease;
        });
        return { ...a, values: vals };
      });
      GIS.charts.radar(canvas, {
        dims: cap.dimensions || [], labels: (GIS.state.data || {}).labels,
        agents: agentsNow, highlight: S.highlight, showInitial: true,
        initial: cap.initial_capability,
      });
      S.display = {};
      agentsNow.forEach((a) => { S.display[a.id] = a.values; });
      if (t < 1) S.anim = requestAnimationFrame(step);
      else S.display = to;
    };
    S.anim = requestAnimationFrame(step);
  }

  function renderMatrix() {
    const box = document.getElementById("capMatrix");
    if (!box) return;
    const cap = capData() || {};
    const dims = cap.dimensions || [];
    const agents = cap.agents || {};
    const frame = currentFrame();
    const prev = S.frame > 0 ? S.frames[S.frame - 1] : null;
    let html = "<table class='matrix'><thead><tr><th>智能体</th>";
    dims.forEach((dim) => { html += "<th>" + esc(GIS.meta.dimLabel(dim)) + "</th>"; });
    html += "<th>尝试</th><th>成功</th><th>失败</th></tr></thead><tbody>";
    Object.keys(agents).sort().forEach((id) => {
      const st = (frame.stats && frame.stats[id]) || agents[id].stats || {};
      html += "<tr><td><div class='agent-cell'><span class='dot' style='background:" + GIS.meta.agentColor(id) + "'></span>智能体 " + esc(agents[id].name || id) + "</div></td>";
      dims.forEach((dim) => {
        const v = Number((frame.vectors[id] || {})[dim] || 0);
        let cls = "v";
        if (prev && prev.vectors[id] && S.frame > 0) {
          const pv = Number(prev.vectors[id][dim] || 0);
          if (v > pv + 1e-9) cls += " up";
          else if (v < pv - 1e-9) cls += " down";
        }
        html += "<td class='" + cls + "'>" + v.toFixed(4) + "<span class='cap-heat' style='display:block;margin-top:3px'><i style='width:" +
          (v * 100).toFixed(1) + "%;background:" + GIS.meta.agentColor(id) + "'></i></span></td>";
      });
      html += "<td class='v'>" + (st.attempts || 0) + "</td><td class='v'>" + (st.successes || 0) + "</td><td class='v'>" + (st.failures || 0) + "</td></tr>";
    });
    html += "</tbody></table>";
    box.innerHTML = html;
  }

  function renderLine() {
    const canvas = document.getElementById("capLines");
    if (!canvas) return;
    const cap = capData() || {};
    const dims = cap.dimensions || [];
    if (!S.dim || dims.indexOf(S.dim) < 0) S.dim = dims[0];
    const series = Object.keys(cap.agents || {}).sort().map((id) => ({
      values: S.frames.map((f) => ((f.vectors[id] || {})[S.dim] || 0)),
      color: GIS.meta.agentColor(id),
      dimmed: S.highlight && S.highlight !== id,
    }));
    GIS.charts.lines(canvas, {
      frames: S.frames,
      series,
      title: "维度：" + GIS.meta.dimLabel(S.dim) + " · 每帧为一次能力进化",
    });
  }

  function renderEvents() {
    const box = document.getElementById("capEvents");
    if (!box) return;
    const cap = capData() || {};
    const history = cap.history || [];
    if (!history.length) {
      box.innerHTML = GIS.ui.empty("还没有进化事件", "能力值只有经过执行评估才会变化。", "spark");
      return;
    }
    box.innerHTML = history.slice().reverse().map((e, revIdx) => {
      const idx = history.length - revIdx;
      const deltaSum = Object.keys(e.delta || {}).reduce((s, k) => s + Number(e.delta[k] || 0), 0);
      const detail = (e.dims || []).map((dim) =>
        GIS.meta.dimLabel(dim) + " " + Number((e.before || {})[dim] || 0).toFixed(3) + "→" + Number((e.after || {})[dim] || 0).toFixed(3)).join("、");
      return "<div class='evolution-item " + (idx === S.frame ? "current" : "") + "' data-frame='" + idx + "'>" +
        "<div class='evolution-top'><span class='dot' style='background:" + GIS.meta.agentColor(e.agent_id) + "'></span>" +
        "<b>智能体 " + esc(e.agent_name || GIS.meta.agentName(e.agent_id)) + "</b>" +
        "<span class='chip " + (e.outcome === "success" ? "ok" : "err") + "'>" + (e.outcome === "success" ? "成功" : "失败") + "</span>" +
        "<span class='delta " + GIS.ui.deltaClass(deltaSum) + "' style='margin-left:auto'>" + U.signed(deltaSum, 4) + "</span></div>" +
        "<div class='evolution-detail'>" + esc(detail) + " · " + esc(e.ts || "") + "</div>" +
        "<div class='tiny faint' style='margin-top:2px'>" + esc(U.truncate(e.question || "", 88)) + "</div></div>";
    }).join("");
    box.querySelectorAll("[data-frame]").forEach((el) => {
      el.addEventListener("click", () => { stop(); setFrame(Number(el.dataset.frame)); });
    });
  }

  function updateAll() {
    const frame = currentFrame();
    const cap = capData() || {};
    const caption = document.getElementById("frameCaption");
    if (caption) caption.innerHTML = frameCaption(frame);
    const slider = document.getElementById("capSlider");
    if (slider) { slider.max = String(S.frames.length - 1); slider.value = String(S.frame); }
    const label = document.getElementById("frameIndex");
    if (label) label.textContent = S.frame + " / " + (S.frames.length - 1);
    drawRadar(); renderMatrix(); renderLine(); renderEvents();
    const playBtn = document.getElementById("capPlay");
    if (playBtn) playBtn.innerHTML = S.playing ? GIS.ui.icon("pause") + "暂停" : GIS.ui.icon("play") + "播放进化";
  }

  function setFrame(index) {
    S.frame = Math.max(0, Math.min(S.frames.length - 1, index));
    updateAll();
  }

  function stop() {
    S.playing = false;
    if (S.timer) { clearInterval(S.timer); S.timer = null; }
    updateAll();
  }

  function play() {
    if (S.playing) { stop(); return; }
    S.playing = true;
    if (S.frame >= S.frames.length - 1) S.frame = 0;
    S.timer = setInterval(() => {
      if (S.frame >= S.frames.length - 1) { stop(); return; }
      S.frame += 1;
      updateAll();
    }, 1050);
    updateAll();
  }

  function statsHeader() {
    const cap = capData() || {};
    const dims = cap.dimensions || [];
    const agents = cap.agents || {};
    const init = Number(cap.initial_capability != null ? cap.initial_capability : 0.5);
    const ids = Object.keys(agents);
    let best = { agent: null, dim: null, value: -1, gain: 0 };
    let avg = 0;
    ids.forEach((id) => {
      dims.forEach((dim) => {
        const v = Number((agents[id].capabilities || {})[dim] || 0);
        avg += v;
        if (v - init > best.gain) best = { agent: id, dim, value: v, gain: v - init };
      });
    });
    avg = avg / Math.max(1, ids.length * dims.length);
    const events = (cap.history || []).length;
    return "<div class='kv-grid'>" +
      "<div class='kv'><dt>平均能力值</dt><dd class='mono'>" + avg.toFixed(4) + "</dd></div>" +
      "<div class='kv'><dt>进化事件</dt><dd>" + events + " 次</dd></div>" +
      "<div class='kv'><dt>最大分化</dt><dd>" + (best.agent ? "智能体 " + esc(GIS.meta.agentName(best.agent)) + " · " + esc(GIS.meta.dimLabel(best.dim)) : "无") + "</dd></div>" +
      "<div class='kv'><dt>相对初始增益</dt><dd class='mono' style='color:var(--ok)'>" + (best.gain > 0 ? U.signed(best.gain, 4) : "0.0000") + "</dd></div>" +
      "</div>";
  }

  function render() {
    const d = GIS.state.data || {};
    const cap = capData() || {};
    const dims = cap.dimensions || [];
    if (!S.dim || dims.indexOf(S.dim) < 0) S.dim = dims[0];
    const sourceNote = S.source === "real"
      ? "项目真实能力状态（data/agent_capabilities.json，只读）"
      : "演示会话能力状态（web/data/demo_state.json，由项目快照初始化）";
    return "<div class='stack-lg'>" +
      "<div class='card' style='padding:14px 18px'>" +
      "<div class='row between wrap'>" +
      "<div class='row wrap' style='gap:10px'>" +
      "<div class='segmented' id='capSource'>" +
      "<button data-source='demo' class='" + (S.source === "demo" ? "active" : "") + "'>演示会话</button>" +
      "<button data-source='real' class='" + (S.source === "real" ? "active" : "") + "'>项目真实</button></div>" +
      "<span class='tiny muted'>" + esc(sourceNote) + "</span></div>" +
      "<div class='row wrap' style='gap:6px'>" +
      "<a class='btn sm ghost' href='/artifact/capability-chart.html' target='_blank' rel='noopener'>" + GIS.ui.icon("radar") + "项目原始动态图</a>" +
      "<button class='btn sm ghost' data-cap-action='sync'" + (S.source === "real" ? " disabled" : "") + ">" + GIS.ui.icon("download") + "同步真实快照</button>" +
      "<button class='btn sm danger' id='resetAllCaps'" + (S.source === "real" ? " disabled" : "") + " title='将全部智能体能力向量恢复为初始 0.500'>" +
      GIS.ui.icon("reset") + "重置所有智能体</button>" +
      "</div></div></div>" +

      statsHeader() +

      "<div class='grid' style='grid-template-columns:minmax(0,1fr) minmax(430px,.9fr);align-items:start'>" +
      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("radar") + "</span>" +
      "<div><h2>动态能力向量图</h2><p class='sub'>拖动时间轴回放每一次执行后的能力变化；虚线为初始均衡基线 0.50</p></div>" +
      "<div class='right'><span class='chip mono' id='frameIndex'>0 / 0</span></div></div>" +
      "<div class='radar-wrap'><canvas id='capRadar'></canvas></div>" +
      "<div class='radar-legend' id='capLegend'>" + Object.keys(cap.agents || {}).sort().map((id) =>
        "<button class='chip " + (S.highlight === id ? "solid" : "muted") + "' data-highlight='" + id + "'>" +
        "<span class='dot' style='background:" + (S.highlight === id ? "#fff" : GIS.meta.agentColor(id)) + "'></span>智能体 " + esc(GIS.meta.agentName(id)) + "</button>").join("") +
      "<button class='chip " + (S.highlight ? "muted" : "brand") + "' data-highlight=''>全部</button></div>" +
      "<div class='timeline-controls' style='margin-top:10px'>" +
      "<button class='btn sm' id='capPlay'>" + GIS.ui.icon("play") + "播放进化</button>" +
      "<input type='range' id='capSlider' min='0' max='0' value='0' aria-label='进化时间轴'>" +
      "<button class='btn sm ghost' id='capLatest'>最新</button></div>" +
      "<div class='frame-caption' id='frameCaption' style='margin-top:10px'></div>" +
      "<div class='hr-soft'></div><div class='grid grid-2' style='gap:8px'>" + dims.map((dim) =>
        "<div><b class='small'>" + esc(GIS.meta.dimLabel(dim)) + "</b><div class='tiny muted'>" + esc(GIS.meta.dimGlossary(dim)) + "</div></div>").join("") + "</div>" +
      "</div>" +

      "<div class='stack'>" +
      "<div class='card'><div class='card-head'><div><h3>能力矩阵</h3><p class='sub'>当前帧数值；绿色上升、红色回落</p></div></div>" +
      "<div id='capMatrix' style='overflow:auto'></div></div>" +
      "<div class='card'><div class='card-head'><div><h3>维度趋势</h3><p class='sub'>切换维度查看各智能体的进化曲线</p></div></div>" +
      "<div class='chip-row' id='capDimTabs' style='margin-bottom:8px'>" + dims.map((dim) =>
        "<button class='filter-pill " + (S.dim === dim ? "active" : "") + "' data-dim='" + dim + "'>" + esc(GIS.meta.dimLabel(dim)) + "</button>").join("") + "</div>" +
      "<canvas id='capLines' style='width:100%;height:190px'></canvas></div>" +
      "</div></div>" +

      "<div class='card'><div class='card-head'><span class='card-title-icon'>" + GIS.ui.icon("spark") + "</span>" +
      "<div><h2>进化记录</h2><p class='sub'>点击任意记录可跳到该帧；只更新子任务所需维度</p></div>" +
      "<div class='right'><span class='chip'>" + (cap.history || []).length + " 次</span></div></div>" +
      "<div class='evolution-list' id='capEvents'></div></div>" +
      "</div>";
  }

  function refreshData() {
    if (GIS.state.mode === "static") {
      S.frames = buildFrames(capData());
      if (S.frame >= S.frames.length) S.frame = S.frames.length - 1;
      updateAll();
      return;
    }
    const source = S.source;
    GIS.api.capability(source).then((payload) => {
      if (!payload) return;
      if (source === "real") GIS.state.data.real_capability = payload;
      else {
        GIS.state.data.capability = payload;
        GIS.state.data.counts.evolution_events = (payload.history || []).length;
      }
      S.frames = buildFrames(capData());
      S.frame = S.frames.length - 1;
      updateAll();
    }).catch(() => {
      S.frames = buildFrames(capData());
      S.frame = S.frames.length - 1;
      updateAll();
    });
  }

  function mount() {
    S.frames = buildFrames(capData());
    S.frame = S.frames.length - 1;
    updateAll();

    const slider = document.getElementById("capSlider");
    if (slider) slider.addEventListener("input", (e) => { stop(); setFrame(Number(e.target.value)); });
    const playBtn = document.getElementById("capPlay");
    if (playBtn) playBtn.addEventListener("click", play);
    const latest = document.getElementById("capLatest");
    if (latest) latest.addEventListener("click", () => { stop(); setFrame(S.frames.length - 1); });

    document.querySelectorAll("[data-source]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = btn.dataset.source;
        if (next === S.source) return;
        stop();
        S.source = next;
        S.highlight = null;
        GIS.toast(next === "real" ? "已切换到项目真实能力状态（只读）" : "已切换到演示会话能力状态", "ok");
        GIS.refreshView();
      });
    });

    document.querySelectorAll("[data-highlight]").forEach((btn) => {
      btn.addEventListener("click", () => {
        S.highlight = btn.dataset.highlight || null;
        document.querySelectorAll("[data-highlight]").forEach((b) => {
          const active = (b.dataset.highlight || null) === S.highlight;
          b.classList.toggle("muted", !active);
          b.classList.toggle("solid", active && !!S.highlight);
          b.classList.toggle("brand", active && !S.highlight);
        });
        updateAll();
      });
    });

    document.querySelectorAll("[data-dim]").forEach((btn) => {
      btn.addEventListener("click", () => {
        S.dim = btn.dataset.dim;
        document.querySelectorAll("[data-dim]").forEach((b) => b.classList.toggle("active", b.dataset.dim === S.dim));
        renderLine();
      });
    });

    const syncBtn = document.querySelector("[data-cap-action='sync']");
    if (syncBtn) {
      syncBtn.addEventListener("click", async () => {
        if (S.source !== "demo") { GIS.toast("项目真实能力状态为只读，切回演示会话后可操作", "warn"); return; }
        const ok = await GIS.confirm(
          "同步项目真实快照",
          "用项目 data/agent_capabilities.json 的真实状态覆盖演示会话（包含当前全部进化历史）。",
          "同步"
        );
        if (!ok) return;
        try {
          const payload = await GIS.api.resetCapability("real", false);
          GIS.state.data.capability = payload.capability;
          GIS.state.data.counts.evolution_events = (payload.capability.history || []).length;
          GIS.toast("已同步项目真实能力快照", "ok");
          if (window.GIS.refreshNav) window.GIS.refreshNav();
          GIS.refreshView();
        } catch (err) {
          GIS.toast(err.message || "操作失败", "err");
        }
      });
    }

    const resetAll = document.getElementById("resetAllCaps");
    if (resetAll) {
      resetAll.addEventListener("click", () => {
        if (S.source !== "demo") {
          GIS.toast("当前查看的是项目真实状态（只读），请切回演示会话后重置", "warn");
          return;
        }
        GIS.ui.openCapabilityReset();
      });
    }

    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => { drawRadar(); renderLine(); });
      const radar = document.getElementById("capRadar");
      if (radar) ro.observe(radar.parentElement);
    }
  }

  GIS.views.capability = {
    title: "能力进化",
    subtitle: "回放每一次执行后的能力向量变化",
    render,
    mount,
    unmount() {
      stop();
      if (S.anim) { cancelAnimationFrame(S.anim); S.anim = null; }
    },
    forceSource(source) {
      S.source = source === "real" ? "real" : "demo";
      S.highlight = null;
      S.frames = [];
      S.frame = 0;
    },
    async before() {
      await GIS.api.bootstrap();
      const qp = GIS.state.query || {};
      if (qp.source === "real" || qp.source === "demo") S.source = qp.source;
      const d = GIS.state.data;
      if (S.frames.length === 0) {
        // 首次进入时若已有演示数据则直接使用
        S.frames = buildFrames(S.source === "real" ? d.real_capability : d.capability);
      }
    },
  };
})();
