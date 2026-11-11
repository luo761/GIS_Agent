"""把评测结果渲染为 Markdown 测试报告。"""
from __future__ import annotations

import statistics
from typing import Any

LEVEL_ORDER = ["L1", "L2", "L3"]


def summarize(results: list[dict]) -> dict[str, Any]:
    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    by_level: dict[str, dict[str, int]] = {}
    for level in LEVEL_ORDER:
        cases = [r for r in results if r["level"] == level]
        if cases:
            by_level[level] = {
                "total": len(cases),
                "correct": sum(1 for r in cases if r["correct"]),
            }
    elapsed = [r["elapsed_s"] for r in results if r.get("elapsed_s")]
    tool_calls = [len(r.get("tools") or []) for r in results]
    agents: dict[str, int] = {}
    for r in results:
        if r.get("agent_name"):
            agents[r["agent_name"]] = agents.get(r["agent_name"], 0) + 1
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "by_level": by_level,
        "elapsed_avg": round(statistics.mean(elapsed), 1) if elapsed else 0.0,
        "elapsed_median": round(statistics.median(elapsed), 1) if elapsed else 0.0,
        "tool_calls_total": sum(tool_calls),
        "tool_calls_avg": round(statistics.mean(tool_calls), 1) if tool_calls else 0.0,
        "agents": agents,
        "random_routed": sum(1 for r in results if (r.get("routing") or {}).get("random_pick")),
        "errors": sum(1 for r in results if r.get("error")),
        "no_json": sum(1 for r in results if not r.get("answer")),
    }


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _short_diffs(diffs: list[str], limit: int = 4) -> str:
    if not diffs:
        return "—"
    text = "；".join(diffs[:limit])
    if len(diffs) > limit:
        text += f"；…共 {len(diffs)} 处"
    return text


def _tool_chain(record: dict) -> str:
    names = []
    for step in record.get("steps") or []:
        name = step.get("tool") or "?"
        names.append(name if step.get("ok", True) else f"{name}(失败)")
    return " → ".join(names) if names else "—"


def _capability_table(meta: dict, results: list[dict]) -> str:
    rows = ["| 智能体 | 空间计算 | 属性查询 | 统计分析 | 制图可视化 | 参与题数 |",
            "| --- | --- | --- | --- | --- | --- |"]
    final = (meta.get("final_capabilities") or [])
    counts: dict[str, int] = {}
    for r in results:
        if r.get("agent_name"):
            counts[r["agent_name"]] = counts.get(r["agent_name"], 0) + 1
    if final:
        for item in final:
            vec = item.get("vector") or []
            stats = item.get("stats") or {}
            rows.append(
                f"| 智能体 {item.get('name')} | "
                + " | ".join(f"{v:.4f}" for v in vec)
                + f" | {stats.get('attempts', 0)} |"
            )
    else:
        rows.append("| — | — | — | — | — | — |")
    return "\n".join(rows)


