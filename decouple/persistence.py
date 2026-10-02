# persistence.py —— Postgres 持久化配置 + 共享经验池 + 技能沉淀

from typing import Final, Tuple, List

from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage

from models import model

# =====================================================================
# 2. 持久化配置（Postgres）
# =====================================================================
DB_URL = "postgresql://langgraph_user:123456@localhost:5432/langgraph_db?sslmode=disable"

AGENTS_NS: Final[Tuple[str]] = ("agents",)               # 智能体独立记忆根
EXPERIENCE_NS: Final[Tuple[str]] = ("experience_pool",)  # 共享经验池
SKILLS_NS: Final[Tuple[str]] = ("skills",)               # 技能库

# =====================================================================
# 6. 共享经验池 & 技能沉淀（PostgresStore 操作）
# =====================================================================

class ExperiencePool:
    """共享经验池：所有智能体共用，记录成功任务轨迹，供后续 few-shot 检索"""

    @staticmethod
    def record(store, task: str, agent: str, trajectory: List[str],
               result: str) -> None:
        """把一次成功任务写入共享经验池"""
        entry_id = f"exp_{abs(hash(task + agent + str(len(trajectory))))}"
        store.put(
            EXPERIENCE_NS,
            entry_id,
            {
                "task": task,
                "agent": agent,
                "trajectory": trajectory,     # 成功思路轨迹
                "result": result,
                "source": "shared",
            },
        )
        logger.info(f"[经验池] 已记录成功任务 {entry_id}：{agent} <- {task}")

    @staticmethod
    def retrieve(store, query: str, k: int = 3) -> List[dict]:
        """按前缀检索共享经验（可扩展为向量相似度）"""
        items = store.search(EXPERIENCE_NS)
        # 简化检索：按 query 关键词匹配
        hits = []
        for item in items:
            val = item.value
            if any(kw in query for kw in val.get("task", "")) or \
               any(kw in val.get("result", "") for kw in query.split()):
                hits.append(val)
            if len(hits) >= k:
                break
        return hits

class SkillManager:
    """技能沉淀：任务成功后用 LLM 把成功思路归纳成可复用 skill 写入数据库"""

    @staticmethod
    def build_skill_from_trajectory(trajectory: List[str], result: str,
                                    domain: str) -> str:
        """LLM 把成功执行轨迹提炼为通用方法论（skill）"""
        prompt = SystemMessage(content=(
            "你是技能沉淀引擎。给定一次成功完成的 GIS 任务执行轨迹与结果，"
            "请提炼成一段可复用的『技能描述』，说明：任务的通用场景、关键步骤、"
            "推荐调用的工具、注意事项。要求简洁、通用、可迁移。"
        ))
        human = HumanMessage(content=(
            f"领域：{domain}\n执行轨迹：\n" + "\n".join(trajectory) +
            f"\n最终结果：{result}"
        ))
        resp = model.invoke([prompt, human])
        return resp.content

    @staticmethod
    def store_skill(store, skill_id: str, skill_text: str, domain: str) -> None:
        """把 skill 写入数据库（skills 命名空间）"""
        store.put(
            (*SKILLS_NS, domain),
            skill_id,
            {"skill": skill_text, "domain": domain, "reuse": 0},
        )
        logger.info(f"[技能库] 已沉淀技能 {skill_id}（{domain}）")
