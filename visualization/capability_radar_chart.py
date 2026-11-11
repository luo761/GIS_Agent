"""动态能力向量图。

一张自包含的 HTML（data/capability_vector_chart.html）：雷达图 + 时间轴，可回放
"初始均衡 → 每次执行后的能力演化"全过程；同时输出当前状态的静态 PNG
（data/capability_vector_chart.png，若环境装有 matplotlib）。

不依赖任何外部 CDN / 第三方 JS，双击即可在浏览器打开。
"""
from __future__ import annotations

import html
import json
import time
import unicodedata
from pathlib import Path
from typing import Any

from config import settings

PLACEHOLDER = "__CAPABILITY_DATA__"

_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2"]


# ---------------------------------------------------------------- 公共入口
def render(snapshot: dict[str, Any], *, html_path: str | Path | None = None,
           png_path: str | Path | None = None) -> dict[str, str | None]:
    """按当前快照重绘能力向量图，返回生成的文件路径。"""
    out: dict[str, str | None] = {"html": None, "png": None}
    try:
        out["html"] = str(render_html(snapshot, html_path))
    except Exception:  # 图表失败不应影响主流程
        out["html"] = None
    try:
        out["png"] = render_png(snapshot, png_path)
    except Exception:
        out["png"] = None
    return out


# ---------------------------------------------------------------- HTML
def render_html(snapshot: dict[str, Any], path: str | Path | None = None) -> Path:
    path = Path(path or settings.CAPABILITY_CHART_HTML)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    document = _TEMPLATE.replace(PLACEHOLDER, payload).replace(
        "__GENERATED_AT__", html.escape(snapshot.get("updated_at") or
                                        time.strftime("%Y-%m-%d %H:%M:%S"))
    )
    path.write_text(document, encoding="utf-8")
    return path


# ---------------------------------------------------------------- PNG
def render_png(snapshot: dict[str, Any], path: str | Path | None = None) -> str | None:
    """静态快照（当前向量）。matplotlib 不可用时返回 None。"""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except Exception:
        return None

    available = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
                 "Source Han Sans SC", "Arial Unicode MS", "DejaVu Sans"):
        if cand in available:
            matplotlib.rcParams["font.sans-serif"] = [cand]
            break
    matplotlib.rcParams["axes.unicode_minus"] = False

    dims: list[str] = snapshot["dimensions"]
    labels: dict[str, str] = snapshot.get("labels", {})
    agents: dict[str, Any] = snapshot["agents"]
    n = len(dims)
    angles = [2 * 3.141592653589793 * i / n for i in range(n)]

    path = Path(path or settings.CAPABILITY_CHART_PNG)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(7.6, 7.6), dpi=150)
    ax = fig.add_subplot(projection="polar")
    ax.set_theta_offset(3.141592653589793 / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 1)
    ax.set_xticks(angles)
    ax.set_xticklabels([labels.get(d, d) for d in dims], fontsize=11)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels([])          # 环值统一写在图注里，避免与折线重叠
    ax.set_title("智能体能力向量图（动态进化）", fontsize=14, pad=24)

    for i, aid in enumerate(sorted(agents)):
        caps = agents[aid]["capabilities"]
        vals = [float(caps.get(d, 0.0)) for d in dims]
        vals_c = vals + vals[:1]
        ang_c = angles + angles[:1]
        color = _COLORS[i % len(_COLORS)]
        ax.plot(ang_c, vals_c, color=color, linewidth=2, label=f"智能体 {agents[aid]['name']}")
        ax.fill(ang_c, vals_c, color=color, alpha=0.08)

    ax.legend(loc="upper right", bbox_to_anchor=(1.18, 1.10), fontsize=9, frameon=False)
    fig.text(0.02, 0.02, f"同心环：0.25 / 0.50 / 0.75 / 1.00｜更新于 {snapshot.get('updated_at', '')}"
                         f"｜共 {len(snapshot.get('history', []))} 次能力进化",
             fontsize=8, color="#666")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