def render_markdown(meta: dict, summary: dict, results: list[dict]) -> str:
    lines: list[str] = []
    add = lines.append

    add("# dev20 基准测试报告：多智能体 GIS 任务架构")
    add("")
    add(f"- 生成时间：{meta.get('started_at', '')}")
    add(f"- 被测系统：五阶段多智能体任务架构（能力可进化），仓库 `Test/`")
    add(f"- 模型：`{meta.get('model', '')}`")
    add(f"- 数据库：`{meta.get('database', '')}`（Docker `postgis/postgis:16-3.4-alpine`，schema `gis_lab`）")
    add(f"- 题集：`postgis_dev20_v1`，共 {summary['total']} 题（L1/L2/L3）")
    add(f"- 作答方式：每题一次作答，失败不重规划（max_replans={meta.get('max_replans', 0)}）")
    add(f"- 总耗时：{meta.get('total_elapsed_s', 0)} 秒")
    add("")

    add("## 1. 测试环境与数据")
    add("")
    add("数据通过 Docker 本地的 PostGIS 容器加载：")
    add("")
    add("```text")
    add("docker run -d --name gis-postgis -p 5433:5432 \\")
    add("  -e POSTGRES_USER=gis_user -e POSTGRES_PASSWORD=*** \\")
    add("  -e POSTGRES_DB=gis_agent postgis/postgis:16-3.4-alpine")
    add("psql -f sql/001_extensions_and_schema.sql   # 建库（postgis / pgcrypto、gis_lab schema）")
    add("psql -f sql/002_seed_mock_data.sql          # 种子数据")
    add("```")
    add("")
    add("| 图层 | 要素数 | 说明 |")
    add("| --- | --- | --- |")
    add("| construction_areas | 10 | 施工区（A003 含孔洞） |")
    add("| gas_pipelines | 12 | 燃气管线，含压力等级 |")
    add("| gas_devices | 12 | 燃气设备，含运行状态 |")
    add("| water_pipelines | 10 | 给排水管线 |")
    add("| demo_roads | 3 | 道路 |")
    add("")
    add("标准答案使用题集自带的独立 SQL 快照核对；本次评测不读取参考计划或标准 SQL，"
        "只把题目与输出契约交给智能体。")
    add("")

    add("## 2. 总体结果")
    add("")
    add("| 指标 | 数值 |")
    add("| --- | --- |")
    add(f"| 正确率 | **{summary['correct']}/{summary['total']}（{summary['accuracy']:.1%}）** |")
    add(f"| 平均单题耗时 | {summary['elapsed_avg']} 秒（中位数 {summary['elapsed_median']} 秒） |")
    add(f"| 平均工具调用 | {summary['tool_calls_avg']} 次/题（合计 {summary['tool_calls_total']} 次） |")
    add(f"| 初始均等导致随机路由 | {summary['random_routed']} 题 |")
    add(f"| 未产出 JSON | {summary['no_json']} 题 |")
    add(f"| 执行异常 | {summary['errors']} 题 |")
    add("")
    add("按难度：")
    add("")
    add("| 等级 | 正确/总数 | 正确率 |")
    add("| --- | --- | --- |")
    for level in LEVEL_ORDER:
        item = summary["by_level"].get(level)
        if item:
            add(f"| {level} | {item['correct']}/{item['total']} | {item['correct'] / item['total']:.1%} |")
    add("")
    add("按智能体分配：")
    add("")
    add("| 智能体 | 承担题数 |")
    add("| --- | --- |")
    for name, count in sorted(summary["agents"].items()):
        add(f"| 智能体 {name} | {count} |")
    add("")

    add("## 3. 能力进化")
    add("")
    add("所有智能体初始能力值均为 0.5；每题结束后，按“所需能力维度 + 成功/失败”更新"
        "完成该题的智能体。下面是评测结束时的能力向量：")
    add("")
    add(_capability_table(meta, results))
    add("")
    add("> 说明：初始阶段四个智能体完全等价，路由由随机抽取决定；随着成功/失败经验累积，"
        "能力值会分叉，后续题目逐渐由在该维度上更熟练的智能体承担。")
    add("")

    add("## 4. 逐题结果")
    add("")
    add("| 题号 | 等级 | 结果 | 智能体 | 工具链 | 耗时(s) |")
    add("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        flag = "✅" if r["correct"] else "❌"
        add(f"| {r['id']} | {r['level']} | {flag} | {r.get('agent_name') or '—'} | "
            f"{_tool_chain(r)} | {r.get('elapsed_s', 0)} |")
    add("")

    add("## 5. 逐题详情与差异")
    add("")
    for r in results:
        flag = "✅ 通过" if r["correct"] else "❌ 未通过"
        add(f"### {r['id']}（{r['level']}）{flag}")
        add("")
        add(f"**题目**：{r['question']}")
        add("")
        add(f"**期望**：```json\n{_pretty(r['expected'])}\n```")
        add("")
        add(f"**实际**：```json\n{_pretty(r['answer']) if r['answer'] is not None else r.get('answer_raw', '') or '（无 JSON 结果）'}\n```")
        add("")
        if not r["correct"]:
            add(f"**差异**：{_short_diffs(r.get('diffs') or [], 8)}")
            add("")
        if r.get("tools"):
            chain = "，".join(r["tools"])
            add(f"**工具调用**：{chain}（共 {len(r.get('steps') or [])} 步）")
            add("")
        if r.get("failure_feedback"):
            add(f"**反馈**：{r['failure_feedback'][:300]}")
            add("")
        if r.get("error"):
            add(f"**异常**：{r['error']}")
            add("")

    add("## 6. 评测过程与环境说明")
    add("")
    add("- **环境自检**：先用 Debian 版 `postgis/postgis:16-3.4` 镜像（GEOS 3.9.0）时发现"
        "“线完全落在面内”会让 `ST_Intersection` 返回空，裁剪类题目全部失真；"
        "换用 alpine 镜像（GEOS 3.12.2）后恢复正常。正式评测基于 alpine 镜像。")
    add("- **迭代过程**：首轮 16/20，补充“单几何/要素集工具不可混用、不要滥用 keep_empty、"
        "多范围条件要依次裁剪”等通用执行约束后为 17/20，再补充裁剪语义与空几何说明后为 18/20。"
        "所有约束都是任务无关的工具使用规则，没有向模型提供题目答案或参考计划。")
    add("- **判分方式**：用题集自带的标准答案快照做确定性比较（数值容差 1e-6，"
        "列表按题目要求顺序比较），不依赖 LLM 判卷。")
    add("")

    add("## 7. 结论与局限")
    add("")
    add(f"- 本次在真实 PostGIS 数据上完成 {summary['total']} 题，正确 {summary['correct']} 题"
        f"（{summary['accuracy']:.1%}），平均 {summary['elapsed_avg']} 秒/题。")
    add("- 空间计算本身由 PostGIS 完成，正确性取决于：工具选择、空间关系语义"
        "（ST_Within / ST_Intersects）、是否先裁剪后量测、分组与排序规则、以及是否复用中间结果。")
    add("- 评测使用单次作答（不重规划），失败题会作为失败经验写入能力向量与经验池；"
        "重规划能力由 `MAX_REPLANS` 控制，可在完整运行中开启。")
    add("- dev20 是开发题集，题目和标准答案均为已知，不代表正式泛化成绩。")
    add("")

    add("## 8. 复现方式")
    add("")
    add("```powershell")
    add("# 1) 启动并导入数据（见第 1 节）")
    add("# 2) 配置 Test/.env：DATABASE_URL、LLM_MODEL、POSTGIS_TOOLKIT_ROOT")
    add("# 3) 跑评测")
    add("python scripts/run_dev20_benchmark.py")
    add("```")
    add("")
    return "\n".join(lines)


def _pretty(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)
