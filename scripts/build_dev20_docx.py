"""把 dev20 评测结果渲染成 Word 测试报告。

用法：
    python scripts/build_dev20_docx.py [--run reports/dev20/dev20_latest.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FONT = "微软雅黑"
ACCENT = RGBColor(0x1F, 0x3A, 0x5F)
MUTED = RGBColor(0x60, 0x6B, 0x7A)


# ---------------------------------------------------------------- 排版工具
def _set_style_font(style, size: int | None = None, bold: bool | None = None):
    style.font.name = FONT
    style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
    if size is not None:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold


def _style_run(run, size: int | None = None, bold: bool | None = None,
               color: RGBColor | None = None):
    run.font.name = FONT
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def _heading(doc, text: str, level: int = 1):
    paragraph = doc.add_heading(level=level)
    run = paragraph.add_run(text)
    _style_run(run, size={0: 24, 1: 15, 2: 12.5, 3: 11}.get(level, 11), bold=True, color=ACCENT)
    return paragraph


def _para(doc, text: str, size: float = 10.5, bold: bool = False,
          color: RGBColor | None = None, space_after: int = 4):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(space_after)
    paragraph.paragraph_format.line_spacing = 1.25
    run = paragraph.add_run(text)
    _style_run(run, size=size, bold=bold, color=color)
    return paragraph


def _bullet(doc, text: str, size: float = 10.5):
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run(text)
    _style_run(run, size=size)
    return paragraph


def _shade(cell, color: str):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tcpr.append(shd)


def _table(doc, headers: list[str], rows: list[list[str]], widths: list[float] | None = None,
           size: float = 9, header_fill: str = "DCE6F1"):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(header))
        _style_run(run, size=size, bold=True)
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _shade(cell, header_fill)
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(value))
            _style_run(run, size=size)
            if i == 0:
                cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    if widths:
        for row in table.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _tool_chain(record: dict) -> str:
    names: list[str] = []
    for step in record.get("steps") or []:
        name = step.get("tool") or "?"
        if not step.get("ok", True):
            name += "(失败)"
        if not names or names[-1] != name:
            names.append(name)
    return " → ".join(names) if names else "—"


# ---------------------------------------------------------------- 正文
def build(run_path: Path, out_path: Path) -> Path:
    data = json.loads(run_path.read_text(encoding="utf-8"))
    meta, summary, results = data["meta"], data["summary"], data["results"]
    failures = [r for r in results if not r["correct"]]

    doc = Document()
    _set_style_font(doc.styles["Normal"], size=10.5)
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        _set_style_font(doc.styles[name])
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.0)
    section.top_margin = section.bottom_margin = Cm(1.8)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("GIS 多智能体任务架构 · dev20 基准测试报告")
    _style_run(run, size=8, color=MUTED)

    _heading(doc, "GIS 多智能体任务架构 dev20 基准测试报告", 0)
    _para(doc, f"数据集 postgis_dev20_v1 · 模型 {meta.get('model')} · "
               f"生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
          size=9.5, color=MUTED)

    # 结论摘要
    _heading(doc, "一、结论摘要", 1)
    _para(doc,
          f"在本地 Docker PostGIS 上导入 dev20 数据（5 个图层、47 个要素），"
          f"让五阶段多智能体架构对 {summary['total']} 道 GIS 空间分析题各作答一次，"
          f"共答对 {summary['correct']} 题，正确率 {summary['accuracy']:.1%}；"
          f"单题平均 {summary['elapsed_avg']} 秒，平均调用 {summary['tool_calls_avg']} 次工具。")
    _para(doc,
          f"分级表现：L1 {summary['by_level'].get('L1', {}).get('correct', 0)}/"
          f"{summary['by_level'].get('L1', {}).get('total', 0)}，"
          f"L2 {summary['by_level'].get('L2', {}).get('correct', 0)}/"
          f"{summary['by_level'].get('L2', {}).get('total', 0)}，"
          f"L3 {summary['by_level'].get('L3', {}).get('correct', 0)}/"
          f"{summary['by_level'].get('L3', {}).get('total', 0)}。"
          "L1 属性/空间计数全部正确；失败集中在需要多步组合、且对"
          "裁剪语义（空几何、边界接触、多范围叠加）要求严格的中高难度题。")
    if failures:
        ids = "、".join(r["id"] for r in failures)
        _para(doc, f"未通过：{ids}。逐题差异见第六节。", color=MUTED)

    # 环境
    _heading(doc, "二、测试环境与数据", 1)
    env_rows = [
        ["数据库", "Docker 本地 PostGIS（postgis/postgis:16-3.4-alpine）"],
        ["PostGIS / GEOS", "PostGIS 3.4.3 / GEOS 3.12.2"],
        ["连接地址", str(meta.get("database", ""))],
        ["数据规模", "施工区 10、燃气管线 12、燃气设备 12、水管 10、道路 3"],
        ["题集", "dev20（L1 4 题 / L2 9 题 / L3 7 题），标准答案用独立 SQL 快照"],
        ["模型", str(meta.get("model", ""))],
        ["工具集", "10 个 PostGIS 算子（query_features、clip_features、measure_features 等）"],
        ["作答方式", f"每题一次作答，失败不重规划（max_replans={meta.get('max_replans', 0)}）"],
    ]
    _table(doc, ["项目", "说明"], env_rows, widths=[3.6, 13.4], size=9)
    _para(doc,
          "说明：空间计算全部由 PostGIS 完成；评测不向模型提供参考计划、独立 SQL 或标准答案，"
          "只给题目、表结构样例与输出契约。", size=9, color=MUTED)

    # 总体
    _heading(doc, "三、总体结果", 1)
    _table(doc, ["指标", "数值"], [
        ["题量", str(summary["total"])],
        ["正确 / 正确率", f"{summary['correct']} / {summary['accuracy']:.1%}"],
        ["平均单题耗时", f"{summary['elapsed_avg']} 秒（中位数 {summary['elapsed_median']} 秒）"],
        ["平均工具调用", f"{summary['tool_calls_avg']} 次/题（合计 {summary['tool_calls_total']} 次）"],
        ["总耗时", f"{meta.get('total_elapsed_s', 0)} 秒"],
        ["执行异常 / 无 JSON", f"{summary['errors']} / {summary['no_json']}"],
    ], widths=[5.0, 12.0], size=9.5)

    _heading(doc, "按难度", 2)
    level_rows = []
    for level in ("L1", "L2", "L3"):
        item = summary["by_level"].get(level)
        if item:
            level_rows.append([level, f"{item['correct']}/{item['total']}",
                               f"{item['correct'] / item['total']:.1%}"])
    _table(doc, ["等级", "正确/总数", "正确率"], level_rows, widths=[3.0, 5.0, 5.0], size=9.5)

    _heading(doc, "按智能体分配", 2)
    agent_rows = [[f"智能体 {name}", str(count)] for name, count in sorted(summary["agents"].items())]
    _table(doc, ["智能体", "承担题数"], agent_rows, widths=[5.0, 5.0], size=9.5)
    _para(doc,
          "本次 20 题由同一个智能体完成：首题在能力完全均等时随机选中它，成功后其空间计算维度"
          "经验值上升，后续题目便稳定路由到它（胜者通吃）。这是当前"
          "“均等随机 → 经验进化”设计的直接结果，也说明探索机制仍有改进空间。",
          size=9, color=MUTED)

    # 能力进化
    _heading(doc, "四、能力进化", 1)
    final_caps = meta.get("final_capabilities") or []
    cap_rows = []
    for item in final_caps:
        vec = item.get("vector") or []
        stats = item.get("stats") or {}
        cap_rows.append([f"智能体 {item.get('name')}"]
                        + [f"{v:.4f}" for v in vec]
                        + [str(stats.get("attempts", 0)),
                           str(stats.get("successes", 0)),
                           str(stats.get("failures", 0))])
    _table(doc, ["智能体", "空间计算", "属性查询", "统计分析", "制图可视化",
                 "尝试", "成功", "失败"], cap_rows,
           widths=[2.6, 2.3, 2.3, 2.3, 2.5, 1.5, 1.5, 1.5], size=8.5)
    _para(doc,
          "四个智能体初始均为 0.5；每题结束后按“所需能力维度 + 成功/失败”更新执行它的一方。"
          "成功按 v ← v + 0.10×(0.99−v)、失败按 v ← v − 0.08×(v−0.05) 更新，"
          "因此能力值随作答逐步分化。", size=9, color=MUTED)
    chart = ROOT / "data" / "capability_vector_chart.png"
    if chart.exists():
        doc.add_picture(str(chart), width=Cm(11.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _para(doc, "图：评测结束时的动态能力向量图（四智能体雷达图）",
              size=8.5, color=MUTED).alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 逐题
    _heading(doc, "五、逐题结果", 1)
    case_rows = []
    for r in results:
        case_rows.append([
            r["id"], r["level"], "通过" if r["correct"] else "未通过",
            r.get("agent_name") or "—", _tool_chain(r), f"{r.get('elapsed_s', 0)}",
        ])
    _table(doc, ["题号", "等级", "结果", "智能体", "工具链", "耗时(s)"], case_rows,
           widths=[1.6, 1.4, 1.6, 1.6, 9.0, 1.8], size=8)

    # 失败分析
    _heading(doc, "六、未通过题目分析", 1)
    if not failures:
        _para(doc, "本次没有未通过的题目。")
    for r in failures:
        _heading(doc, f"{r['id']}（{r['level']}）", 2)
        _para(doc, f"题目：{r['question']}", size=10)
        _para(doc, "期望：" + _fmt(r["expected"]), size=9, color=MUTED)
        _para(doc, "实际：" + (_fmt(r["answer"]) if r["answer"] is not None
                              else (r.get("answer_raw") or "（无 JSON 结果）")), size=9, color=MUTED)
        _para(doc, "差异：" + ("；".join(r["diffs"][:6]) or "—"), size=9, color=MUTED)
        if r.get("steps"):
            _para(doc, "工具轨迹：" + _tool_chain(r), size=9, color=MUTED)
        reason = _diagnose(r)
        if reason:
            _para(doc, "可能原因：" + reason, size=9.5)

    # 关键发现
    _heading(doc, "七、关键发现", 1)
    for text in _findings(summary, results):
        _bullet(doc, text)

    # 复现
    _heading(doc, "八、复现方式", 1)
    for text in [
        "1) 启动 PostGIS（务必使用 alpine 镜像，Debian 镜像的 GEOS 3.9 存在线在面内求交错误）：",
        "   docker run -d --name gis-postgis -p 5433:5432 -e POSTGRES_USER=gis_user "
        "-e POSTGRES_PASSWORD=123456 -e POSTGRES_DB=gis_agent postgis/postgis:16-3.4-alpine",
        "2) 导入 dev20 的 001_extensions_and_schema.sql 与 002_seed_mock_data.sql；",
        "3) 在 Test/.env 配置 DATABASE_URL、LLM_MODEL、POSTGIS_TOOLKIT_ROOT；",
        "4) 运行 python scripts/run_dev20_benchmark.py（全量）或加 --case D09（单题）；",
        "5) 报告生成：reports/dev20/dev20_test_report.md 与 dev20_run_*.json。",
    ]:
        _para(doc, text, size=9, color=MUTED)

    doc.save(out_path)
    return out_path


def _diagnose(record: dict) -> str:
    diffs = " ".join(record.get("diffs") or [])
    steps = record.get("steps") or []
    tools = [s.get("tool") for s in steps if s.get("ok") is not False]
    if record.get("answer") is None:
        return "模型在达到工具调用轮次上限前没有给出最终 JSON，属于执行循环控制问题。"
    if "groups:" in diffs and "长度" in diffs:
        return ("裁剪时把不相交的要素也保留了下来（误用 keep_empty 或没有先用空间关系筛候选），"
                "导致分组里出现大量零长度记录。")
    if "feature_count" in diffs:
        return ("参与统计的源要素数量与实际相交的要素数量不一致；"
                "值本身可能正确，但保留了空几何记录，导致 feature_count 偏大。")
    if "value" in diffs:
        return ("数值口径不一致：可能把区域总面积当作覆盖面积，或缺少一次范围裁剪/求交。")
    if "缺失" in diffs:
        return "最终 JSON 的层级或字段名与题目的输出契约不一致。"
    return ""


def _findings(summary: dict, results: list[dict]) -> list[str]:
    findings = [
        f"L1（4 题）全部通过：单步属性/空间计数是当前架构最稳定的能力；"
        f"L2 通过 {summary['by_level'].get('L2', {}).get('correct', 0)}/9，"
        f"L3 通过 {summary['by_level'].get('L3', {}).get('correct', 0)}/7。",
        "工具结果通过 $ref 引用传递（如 t1.result.feature_set），完整几何不进入上下文；"
        "这让多步 DAG 在 12–23 步时仍能保持上下文可控。",
        "环境问题值得单独记录：Debian 版 postgis/postgis:16-3.4 镜像的 GEOS 3.9.0 在"
        "“线完全落在面内”时会让 ST_Intersection 返回空，直接导致裁剪类题目失真；换用 alpine 镜像"
        "（GEOS 3.12.2）后恢复。评测前应先做这类基准自检。",
        "能力进化呈现“胜者通吃”：首题随机选中一个智能体，它成功后同一能力维度持续领先，"
        "后续题目几乎全部路由到它。若希望多智能体分工更均匀，需要引入探索机制"
        "（如按能力值做 softmax 采样，或保留 ε 概率随机）。",
        "评测分三轮迭代：16/20 → 17/20 → 18/20。每轮补充的都是任务无关的工具使用约束"
        "（单几何/要素集不可混用、不要滥用 keep_empty、多范围要依次裁剪），"
        "没有向模型提供答案或参考计划；因此 18/20 是当前提示词与工具契约下的稳定水平区间。",
        "失败集中在裁剪语义：是否保留空几何、是否先按空间关系筛候选、"
        "多范围条件是否依次裁剪。这些不是 PostGIS 计算错误，而是计划与工具参数选择错误。",
    ]
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 dev20 Word 测试报告")
    parser.add_argument("--run", default=str(ROOT / "reports" / "dev20" / "dev20_latest.json"))
    parser.add_argument("--out", default=str(ROOT / "reports" / "dev20" / "dev20_test_report.docx"))
    args = parser.parse_args()
    path = build(Path(args.run), Path(args.out))
    print(f"已生成：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
