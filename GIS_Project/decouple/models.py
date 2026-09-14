# models.py

from typing import List, Literal

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from pydantic import BaseModel, Field

load_dotenv(override=True)

model = ChatDeepSeek(
    model="deepseek-v4-flash",
    extra_body={
        "thinking": {
            "type": "disabled"
        }
    },
    temperature=0.1
)


# [新增-文档版] 结构化输出 Schema：用于自动识别用户问题涉及的 GIS 业务领域。
class DomainDetectResult(BaseModel):
    """LLM 结构化输出：识别用户问题涉及哪些 GIS 业务领域。"""

    domains: List[Literal["燃气", "水务", "电务"]] = Field(
        description="从【燃气、水务、电务】中选出问题相关领域，根据匹配可返回含多个领域的列表，无匹配返回空列表"
    )
    reason: str = Field(
        description="简短推理说明，为什么选出这些或这个领域"
    )


# [新增-文档版] 专用于领域检测的结构化输出模型。
domain_router = model.with_structured_output(DomainDetectResult)
