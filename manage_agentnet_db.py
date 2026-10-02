"""
================================================================================
manage_agentnet_db.py — AgentNet-GIS 数据库管理脚本
================================================================================
用于查看 / 删除 / 重建 LangGraph PostgresStore 中由 agentnet_gis.py
产生的数据，以及原 project.py 产生的数据。

数据库分层（PostgresStore namespace）：
  ("agents", <智能体名>)     → 智能体独立记忆（agentnet_gis.py 新增）
  ("experience_pool",)       → 共享经验池（agentnet_gis.py 新增）
  ("skills", <领域>)         → 技能库（agentnet_gis.py 新增）
  ("fields", <领域>)         → 领域知识库（project.py 原有）
  ("users", <用户名>)        → 用户档案（project.py 原有）

Checkpoint（PostgresSaver，thread 历史）：
  agentnet_gis_demo           → agentnet_gis.py 运行产生的 thread

用法：
  python manage_agentnet_db.py show                # 仅查看，不做任何删除
  python manage_agentnet_db.py clean-agentnet      # 删除 agentnet 产生的内容
  python manage_agentnet_db.py clean-fields        # 删除领域知识库 + 用户档案（project.py 内容）
  python manage_agentnet_db.py clean-all           # 删除 store 全部内容 + 全部 checkpoint
  python manage_agentnet_db.py reset               # clean-all + 重新初始化(setup)
================================================================================
"""
import sys
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

DB_URL = "postgresql://langgraph_user:123456@localhost:5432/langgraph_db?sslmode=disable"

# agentnet_gis.py 使用到的命名空间
AGENTNET_NS = [
    ("agents",),          # 智能体独立记忆
    ("experience_pool",), # 共享经验池
    ("skills",),          # 技能库
]
# project.py 原有命名空间
PROJECT_NS = [
    ("fields",),          # 领域知识库
    ("users",),           # 用户档案
]


def show(store, checkpointer=None):
    """列出所有命名空间及其条目数量"""
    print("=" * 60)
    print("PostgresStore 命名空间总览")
    print("=" * 60)
    namespaces = store.list_namespaces()
    if not namespaces:
        print("  （数据库为空，无任何命名空间）")
    for ns in namespaces:
        items = store.search(ns)
        print(f"\n  [{ns}]  {len(items)} 条")
        for it in items:
            print(f"      · key={it.key}")
            if isinstance(it.value, dict):
                summary = {k: (str(v)[:60] + "…" if len(str(v)) > 60 else v)
                           for k, v in it.value.items()}
                print(f"        值: {summary}")

    print("\n" + "=" * 60)
    print("Checkpoint（thread 历史）")
    print("=" * 60)
    if checkpointer is None:
        print("  （未传入 checkpointer，跳过）")
        return
    threads = []
    for tup in checkpointer.list(None):
        cfg = tup.config.get("configurable", {})
        threads.append(cfg)
    if not threads:
        print("  无 checkpoint")
    for cfg in threads:
        print(f"  thread_id = {cfg.get('thread_id')}")


def delete_namespace(store, ns_prefix):
    """删除某个命名空间前缀下的所有条目（store 无 delete_namespace，需逐条删除）"""
    items = store.search(ns_prefix)
    if not items:
        return 0
    for it in items:
        store.delete(it.namespace, it.key)
    return len(items)


def clean(store, checkpointer, ns_list, *, clean_checkpoints=False, label=""):
    """批量删除指定命名空间；可选清理所有 checkpoint"""
    if label:
        print(f"\n[{label}]")
    total = 0
    for ns in ns_list:
        n = delete_namespace(store, ns)
        if n:
            print(f"  已删除 {ns} 下 {n} 条")
        total += n
    cp_n = 0
    if clean_checkpoints and checkpointer is not None:
        # 删除所有 thread checkpoint
        for tup in list(checkpointer.list(None)):
            checkpointer.delete_thread(tup.config)
            cp_n += 1
        print(f"  已删除 {cp_n} 个 thread checkpoint")
    print(f"  共清理 {total} 条 store 数据" + (f"，{cp_n} 个 checkpoint" if clean_checkpoints else ""))
    return total


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "show"

    # 建立连接
    with PostgresStore.from_conn_string(DB_URL) as store, \
            PostgresSaver.from_conn_string(DB_URL) as checkpointer:
        store.setup()
        checkpointer.setup()

        if cmd == "show":
            show(store, checkpointer)

        elif cmd == "clean-agentnet":
            clean(store, checkpointer, AGENTNET_NS,
                  clean_checkpoints=True, label="清理 agentnet 数据")

        elif cmd == "clean-fields":
            clean(store, checkpointer, PROJECT_NS,
                  clean_checkpoints=False, label="清理 project.py 数据")

        elif cmd == "clean-all":
            clean(store, checkpointer, AGENTNET_NS + PROJECT_NS,
                  clean_checkpoints=True, label="清理全部数据")

        elif cmd == "reset":
            clean(store, checkpointer, AGENTNET_NS + PROJECT_NS,
                  clean_checkpoints=True, label="重置")
            print("\n[reset] 重新初始化完成。")

        else:
            print("未知命令:", cmd)
            print("可用: show | clean-agentnet | clean-fields | clean-all | reset")
            sys.exit(1)

    print("\n完成。")


if __name__ == "__main__":
    main()

# # 1. 只查看，不做任何删除（安全）
# python
# manage_agentnet_db.py
# show
#
# # 2. 只删 AgentNet 产生的数据（智能体记忆+经验池+技能库）+ agentnet_gis_demo 的 checkpoint
# python
# manage_agentnet_db.py
# clean - agentnet
#
# # 3. 只删 project.py 原有的知识库和用户档案（不影响 agentnet）
# python
# manage_agentnet_db.py
# clean - fields
#
# # 4. 删除 store 里全部数据 + 全部 checkpoint
# python
# manage_agentnet_db.py
# clean - all
#
# # 5. 全清空并重新初始化（setup），用于重建数据库
# python
# manage_agentnet_db.py
# reset