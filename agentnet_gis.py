"""
================================================================================
AgentNet-GIS：去中心化多智能体智能网络
================================================================================
在原有单智能体 GIS LangGraph 脚本（project.py）基础上，落地 AgentNet
(NeurIPS 2025) 的三项核心机制：

  1. 去中心化智能体集合  → AgentRegistry + GISAgent（每个智能体能力向量独立）
  2. 动态任务协调分工    → Coordinator 按能力相似度匹配智能体，可拆子任务协作
  3. 记忆独立 + 经验共享 → 每个智能体独立记忆 namespace；共享经验池 namespace
  4. 经验→技能沉淀      → 任务成功后把成功思路提炼成 skill 写入数据库

数据分层（PostgresStore）：
  - ("agents", <agent_name>)        ：智能体独立记忆（私有，各自 namespace）
  - ("experience_pool",)            ：共享经验池（所有智能体共用）
  - ("skills", <skill_id>)          ：沉淀后的可复用技能库
================================================================================
"""
from dataclasses import dataclass, field
from time import sleep
from typing import TypedDict, Annotated, Literal, Optional, Final, Tuple, List
from operator import add

from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy, CachePolicy, Command, interrupt
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langgraph.graph.message import MessagesState
from langgraph.managed import RemainingSteps
from langgraph.runtime import Runtime

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from langchain.tools import tool
from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv
from loguru import logger
from requests.exceptions import HTTPError
from pydantic import BaseModel, Field

load_dotenv(override=True)

# =====================================================================
# 0. 模型
# =====================================================================
model = ChatDeepSeek(
    model="deepseek-v4-flash",
    extra_body={"thinking": {"type": "disabled"}},
    temperature=0.1,
)

# =====================================================================
# 1. 数据模型 / 状态
# =====================================================================

@dataclass
class UserContext:
    username: str
    membership_level: str = "普通用户"


class AgentNetState(MessagesState):
    remaining_steps: RemainingSteps
    input: str                                    # 用户原始问题
    info: Annotated[list[str], add]               # 过程日志
    output: str                                   # 最终输出
    detected_domain: Optional[str]                # 识别出的领域
    task_type: Optional[str]                      # 识别出的任务类型（工具名）
    selected_agent: Optional[str]                 # 当前选中的智能体
    subtasks: List[str] = field(default_factory=list)   # 待处理子任务
    subtask_results: Annotated[list[str], add]    # 子任务结果汇总
    cooperation: Optional[bool]                   # 是否需要多智能体协作
    trajectory: Annotated[list[str], add]         # 任务执行轨迹（用于提炼 skill）
    task_success: Optional[bool]                  # 任务是否成功
    preferences: dict                             # 领域知识库


class InputState(MessagesState):
    input: str


class OutputState(MessagesState):
    info: list[str]
    output: str


# =====================================================================
# 2. 持久化配置（Postgres）
# =====================================================================
DB_URL = "postgresql://langgraph_user:123456@localhost:5432/langgraph_db?sslmode=disable"

AGENTS_NS: Final[Tuple[str]] = ("agents",)           # 智能体独立记忆根
EXPERIENCE_NS: Final[Tuple[str]] = ("experience_pool",)  # 共享经验池
SKILLS_NS: Final[Tuple[str]] = ("skills",)           # 技能库


# =====================================================================
# 3. GIS 工具（与 project.py 保持一致）
# =====================================================================
@tool(parse_docstring=True)
def buffer_analysis(domain: str, layer: str, buffer_distance: float) -> str:
    """
    GIS缓冲区分析算子，生成要素周边缓冲区范围

    Args:
        domain: 业务领域，燃气/水务/电务
        layer: 图层名称，例如燃气管线、水务隐患点
        buffer_distance: 缓冲距离，单位米
    """
    return (f"【模拟缓冲区分析结果】领域:{domain},图层:{layer},"
            f"缓冲距离:{buffer_distance}米，生成缓冲区面要素共12个，缓冲区总面积2.36平方公里。")


