# main.py

from graph import builder
from states import UserContext
from persistence import DB_URL
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

if __name__ == "__main__":
    # with内部才拿到真正的checkpointer、store实例
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
            PostgresStore.from_conn_string(DB_URL) as store:

        # compile 在with内部执行
        graph = builder.compile(checkpointer=checkpointer, store=store)

        config = {
            "configurable": {
                "thread_id": "gis_demo_003"
            },
            "recursion_limit": 10
        }

        # 示例1：燃气业务提问
        res1 = graph.invoke(
            {
                "input": "帮我统计燃气管线总长度",
                "fieldname": "燃气"
            },
            config=config,
            context=UserContext(username="老王", membership_level="普通用户")
        )

        for msg in res1["messages"]:
            msg.pretty_print()

        print("=====提问1结果=====")
        print(res1["output"])

        # # 示例2：水务缓冲区分析提问，复用同一个thread会话
        # res2 = graph.invoke(
        #     {
        #         "input": "给水隐患点做100米缓冲区分析",
        #         "fieldname": "水务"
        #     },
        #     config=config,
        #     context=UserContext(username="老王", membership_level="普通用户")
        # )
        # print("\n=====提问2结果=====")
        # print(res2["output"])