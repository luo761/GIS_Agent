"""离线演示：不调用任何 LLM，模拟一串任务，展示"初始均衡 → 经验进化"的过程。

演示在临时目录中进行，不会改动 data/ 下的真实能力状态；
生成的能力向量图写到 docs/，可直接打开查看动画。

用法：
    python scripts/demo_evolution.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402

# ---- 先把所有落盘路径指向临时目录，避免污染真实状态 ----
_TMP = Path(tempfile.mkdtemp(prefix="gis_mas_demo_"))
settings.BASE_DIR = _TMP
settings.DATA_DIR = _TMP
settings.CAPABILITY_PATH = _TMP / "agent_capabilities.json"
settings.EXPERIENCE_PATH = _TMP / "experience.json"
settings.AGENT_MEMORY_BASE = _TMP / "memory"
settings.CAPABILITY_CHART_HTML = ROOT / "docs" / "demo_capability_vector_chart.html"
settings.CAPABILITY_CHART_PNG = ROOT / "docs" / "demo_capability_vector_chart.png"

from experience.experience_pool import ExperiencePool  # noqa: E402
from agents.capability_store import CapabilityStore, set_default_store  # noqa: E402
from visualization import capability_radar_chart  # noqa: E402
from pipeline import llm_client as llm  # noqa: E402
import pipeline.stage5_evaluate as stage5  # noqa: E402
from experience import experience_retriever as retrieval  # noqa: E402


# ---------------------------------------------------------------- 场景
SCENARIOS = [
    dict(q="统计各区县供水管网总长度并从大到小排序", task_type="统计分析",
         dims=["statistics"], ok=True, answer="各区县管网长度已排序"),
    dict(q="统计各区县供水管网总长度并从大到小排序", task_type="统计分析",
         dims=["statistics"], ok=True, answer="各区县管网长度已排序"),
    dict(q="为燃气管线生成50米缓冲并统计受影响的阀门", task_type="空间计算",
         dims=["spatial_compute"], ok=True, answer="受影响阀门 37 个"),
    dict(q="为燃气管线生成50米缓冲并统计受影响的阀门", task_type="空间计算",
         dims=["spatial_compute"], ok=True, answer="受影响阀门 37 个"),
    dict(q="筛选2023年新增的供水管段", task_type="属性查询",
         dims=["attribute_query"], ok=True, answer="新增供水管段 128 条"),
    dict(q="筛选2023年新增的供水管段", task_type="属性查询",
         dims=["attribute_query"], ok=True, answer="新增供水管段 128 条"),
    dict(q="制作土地利用专题图并导出 PNG", task_type="制图可视化",
         dims=["mapping"], ok=True, answer="专题图已导出"),
    dict(q="制作土地利用专题图并导出 PNG", task_type="制图可视化",
         dims=["mapping"], ok=True, answer="专题图已导出"),
    dict(q="统计各电压等级线路长度占比", task_type="统计分析",
         dims=["statistics"], ok=False, answer="占比算错了"),
    dict(q="统计各电压等级线路长度占比", task_type="统计分析",
         dims=["statistics"], ok=True, answer="占比已给出"),
]


class DemoLLM:
    """根据当前场景返回固定内容。"""

    def __init__(self):
        self.scenario = SCENARIOS[0]
        self.used_tools: list[str] = []

    def chat(self, prompt: str, system: str = "") -> str:
        if "压缩为不超过200字" in prompt:
            return "演示经验摘要"
        if "汇总为一份完整答案" in prompt:
            return "演示汇总答案"
        if "避免措施" in prompt:
            return "参数与表名不匹配，下一次先核对字段"
        return "演示输出"

    def chat_json(self, prompt: str, system: str = "") -> dict:
        sc = self.scenario
        if "候选领域" in prompt:
            return {"domain": "general", "task_type": sc["task_type"], "reason": "演示"}
        if "formalize" in prompt:
            return {
                "formalized_question": sc["q"],
                "subtasks": [{
                    "subtask_id": "t1",
                    "question": sc["q"],
                    "required_capabilities": sc["dims"],
                }],
            }
        if "请参考你的专属记忆与共享经验" in prompt:
            tool = TOOL_FOR_DIM[sc["dims"][0]]
            return {"plan": {"nodes": [{"id": "s1", "action": tool,
                                        "params": TOOL_PARAMS[tool],
                                        "depends_on": []}],
                             "edges": []}}
        if "正确答案" in prompt:
            if sc["ok"]:
                return {"correct": True, "reason": "演示：结果一致", "faulty_subtasks": []}
            return {"correct": False, "reason": "演示：数值口径错误", "faulty_subtasks": ["t1"]}
        return {}

    def chat_with_tools(self, messages):
        """模拟绑定工具后的模型：先发起一次工具调用，再给出最终结果。"""
        sc = self.scenario
        tool = TOOL_FOR_DIM[sc["dims"][0]]
        tool_msgs = [m for m in messages if getattr(m, "type", "") == "tool"]
        if not tool_msgs:
            return _AI(tool_calls=[{"name": tool, "args": TOOL_PARAMS[tool],
                                    "id": "call_1"}])
        return _AI(content=sc["answer"])


class _AI:
    """模拟 AIMessage：带 tool_calls 或带最终 content。"""

    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


TOOL_FOR_DIM = {
    "statistics": "group_aggregate",
    "spatial_compute": "buffer",
    "attribute_query": "attribute_filter",
    "mapping": "render_thematic_map",
}

TOOL_PARAMS = {
    "group_aggregate": {"table": "region_stat", "group_by": "region_name",
                        "field": "area", "stat_type": "sum"},
    "buffer": {"layer": "gas_pipeline", "distance": 50, "unit": "m"},
    "attribute_filter": {"table": "water_pipeline", "condition": "year=2023"},
    "render_thematic_map": {"layer": "land_use_2023", "field": "type", "scheme": "graded"},
}


def main() -> int:
    store = CapabilityStore(settings.CAPABILITY_PATH, with_chart=True)
    set_default_store(store)
    stage5._store = ExperiencePool(settings.EXPERIENCE_PATH)
    retrieval._store = stage5._store

    stub = DemoLLM()
    llm.chat = stub.chat
    llm.chat_json = stub.chat_json
    llm.chat_with_tools = stub.chat_with_tools

    from pipeline.pipeline_graph import ask

    print("【初始能力向量表】所有智能体所有维度 = 0.50")
    print(capability_radar_chart.render_ascii(store.snapshot()))
    print()

    for i, sc in enumerate(SCENARIOS, 1):
        stub.scenario = sc
        state = ask(sc["q"], ground_truth=sc["answer"] if not sc["ok"] else None)
        agent = state.subtasks[0].assigned_agent_name if state.subtasks else "-"
        tag = "随机" if state.subtasks and state.subtasks[0].routing.get("random_pick") else "能力最高"
        print(f"{i:2d}. {sc['q'][:26]:<30} → 智能体 {agent}（{tag}）｜评估 {state.evaluation}")

    snapshot = store.snapshot()
    print("\n【演示结束 · 能力向量表】")
    print(capability_radar_chart.render_ascii(snapshot))
    paths = store.refresh_chart()
    print(f"\n动态能力向量图（可回放）：{paths.get('html')}")
    if paths.get("png"):
        print(f"当前状态快照：{paths['png']}")
    print(f"\n演示状态目录（临时）：{_TMP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