@tool(parse_docstring=True)
def pipe_length_stat(domain: str, filter_condition: str = "") -> str:
    """
    管线长度统计算子，统计指定领域管线总长度

    Args:
        domain: 业务领域，燃气/水务/电务
        filter_condition: 筛选条件，如"高压管线"、"隐患管线"
    """
    total = {"燃气": 128.72, "水务": 246.15}.get(domain, 88.2)
    return (f"【模拟管线统计结果】领域:{domain},筛选条件:{filter_condition},"
            f"管线总长度：{total} KM")


@tool(parse_docstring=True)
def hazard_query(domain: str, hazard_type: str = "all") -> str:
    """
    隐患筛查查询算子，查询领域内空间隐患分布

    Args:
        domain: 业务领域：燃气/水务/电务
        hazard_type: 隐患类型，all全部，泄漏、腐蚀、破损
    """
    mock_data = {
        "燃气": ["阀门腐蚀隐患 3处", "管线泄漏风险点 2处"],
        "水务": ["管网破损点 5处", "排水淤积隐患4处"],
    }
    items = mock_data.get(domain, [])
    return (f"【模拟隐患查询结果】领域:{domain},隐患类型:{hazard_type},"
            f"隐患列表：{items}")


@tool(parse_docstring=True)
def overlay_analysis(domain: str, layer_a: str, layer_b: str) -> str:
    """
    GIS叠加分析算子，图层叠加，用于管线交叉冲突检测

    Args:
        domain: 业务领域
        layer_a: 图层A
        layer_b: 图层B
    """
    return (f"【模拟叠加分析结果】领域:{domain},图层A:{layer_a},图层B:{layer_b},"
            f"检测到图层交叉冲突位置共4处，已输出冲突空间坐标。")


# GIS 工具改为从独立 Skill 库（gis_skill_library.py）导入：主程序与算子库解耦，
# 算子的定义、模拟数据与使用说明统一在 Skill 库中维护。
try:
    from gis_skill_library import ATOMIC_TOOLS as gis_tools, SKILL_USAGE_DOCS
except ImportError:
    logger.warning("未能导入 gis_skill_library，回退到内置4个演示工具")
    gis_tools = [buffer_analysis, pipe_length_stat, hazard_query, overlay_analysis]
    SKILL_USAGE_DOCS = {}
model_with_gis_tools = model.bind_tools(gis_tools)


# =====================================================================
# 4. 智能体注册表（AgentNet 的核心：注册多个不同智能体，能力向量独立）
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


# =====================================================================
# 5. 结构化输出：领域识别 + 路由决策（协调分工）
# =====================================================================

class DetectResult(BaseModel):
    """识别任务领域与任务类型"""
    domain: Literal["燃气", "水务", "电务", "无"] = Field(description="问题所属领域")
    task_type: str = Field(description="任务类型：管线统计/缓冲区分析/隐患查询/叠加分析")
    reason: str = Field(description="简短推理理由")


class RouteResult(BaseModel):
    """路由决策：选择智能体，判断是否拆分子任务协作"""
    agent: str = Field(description="选中的智能体名称，从注册表中选取")
    cooperation: bool = Field(description="是否需要多个智能体协作完成")
    subtasks: List[str] = Field(description="若协作则拆分的子任务描述列表，否则空列表")
    reason: str = Field(description="路由决策理由")


detect_router = model.with_structured_output(DetectResult)
route_router = model.with_structured_output(RouteResult)


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


# =====================================================================
# 7. 节点：领域识别 → 路由分工 → 执行 → 学习沉淀
# =====================================================================

DOMAIN_KEYWORDS = {
    "燃气": ["燃气", "阀门", "泄漏", "管材", "铸铁", "PE管"],
    "水务": ["水务", "供水", "排水", "隐患点", "洪涝", "淤积", "水质"],
    "电务": ["电力", "电务", "缆线", "杆塔", "电压"],
}

