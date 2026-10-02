# main.py —— 演示入口：编译图并交互式运行一次完整任务

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langgraph.types import Command

from graph import builder
from states import UserContext
from agents import registry
from persistence import DB_URL, SKILLS_NS


def run_demo():
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
            PostgresStore.from_conn_string(DB_URL) as store:
        checkpointer.setup()
        store.setup()
        graph = builder.compile(checkpointer=checkpointer, store=store)

        config = {"configurable": {"thread_id": "agentnet_gis_demo"},
                  "recursion_limit": 20}
        context = UserContext(username="GIS测试用户", membership_level="普通用户")

        print("=" * 60)
        print("已注册智能体网络：")
        for a in registry.all():
            print(f"  • {a.name}（{a.domain}）能力={a.capabilities}")
        print("=" * 60)

        inputs = {"input": "帮我统计燃气管线总长度，并筛查燃气泄漏隐患"}
        final_state = None
        while True:
            try:
                for event in graph.stream(
                    inputs,
                    config=config,
                    context=context,
                    stream_mode=["updates", "values"],
                    version="v2"
                ):
                    print(event)
                    # ---------- 兼容 v2 结构：从 data / interrupts 中取中断信息 ----------
                    data = event.get("data") if isinstance(event, dict) else None
                    interrupts = (
                        event.get("__interrupt__")
                        or (data.get("__interrupt__") if isinstance(data, dict) else None)
                        or event.get("interrupts")
                    )
                    if interrupts:
                        for inter in interrupts:
                            print(f"⏸️ 中断：{inter.value}")
                            user_input = input("是否继续？(yes/no): ").strip().lower()
                            if user_input == "yes":
                                inputs = Command(resume=True)
                                break
                            else:
                                print("用户取消，流程终止。")
                                return
                        else:
                            continue
                        break  # 恢复后跳出 for，重新进入 while 继续流
                    else:
                        # 正常事件，保留最新状态（兼容 v2 结构：状态在 event['data']）
                        ev_data = data if isinstance(data, dict) else event
                        if isinstance(ev_data, dict) and "output" in ev_data:
                            final_state = ev_data
                else:
                    # for 正常结束（无中断）说明流执行完毕
                    break
            except KeyboardInterrupt:
                print("\n用户中断执行。")
                return

        print("\n====================执行过程记录====================")
        if final_state:
            for info in final_state.get("info", []):
                print(f"  {info}")
            print("\n====================最终输出====================")
            print(final_state.get("output", ""))
        print("\n====================沉淀的技能====================")
        skill_items = store.search((*SKILLS_NS, "燃气"))
        for item in skill_items:
            print(f"  [{item.key}] {item.value['skill']}")


if __name__ == "__main__":
    run_demo()
