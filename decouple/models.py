# models.py —— 大模型初始化与结构化输出路由（领域识别 / 路由决策）

from typing import Literal, List

from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv
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
# 结构化输出模型：领域识别 + 路由决策（协调分工）
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
