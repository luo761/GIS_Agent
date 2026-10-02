"""
================================================================================
manage_knowledge.py —— GIS 智能体知识库（skills / experience_pool）管理工具
================================================================================
知识分层设计：
  初始知识（固定 key，幂等播种，重跑不重复）：
    - skill_atomic_ops_manual_* ：各域原子算子使用说明（来自 gis_skill_library）
    - skill_tpl_<任务ID>        ：标准任务执行模板（来自测试数据集 workflow）
  增量知识（运行时产生，可清理）：
    - exp_*                     ：共享经验池的成功任务轨迹（experience_pool）
    - skill_<hash>              ：从经验蒸馏出的技能（skills/<domain>）

子命令：
  inspect                       查看技能库与经验池内容（数量/来源/重复/预览）
  clean-experience              清空共享经验池（exp_*）
  clean-distilled-skills        清空运行时蒸馏的技能（skill_<hash>），保留初始知识
  seed-base                     幂等播种初始知识（算子说明 + 标准任务模板）
  reset                         清经验池 + 清蒸馏技能 + 重播初始知识（回到出厂状态）
  dedupe                        对经验池按任务文本去重（保留最新）

用法示例：
  python manage_knowledge.py inspect
  python manage_knowledge.py inspect 燃气
  python manage_knowledge.py reset
  python manage_knowledge.py clean-experience
================================================================================
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from langgraph.store.postgres import PostgresStore

from agentnet_gis import DB_URL, SKILL_USAGE_DOCS
from gis_skill_library import ATOMIC_TOOLS

DEFAULT_DATASET = Path(__file__).parent / "GIS智能体测试数据集_v2.json"

BASE_SKILL_KEYS = ("skill_atomic_ops_manual",)   # 初始知识 key 前缀


def _is_base_skill(key: str) -> bool:
    """判断是否为初始知识（算子说明 / 标准任务模板）"""
    return key.startswith(BASE_SKILL_KEYS) or key.startswith("skill_tpl_")


def build_templates(dataset_path: Path):
    """从测试数据集生成标准任务执行模板（初始知识）"""
    data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    templates = {}
    for task in data.get("tasks", []):
        steps = "\n".join(f"  {s['step']}. {s['action']}（{s['tool']}）"
                          for s in task.get("workflow", []))
        ops = "、".join(o["operator"] for o in task.get("gis_operators", []))
        text = (f"【标准任务模板·{task['title']}】\n"
                f"场景背景：{task.get('scenario', {}).get('background', '')}\n"
                f"典型问法：{task.get('colloquial_question', '')}\n"
                f"推荐算子链：{ops}\n"
                f"标准执行流程：\n{steps}\n"
                f"结果要求：{task.get('output', {}).get('expected_check', '')}")
        templates[task["id"]] = {"text": text, "domain": None}
    return templates


def _domain_of_template(task: dict) -> str:
    """从任务文本推断模板归属域（用于选择 skills/<domain> 命名空间）"""
    blob = task.get("title", "") + task.get("scenario", {}).get("background", "") + \
           task.get("colloquial_question", "")
    for d, kws in (("燃气", ["燃气", "阀门", "泄漏", "管材", "铸铁"]),
                   ("水务", ["水务", "供水", "排水", "隐患", "洪涝", "水质", "服务区"]),
                   ("电务", ["电力", "电务", "缆线", "杆塔", "电压"])):
        if any(kw in blob for kw in kws):
            return d
    return "燃气"


def seed_base(store, dataset_path: Path = DEFAULT_DATASET):
    """幂等播种初始知识：算子使用说明 + 标准任务执行模板（固定 key，重跑覆盖不重复）"""
    n = 0
    for domain, doc in SKILL_USAGE_DOCS.items():
        store.put(("skills", domain), "skill_atomic_ops_manual",
                  {"skill": doc, "domain": domain, "reuse": 0, "origin": "base"})
        n += 1
    templates = build_templates(dataset_path)
    data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    for task in data.get("tasks", []):
        tid = task["id"]
        domain = _domain_of_template(task)
        text = templates[tid]["text"]
        store.put(("skills", domain), f"skill_tpl_{tid}",
                  {"skill": text, "domain": domain, "reuse": 0, "origin": "base", "task_id": tid})
        n += 1
    print(f"[seed-base] 初始知识播种完成：算子说明 {len(SKILL_USAGE_DOCS)} 条 + "
          f"标准任务模板 {len(templates)} 条（幂等，固定key）")
    return n


def inspect(store, domain_filter: str = ""):
    """检查技能库与经验池内容"""
    print("=" * 72)
    print("【技能库 skills/<domain>】")
    total_base, total_distilled = 0, 0
    for domain in ("燃气", "水务", "电务"):
        if domain_filter and domain_filter != domain:
            continue
        items = store.search(("skills", domain))
        base = [it for it in items if _is_base_skill(it.key)]
        distilled = [it for it in items if not _is_base_skill(it.key)]
        total_base += len(base)
        total_distilled += len(distilled)
        print(f"\n  ◆ {domain} 域（初始知识 {len(base)} 条 / 蒸馏技能 {len(distilled)} 条）")
        for it in base:
            val = it.value
            print(f"    [初始] {it.key}  长度{len(str(val.get('skill', '')))}字  "
                  f"预览: {str(val.get('skill', ''))[:60]}...")
        for it in distilled:
            val = it.value
            print(f"    [蒸馏] {it.key}  预览: {str(val.get('skill', ''))[:60]}...")

    print("\n" + "=" * 72)
    print("【共享经验池 experience_pool】")
    items = store.search(("experience_pool",))
    print(f"  总条目: {len(items)}")
    seen = {}
    dups = 0
    for it in items:
        task = str(it.value.get("task", ""))
        sig = hashlib.md5(task.encode()).hexdigest()
        if sig in seen:
            dups += 1
            print(f"  [重复] {it.key} 与 {seen[sig]} 任务文本相同: {task[:40]}...")
        else:
            seen[sig] = it.key
    for it in items:
        val = it.value
        traj = val.get("trajectory", [])
        print(f"  exp {it.key}  agent={val.get('agent', '?')}  轨迹{len(traj)}步")
        print(f"    任务: {str(val.get('task', ''))[:66]}")
        print(f"    结果: {str(val.get('result', ''))[:66]}")
    print(f"\n  重复条目: {dups}")
    print(f"【汇总】初始知识 {total_base} 条 / 蒸馏技能 {total_distilled} 条 / "
          f"经验 {len(items)} 条（重复 {dups}）")


def clean_experience(store):
    # search 是前缀搜索且有分页限制，循环删到清空为止
    total = 0
    while True:
        items = store.search(("experience_pool",))
        if not items:
            break
        for it in items:
            # 实际条目可能在 ("experience_pool", <agent>) 子命名空间
            store.delete(tuple(it.namespace), it.key)
        total += len(items)
        if len(items) < 10:  # 小于一页说明已到底
            break
    print(f"[clean-experience] 已清空经验池 {total} 条")


def clean_distilled_skills(store):
    n = 0
    for domain in ("燃气", "水务", "电务"):
        for it in store.search(("skills", domain)):
            if not _is_base_skill(it.key):
                store.delete(("skills", domain), it.key)
                n += 1
    print(f"[clean-distilled-skills] 已清空蒸馏技能 {n} 条（初始知识保留）")


def dedupe_experience(store):
    items = store.search(("experience_pool",))
    seen, removed = {}, 0
    for it in items:
        sig = hashlib.md5(str(it.value.get("task", "")).encode()).hexdigest()
        if sig in seen:
            store.delete(tuple(it.namespace), it.key)
            removed += 1
        else:
            seen[sig] = it.key
    print(f"[dedupe] 经验池去重完成，删除 {removed} 条重复项")


def main():
    parser = argparse.ArgumentParser(description="GIS智能体知识库管理工具")
    parser.add_argument("command", choices=["inspect", "clean-experience",
                                            "clean-distilled-skills", "seed-base",
                                            "reset", "dedupe"])
    parser.add_argument("filter", nargs="?", default="", help="inspect时按域过滤（燃气/水务/电务）")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    args = parser.parse_args()

    with PostgresStore.from_conn_string(DB_URL) as store:
        store.setup()
        if args.command == "inspect":
            inspect(store, args.filter)
        elif args.command == "clean-experience":
            clean_experience(store)
        elif args.command == "clean-distilled-skills":
            clean_distilled_skills(store)
        elif args.command == "seed-base":
            seed_base(store, Path(args.dataset))
        elif args.command == "reset":
            clean_experience(store)
            clean_distilled_skills(store)
            seed_base(store, Path(args.dataset))
            print("[reset] 知识库已恢复出厂状态：初始知识就位，增量知识清零")
        elif args.command == "dedupe":
            dedupe_experience(store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
