"""阶段① 任务理解：领域识别与基础分类 + 问题合法性判定 + 权限注入 + 知识库加载。

本阶段只做理解，不精炼问题（精炼在阶段②）。两处安全增强都在**同一次 LLM 调用**里完成，
不新增流水线节点：

1. **问题不合法**：领域识别时多给一个候选领域 `invalid`（问题不合法）。LLM 若判定
   问题缺少可执行要素、越权或与 GIS 无关，则写入 `is_valid=False` 与缺失信息清单，
   由主图直接结束本次执行并返回追问文本；用户补充信息后重新从阶段①开始。
2. **用户权限**：按 `state.user_role` 过滤注入的表结构，并把"可查/不可查"的
   表级增删改查权限写进 `permission_context`，让模型在规划阶段就知道边界。
"""
from __future__ import annotations

import yaml
from pathlib import Path

from pipeline.pipeline_state import PipelineState
from pipeline import llm_client as llm
from knowledge import db_schema_retriever, task_skill_library
from security import question_guard, permissions

_TAXONOMY = yaml.safe_load(
    (Path(__file__).parent.parent / "config" / "domains_taxonomy.yaml").read_text(encoding="utf-8")
)

INVALID_TASK_TYPE = "问题不合法"
INVALID_DOMAIN_KEY = "invalid"


def _business_domains() -> dict[str, dict]:
    """业务领域（排除 invalid 这类特殊领域）。"""
    return {
        key: value
        for key, value in (_TAXONOMY.get("domains") or {}).items()
        if not (value or {}).get("special")
    }


def _permission_context(role: str) -> str:
    """把当前角色的表级权限渲染成提示词片段。"""
    table = permissions.get_table()
    allowed = table.allowed_tables(role, "select")
    denied = [t for t in table.tables if t not in allowed]
    parts = [
        "【当前用户与数据权限】",
        f"用户类别：{table.role_name(role)}（{role}）",
    ]
    if allowed:
        detail = "；".join(
            f"{t}（{'/'.join(permissions.ACTION_LABELS[a] for a in table.allowed_actions(role, t))}）"
            for t in allowed
        )
        parts.append(f"可访问的表：{detail}")
    else:
        parts.append("可访问的表：无（当前角色没有任何表的查询权限）")
    if denied:
        parts.append(f"无权访问的表：{'、'.join(denied)}（不得查询、写入或删除）")
    parts.append("约束：只能使用上述可访问的表；越权调用会被执行器拒绝并记录审计日志。")
    return "\n".join(parts)


def run(state: PipelineState) -> PipelineState:
    rules = question_guard.load_rules()
    domain_cfg = _TAXONOMY.get("domains") or {}
    invalid_name = str((domain_cfg.get(INVALID_DOMAIN_KEY) or {}).get("name") or "问题不合法")

    # 1. LLM 领域识别 + 合法性判定（同一次调用，不新增阶段）
    domain_list = "\n".join(
        f"- {k}: {v['name']}（关键词：{'、'.join(v.get('keywords') or [])}）"
        for k, v in _business_domains().items()
    )
    task_types = _TAXONOMY["task_types"]
    sys = "你是公用事业GIS领域任务理解模块，同时负责问题合法性审查，只输出JSON。"
    res = llm.chat_json(
        f"用户口语化问题：{state.raw_question}\n\n"
        f"合法业务领域（业务行业）：\n{domain_list}\n"
        f"- {INVALID_DOMAIN_KEY}: {invalid_name}（缺少可执行要素 / 越权 / 与GIS无关，"
        f"判定口径见下文）\n\n"
        f"候选任务类型：{task_types}\n\n"
        f"{question_guard.render_criteria(rules)}\n\n"
        f"请输出 JSON：\n"
        f'{{"domain": "业务领域key，或 {INVALID_DOMAIN_KEY}", '
        f'"task_type": "任务类型之一（不合法时可留空）", '
        f'"is_valid": true/false, '
        f'"invalid_reasons": ["不合法原因，最多3条"], '
        f'"missing_slots": ["缺失信息槽位key，如 object/extent/condition/metric/time"], '
        f'"clarification_question": "向用户追问的一句话", '
        f'"reason": "判断依据"}}',
        system=sys,
    )

    verdict = question_guard.evaluate(state.raw_question, res, rules)
    state.is_valid = bool(verdict["is_valid"])
    state.validity_source = str(verdict.get("source") or "")

    # 1a. 问题不合法：不进入②~⑤，直接给出追问文本并结束本次执行
    if not state.is_valid:
        state.domain = INVALID_DOMAIN_KEY
        state.task_type = INVALID_TASK_TYPE
        state.invalid_reasons = list(verdict.get("reasons") or [])
        state.missing_info = list(verdict.get("missing_info") or [])
        state.clarification = str(verdict.get("clarification") or "")
        state.final_answer = state.clarification
        state.refined_question = ""
        state.injected_context = ""
        state.loaded_knowledge = ""
        state.permission_context = ""
        return state

    # 2. 合法：写入领域/任务类型，解析用户角色并注入表级权限说明
    domain = str(res.get("domain") or "").strip()
    if domain not in _business_domains():
        domain = "general"
    state.domain = domain
    state.task_type = str(res.get("task_type") or "").strip() or task_types[0]

    role = permissions.resolve_role(state.user_role)
    state.user_role = role
    state.permission_context = _permission_context(role)

    # 3. 上下文注入：先按权限过滤表，再按领域缩小候选范围、筛选相关表名与字段含义
    state.injected_context = db_schema_retriever.get_context(
        state.raw_question, state.domain, role=role
    )

    # 4. 加载知识库：按余弦相似度检索最相关的领域知识与任务级 skill
    state.loaded_knowledge = task_skill_library.load_skills(state.raw_question, state.domain)
    return state
