# persistence.py

from typing import Final, Tuple

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from loguru import logger

DB_URL = "postgresql://langgraph_user:123456@localhost:5432/langgraph_db?sslmode=disable"

FIELDS_NS: Final[Tuple[str]] = ("fields",)
PREFERENCES_KEY: Final[str] = "preferences"


# [新增-文档版] 将原 __main__ 初始化逻辑封装为函数，便于入口按需调用。
def init_knowledge_base():
    """初始化记忆库，写入燃气、水务、电务领域知识库，只需要运行一次。"""

    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
            PostgresStore.from_conn_string(DB_URL) as store:
        checkpointer.setup()
        store.setup()

        namespace1 = (*FIELDS_NS, "水务")
        value1 = {
            "description": "水务信息系统，包含供水管线、排水管网、水务设施、水务隐患",
            "term": "管线长度、管网覆盖、排水隐患、供水范围、缓冲区、管线叠加、设施统计",
            "skill": "管线统计、隐患筛查、缓冲区分析、叠加分析、邻近分析"
        }

        namespace2 = (*FIELDS_NS, "电务")
        value2 = {
            "description": "电务信息系统，电力管线、电力设施",
            "term": "电缆长度、电力隐患、电力保护区缓冲区",
            "skill": "管线统计、隐患筛查"
        }

        namespace3 = (*FIELDS_NS, "燃气")
        value3 = {
            "description": "燃气信息系统，燃气管线、阀门、调压站、燃气泄漏隐患",
            "term": "燃气管线长度、泄漏隐患、燃气保护区缓冲区、管线交叉冲突",
            "skill": "管线长度统计、隐患筛查、缓冲区分析、管线叠加冲突检测"
        }

        store.put(namespace1, PREFERENCES_KEY, value1)
        store.put(namespace2, PREFERENCES_KEY, value2)
        store.put(namespace3, PREFERENCES_KEY, value3)

    logger.info("领域知识库初始化完成")


if __name__ == "__main__":
    init_knowledge_base()
