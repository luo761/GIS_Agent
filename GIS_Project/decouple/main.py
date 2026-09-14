# main.py

import os

# Must be set before importing graph/nodes/tools.
os.environ["GIS_TOOL_PROFILE"] = "operator"
os.environ["GIS_TOOL_EXECUTION_MODE"] = "sequential"

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langgraph.types import Command

from graph import builder
from persistence import DB_URL
from states import UserContext


TEST_QUESTIONS = [
    # {
    #     "name": "pipe_length_in_area",
    #     "input": "请统计 A区 内燃气管线的总长度。请先分析问题并规划步骤，只能调用底层 GIS operators 完成计算。",
    #     "fieldnames": ["燃气"],
    # },
    {
        "name": "hazards_near_pipes",
        "input": "请查询燃气管线 100 米范围内有哪些隐患点。请先分析问题并规划步骤，只能调用底层 GIS operators 完成计算。",
        "fieldnames": ["燃气"],
    },
    # {
    #     "name": "gas_water_cross_conflict",
    #     "input": "请检查燃气管线和水务管线是否存在交叉或 20 米内的近距离冲突。请先分析问题并规划步骤，只能调用底层 GIS operators 完成计算。",
    #     "fieldnames": ["燃气", "水务"],
    # },
    # {
    #     "name": "facility_coverage_in_area",
    #     "input": "请统计 A区 内燃气设施 300 米服务半径的覆盖面积和覆盖率。请先分析问题并规划步骤，只能调用底层 GIS operators 完成计算。",
    #     "fieldnames": ["燃气"],
    # },
]


def _normalize_event(event):
    """Support both dict events and (stream_mode, data) events."""

    if isinstance(event, tuple) and len(event) == 2:
        event_type, data = event
        return event_type, data if isinstance(data, dict) else {}

    if isinstance(event, dict):
        event_type = event.get("type")
        data = event.get("data", {})
        return event_type, data if isinstance(data, dict) else {}

    return None, {}


def _get_interrupts(event, data):
    if isinstance(event, dict):
        return event.get("interrupts") or data.get("__interrupt__")
    return data.get("__interrupt__")


def run_one_case(graph, case, case_index):
    config = {
        "configurable": {"thread_id": f"GIS_operator_test_{case_index}_{case['name']}"},
        "recursion_limit": 50,
    }
    context = UserContext(username="GIS测试用户", membership_level="普通用户")

    inputs = {
        "input": case["input"],
        "fieldnames": case["fieldnames"],
    }
    final_state = None

    print(f"\n==================== 测试 {case_index}: {case['name']} ====================")
    print(case["input"])

    while True:
        interrupted = False

        for event in graph.stream(
            inputs,
            config=config,
            context=context,
            stream_mode=["updates", "values"],
        ):
            print(event)

            event_type, data = _normalize_event(event)
            interrupts = _get_interrupts(event, data)

            if interrupts:
                interrupted = True
                for inter in interrupts:
                    print(f"中断：{inter.value}")
                    user_input = input("是否继续？(yes/no): ").strip().lower()
                    if user_input == "yes":
                        inputs = Command(resume=True)
                        break
                    print("用户取消，流程终止。")
                    return final_state
                break

            if event_type == "values" and data:
                final_state = data

        if not interrupted:
            break

    if final_state:
        if final_state.get("info"):
            print("\n==================== 执行过程记录 ====================")
            for info_msg in final_state["info"]:
                print(info_msg)

        print("\n==================== 消息记录 ====================")
        for msg in final_state.get("messages", []):
            msg.pretty_print()

        if final_state.get("output"):
            print("\n==================== 最终输出 ====================")
            print(final_state["output"])

    return final_state


def run_demo():
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
         PostgresStore.from_conn_string(DB_URL) as store:
        checkpointer.setup()
        store.setup()
        graph = builder.compile(checkpointer=checkpointer, store=store)

        for index, case in enumerate(TEST_QUESTIONS, start=1):
            run_one_case(graph, case, index)


if __name__ == "__main__":
    print("GIS_TOOL_PROFILE =", os.environ["GIS_TOOL_PROFILE"])
    print("GIS_TOOL_EXECUTION_MODE =", os.environ["GIS_TOOL_EXECUTION_MODE"])
    run_demo()
