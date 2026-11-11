"""智能体能力层：编号命名、初始 0.5、经验进化、平局随机路由。"""
from agents.agent_registry import (  # noqa: F401
    agent_ids,
    agent_name,
    agents_config,
    dimensions,
    initial_vectors,
    load_agents_config,
)
from agents.capability_store import (  # noqa: F401
    CapabilityStore,
    get_default_store,
    load_store,
    set_default_store,
)
from agents.capability_router import RoutingDecision, route, set_random_seed  # noqa: F401
