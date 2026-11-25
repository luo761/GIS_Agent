"""端到端入口。

用法：
    python main.py "查询2023年长江流域各省份的耕地面积并从大到小排序"
    python main.py "问题" --truth "参考答案"     # 测试模式：与正确答案对比
    python main.py "问题" --reset               # 先把能力向量复位为初始 0.5
    python main.py "问题" --user guest          # 以“访客”身份运行（只读权限）
    python main.py "问题" --role viewer --no-clarify

安全增强：
  * 阶段①会判定问题是否合法；命中“问题不合法”时不拆解、不执行，
    只打印追问文本，交互终端下可连续补充信息后重跑（最多 3 轮）。
  * `--user/--role` 按 `config/user_permissions.yaml` 解析用户类别，
    表结构注入与工具执行都会按该角色的增删改查权限校验。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agents.capability_store import get_default_store
from config import settings
from pipeline.pipeline_graph import ask
from security import permissions, question_guard
from visualization import capability_radar_chart

EXIT_INVALID_QUESTION = 2


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


def _print_permission(role: str) -> None:
    table = permissions.get_table()
    allowed = table.allowed_tables(role, "select")
    print(f"[用户类别] {table.role_name(role)}（{role}）"
          f"｜可查询 {len(allowed)} 张表：" + ("、".join(allowed) or "无"))


def _print_invalid(state) -> None:
    print("\n【问题不合法】本次不进入拆解/规划/执行，未产生任何数据库操作。")
    print("【判定来源】" + (state.validity_source or "rule"))
    for reason in state.invalid_reasons:
        print("  - " + reason)
    if state.missing_info:
        print("【缺少信息】" + "、".join(m["name"] for m in state.missing_info))
    print("\n" + (state.clarification or state.final_answer))


def _clarify(question: str, args, user: str) -> int:
    """问题不合法时的补充信息循环：用户不断补充，直到可执行或用完轮数。"""
    max_rounds = max(1, int(args.clarify_rounds))
    rounds = 0
    current = question
    while True:
        state = ask(current, args.truth, user=user, rounds=rounds)
        if state.is_valid:
            break
        _print_invalid(state)
        interactive = not args.no_clarify and sys.stdin.isatty()
        if not interactive:
            if not args.no_clarify:
                print("\n[提示] 当前不是交互终端，未进入追问；请补充信息后重新运行。")
            return EXIT_INVALID_QUESTION
        if rounds >= max_rounds:
            print(f"\n[提示] 已达到最大追问轮数 {max_rounds}，仍缺少关键信息，本次结束。")
            return EXIT_INVALID_QUESTION
        print(f"\n[追问 {rounds + 1}/{max_rounds}] 请补充缺失信息（直接回车或输入 q 退出）：")
        try:
            supplement = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[已取消]")
            return EXIT_INVALID_QUESTION
        if not supplement or supplement.lower() in ("q", "quit", "exit"):
            print("[已取消] 问题仍未补充完整。")
            return EXIT_INVALID_QUESTION
        rounds += 1
        current = current + "\n补充说明：" + supplement
        print("\n[重新识别] 结合补充信息重新执行阶段①…")

    print("\n【路由过程】")
    _print_routing(state)

    print("\n【领域识别】" + f"{state.domain} / {state.task_type}")
    print("【精炼问题】" + state.refined_question)
    print(f"【评估】{state.evaluation}")
    if state.failure_feedback:
        print("【失败反馈】" + state.failure_feedback[:300])
    if state.permission_denials:
        print("【权限拒绝】" + str(len(state.permission_denials)) + " 次："
              + "；".join(f"{d.get('table')}/{d.get('action')}" for d in state.permission_denials))
    print("【最终答案】" + str(state.final_answer))
    if state.clarification_rounds:
        print(f"【追问轮数】{state.clarification_rounds}")

    print("\n【本次能力进化】")
    _print_changes(state)
    print("\n【执行后 · 能力向量表】")
    print(capability_radar_chart.render_ascii(get_default_store().snapshot()))
    if state.capability_chart:
        print(f"\n动态能力向量图：{Path(state.capability_chart).resolve()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="GIS 多智能体任务求解（能力可进化 + 权限校验）")
    parser.add_argument("question", nargs="?",
                        default="统计严格位于施工区 A001 内、状态为正常的燃气设备数量，边界上的设备不计入。")
    parser.add_argument("--truth", default=None, help="参考答案（测试模式，用于判定成功/失败）")
    parser.add_argument("--reset", action="store_true", help="先把所有能力值复位为 0.5")
    parser.add_argument("--no-chart", action="store_true", help="不重绘能力向量图")
    parser.add_argument("--role", default="analyst",
                        choices=["admin", "analyst", "operator", "viewer"],
                        help="用户类别（角色），决定表级增删改查权限")
    parser.add_argument("--user", default="",
                        help="用户标识，按权限表 principals 解析角色（优先于 --role）")
    parser.add_argument("--no-clarify", action="store_true",
                        help="问题不合法时只打印追问，不进入交互补充循环")
    parser.add_argument("--clarify-rounds", type=int,
                        default=int(question_guard.load_rules().get("max_clarify_rounds") or 3),
                        help="问题不合法时最多追问轮数")
    args = parser.parse_args()

    if args.no_chart:
        settings.CAPABILITY_CHART_ENABLED = False

    role = permissions.resolve_role(args.user or args.role)
    user = args.user or role
    if args.user and args.user in permissions.get_table().principals and args.user not in permissions.get_table().roles:
        print(f"[身份] 用户 {args.user} → 角色 {role}（{permissions.get_table().role_name(role)}）")

    store = get_default_store()
    if args.reset:
        store.reset()
        print("[已复位] 所有智能体能力值回到 0.50，进化历史清空\n")

    print("[输入] " + args.question + "\n")
    _print_permission(role)
    print("\n【执行前 · 能力向量表】")
    print(capability_radar_chart.render_ascii(store.snapshot()))
    return _clarify(args.question, args, user)


if __name__ == "__main__":
    sys.exit(main())
