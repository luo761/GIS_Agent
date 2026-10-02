import psycopg

DB_URL = "postgresql://langgraph_user:123456@localhost:5432/langgraph_db?sslmode=disable"

def clear_all_checkpoints():
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE checkpoints, checkpoint_writes, checkpoint_blobs CASCADE;")
        conn.commit()
    print("所有 checkpoint 已清空，store 数据未受影响。")

def clear_thread(thread_id: str):
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
            cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
        conn.commit()
    print(f"thread_id={thread_id} 的 checkpoint 已清空。")

if __name__ == "__main__":
    # 调用示例
    clear_all_checkpoints()
    # clear_thread("gis_demo_001")