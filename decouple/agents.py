# agents.py —— 智能体注册表（AgentNet 核心：多智能体能力向量独立）

from dataclasses import dataclass
from typing import Tuple, Optional, List

from loguru import logger

from persistence import AGENTS_NS

# =====================================================================
# 4. 智能体注册表（注册多个不同智能体，能力向量独立）
# =====================================================================

@dataclass
class GISAgent:
    """单个 GIS 智能体：领域 + 描述 + 能力向量 + 独立记忆 namespace"""
    name: str
    domain: str
    description: str
    capabilities: dict                      # 能力向量 {能力: 分数}
    memory_ns: Tuple[str, ...]              # 独立记忆 namespace

    def memory_namespace(self) -> Tuple[str, ...]:
        return (*AGENTS_NS, self.name)

class AgentRegistry:
    """智能体注册表：动态注册、按名取用、全量遍历"""
    def __init__(self):
        self._agents: dict[str, GISAgent] = {}

    def register(self, agent: GISAgent) -> "AgentRegistry":
        if agent.name in self._agents:
            logger.warning(f"智能体 {agent.name} 已存在，覆盖注册")
        self._agents[agent.name] = agent
        logger.info(f"[注册表] 注册智能体：{agent.name}（领域={agent.domain}）")
        return self

    def get(self, name: str) -> Optional[GISAgent]:
        return self._agents.get(name)

    def all(self) -> List[GISAgent]:
        return list(self._agents.values())

    def match(self, domain: str) -> Optional[GISAgent]:
        """按领域匹配最合适的智能体（去中心化：每个智能体只关心自己擅长领域）"""
        for agent in self._agents.values():
            if domain and agent.domain == domain:
                return agent
        # 兜底：能力向量总和最高的智能体
        if self._agents:
            return max(self._agents.values(),
                       key=lambda a: sum(a.capabilities.values()))
        return None

# 实例化并注册三个不同智能体（燃气 / 水务 / 电务）
registry = AgentRegistry()

registry.register(GISAgent(
    name="燃气智能体",
    domain="燃气",
    description="负责燃气管线长度统计、泄漏隐患筛查、燃气保护区缓冲区、管线交叉冲突检测",
    capabilities={"管线统计": 0.9, "隐患筛查": 0.85, "缓冲区分析": 0.8, "叠加分析": 0.7},
    memory_ns=("agents", "燃气"),
))

registry.register(GISAgent(
    name="水务智能体",
    domain="水务",
    description="负责供水管线、排水管网统计、管网破损与淤积隐患筛查、水务缓冲区分析",
    capabilities={"管线统计": 0.85, "隐患筛查": 0.8, "缓冲区分析": 0.85, "叠加分析": 0.6},
    memory_ns=("agents", "水务"),
))

registry.register(GISAgent(
    name="电务智能体",
    domain="电务",
    description="负责电力管线统计、电力隐患筛查、电力保护区缓冲区分析",
    capabilities={"管线统计": 0.8, "隐患筛查": 0.75, "缓冲区分析": 0.8, "叠加分析": 0.5},
    memory_ns=("agents", "电务"),
))
