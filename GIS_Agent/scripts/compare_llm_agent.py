from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.compare import compare_agents


def main() -> None:
    cases = compare_agents()
    print("真实 LLM Agent 与确定性 Agent 对比")
    print("=" * 80)
    for index, case in enumerate(cases, start=1):
        deterministic_tool = case.deterministic["plan"][0]["name"]
        llm_tool = case.llm["plan"][0]["name"]
        print(f"{index}. {case.question}")
        print(f"   deterministic tool: {deterministic_tool}")
        print(f"   llm tool          : {llm_tool}")
        print(f"   same_tool         : {case.same_tool}")
        print(f"   same_arguments    : {case.same_arguments}")
        print(f"   same_key_result   : {case.same_key_result}")
        print(f"   deterministic answer: {case.deterministic['answer']}")
        print(f"   llm answer          : {case.llm['answer']}")
        print("-" * 80)


if __name__ == "__main__":
    main()
