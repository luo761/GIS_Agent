"""从真实比较结果生成可独立打开的中文 HTML；不访问模型或数据库。

用法：
    python scripts/build_dev50_comparison_html.py
    python scripts/build_dev50_comparison_html.py --input path/comparison.json --output path/comparison.html
"""
from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "reports" / "dev50_comparison" / "comparison.json"
MODES = (("no_replan", "关闭重规划", "baseline"), ("with_replan", "开启重规划", "replan"))


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _number(value: Any, digits: int = 1) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "未运行"
    return f"{value:,.{digits}f}" if digits else f"{value:,.0f}"


def _percent(value: Any) -> str:
    return "未运行" if value is None else f"{100 * value:.1f}%"


def _summary_card(title: str, summaries: dict, key: str, *, percent: bool = False,
                  digits: int = 1, suffix: str = "") -> str:
    rows = []
    for mode, label, color in MODES:
        summary = summaries.get(mode, {})
        value = summary.get(key)
        if not summary.get("completed"):
            value = None
        display = _percent(value) if percent else _number(value, digits)
        unit = suffix if value is not None else ""
        rows.append(f'<div class="metric-row"><span><i class="dot {color}"></i>{label}</span>'
                    f'<strong>{display}<small>{unit}</small></strong></div>')
    return f'<article class="card metric-card"><h3>{title}</h3>{"".join(rows)}</article>'


def _chart(title: str, summaries: dict, key: str, unit: str, *, percent: bool = False,
           usage: bool = False, digits: int = 1) -> str:
    values = []
    for mode, _, _ in MODES:
        summary = summaries.get(mode, {})
        source = summary.get("llm_usage", {}) if usage else summary
        value = source.get(key)
        if not summary.get("completed") or (usage and key != "llm_calls" and not source.get("usage_reported_calls")):
            value = None
        values.append(value)
    maximum = 1 if percent else max((value for value in values if isinstance(value, (int, float))), default=0)
    rows = []
    for (_, label, color), value in zip(MODES, values):
        display = _percent(value) if percent else _number(value, digits)
        width = min(100, max(0, 100 * value / maximum)) if value is not None and maximum else 0
        rows.append(f'<div class="chart-row"><div class="chart-label"><span>{label}</span>'
                    f'<strong>{display}{(" " + unit) if value is not None and not percent else ""}</strong></div>'
                    f'<div class="track"><div class="fill {color}" style="width:{width:.4f}%"></div></div></div>')
    return f'<article class="card chart"><h3>{title}</h3>{"".join(rows)}</article>'


def _level_cards(report: dict) -> str:
    cards = []
    for level, modes in sorted(report.get("by_level", {}).items()):
        rows = []
        for mode, label, color in MODES:
            summary = modes.get(mode, {})
            count = summary.get("completed", 0)
            score = f'{summary.get("correct", 0)} / {count}' if count else "未运行"
            rate = _percent(summary.get("accuracy"))
            rows.append(f'<div class="level-row"><span><i class="dot {color}"></i>{label}</span>'
                        f'<strong>{score}</strong><small>{rate}</small></div>')
        cards.append(f'<article class="card level"><h3>{_escape(level)}</h3>{"".join(rows)}</article>')
    return "".join(cards)


