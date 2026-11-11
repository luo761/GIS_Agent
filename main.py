"""端到端入口。

用法：
    python main.py "查询2023年长江流域各省份的耕地面积并从大到小排序"
    python main.py "问题" --truth "参考答案"     # 测试模式：与正确答案对比
    python main.py "问题" --reset               # 先把能力向量复位为初始 0.5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agents.capability_store import get_default_store
from config import settings
from pipeline.pipeline_graph import ask
from visualization import capability_radar_chart


def _print_routing(state) -> None:
    for sub in state.subtasks:
        decision = sub.routing or {}
        tied = decision.get("tied") or []
        way = "随机抽取" if decision.get("random_pick") else "能力最高"
        print(f"  - [{sub.subtask_id}] {sub.question[:40]}")
        print(f"      所需能力: {sub.required_capabilities}")
        print(f"      候选得分: " + "、".join(f"{k}={v:.4f}" for k, v in (decision.get('scores') or {}).items()))
        print(f"      → 智能体 {sub.assigned_agent_name}（{way}"
              + (f"，并列 {len(tied)} 个" if decision.get("random_pick") else "") + "）")


def _print_changes(state) -> None:
    if not state.capability_changes:
        print("  （无）")
        return
    for c in state.capability_changes:
        detail = "、".join(
            f"{d} {c['before'][d]:.4f}→{c['after'][d]:.4f}" for d in c["dims"]
        )
        tag = "成功" if c["outcome"] == "success" else "失败"
        print(f"  - 智能体 {c['agent_name']}（{c['subtask_id']}｜{tag}）：{detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="GIS 多智能体任务求解（能力可进化）")
    parser.add_argument("question", nargs="?",
                        default="统计严格位于施工区 A001 内、状态为正常的燃气设备数量，边界上的设备不计入。")
    parser.add_argument("--truth", default=None, help="参考答案（测试模式，用于判定成功/失败）")
    parser.add_argument("--reset", action="store_true", help="先把所有能力值复位为 0.5")
    parser.add_argument("--no-chart", action="store_true", help="不重绘能力向量图")
    args = parser.parse_args()

    if args.no_chart:
        settings.CAPABILITY_CHART_ENABLED = False

    store = get_default_store()
    if args.reset:
        store.reset()
        print("[已复位] 所有智能体能力值回到 0.50，进化历史清空\n")

    print("[输入] " + args.question + "\n")
    print("【执行前 · 能力向量表】")
    print(capability_radar_chart.render_ascii(store.snapshot()))
    print("\n【路由过程】")

    state = ask(args.question, args.truth)
    _print_routing(state)

    print("\n【领域识别】" + f"{state.domain} / {state.task_type}")
    print("【精炼问题】" + state.refined_question)
    print(f"【评估】{state.evaluation}")
    if state.failure_feedback:
        print("【失败反馈】" + state.failure_feedback[:300])
    print("【最终答案】" + str(state.final_answer))

    print("\n【本次能力进化】")
    _print_changes(state)
    print("\n【执行后 · 能力向量表】")
    print(capability_radar_chart.render_ascii(store.snapshot()))
    if state.capability_chart:
        print(f"\n动态能力向量图：{Path(state.capability_chart).resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
