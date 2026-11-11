"""阶段① 任务理解：领域识别与基础分类 + 上下文注入 + 知识库加载（不精炼问题）"""
from __future__ import annotations
import yaml
from pathlib import Path
from pipeline.pipeline_state import PipelineState
from pipeline import llm_client as llm
from knowledge import db_schema_retriever, task_skill_library

_DOMAINS = yaml.safe_load(
    (Path(__file__).parent.parent / "config" / "domains_taxonomy.yaml").read_text(encoding="utf-8")
)


def run(state: PipelineState) -> PipelineState:
    # 1. LLM 领域识别与基础分类（此处只分类，不精炼问题——精炼在阶段②）
    domain_list = "\n".join(
        f"- {k}: {v['name']}（关键词：{'、'.join(v['keywords'])}）"
        for k, v in _DOMAINS["domains"].items()
    )
    task_types = _DOMAINS["task_types"]
    sys = "你是公用事业GIS领域任务理解模块，只输出JSON。"
    res = llm.chat_json(
        f"用户口语化问题：{state.raw_question}\n"
        f"候选领域（业务行业）：\n{domain_list}\n"
        f"候选任务类型：{task_types}\n\n"
        f'请输出 {{"domain": "领域key", "task_type": "任务类型之一", '
        f'"reason": "判断依据"}}',
        system=sys,
    )
    state.domain = res["domain"]
    state.task_type = res["task_type"]

    # 2. 上下文注入：按领域缩小候选范围，筛选相关表名与字段含义
    state.injected_context = db_schema_retriever.get_context(
        state.raw_question, state.domain
    )

    # 3. 加载知识库：按余弦相似度检索最相关的领域知识与任务级 skill
    state.loaded_knowledge = task_skill_library.load_skills(state.raw_question, state.domain)
    return state