def build_html(report: dict) -> str:
    """只展示输入快照中的真实指标，未完成的题目保留为待完成。"""
    if not isinstance(report.get("summaries"), dict) or not isinstance(report.get("pairs"), list):
        raise ValueError("输入文件不是有效的 dev50 comparison.json")
    status = report.get("status", "partial")
    meta = report.get("meta", {})
    planned = report.get("planned_case_count", 0)
    paired = report.get("paired_case_count", len(report["pairs"]))
    complete = status == "completed" and paired == planned and planned > 0
    label = "已完成" if complete else ("实验受阻" if status == "blocked" else "尚未完成")
    status_class = "complete" if complete else ("blocked" if status == "blocked" else "partial")
    warning = ""
    if not complete:
        details = "；".join(str(item.get("message", "运行条件未满足")) for item in report.get("blockers", []))
        warning = ('<aside class="notice"><strong>这份报告尚未完成全部配对。</strong>'
                   f'<span>目前完成 {paired} / {planned} 题。汇总仅覆盖已完成题目，未运行题目不计为答错。'
                   '当前指标不能作为完整题集的最终结论。</span>'
                   + (f'<span>{_escape(details)}</span>' if details else "") + '</aside>')
    summaries = report["summaries"]
    cards = "".join((
        _summary_card("最终正确率", summaries, "accuracy", percent=True),
        _summary_card("首次作答正确率", summaries, "first_accuracy", percent=True),
        _summary_card("平均作答轮数", summaries, "mean_attempts", digits=2, suffix="轮"),
        _summary_card("题内重规划挽回", summaries, "rescued_after_first_failure", digits=0, suffix="题"),
    ))
    charts = "".join((
        _chart("平均单题耗时", summaries, "mean_elapsed_s", "秒"),
        _chart("平均单题工具调用", summaries, "mean_tool_calls", "次", digits=2),
        _chart("总模型调用", summaries, "llm_calls", "次", usage=True, digits=0),
        _chart("服务端报告的总 token", summaries, "total_tokens", "tokens", usage=True, digits=0),
    ))
    delta = report.get("paired_accuracy_delta_pp")
    delta_text = "待完成配对" if delta is None else f"{delta:+.1f} 个百分点"
    baseline_better = report.get("regressed_case_ids", [])
    replan_better = report.get("rescued_case_ids", [])
    notes = (f'<div><span>已配对题目的正确率差（开启 − 关闭）</span><strong>{delta_text}</strong></div>'
             f'<p>开启正确、关闭错误：<b>{_escape("、".join(replan_better) or "暂无")}</b></p>'
             f'<p>关闭正确、开启错误：<b>{_escape("、".join(baseline_better) or "暂无")}</b></p>')
    payload = json.dumps(report, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    replacements = {
        "@@TITLE@@": f"{planned} 题 GIS · 重规划对比",
        "@@MODEL@@": _escape(meta.get("model", "未记录")),
        "@@BUDGET@@": _escape(meta.get("max_replans", "未记录")),
        "@@STATUS_CLASS@@": status_class,
        "@@STATUS@@": label,
        "@@PAIRED@@": str(paired),
        "@@PLANNED@@": str(planned),
        "@@WARNING@@": warning,
        "@@CARDS@@": cards,
        "@@CHARTS@@": charts,
        "@@LEVEL_CARDS@@": _level_cards(report),
        "@@NOTES@@": notes,
        "@@GENERATED@@": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "@@REPORT_JSON@@": payload,
    }
    document = HTML_TEMPLATE
    for key, value in replacements.items():
        document = document.replace(key, value)
    return document


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<style>
:root{--bg:#f4f7f8;--ink:#172c39;--muted:#647782;--line:#e0e8ed;--blue:#5266bd;--teal:#138979;--card:#fff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",sans-serif;font-size:15px;line-height:1.65}
main{max-width:1180px;padding:48px 28px 32px;margin:auto}header{display:flex;justify-content:space-between;gap:30px;align-items:flex-start;margin-bottom:24px}
.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--teal);font-weight:700;margin:0 0 8px}h1{font-size:38px;line-height:1.2;letter-spacing:-.035em;margin:0 0 14px;font-weight:700}h2{font-size:21px;margin:0 0 15px;letter-spacing:-.02em}h3{font-size:14px;font-weight:600;color:var(--muted);margin:0 0 18px}.subtitle{margin:0;max-width:750px;color:var(--muted)}.meta{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}.chip{font-size:12px;line-height:1.8;padding:3px 10px;border:1px solid var(--line);border-radius:30px;background:#fff;color:var(--muted)}
.status{display:flex;align-items:center;gap:8px;white-space:nowrap;font-size:13px;font-weight:650;border-radius:30px;padding:8px 13px}.status:before{content:"";width:7px;height:7px;border-radius:100%;background:currentColor}.complete{background:#e2f3ec;color:#197957}.partial{background:#fff0d0;color:#946008}.blocked{background:#ffe7e1;color:#a54229}.notice{border:1px solid #ead398;background:#fff7e5;padding:16px 20px;border-radius:12px;margin-bottom:24px;color:#775617}.notice strong,.notice span{display:block}.notice strong{margin-bottom:4px}.notice span{font-size:13px}
.grid{display:grid;gap:16px}.metrics{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:22px}.card{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:21px 22px;box-shadow:0 2px 4px #17344403}.metric-row{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:12px 0 0}.metric-row span{font-size:12px;color:var(--muted);white-space:nowrap}.metric-row strong{font-size:23px;letter-spacing:-.03em;white-space:nowrap;font-weight:650}.metric-row small{font-size:11px;color:var(--muted);font-weight:400;letter-spacing:0;margin-left:5px}.dot{width:8px;height:8px;display:inline-block;border-radius:100%;margin-right:7px}.baseline{background:var(--blue)}.replan{background:var(--teal)}
.outcome{display:grid;grid-template-columns:1.2fr 1fr;gap:18px;padding:24px 26px;margin:0 0 34px;background:#eaf2f1;border:1px solid #cfe2de;border-radius:13px;align-items:center}.outcome div{grid-row:span 2}.outcome span{display:block;font-size:13px;color:#50736c}.outcome strong{font-size:31px;font-weight:650;letter-spacing:-.04em;color:#176756;line-height:1.6}.outcome p{margin:0;font-size:13px;color:#50736c}.outcome b{font-weight:600;color:#2d564e;overflow-wrap:anywhere}.section{margin-bottom:34px}.section-heading{display:flex;justify-content:space-between;gap:15px;align-items:baseline}.section-note{font-size:12px;color:var(--muted);margin:0 0 15px}.charts{grid-template-columns:repeat(4,minmax(0,1fr))}.chart-row{margin-top:17px}.chart-label{display:flex;justify-content:space-between;gap:8px;font-size:11px;margin-bottom:6px;color:var(--muted)}.chart-label strong{color:var(--ink);font-weight:600;white-space:nowrap}.track{height:9px;border-radius:15px;background:#edf1f5;overflow:hidden}.fill{height:100%;border-radius:15px;min-width:0}.levels{grid-template-columns:repeat(3,minmax(0,1fr))}.level h3{font-size:20px;color:var(--ink);margin-bottom:12px}.level-row{display:grid;grid-template-columns:1fr auto 60px;align-items:center;gap:10px;margin-top:9px;font-size:12px}.level-row span{color:var(--muted)}.level-row strong{font-size:16px;font-weight:600}.level-row small{text-align:right;color:var(--muted)}
.table-panel{background:#fff;border:1px solid var(--line);border-radius:13px;overflow:hidden}.filters{display:flex;align-items:center;gap:10px;padding:18px 20px;border-bottom:1px solid var(--line);flex-wrap:wrap}.filters label{font-size:12px;color:var(--muted);display:flex;gap:8px;align-items:center}.filters select,.filters input{font-family:inherit;font-size:12px;border:1px solid #d6e0e5;border-radius:7px;padding:7px 10px;background:#fff;color:var(--ink);height:34px}.filters input{flex:1;min-width:160px;max-width:300px}.filter-count{font-size:12px;color:var(--muted);margin-left:auto}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px;text-align:left}thead{background:#f7f9fb}th{color:#6a7b87;font-weight:600;white-space:nowrap;padding:13px 15px}td{padding:14px 15px;border-top:1px solid #edf1f4;vertical-align:top}.case-id{font-weight:700;font-variant-numeric:tabular-nums;color:var(--blue);white-space:nowrap}.case-text{min-width:250px;max-width:440px;line-height:1.8}.case-text details summary{cursor:pointer;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;list-style:none}.case-text details[open] summary{display:block}.case-text details[open] summary:after{content:"　收起";font-size:11px;color:var(--teal)}.level-tag{font-size:11px;border:1px solid var(--line);border-radius:5px;padding:2px 6px;color:var(--muted);white-space:nowrap}.badge{display:inline-block;border-radius:5px;padding:2px 7px;font-weight:600;white-space:nowrap}.correct{background:#e9f5ef;color:#227757}.incorrect{background:#fcece8;color:#ac4b3e}.pending{background:#f0f3f5;color:#87969d}.delta{font-variant-numeric:tabular-nums;white-space:nowrap;text-align:right}.pair-better td:first-child{box-shadow:inset 3px 0 var(--teal)}.pair-worse td:first-child{box-shadow:inset 3px 0 #c76a5c}.empty{text-align:center;color:var(--muted);padding:30px}.table-foot{padding:14px 20px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);margin:0}
.method{font-size:12px;color:var(--muted);padding-top:22px;border-top:1px solid var(--line)}.method p{margin:0 0 9px}.links{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-top:20px;font-size:12px;color:#87969d}a{color:var(--teal);text-decoration:none}a:hover{text-decoration:underline}
@media(max-width:1050px){.metrics,.charts{grid-template-columns:repeat(2,minmax(0,1fr))}.level-row{grid-template-columns:1fr auto}.level-row small{display:none}}@media(max-width:650px){main{padding:28px 16px}header{display:block}header .status{display:inline-flex;margin-top:20px}h1{font-size:30px}.metrics,.charts,.levels{grid-template-columns:1fr}.outcome{grid-template-columns:1fr;gap:9px}.outcome div{grid-row:auto}.card{padding:20px}.section-heading{display:block}.filter-count{margin-left:0;width:100%}.filters input{max-width:none}.level-row{grid-template-columns:1fr auto 70px}.level-row small{display:block}}
@media print{body{background:white}main{padding:0;max-width:none}.filters,.links{display:none}.card,.table-panel,.outcome{box-shadow:none;break-inside:avoid}th,td{padding:8px}.case-text details summary{display:block}.metrics,.charts{grid-template-columns:repeat(2,1fr)}.section{break-inside:avoid}}
</style>
</head>
<body>
<main>
<header><div><p class="eyebrow">GIS BENCHMARK / PAIRED COMPARISON</p><h1>重规划对比</h1><p class="subtitle">同一组空间分析问题，比较最终作答表现、首次作答表现与计算代价。</p><div class="meta"><span class="chip">@@PLANNED@@ 道题</span><span class="chip">模型：@@MODEL@@</span><span class="chip">关闭：0 次 · 开启：最多 @@BUDGET@@ 次重规划</span></div></div><span class="status @@STATUS_CLASS@@">@@STATUS@@ · @@PAIRED@@ / @@PLANNED@@</span></header>
@@WARNING@@
<section class="grid metrics" aria-label="作答表现">@@CARDS@@</section>
<section class="outcome" aria-label="配对差异">@@NOTES@@</section>
<section class="section"><div class="section-heading"><h2>计算代价</h2><p class="section-note">耗时与调用数包含全部作答轮次</p></div><div class="grid charts">@@CHARTS@@</div></section>
<section class="section"><div class="section-heading"><h2>分难度表现</h2><p class="section-note">正确题数 / 已完成题数</p></div><div class="grid levels">@@LEVEL_CARDS@@</div></section>
<section class="section"><div class="section-heading"><h2>逐题比较</h2><p class="section-note">筛选仅影响逐题表，上方指标保留全局汇总</p></div><div class="table-panel">
<div class="filters"><label>难度<select id="level-filter"><option value="all">全部难度</option><option>L1</option><option>L2</option><option>L3</option></select></label><label>结果<select id="result-filter"><option value="all">全部结果</option><option value="better">开启正确、关闭错误</option><option value="worse">关闭正确、开启错误</option><option value="same">两组一致</option><option value="pending">待完成配对</option></select></label><input id="search" type="search" placeholder="搜索题号或题目" aria-label="搜索题号或题目"><span class="filter-count" id="filter-count"></span></div>
<div class="table-wrap"><table><thead><tr><th>题号</th><th>难度</th><th>题目</th><th>关闭</th><th>开启</th><th>开启首轮</th><th class="delta">工具调用差<br>开启 − 关闭</th><th class="delta">耗时差 / 秒<br>开启 − 关闭</th></tr></thead><tbody id="case-table"></tbody></table></div><p class="table-foot">点击长题目可展开。正的调用量或耗时差表示开启模式使用更多；待完成题目暂不参与正确率计算。</p></div></section>
<section class="method"><p>两种模式使用相同题集、数据库、模型参数和路由种子。每道题、每种模式从独立的空能力、经验和记忆状态开始；题目之间不学习，题内重规划可以利用失败反馈和经验。开启模式最多额外重规划 @@BUDGET@@ 次，首次作答也计入轮数。</p><p>“题内重规划挽回”指开启模式自身首轮错误、后续轮正确；它与“开启正确、关闭错误”的独立模式差异分别统计。评估反馈仅给出错误字段，不提供标准答案值。</p><p>本报告是单次配对的描述性比较。固定路由种子不保证模型输出完全确定，结果不代表统计显著性。Token 为服务端报告的用量；单题耗时不等同于并行实验的总墙钟时间。</p></section>
<footer class="links"><span>报告快照生成于 @@GENERATED@@</span><span><a href="comparison.json">原始比较数据</a> · <a href="comparison_report.md">文字报告</a></span></footer>
</main>
<script id="report-data" type="application/json">@@REPORT_JSON@@</script>
<script>
(()=>{
  const report=JSON.parse(document.getElementById('report-data').textContent);
  const paired=new Map(report.pairs.map(row=>[row.id,row]));
  const ids=report.meta?.case_ids?.length?report.meta.case_ids:report.pairs.map(row=>row.id);
  const rows=ids.map(id=>paired.get(id)||{id,pending:true});
  const table=document.getElementById('case-table');
  const level=document.getElementById('level-filter');
  const outcome=document.getElementById('result-filter');
  const search=document.getElementById('search');
  function td(text,cls=''){const item=document.createElement('td');item.className=cls;item.textContent=text;return item;}
  function badge(value,pending){const cell=document.createElement('td'),tag=document.createElement('span');tag.className='badge '+(pending?'pending':value?'correct':'incorrect');tag.textContent=pending?'待完成':value?'正确':'错误';cell.append(tag);return cell;}
  function signed(value,digits){if(typeof value!=='number')return '—';return (value>0?'+':'')+value.toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits});}
  function render(){
    const query=search.value.trim().toLowerCase();
    const filtered=rows.filter(row=>{
      if(level.value!=='all'&&row.level!==level.value)return false;
      if(query&&!`${row.id} ${row.question||''}`.toLowerCase().includes(query))return false;
      if(outcome.value==='pending')return row.pending;
      if(outcome.value==='better')return !row.pending&&row.accuracy_delta>0;
      if(outcome.value==='worse')return !row.pending&&row.accuracy_delta<0;
      if(outcome.value==='same')return !row.pending&&row.accuracy_delta===0;
      return true;
    });
    table.replaceChildren();
    for(const row of filtered){
      const tr=document.createElement('tr');
      if(row.accuracy_delta>0)tr.className='pair-better';else if(row.accuracy_delta<0)tr.className='pair-worse';
      tr.append(td(row.id,'case-id'));
      const levelCell=td(''),levelTag=document.createElement('span');levelTag.className='level-tag';levelTag.textContent=row.level||'待完成';levelCell.append(levelTag);tr.append(levelCell);
      const questionCell=td('','case-text');
      if(row.pending)questionCell.textContent='尚未完成该题的两种模式配对。';else{const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=row.question||'';details.append(summary);questionCell.append(details);}
      tr.append(questionCell,badge(row.no_replan_correct,row.pending),badge(row.with_replan_correct,row.pending),badge(row.with_replan_first_correct,row.pending),td(signed(row.tool_calls_delta,0),'delta'),td(signed(row.elapsed_delta_s,2),'delta'));
      table.append(tr);
    }
    if(!filtered.length){const tr=document.createElement('tr'),cell=td('没有符合筛选条件的题目。','empty');cell.colSpan=8;tr.append(cell);table.append(tr);}
    document.getElementById('filter-count').textContent=`显示 ${filtered.length} / ${rows.length} 题`;
  }
  level.addEventListener('change',render);outcome.addEventListener('change',render);search.addEventListener('input',render);render();
})();
</script>
</body>
</html>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.input.with_name("comparison.html")
    if output.suffix.lower() != ".html" or output.resolve() == args.input.resolve():
        parser.error("输出必须是独立的 .html 文件，不能覆盖输入 JSON")
    try:
        report = json.loads(args.input.read_text(encoding="utf-8"))
        document = build_html(report)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".html.tmp")
        temporary.write_text(document, encoding="utf-8")
        temporary.replace(output)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"output": str(output.resolve()), "status": report.get("status"),
                      "paired_case_count": report.get("paired_case_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
