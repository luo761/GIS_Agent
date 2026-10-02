"""
================================================================================
run_gis_tests.py —— AgentNet-GIS 基础算子能力测试 Harness（与主程序解耦）
================================================================================
用途：
  用一批"现实生活中可能遇到的真实GIS问题"测试 agentnet_gis.py 智能体是否能
  正确选择并调用原子GIS算子完成任务，用于向甲方证明智能体的基础GIS能力。

与主程序/数据集的解耦方式：
  - 本文件不修改主程序逻辑，仅 import 主程序的 builder / registry / DB_URL，
    由 harness 自行持有 Postgres 连接并编译图；
  - 测试用例全部来自外部 JSON 配置文件（默认 GIS智能体测试数据集_v2.json，
    格式与《GIS智能体测试数据集.json》一致），增删用例只改 JSON；
  - 数据集里的 gis_operators.operator 通过 OPERATOR_TOOL_MAP 映射到
    Skill 库（gis_skill_library.py）中的原子工具；
  - 运行前自动把 Skill 库使用说明写入 PostgresStore 的 ("skills", domain)
    命名空间，供 execute_node 检索注入；
  - 自动应答图中的 interrupt（相当于测试中模拟用户按"yes"）；
  - 评分维度：
      (1) 流程跑通（无异常）
      (2) 领域识别正确（燃气/水务/电务）
      (3) 工具选择正确（实际调用的算子与数据集 gis_operators 期望匹配）
      (4) 结果有效（工具原始输出非空，即确实执行了原子算子并返回原始数据）
  - 输出：
      控制台报告 + JSON 报告（output/gis_test_report_*.json）
      + 可视化 PNG（output/gis_test_visual_*.png）：
        各任务执行路径（LangGraph节点序列）、单任务耗时与通过状态、
        各类别准确率、算子调用分布、总耗时/平均耗时汇总。

用法：
  python run_gis_tests.py                     # 跑全部用例
  python run_gis_tests.py -f 燃气              # 按 scenario/question 关键字过滤
  python run_gis_tests.py --id GIS-105        # 只跑指定用例
  python run_gis_tests.py --dataset xxx.json  # 指定其他数据集文件
================================================================================
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from langgraph.types import Command
from loguru import logger

# ---------- 导入主程序（智能体本体，不做任何修改） ----------
# 注意：主程序 get_graph() 内部用 with 建连接后返回，连接在返回时已关闭，
# 因此这里导入 builder 自行编译，由 harness 持有 Postgres 连接生命周期。
from agentnet_gis import builder, registry, DB_URL, UserContext, SKILL_USAGE_DOCS
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from gis_skill_library import ATOMIC_TOOLS

VALID_TOOL_NAMES = {t.name for t in ATOMIC_TOOLS}
REPORT_DIR = Path(__file__).parent / "output"
REPORT_DIR.mkdir(exist_ok=True)
DEFAULT_DATASET = Path(__file__).parent / "GIS智能体测试数据集_v2.json"

# 数据集算子名 → Skill 库原子工具名 的映射
OPERATOR_TOOL_MAP = {
    "AttributeQuery": ["spatial_query"],
    "AttributeStat": ["attribute_agg"],
    "Buffer": ["buffer_analysis"],
    "SpatialJoin": ["spatial_join"],
    "Distance": ["features_within_distance", "buffer_analysis"],
    "Nearest": ["nearest_features"],
    "Intersect": ["overlay_intersect"],
    "LengthMeasure": ["length_measure", "spatial_query"],
    "AreaMeasure": ["area_measure"],
    "Clip": ["clip_analysis"],
    "ShortestPath": ["shortest_path"],
    "ServiceArea": ["service_area"],
    "TerrainProfile": ["terrain_profile"],
    "DensityHeatmap": ["density_heatmap"],
    "TopologyCheck": ["topology_check"],
}

# 每个原子算子原始输出的固定标记（用于校验返回的是原始数据格式而非精炼结论）
TOOL_OUTPUT_MARKERS = {
    "spatial_query": "[SQL查询结果]",
    "attribute_agg": "[SQL查询结果]",
    "features_within_distance": "[SQL查询结果]",
    "nearest_features": "[SQL查询结果]",
    "overlay_intersect": "[SQL查询结果]",
    "spatial_join": "[SQL查询结果]",
    "clip_analysis": "[SQL查询结果]",
    "buffer_analysis": "[缓冲区生成结果]",
    "length_measure": "[长度量算结果]",
    "area_measure": "[面积量算结果]",
    "shortest_path": "[最短路径结果]",
    "service_area": "[服务区分析结果]",
    "terrain_profile": "[地形剖面结果]",
    "density_heatmap": "[格网密度结果]",
    "topology_check": "[拓扑检查结果]",
}


def load_dataset(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for task in data.get("tasks", []):
        ops = [o["operator"] for o in task.get("gis_operators", [])]
        any_of = sorted({t for op in ops for t in OPERATOR_TOOL_MAP.get(op, [op.lower()])})
        cases.append({
            "id": task["id"],
            "title": task.get("title", ""),
            "category": task.get("category", ""),
            "question": task["colloquial_question"],
            "background": task.get("scenario", {}).get("background", ""),
            "dataset_operators": ops,
            "expected_tools": {"any_of": any_of},
        })
    return data.get("meta", {}), cases


# =====================================================================
# Skill 库播种：把算子使用说明写入 PostgresStore 的 skills 命名空间
# =====================================================================
def seed_skills(store):
    """幂等播种初始知识：算子使用说明 + 标准任务执行模板（固定key，重跑不重复）"""
    from manage_knowledge import seed_base, DEFAULT_DATASET
    n = seed_base(store, DEFAULT_DATASET)
    logger.info(f"[Skill播种] 初始知识播种完成，共 {n} 条（算子说明 + 标准任务模板，幂等固定key）")


# =====================================================================
# 单用例执行
# =====================================================================
def extract_tool_calls(events_log):
    """从事件流中提取实际调用的工具名、工具原始输出与节点执行路径"""
    tool_names, tool_outputs, node_path = [], [], []
    for ev in events_log:
        data = ev.get("data") if isinstance(ev, dict) else None
        d = data if isinstance(data, dict) else ev
        if isinstance(d, dict):
            # updates 流：key 即节点名
            node_keys = [k for k in d.keys()
                         if k.endswith("_node") and k not in node_path]
            node_path += node_keys
        msgs = d.get("messages") if isinstance(d, dict) else None
        if not msgs:
            continue
        for m in msgs:
            tc = getattr(m, "tool_calls", None)
            if tc:
                tool_names += [t["name"] for t in tc]
            if getattr(m, "type", "") == "tool":
                tool_outputs.append(str(getattr(m, "content", "")))
    seen, uniq = set(), []
    for n in tool_names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq, tool_outputs, node_path


def run_one_case(graph, case, context):
    thread_id = f"gistest_{case['id']}_{int(time.time())}"
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    inputs = {"input": case["question"]}
    events_log, final_state = [], {}
    t0 = time.time()

    try:
        resumed = False
        while True:
            payload = inputs if not resumed else Command(resume=True)
            got_interrupt = False
            for ev in graph.stream(payload, config=config, context=context,
                                   stream_mode=["updates", "values"], version="v2"):
                events_log.append(ev)
                data = ev.get("data") if isinstance(ev, dict) else None
                interrupts = (ev.get("__interrupt__")
                              or (data.get("__interrupt__") if isinstance(data, dict) else None)
                              or ev.get("interrupts"))
                if interrupts:
                    got_interrupt = True
                    break
                ev_data = data if isinstance(data, dict) else ev
                if isinstance(ev_data, dict):
                    final_state.update(ev_data)
            if got_interrupt:
                resumed = True
                continue  # 自动应答 yes
            break
        ok_run, error = True, ""
    except Exception as e:
        ok_run, error = False, f"{type(e).__name__}: {e}"

    elapsed = round(time.time() - t0, 1)
    tool_names, tool_outputs, node_path = extract_tool_calls(events_log)
    final_output = final_state.get("output", "")
    info = final_state.get("info", []) if isinstance(final_state.get("info"), list) else []

    # ---- 评分 ----
    domain_hit = any(kw in str(info) + str(final_output) for kw in ("燃气", "水务", "电务"))
    any_of = case["expected_tools"]["any_of"]
    tools_ok = bool(set(tool_names) & set(any_of)) if any_of else True
    # 输出有效性：调用的算子返回了带固定标记的原始数据，且无错误行
    output_ok = bool(tool_outputs) and not any(
        o.lstrip().startswith("[错误]") for o in tool_outputs)
    if output_ok:
        output_ok = any(
            TOOL_OUTPUT_MARKERS.get(t, "") in "\n".join(tool_outputs)
            for t in tool_names)

    checks = {
        "run_ok": ok_run,
        "domain_ok": domain_hit,
        "tools_ok": tools_ok,
        "output_ok": output_ok,
    }
    return {
        "id": case["id"], "title": case["title"],
        "category": case["category"], "question": case["question"],
        "dataset_operators": case["dataset_operators"],
        "expected_tools": any_of,
        "actual_tools": tool_names,
        "node_path": node_path,
        "tool_output_sample": tool_outputs[0][:300] if tool_outputs else "",
        "final_output_preview": str(final_output)[:300],
        "error": error,
        "elapsed_s": elapsed,
        "checks": checks,
        "passed": all(checks.values()),
    }


# =====================================================================
# 主流程
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="AgentNet-GIS 基础算子能力测试")
    parser.add_argument("-f", "--filter", default="", help="按问题文本关键字过滤用例")
    parser.add_argument("--id", default="", help="按用例ID运行")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="测试数据集JSON路径")
    parser.add_argument("--no-seed", action="store_true", help="跳过Skill播种")
    args = parser.parse_args()

    meta, all_cases = load_dataset(Path(args.dataset))
    cases = [c for c in all_cases
             if (not args.filter or args.filter in c["question"] + c["title"])
             and (not args.id or args.id == c["id"])]
    if not cases:
        print("没有匹配的测试用例。")
        return 1

    print("=" * 70)
    print(f"{meta.get('title', 'GIS 智能体测试')} v{meta.get('version', '?')}")
    print(f"  数据集: {args.dataset}")
    print(f"  用例数: {len(cases)} / {len(all_cases)}")
    print(f"  数据库: {DB_URL.split('@')[-1]}")
    print(f"  已注册智能体: {', '.join(a.name for a in registry.all())}")
    print(f"  Skill库原子算子({len(VALID_TOOL_NAMES)}个): {', '.join(sorted(VALID_TOOL_NAMES))}")
    print("=" * 70)

    # harness 持有数据库连接生命周期，用主程序的 builder 编译图
    # （主程序 get_graph() 内部 with 退出后连接已关闭，不能直接用）
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
            PostgresStore.from_conn_string(DB_URL) as store:
        checkpointer.setup()
        store.setup()
        if not args.no_seed:
            seed_skills(store)
        graph = builder.compile(checkpointer=checkpointer, store=store)
        results = run_all_cases(graph, cases)

    return finish(results, meta, args.dataset)


def run_all_cases(graph, cases):
    context = UserContext(username="GIS测试用户", membership_level="测试")
    results = []
    for i, case in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] {case['id']} {case['title']}（{case['category']}）")
        print(f"  问题: {case['question']}")
        r = run_one_case(graph, case, context)
        results.append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  => {status} | 调用算子: {r['actual_tools'] or '无'} "
              f"| 节点路径: {' → '.join(r['node_path']) or '无'} | 耗时 {r['elapsed_s']}s")
        if r["error"]:
            print(f"     错误: {r['error']}")
    return results


# =====================================================================
# 汇总报告 + 可视化
# =====================================================================
def finish(results, meta, dataset):
    n_pass = sum(1 for r in results if r["passed"])
    summary = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(dataset),
        "total": len(results), "passed": n_pass,
        "pass_rate": round(n_pass / len(results) * 100, 1),
        "total_time_s": round(sum(r["elapsed_s"] for r in results), 1),
        "avg_time_s": round(sum(r["elapsed_s"] for r in results) / max(len(results), 1), 1),
        "by_category": {},
        "by_tool": {},
    }
    for r in results:
        g = summary["by_category"].setdefault(r["category"], {"total": 0, "passed": 0})
        g["total"] += 1
        g["passed"] += 1 if r["passed"] else 0
        for t in r["actual_tools"]:
            summary["by_tool"][t] = summary["by_tool"].get(t, 0) + 1

    print("\n" + "=" * 70)
    print(f"测试完成：{n_pass}/{len(results)} 通过（准确率 {summary['pass_rate']}%）"
          f"  总耗时 {summary['total_time_s']}s，平均 {summary['avg_time_s']}s/任务")
    for c, s in summary["by_category"].items():
        print(f"  {c}: {s['passed']}/{s['total']}")
    print(f"  算子调用分布: {summary['by_tool']}")
    print("-" * 70)
    for r in results:
        mark = "✓" if r["passed"] else "✗"
        fail_reason = "" if r["passed"] else \
            " 失败项:" + ",".join(k for k, v in r["checks"].items() if not v)
        print(f"  {mark} {r['id']} [{r['category']}] 算子={r['actual_tools'] or '无'}{fail_reason}")

    report_path = REPORT_DIR / f"gis_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps({"summary": summary, "results": results},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n详细报告已写入: {report_path}")

    try:
        viz_path = render_visual_report(results, summary, meta)
        print(f"可视化报告已生成: {viz_path}")
    except Exception as e:
        print(f"[警告] 可视化生成失败: {type(e).__name__}: {e}")

    return 0 if n_pass == len(results) else 2


def render_visual_report(results, summary, meta):
    """生成可视化PNG：各任务执行路径 + 耗时 + 准确度汇总 + 算子调用分布"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False

    n = len(results)
    fig = plt.figure(figsize=(16, 3.5 + 0.55 * n + 3.5))
    gs = fig.add_gridspec(n + 4, 10, hspace=0.55)

    # ---------- 顶部汇总卡 ----------
    ax0 = fig.add_subplot(gs[0:2, :])
    ax0.axis("off")
    cards = [
        (f"{summary['passed']}/{summary['total']}", "通过任务数",
         "#2e7d32" if summary["passed"] == summary["total"] else "#c62828"),
        (f"{summary['pass_rate']}%", "任务准确率", "#1565c0"),
        (f"{summary['total_time_s']}s", "总执行时间", "#6a1b9a"),
        (f"{summary['avg_time_s']}s", "平均单任务耗时", "#ef6c00"),
    ]
    for i, (val, label, color) in enumerate(cards):
        x = 0.02 + i * 0.25
        ax0.add_patch(FancyBboxPatch((x, 0.08), 0.21, 0.8,
                                     boxstyle="round,pad=0.012", fc="#f5f5f5", ec=color, lw=1.6))
        ax0.text(x + 0.105, 0.62, val, ha="center", fontsize=17, color=color, weight="bold")
        ax0.text(x + 0.105, 0.22, label, ha="center", fontsize=10, color="#555555")
    ax0.set_title(f"{meta.get('title', 'GIS 智能体测试')} · 执行报告（{summary['time']}）",
                  fontsize=13, weight="bold", pad=14)

    # ---------- 各任务执行路径（节点序列） + 耗时条 ----------
    node_colors = {
        "detect_node": "#64b5f6", "route_node": "#81c784", "execute_node": "#ffb74d",
        "tool_node": "#e57373", "final_answer_node": "#9575cd", "learn_node": "#4db6ac",
        "end_node": "#b0bec5",
    }
    max_t = max(max(r["elapsed_s"] for r in results), 1)
    for idx, r in enumerate(results):
        row = n - 1 - idx
        ax = fig.add_subplot(gs[row, 0:7])
        ax.set_xlim(-0.5, 8.5)
        ax.set_ylim(-0.45, 0.45)
        ax.axis("off")
        path = r["node_path"]
        for j, nd in enumerate(path[:7]):
            fc = node_colors.get(nd, "#eeeeee")
            ax.add_patch(FancyBboxPatch((j, -0.22), 1.15, 0.44,
                                        boxstyle="round,pad=0.012", fc=fc, ec="#9e9e9e", lw=0.8))
            ax.text(j + 0.575, 0, nd.replace("_node", ""), ha="center", va="center", fontsize=7.5)
            if j > 0:
                ax.annotate("", xy=(j - 0.02, 0), xytext=(j - 0.18, 0),
                            arrowprops=dict(arrowstyle="->", color="#757575", lw=1))
        if len(path) > 7:
            ax.text(7.55, 0, f"+{len(path) - 7}", fontsize=8, color="#757575", va="center")
        ax.text(-0.35, 0, r["id"], ha="right", va="center", fontsize=8.5,
                color="#2e7d32" if r["passed"] else "#c62828", weight="bold")

        axt = fig.add_subplot(gs[row, 7:10])
        w = max(r["elapsed_s"], 0.05)
        axt.barh([0], [w], color="#42a5f5" if r["passed"] else "#ef5350", height=0.55)
        axt.set_xlim(0, max_t * 1.3)
        axt.set_yticks([])
        axt.set_xticks([])
        for s in axt.spines.values():
            s.set_visible(False)
        axt.text(w, 0, f" {r['elapsed_s']}s {'通过' if r['passed'] else '未通过'}",
                 va="center", fontsize=8.5,
                 color="#2e7d32" if r["passed"] else "#c62828", weight="bold")

    # ---------- 类别准确率 ----------
    axc = fig.add_subplot(gs[n + 1:n + 4, 0:5])
    cats = list(summary["by_category"].items())
    labels = [c for c, _ in cats]
    rates = [s["passed"] / s["total"] * 100 for _, s in cats]
    bars = axc.bar(labels, rates, color="#66bb6a")
    for lbl, rate, (_, s) in zip(bars, rates, cats):
        if rate < 100:
            lbl.set_color("#ef5350")
        axc.text(lbl.get_x() + lbl.get_width() / 2, rate + 2,
                 f"{int(rate)}%\n({s['passed']}/{s['total']})", ha="center", fontsize=8)
    axc.set_ylim(0, 118)
    axc.set_ylabel("准确率 (%)", fontsize=9)
    axc.set_title("各类别任务准确率", fontsize=11, weight="bold")
    axc.tick_params(axis="x", labelsize=8, rotation=25)
    axc.axhline(100, color="#bbbbbb", ls="--", lw=0.8)

    # ---------- 算子调用分布 ----------
    axo = fig.add_subplot(gs[n + 1:n + 4, 5:10])
    tools = sorted(summary["by_tool"].items(), key=lambda kv: -kv[1])
    tl = [t for t, _ in tools]
    tv = [v for _, v in tools]
    axo.barh(tl[::-1], tv[::-1], color="#5c6bc0")
    for i, v in enumerate(tv[::-1]):
        axo.text(v + 0.05, i, str(v), va="center", fontsize=8)
    axo.set_title("原子算子调用分布", fontsize=11, weight="bold")
    axo.tick_params(axis="y", labelsize=8)
    axo.set_xlim(0, max(tv) * 1.2 if tv else 1)

    out = REPORT_DIR / f"gis_test_visual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


if __name__ == "__main__":
    sys.exit(main())