def detect_node(state: AgentNetState) -> AgentNetState:
    """识别问题领域与任务类型；识别不出时不终止，降级为综合模式由智能体按Skill库求解"""
    res: DetectResult = detect_router.invoke(
        [SystemMessage(content="识别GIS问题的领域(燃气/水务/电务)与任务类型。"),
         HumanMessage(content=state["input"])]
    )
    domain = res.domain
    if domain == "无":
        # 兜底1：关键词扫描
        for d, kws in DOMAIN_KEYWORDS.items():
            if any(kw in state["input"] for kw in kws):
                domain = d
                break
    if domain == "无":
        # 兜底2：进入综合模式，交给智能体依据 Skill 库算子说明自行求解
        return {"detected_domain": "综合",
                "task_type": res.task_type or "综合分析",
                "task_success": True,
                "info": [f"{len(state.get('info', []))+1}. 领域未明确，进入综合模式（依托Skill库求解）"]}
    return {"detected_domain": domain,
            "task_type": res.task_type,
            "task_success": True,
            "info": [f"{len(state.get('info', []))+1}. 领域识别：{res.domain}，任务：{res.task_type}"]}


def route_node(state: AgentNetState, runtime: Runtime) -> AgentNetState:
    """协调路由：按能力匹配智能体，决定执行 or 拆分协作（AgentNet Forward/Split/Execute）"""
    # ---------- 中断确认：读取共享知识库/经验池前征得用户同意 ----------
    confirm = interrupt("准备读取共享经验池与智能体网络，进行任务分工，是否继续？(yes/no)")
    if confirm not in (True, "yes"):
        return Command(goto=END, update={"info": "用户取消读取共享知识库，流程终止。",
                                        "task_success": False})

    available = registry.all()
    agent_names = ", ".join(a.name for a in available)
    res: RouteResult = route_router.invoke(
        [SystemMessage(content=(
            f"你是去中心化协调器。从这些已注册智能体中选择最合适的处理当前GIS任务：{agent_names}。"
            f"如任务跨多个领域需要协作，设置cooperation=True并拆分子任务。")),
         HumanMessage(content=f"领域={state['detected_domain']}，任务={state['task_type']}，问题={state['input']}")]
    )

    # 校验智能体是否存在于注册表（动态注册体系下的兜底；综合模式匹配能力最强的智能体）
    agent = registry.get(res.agent) or registry.match(state.get("detected_domain", ""))
    if not agent:
        return {"output": "未找到合适智能体，流程终止。", "task_success": False}

    updates = {
        "selected_agent": agent.name,
        "cooperation": res.cooperation,
        "subtasks": res.subtasks,
        "info": [f"{len(state.get('info', []))+1}. 路由到 {agent.name}，"
                 f"协作={res.cooperation}，子任务={res.subtasks or '无'}（执行自身）"],
    }

    # 汇总各智能体独立记忆（每个智能体 namespace 独立，此处在共享决策时按需读取）
    store = runtime.store
    private_mem = store.get(agent.memory_namespace(), "last_task")
    if private_mem:
        updates["info"].append(f"{len(state.get('info', []))+2}. 读取{agent.name}私有记忆：{private_mem.value.get('summary','')}")
    return updates


