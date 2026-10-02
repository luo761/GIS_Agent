from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
DB_URL = "postgresql://langgraph_user:123456@localhost:5432/langgraph_db?sslmode=disable"
with PostgresStore.from_conn_string(DB_URL) as store:
    store.setup()
    print("===== 所有命名空间 =====")
    for ns in store.list_namespaces():
        print(" ", ns)
    for ns in [("agents",), ("experience_pool",), ("skills",)]:
        items = store.search(ns)
        print(f"\n===== {ns} 下条目（{len(items)}个）=====")
        for it in items:
            print(f"  key={it.key}  ns={it.namespace}")