# ---------------------------------------------------------------- 文本表
def _w(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - _w(text))
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def render_ascii(snapshot: dict[str, Any]) -> str:
    """控制台版本的能力向量表。"""
    dims: list[str] = snapshot["dimensions"]
    labels: dict[str, str] = snapshot.get("labels", {})
    agents: dict[str, Any] = snapshot["agents"]
    name_w = max([6] + [_w("智能体")] + [_w(f"智能体{a['name']}") for a in agents.values()])
    col_w = 10
    head = _pad("智能体", name_w) + "".join(
        _pad(labels.get(d, d), col_w, "center") for d in dims
    ) + _pad("尝试", 6, "center") + _pad("成功", 6, "center") + _pad("失败", 6, "center")
    total_w = _w(head)
    lines = [head, "-" * total_w]
    for aid in sorted(agents):
        a = agents[aid]
        caps = a["capabilities"]
        st = a.get("stats", {})
        lines.append(
            _pad(f"智能体{a['name']}", name_w)
            + "".join(_pad(f"{float(caps.get(d, 0)):.4f}", col_w, "center") for d in dims)
            + _pad(str(st.get("attempts", 0)), 6, "center")
            + _pad(str(st.get("successes", 0)), 6, "center")
            + _pad(str(st.get("failures", 0)), 6, "center")
        )
    lines.append("-" * total_w)
    lines.append(f"初始经验值：{snapshot.get('initial_capability', 0.5):.2f}｜"
                 f"进化次数：{len(snapshot.get('history', []))}｜"
                 f"更新于 {snapshot.get('updated_at', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 模板
_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>智能体能力向量图（动态进化）</title>
<style>
  :root { --bg:#f6f8fb; --card:#ffffff; --line:#e3e8f0; --ink:#1f2937; --muted:#6b7280; }
  * { box-sizing: border-box; }
  body { margin:0; padding:20px; background:var(--bg); color:var(--ink);
         font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",system-ui,sans-serif; }
  h1 { font-size:19px; margin:0 0 2px; }
  .sub { color:var(--muted); font-size:12px; margin-bottom:14px; }
  .layout { display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }
  .chart-card { flex:0 0 auto; }
  canvas { width:520px; height:520px; display:block; }
  .side { flex:1 1 420px; min-width:360px; display:flex; flex-direction:column; gap:12px; }
  .controls { display:flex; align-items:center; gap:10px; margin-top:10px; }
  button { border:1px solid var(--line); background:#fff; color:var(--ink); border-radius:8px;
           padding:6px 12px; font-size:12px; cursor:pointer; }
  button:hover { border-color:#2563eb; color:#2563eb; }
  input[type=range] { flex:1; accent-color:#2563eb; }
  .frame-label { font-size:12px; color:var(--muted); margin-top:8px; line-height:1.5;
                 min-height:34px; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th, td { padding:5px 6px; text-align:center; border-bottom:1px solid #eef1f6; }
  th { color:var(--muted); font-weight:500; }
  td.agent { text-align:left; font-weight:600; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }
  .up { background:#e8f7ee; color:#15803d; }
  .down { background:#fdeaea; color:#b91c1c; }
  .events { max-height:250px; overflow:auto; font-size:12px; }
  .event { padding:6px 8px; border-radius:8px; margin-bottom:4px; background:#f8fafc;
           border:1px solid #eef1f6; line-height:1.45; }
  .event.current { outline:2px solid #2563eb; background:#eff6ff; }
  .tag { display:inline-block; padding:1px 6px; border-radius:6px; font-size:11px; margin-right:6px; }
  .tag.ok { background:#e8f7ee; color:#15803d; }
  .tag.bad { background:#fdeaea; color:#b91c1c; }
  .hint { font-size:11px; color:var(--muted); margin-top:8px; line-height:1.6; }
</style>
</head>
<body>
<h1>智能体能力向量图（动态进化）</h1>
<div class="sub">初始所有能力值 = 0.50（能力完全均衡，路由随机）｜能力只随成功/失败经验进化
 ｜更新于 __GENERATED_AT__</div>
<div class="layout">
  <div class="card chart-card">
    <canvas id="radar"></canvas>
    <div class="controls">
      <button id="play">▶ 播放进化</button>
      <input id="slider" type="range" min="0" max="0" value="0">
      <button id="latest">最新</button>
    </div>
    <div class="frame-label" id="frameLabel"></div>
  </div>
  <div class="side">
    <div class="card">
      <table id="capTable"></table>
    </div>
    <div class="card">
      <div style="font-size:13px;font-weight:600;margin-bottom:8px;">进化记录</div>
      <div class="events" id="events"></div>
      <div class="hint">拖动时间轴可回放每一次执行后的能力变化；绿色为能力上升（成功经验），
        红色为下降（失败经验）。刷新页面即可看到最新状态。</div>
    </div>
  </div>
</div>
<script>
const D = __CAPABILITY_DATA__;
const DIMS = D.dimensions;
const LABELS = D.labels || {};
const AGENTS = Object.keys(D.agents).sort();
const COLORS = ["#2563eb","#dc2626","#16a34a","#d97706","#7c3aed","#0891b2"];
const INIT = Number(D.initial_capability);

function colorOf(a){ return COLORS[AGENTS.indexOf(a) % COLORS.length]; }
function emptyStats(){
  const s = {};
  AGENTS.forEach(a => s[a] = { attempts:0, successes:0, failures:0 });
  return s;
}
function copyStats(s){ return JSON.parse(JSON.stringify(s)); }
function initialVectors(){
  const v = {};
  AGENTS.forEach(a => { v[a] = {}; DIMS.forEach(d => v[a][d] = INIT); });
  return v;
}

/* ---------- 构造帧序列：初始 → 每次进化 ---------- */
const frames = [];
frames.push({
  label: "初始状态：所有智能体的所有能力值均为 " + INIT.toFixed(2) + "，完全均衡",
  ts: "",
  vectors: initialVectors(),
  stats: emptyStats(),
  agent: null
});
const vectors = initialVectors();
const stats = emptyStats();
(D.history || []).forEach(function(e){
  vectors[e.agent_id] = e.vector_after;
  const st = stats[e.agent_id];
  st.attempts += 1;
  if (e.outcome === "success") st.successes += 1; else st.failures += 1;
  const detail = e.dims.map(function(d){
    return (LABELS[d] || d) + " " + Number(e.before[d]).toFixed(3) + "→" + Number(e.after[d]).toFixed(3);
  }).join("、");
  frames.push({
    label: e.ts + " · 智能体 " + e.agent_name + (e.outcome === "success" ? " 成功" : " 失败")
           + " · " + detail,
    ts: e.ts,
    vectors: JSON.parse(JSON.stringify(vectors)),
    stats: copyStats(stats),
    agent: e.agent_id,
    dims: e.dims
  });
});
/* 末帧用落盘的当前真实状态，避免与历史推演不一致 */
const last = frames[frames.length - 1];
const curVectors = {};
const curStats = {};
AGENTS.forEach(function(a){
  curVectors[a] = {};
  DIMS.forEach(function(d){ curVectors[a][d] = Number(D.agents[a].capabilities[d]); });
  curStats[a] = D.agents[a].stats || { attempts:0, successes:0, failures:0 };
});
if (JSON.stringify(curVectors) !== JSON.stringify(last.vectors)) {
  frames.push({ label: "当前状态 " + (D.updated_at || ""), ts: D.updated_at || "",
                vectors: curVectors, stats: curStats, agent: null, dims: [] });
} else {
  last.stats = curStats;
}

let idx = frames.length - 1;
let timer = null;

/* ---------- 雷达图 ---------- */
const canvas = document.getElementById("radar");
const ctx = canvas.getContext("2d");

function drawRadar(frame, prev){
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 520, cssH = canvas.clientHeight || 520;
  canvas.width = cssW * dpr; canvas.height = cssH * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const n = DIMS.length;
  const cx = cssW / 2, cy = cssH / 2 + 4;
  const R = Math.min(cssW, cssH) / 2 - 64;
  const angle = i => -Math.PI / 2 + 2 * Math.PI * i / n;
  const pt = (i, v) => [cx + Math.cos(angle(i)) * R * v, cy + Math.sin(angle(i)) * R * v];

  /* 网格 */
  [0.25, 0.5, 0.75, 1.0].forEach(function(r){
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const p = pt(i, r);
      i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
    }
    ctx.closePath();
    ctx.strokeStyle = (r === 1.0) ? "#c9d3e3" : "#e8edf5";
    ctx.lineWidth = 1;
    ctx.stroke();
  });
  /* 轴线 */
  for (let i = 0; i < n; i++) {
    const p = pt(i, 1);
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(p[0], p[1]);
    ctx.strokeStyle = "#e8edf5"; ctx.stroke();
    /* 轴标签 */
    const lp = pt(i, 1.17);
    ctx.font = "12px 'Microsoft YaHei',sans-serif";
    ctx.fillStyle = "#4b5563";
    ctx.textAlign = Math.abs(lp[0] - cx) < 6 ? "center" : (lp[0] > cx ? "left" : "right");
    ctx.textBaseline = "middle";
    ctx.fillText(LABELS[DIMS[i]] || DIMS[i], lp[0], lp[1]);
  }

  /* 数据多边形 */
  AGENTS.forEach(function(a){
    const vals = DIMS.map(function(d){ return Math.max(0, Math.min(1, frame.vectors[a][d])); });
    ctx.beginPath();
    vals.forEach(function(v, i){
      const p = pt(i, v);
      i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
    });
    ctx.closePath();
    ctx.fillStyle = colorOf(a) + "14";
    ctx.fill();
    ctx.strokeStyle = colorOf(a);
    ctx.lineWidth = (frame.agent === a) ? 3.2 : 2;
    ctx.stroke();

    vals.forEach(function(v, i){
      const p = pt(i, v);
      ctx.beginPath();
      ctx.arc(p[0], p[1], (frame.agent === a) ? 4 : 3, 0, 2 * Math.PI);
      ctx.fillStyle = colorOf(a); ctx.fill();
    });
  });

  /* 中心刻度 */
  ctx.font = "10px sans-serif";
  ctx.fillStyle = "#9ca3af";
  ctx.textAlign = "left"; ctx.textBaseline = "top";
  ctx.fillText("0.00", cx + 4, cy + 2);
}

/* ---------- 数值表 ---------- */
function changed(a, d){
  const f = frames[idx];
  return f.agent === a && (f.dims || []).indexOf(d) >= 0;
}
function renderTable(){
  const f = frames[idx];
  const prev = idx > 0 ? frames[idx - 1] : null;
  let html = "<thead><tr><th style='text-align:left'>智能体</th>";
  DIMS.forEach(function(d){ html += "<th>" + (LABELS[d] || d) + "</th>"; });
  html += "<th>尝试</th><th>成功</th><th>失败</th></tr></thead><tbody>";
  AGENTS.forEach(function(a){
    const st = f.stats[a] || { attempts:0, successes:0, failures:0 };
    html += "<tr><td class='agent'><span class='dot' style='background:" + colorOf(a)
          + "'></span>智能体 " + D.agents[a].name + "</td>";
    DIMS.forEach(function(d){
      const v = Number(f.vectors[a][d]);
      let cls = "";
      if (prev && changed(a, d)) {
        const pv = Number(prev.vectors[a][d]);
        cls = v > pv + 1e-12 ? "up" : (v < pv - 1e-12 ? "down" : "");
      }
      html += "<td class='" + cls + "'>" + v.toFixed(4) + "</td>";
    });
    html += "<td>" + st.attempts + "</td><td>" + st.successes + "</td><td>" + st.failures + "</td></tr>";
  });
  html += "</tbody>";
  document.getElementById("capTable").innerHTML = html;
}

/* ---------- 进化记录 ---------- */
function renderEvents(){
  const box = document.getElementById("events");
  const hist = D.history || [];
  if (!hist.length) { box.innerHTML = "<div class='event'>暂无进化记录，先执行一次任务吧。</div>"; return; }
  let html = "";
  hist.slice().reverse().forEach(function(e, i){
    const realIdx = hist.length - 1 - i;
    const cur = frames[idx].ts && frames[idx].ts === e.ts && frames[idx].agent === e.agent_id;
    const detail = e.dims.map(function(d){
      return (LABELS[d] || d) + " " + Number(e.before[d]).toFixed(3) + "→" + Number(e.after[d]).toFixed(3);
    }).join("、");
    html += "<div class='event" + (cur ? " current" : "") + "'>"
          + "<span class='tag " + (e.outcome === "success" ? "ok" : "bad") + "'>"
          + (e.outcome === "success" ? "成功" : "失败") + "</span>"
          + "<b>智能体 " + e.agent_name + "</b> · " + detail
          + "<div style='color:#6b7280;font-size:11px;margin-top:2px'>" + (e.ts || "")
          + (e.question ? " · " + escapeHtml(e.question) : "") + "</div></div>";
  });
  box.innerHTML = html;
}
function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
}

function render(){
  const f = frames[idx];
  document.getElementById("frameLabel").textContent =
    "第 " + idx + " / " + (frames.length - 1) + " 帧 · " + f.label;
  const slider = document.getElementById("slider");
  slider.max = String(frames.length - 1);
  slider.value = String(idx);
  drawRadar(f, idx > 0 ? frames[idx - 1] : null);
  renderTable();
  renderEvents();
}

document.getElementById("slider").addEventListener("input", function(e){
  stopPlay();
  idx = Number(e.target.value);
  render();
});
document.getElementById("latest").addEventListener("click", function(){
  stopPlay(); idx = frames.length - 1; render();
});
function stopPlay(){ if (timer) { clearInterval(timer); timer = null; } document.getElementById("play").textContent = "▶ 播放进化"; }
document.getElementById("play").addEventListener("click", function(){
  if (timer) { stopPlay(); return; }
  if (idx >= frames.length - 1) idx = 0;
  document.getElementById("play").textContent = "⏸ 暂停";
  timer = setInterval(function(){
    if (idx >= frames.length - 1) { stopPlay(); return; }
    idx += 1; render();
  }, 750);
});
window.addEventListener("resize", function(){ drawRadar(frames[idx], null); });
render();
</script>
</body>
</html>
"""