def execute_node(state: AgentNetState, runtime: Runtime) -> AgentNetState:
    """执行节点：让选中的智能体调用 GIS 工具完成当前任务"""
    # ---------- 中断确认：调用大语言模型前征得用户同意 ----------
    confirm = interrupt(f"准备调用大语言模型，由 {state.get('selected_agent','智能体')} 执行任务，是否继续？(yes/no)")
    if confirm not in (True, "yes"):
        return Command(goto=END, update={"info": "用户取消调用大语言模型，流程终止。",
                                        "task_success": False})

    agent = registry.get(state["selected_agent"])
    domain = state["detected_domain"]

    # 组装当前智能体的专属系统提示 + 领域知识
    sys_msg = SystemMessage(content=(
        f"你是【{agent.name}】，专长领域：{domain}。\n"
        f"你的职责：{agent.description}\n"
        f"你的能力向量：{agent.capabilities}\n"
        "你是GIS智能体，按需调用GIS工具完成用户的空间分析请求，不要编造工具。"
    ))

    # 1) 先检索技能库：读取本领域已沉淀的通用方法论（LLM 提炼），用于定任务框架
    #    综合模式下检索不到领域技能时，回退到 Skill 库各域算子使用说明，
    #    让智能体依据算子知识自行拆解求解，而非直接失败。
    store = runtime.store
    try:
        skill_items = store.search((*SKILLS_NS, domain))
    except Exception:
        skill_items = []
    skill_refs = [it.value.get("skill", str(it.value)) for it in skill_items][:2]
    if not skill_refs and SKILL_USAGE_DOCS:
        skill_refs = list(SKILL_USAGE_DOCS.values())[:2]
    method_text = "\n".join(skill_refs) if skill_refs else "（暂无沉淀技能，可参考经验池）"

    # 2) 再从共享经验池检索历史成功轨迹做 few-shot（RAG）
    experiences = ExperiencePool.retrieve(store, state["input"], k=2)
    if experiences:
        # trajectory 可能是 list（逐条轨迹）也可能是字符串，统一转文本
        exp_lines = []
        for e in experiences:
            traj = e.get("trajectory", [])
            if isinstance(traj, list):
                exp_lines.append("\n".join(str(t) for t in traj))
            else:
                exp_lines.append(str(traj))
        exp_text = "\n".join(exp_lines)
    else:
        exp_text = "（无历史经验）"

    messages = [sys_msg,
                SystemMessage(content=f"【技能库·通用方法论】\n{method_text}"),
                SystemMessage(content=f"【共享经验池·历史成功轨迹】\n{exp_text}"),
                HumanMessage(content=state["input"])]
    resp = model_with_gis_tools.invoke(messages)

    updates: dict = {
        "messages": [resp],
        "output": resp.content,
        "trajectory": [f"{agent.name} 调用LLM解析，输出含工具调用",
                       f"{agent.name} 依据领域知识库与共享经验决策"],
        "info": [f"{len(state.get('info', []))+1}. {agent.name} 执行完成"],
    }

    # 记录到该智能体的独立记忆（记忆独立）
    store.put(agent.memory_namespace(), "last_task",
              {"task": state["input"], "summary": resp.content[:200]})
    logger.info(f"[记忆] 已写入 {agent.name} 独立记忆")
    sleep(0.05)
    return updates


def tool_node_wrapper(state: AgentNetState) -> AgentNetState:
    """包装 ToolNode：执行 GIS 工具，并记录轨迹"""
    last_ai = state["messages"][-1]
    tool_calls = getattr(last_ai, "tool_calls", [])
    tool_names = [tc["name"] for tc in tool_calls]
    logger.info(f"即将并行调用工具: {tool_names}")

    builtin_tool_node = ToolNode(gis_tools)
    result_state = builtin_tool_node.invoke(state)

    # 把工具调用追加进轨迹（用于后续提炼 skill）
    if isinstance(result_state, dict):
        traj = [f"{state['selected_agent']} 调用工具 {n}" for n in tool_names]
        result_state.setdefault("trajectory", []).extend(traj)
        result_state["info"] = [f"{len(state.get('info', []))+1}. 工具并行执行：{tool_names}"]
    sleep(0.1)
    return result_state


