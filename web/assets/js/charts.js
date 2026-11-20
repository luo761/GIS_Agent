/* ============================================================
   Canvas 图表：雷达图 / 进化折线 / 环形进度 / 计划 DAG / 迷你趋势
   全部手写，无第三方库。
   ============================================================ */
(function () {
  "use strict";
  const GIS = window.GIS;
  const C = (GIS.charts = GIS.charts || {});

  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const palette = () => ({
    ink: cssVar("--ink") || "#16233a",
    muted: cssVar("--muted") || "#74839a",
    faint: cssVar("--faint") || "#9aa8bd",
    line: cssVar("--line") || "#e2e9f3",
    grid: cssVar("--panel-3") || "#eef4fb",
    panel: cssVar("--panel") || "#ffffff",
    brand: cssVar("--brand") || "#2563eb",
    ok: cssVar("--ok") || "#0f9d63",
    err: cssVar("--err") || "#dc2626",
  });

  function setupCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || canvas.parentElement.clientWidth || 520;
    const h = canvas.clientHeight || 360;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    return { ctx, w, h };
  }
  C.setupCanvas = setupCanvas;

  function roundRect(ctx, x, y, w, h, r) {
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
  }
  C.roundRect = roundRect;

  /* ---------------------------------------------------------- 雷达图 */
  C.radar = function (canvas, options) {
    const opt = options || {};
    const dims = opt.dims || [];
    const labels = opt.labels || {};
    const agents = opt.agents || [];
    const highlight = opt.highlight || null;
    const { ctx, w, h } = setupCanvas(canvas);
    const col = palette();
    const n = dims.length;
    if (!n) return;
    const cx = w / 2;
    const cy = h / 2 + (opt.offsetY || 0);
    const R = Math.max(60, Math.min(w, h) / 2 - (opt.pad || 62));
    const angle = (i) => -Math.PI / 2 + (2 * Math.PI * i) / n;
    const pt = (i, v) => [cx + Math.cos(angle(i)) * R * v, cy + Math.sin(angle(i)) * R * v];

    // 网格
    [0.25, 0.5, 0.75, 1].forEach((r, ringIdx) => {
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const p = pt(i, r);
        if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
      }
      ctx.closePath();
      ctx.strokeStyle = ringIdx === 3 ? col.line : col.grid;
      ctx.lineWidth = ringIdx === 3 ? 1.2 : 1;
      ctx.stroke();
    });
    // 轴线 + 标签
    for (let i = 0; i < n; i++) {
      const p = pt(i, 1);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(p[0], p[1]);
      ctx.strokeStyle = col.grid;
      ctx.stroke();
      const lp = pt(i, 1.18);
      ctx.font = "500 11.5px 'Microsoft YaHei', sans-serif";
      ctx.fillStyle = col.muted;
      ctx.textAlign = Math.abs(lp[0] - cx) < 8 ? "center" : (lp[0] > cx ? "left" : "right");
      ctx.textBaseline = "middle";
      const label = labels[dims[i]] || dims[i];
      ctx.fillText(label, lp[0], lp[1]);
      if (opt.showValues && agents.length === 1) {
        const v = Number((agents[0].values || {})[dims[i]] || 0);
        ctx.font = "600 10px Consolas, monospace";
        ctx.fillStyle = col.brand;
        ctx.fillText(v.toFixed(3), lp[0], lp[1] + 14);
      }
    }

    // 基线 0.5 参考环
    if (opt.showInitial) {
      const init = Number(opt.initial == null ? 0.5 : opt.initial);
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const p = pt(i, init);
        if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
      }
      ctx.closePath();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = col.faint;
      ctx.globalAlpha = 0.55;
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    // 每个智能体
    agents.forEach((agent) => {
      const values = agent.values || {};
      const isHi = !highlight || highlight === agent.id;
      ctx.beginPath();
      dims.forEach((d, i) => {
        const p = pt(i, Math.max(0, Math.min(1, Number(values[d] || 0))));
        if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
      });
      ctx.closePath();
      ctx.fillStyle = hexA(agent.color || col.brand, isHi ? 0.13 : 0.04);
      ctx.fill();
      ctx.strokeStyle = hexA(agent.color || col.brand, isHi ? 1 : 0.28);
      ctx.lineWidth = highlight === agent.id ? 2.8 : (highlight ? 1.4 : 2);
      ctx.stroke();
      if (isHi) {
        dims.forEach((d, i) => {
          const p = pt(i, Math.max(0, Math.min(1, Number(values[d] || 0))));
          ctx.beginPath();
          ctx.arc(p[0], p[1], highlight === agent.id ? 3.6 : 2.6, 0, Math.PI * 2);
          ctx.fillStyle = agent.color || col.brand;
          ctx.fill();
        });
      }
    });

    // 中心原点
    ctx.beginPath();
    ctx.arc(cx, cy, 2.2, 0, Math.PI * 2);
    ctx.fillStyle = col.faint;
    ctx.fill();
    ctx.font = "9px Consolas, monospace";
    ctx.fillStyle = col.faint;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText("0.00", cx + 5, cy + 4);
  };

  function hexA(hex, alpha) {
    const h = String(hex || "#2563eb").replace("#", "");
    const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
    const r = parseInt(full.slice(0, 2), 16);
    const g = parseInt(full.slice(2, 4), 16);
    const b = parseInt(full.slice(4, 6), 16);
    return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
  }
  C.hexA = hexA;

  /* ---------------------------------------------------------- 进化折线 */
  C.lines = function (canvas, options) {
    const opt = options || {};
    const frames = opt.frames || [];
    const series = opt.series || [];
    const { ctx, w, h } = setupCanvas(canvas);
    const col = palette();
    const padL = 38, padR = 12, padT = 14, padB = 24;
    const iw = Math.max(20, w - padL - padR);
    const ih = Math.max(20, h - padT - padB);
    const maxLen = Math.max(1, frames.length - 1);

    // 网格
    [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
      const y = padT + ih * (1 - v);
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.strokeStyle = v === 0 || v === 1 ? col.line : col.grid;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.font = "9px Consolas, monospace";
      ctx.fillStyle = col.faint;
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(v.toFixed(2), padL - 6, y);
    });
    // x 轴标签
    const ticks = Math.min(6, frames.length);
    for (let t = 0; t < ticks; t++) {
      const idx = Math.round((maxLen * t) / Math.max(1, ticks - 1));
      const x = padL + (iw * idx) / maxLen;
      ctx.font = "9px Consolas, monospace";
      ctx.fillStyle = col.faint;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(String(idx), x, h - padB + 6);
    }
    if (!frames.length) {
      ctx.font = "11px 'Microsoft YaHei', sans-serif";
      ctx.fillStyle = col.faint;
      ctx.textAlign = "center";
      ctx.fillText("暂无进化记录", w / 2, h / 2);
      return;
    }
    // 系列
    series.forEach((s) => {
      const values = s.values || [];
      ctx.beginPath();
      values.forEach((v, i) => {
        const x = padL + (iw * i) / maxLen;
        const y = padT + ih * (1 - Math.max(0, Math.min(1, Number(v || 0))));
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = s.color || col.brand;
      ctx.lineWidth = s.width || 1.8;
      ctx.globalAlpha = s.dimmed ? 0.3 : 1;
      ctx.stroke();
      ctx.globalAlpha = 1;
      const last = values.length - 1;
      if (last >= 0) {
        const x = padL + (iw * last) / maxLen;
        const y = padT + ih * (1 - Math.max(0, Math.min(1, Number(values[last] || 0))));
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = s.color || col.brand;
        ctx.fill();
      }
    });
    // 标题
    if (opt.title) {
      ctx.font = "10px 'Microsoft YaHei', sans-serif";
      ctx.fillStyle = col.muted;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(opt.title, padL, 1);
    }
  };

  /* ---------------------------------------------------------- 环形 */
  C.donut = function (canvas, options) {
    const opt = options || {};
    const ratio = Math.max(0, Math.min(1, Number(opt.ratio || 0)));
    const { ctx, w, h } = setupCanvas(canvas);
    const col = palette();
    const cx = w / 2, cy = h / 2;
    const r = Math.min(w, h) / 2 - 10;
    const lw = Math.max(8, r * 0.22);
    ctx.beginPath();
    ctx.arc(cx, cy, r - lw / 2, 0, Math.PI * 2);
    ctx.strokeStyle = col.grid;
    ctx.lineWidth = lw;
    ctx.stroke();
    const start = -Math.PI / 2;
    const end = start + Math.PI * 2 * ratio;
    const grad = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
    grad.addColorStop(0, opt.from || col.brand);
    grad.addColorStop(1, opt.to || "#06b6d4");
    ctx.beginPath();
    ctx.arc(cx, cy, r - lw / 2, start, end);
    ctx.strokeStyle = grad;
    ctx.lineWidth = lw;
    ctx.lineCap = "round";
    ctx.stroke();
    ctx.lineCap = "butt";
  };

  /* ---------------------------------------------------------- DAG */
  C.dag = function (canvas, plan, options) {
    const opt = options || {};
    const col = palette();
    const nodes = (plan && plan.nodes) || [];
    const edges = (plan && plan.edges) || [];
    canvas.style.width = "";
    let view = setupCanvas(canvas);
    let ctx = view.ctx;
    let w = view.w;
    let h = view.h;
    canvas._hitboxes = [];
    if (!nodes.length) {
      ctx.font = "11px 'Microsoft YaHei', sans-serif";
      ctx.fillStyle = col.faint;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("暂无计划节点", w / 2, h / 2);
      return;
    }

    // 分层：最长路径
    const byId = {};
    nodes.forEach((n) => { byId[n.id] = n; });
    const depth = {};
    const resolving = {};
    function layerOf(id) {
      if (depth[id] != null) return depth[id];
      if (resolving[id]) return 0;
      resolving[id] = true;
      const node = byId[id];
      const deps = (node && node.depends_on) || [];
      depth[id] = deps.length ? Math.max.apply(null, deps.map((d) => (byId[d] ? layerOf(d) + 1 : 1))) : 0;
      resolving[id] = false;
      return depth[id];
    }
    nodes.forEach((n) => layerOf(n.id));
    const maxLayer = Math.max.apply(null, Object.values(depth));
    const layers = [];
    for (let i = 0; i <= maxLayer; i++) layers.push([]);
    nodes.forEach((n) => { layers[depth[n.id]].push(n); });

    // 节点较多时给画布一个最小宽度，由容器横向滚动，避免节点重叠
    const needW = Math.max(300, (maxLayer + 1) * 92 + 48);
    if (needW > w + 2) {
      canvas.style.width = needW + "px";
      view = setupCanvas(canvas);
      ctx = view.ctx;
      w = view.w;
      h = view.h;
    }

    const padX = 22;
    const availW = w - padX * 2;
    const colW = availW / (maxLayer + 1);
    const nodeW = Math.max(64, Math.min(120, colW - 14));
    const nodeH = 46;
    const gapY = (h - 30 - nodeH) / Math.max(1, Math.max.apply(null, layers.map((l) => l.length)));
    const pos = {};
    layers.forEach((list, li) => {
      const startY = (h - (list.length * nodeH + (list.length - 1) * 10)) / 2 + 8;
      list.forEach((n, ni) => {
        const x = padX + colW * li + colW / 2 - nodeW / 2;
        const y = startY + ni * (nodeH + 10);
        pos[n.id] = { x, y, w: nodeW, h: nodeH };
      });
    });
    const colorFor = (action) => {
      const a = String(action || "");
      if (a.includes("query")) return "#2563eb";
      if (a.includes("buffer")) return "#0891b2";
      if (a.includes("union")) return "#7c3aed";
      if (a.includes("clip")) return "#d97706";
      if (a.includes("measure")) return "#0f9d63";
      if (a.includes("summarize")) return "#c27803";
      if (a.includes("ratio")) return "#dc2626";
      if (a.includes("intersection")) return "#7c3aed";
      return "#64748b";
    };

    // 边
    edges.forEach(([from, to]) => {
      const a = pos[from], b = pos[to];
      if (!a || !b) return;
      const x1 = a.x + a.w, y1 = a.y + a.h / 2;
      const x2 = b.x, y2 = b.y + b.h / 2;
      const mid = (x1 + x2) / 2;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.bezierCurveTo(mid, y1, mid, y2, x2 - 3, y2);
      ctx.strokeStyle = hexA(col.brand, 0.4);
      ctx.lineWidth = 1.3;
      ctx.stroke();
      // 箭头
      ctx.beginPath();
      ctx.moveTo(x2 - 4, y2 - 3.2);
      ctx.lineTo(x2, y2);
      ctx.lineTo(x2 - 4, y2 + 3.2);
      ctx.strokeStyle = hexA(col.brand, 0.55);
      ctx.lineWidth = 1.3;
      ctx.stroke();
    });

    // 节点
    nodes.forEach((n) => {
      const p = pos[n.id];
      if (!p) return;
      const accent = colorFor(n.action);
      const active = opt.highlight === n.id;
      ctx.save();
      if (active) {
        ctx.shadowColor = hexA(accent, 0.5);
        ctx.shadowBlur = 14;
      }
      roundRect(ctx, p.x, p.y, p.w, p.h, 9);
      ctx.fillStyle = col.panel;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = active ? accent : hexA(accent, 0.32);
      ctx.lineWidth = active ? 2 : 1.2;
      ctx.stroke();
      // 左侧色条
      ctx.save();
      roundRect(ctx, p.x, p.y, p.w, p.h, 9);
      ctx.clip();
      ctx.fillStyle = accent;
      ctx.fillRect(p.x, p.y, 3.5, p.h);
      ctx.restore();
      // 文本
      ctx.fillStyle = col.ink;
      ctx.font = "600 10.5px 'Microsoft YaHei', sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      let label = String(n.label || n.action || "");
      while (ctx.measureText(label).width > p.w - 20 && label.length > 3) label = label.slice(0, -2) + "…";
      ctx.fillText(label, p.x + 10, p.y + p.h / 2 - 7);
      ctx.font = "9px Consolas, monospace";
      ctx.fillStyle = col.faint;
      ctx.fillText(n.id || "", p.x + 10, p.y + p.h / 2 + 9);
      // 右侧序号圆点
      ctx.beginPath();
      ctx.arc(p.x + p.w - 10, p.y + p.h / 2, 2.4, 0, Math.PI * 2);
      ctx.fillStyle = hexA(accent, 0.7);
      ctx.fill();
      ctx.restore();
      canvas._hitboxes.push({ id: n.id, x: p.x, y: p.y, w: p.w, h: p.h, node: n });
    });

    // hover / click
    if (!canvas._dagBound) {
      canvas._dagBound = true;
      canvas.style.cursor = "default";
      canvas.addEventListener("mousemove", (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left, y = e.clientY - rect.top;
        const hit = (canvas._hitboxes || []).find((b) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h);
        canvas.style.cursor = hit ? "pointer" : "default";
        canvas.title = hit ? hit.node.action + " · " + hit.id : "";
      });
      canvas.addEventListener("click", (e) => {
        if (!opt.onNodeClick) return;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left, y = e.clientY - rect.top;
        const hit = (canvas._hitboxes || []).find((b) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h);
        if (hit) opt.onNodeClick(hit.node);
      });
    }
  };

  /* ---------------------------------------------------------- 迷你趋势 */
  C.sparkline = function (canvas, values, color) {
    const { ctx, w, h } = setupCanvas(canvas);
    const vals = (values || []).map(Number);
    if (!vals.length) return;
    const min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    const span = max - min || 1;
    const pad = 3;
    ctx.beginPath();
    vals.forEach((v, i) => {
      const x = pad + ((w - pad * 2) * i) / Math.max(1, vals.length - 1);
      const y = h - pad - ((h - pad * 2) * (v - min)) / span;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color || "#2563eb";
    ctx.lineWidth = 1.6;
    ctx.stroke();
    const last = vals.length - 1;
    const x = pad + ((w - pad * 2) * last) / Math.max(1, vals.length - 1);
    const y = h - pad - ((h - pad * 2) * (vals[last] - min)) / span;
    ctx.beginPath();
    ctx.arc(x, y, 2.2, 0, Math.PI * 2);
    ctx.fillStyle = color || "#2563eb";
    ctx.fill();
  };
})();
