"""共享状态定义：贯穿五阶段的数据结构"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SubTask:
    """一个子任务（阶段②的产物，③④⑤以它为单位执行）"""
    subtask_id: str
    question: str = ""                       # 专业形式精炼后的子问题
    required_capabilities: list[str] = field(default_factory=list)  # 所需能力维度
    assigned_agent: str = ""                 # 路由到的智能体编号 id（agent_01…）
    assigned_agent_name: str = ""            # 编号本身（01/02/…）
    routing: dict = field(default_factory=dict)      # 路由过程（各智能体得分/是否随机）
    plan: dict | None = None                 # 计划表 / DAG（阶段③产物）
    result: Any = None                       # 执行结果（阶段④产物）
    trace: list[dict] = field(default_factory=list)  # 执行轨迹
    tools_used: list[str] = field(default_factory=list)
    status: str = "pending"                  # pending / success / failed（执行是否跑通）
    outcome: str = ""                        # success / failure（评估后的能力进化依据）
    error: str = ""
    capability_update: dict = field(default_factory=dict)  # 本轮能力进化事件


@dataclass
class PipelineState:
    """LangGraph 主图状态"""
    raw_question: str = ""               # 用户原始口语化问题
    domain: str = ""                     # 领域（阶段①）
    task_type: str = ""                  # 基础分类
    refined_question: str = ""           # 专业形式精炼后的问题
    injected_context: str = ""           # 注入的表结构上下文
    loaded_knowledge: str = ""           # 加载的算子 skill 知识
    subtasks: list[SubTask] = field(default_factory=list)   # 阶段②产物
    aggregated_result: Any = None        # 阶段⑤汇总结果
    final_answer: str = ""
    evaluation: str = ""                 # success / failed
    failure_feedback: str = ""           # 报错信息（返回 LLM 总结错误经验）
    capability_changes: list[dict] = field(default_factory=list)  # 本次运行的能力进化事件
    capability_chart: str = ""           # 能力向量图路径
    replans: int = 0                     # 已重新规划次数（阶段⑤失败后 +1）
    ground_truth: Any = None             # 参考答案（测试模式，用于判定成功/失败）
    answer_format: str = ""              # 最终答复的输出格式要求（基准题按题目契约生成）

    def to_dict(self):
        return asdict(self)