def learn_node(state: AgentNetState, runtime: Runtime) -> AgentNetState:
    """
    学习沉淀节点（AgentNet 自适应演化）：
      1) 把成功任务写入共享经验池
      2) 用 LLM 提炼成功思路 → skill，写入数据库
    """
    if not state.get("task_success"):
        return {"info": [f"{len(state.get('info', []))+1}. 任务未成功，跳过经验沉淀"]}

    store = runtime.store
    trajectory = state.get("trajectory", [])
    result = state.get("output", "")

    # 1) 共享经验池记录
    ExperiencePool.record(store, state["input"], state["selected_agent"],
                          trajectory, result)

    # 2) 提炼 skill 写库（AgentNet 经验→技能）
    skill_text = SkillManager.build_skill_from_trajectory(
        trajectory, result, state["detected_domain"])
    skill_id = f"skill_{abs(hash(state['input'] + state['detected_domain']))}"
    SkillManager.store_skill(store, skill_id, skill_text, state["detected_domain"])

    return {"info": [
        f"{len(state.get('info', []))+1}. 经验池已记录，技能已沉淀（{skill_id}）",
        f"{len(state.get('info', []))+2}. 沉淀技能：{skill_text[:80]}..."
    ]}


def final_answer_node(state: AgentNetState) -> AgentNetState:
    """整合节点：工具执行后，让模型基于工具结果生成最终答复（替代开场白）"""
    msgs = state.get("messages", [])
    tool_msgs = [m.content for m in msgs if isinstance(m, ToolMessage)]
    if not tool_msgs:
        return {"output": state.get("output", ""),
                "info": [f"{len(state.get('info', []))+1}. 无工具结果，直接结束"]}

    sys_msg = SystemMessage(content=(
        "你是GIS智能体，请基于下面已执行的工具返回结果，整合成一份简洁、结构化的最终答复"
        "给业务人员，包含关键数据与结论。不要编造未出现的数字。"
    ))
    human = HumanMessage(content=(
        f"原始问题：{state.get('input','')}\n"
        f"工具执行结果：\n" + "\n".join(f"- {t}" for t in tool_msgs)
    ))
    resp = model.invoke([sys_msg, human])
    return {"output": resp.content,
            "trajectory": ["智能体整合工具结果，生成最终答复"],
            "info": [f"{len(state.get('info', []))+1}. 整合生成最终答复"]}


def end_node(state: AgentNetState) -> AgentNetState:
    return {"info": [f"{len(state.get('info', []))+1}. 任务执行完毕"]}


# =====================================================================
# 8. 路由函数（图拓扑决策）
# =====================================================================

def router_after_execute(state: AgentNetState) -> Literal["tool_node", "learn_node"]:
    """执行后：有工具调用则进工具节点，否则直接进入学习沉淀"""
    messages = state["messages"]
    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tool_node"
    return "learn_node"


# =====================================================================
# 9. 构建图
# =====================================================================
builder = StateGraph(
    AgentNetState,
    input_schema=InputState,
    output_schema=OutputState,
    context_schema=UserContext,
)

builder.add_node("detect_node", detect_node)
builder.add_node("route_node", route_node)
builder.add_node("execute_node", execute_node)
builder.add_node("tool_node", tool_node_wrapper,
                 retry_policy=RetryPolicy(max_attempts=3, jitter=False,
                                          retry_on=(HTTPError, ConnectionError)))
builder.add_node("final_answer_node", final_answer_node)
builder.add_node("learn_node", learn_node)
builder.add_node("end_node", end_node)

# 拓扑
builder.add_edge(START, "detect_node")
builder.add_edge("detect_node", "route_node")
builder.add_edge("route_node", "execute_node")
builder.add_conditional_edges("execute_node", router_after_execute)
builder.add_edge("tool_node", "final_answer_node")  # 工具完成后先整合最终答复
builder.add_edge("final_answer_node", "learn_node")  # 再进入学习沉淀
builder.add_edge("learn_node", "end_node")
builder.add_edge("end_node", END)


def get_graph():
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer, \
            PostgresStore.from_conn_string(DB_URL) as store:
        checkpointer.setup()
        store.setup()
        return builder.compile(checkpointer=checkpointer, store=store)


# =====================================================================
# 10. 演示入口
# =====================================================================
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
        skill_items = store.search(("skills", "燃气"))
        for item in skill_items:
            print(f"  [{item.key}] {item.value['skill']}")


if __name__ == "__main__":
    run_demo()
