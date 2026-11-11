"""复位智能体状态。

默认把一切恢复到"刚训练"的初始状态：
  · 能力向量全部回到 0.5，进化历史清空；
  · 共享经验池清空；
  · 各智能体的专属记忆（长期任务记录 + 短期缓存）清空。
用 --keep-* 保留其中一部分。

用法：
    python scripts/reset_agents.py --yes
    python scripts/reset_agents.py --yes --keep-experience --keep-memory
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from agents.capability_store import get_default_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="复位能力向量 / 经验池 / 智能体记忆")
    parser.add_argument("--yes", action="store_true", help="跳过确认")
    parser.add_argument("--keep-experience", action="store_true", help="保留共享经验池")
    parser.add_argument("--keep-memory", action="store_true", help="保留智能体专属记忆")
    args = parser.parse_args()

    if not args.yes:
        print("将把能力值复位为 0.5、清空进化历史"
              + ("" if args.keep_experience else "、清空经验池")
              + ("" if args.keep_memory else "、清空智能体记忆")
              + "。确认请加 --yes")
        return 1

    store = get_default_store()
    store.reset()
    print("[能力向量] 已复位：所有智能体所有能力 = 0.50")

    if not args.keep_experience and settings.EXPERIENCE_PATH.exists():
        settings.EXPERIENCE_PATH.unlink()
        print("[经验池] 已清空")

    if not args.keep_memory:
        mem_root = settings.DATA_DIR / "memory"
        if mem_root.exists():
            shutil.rmtree(mem_root)
            print("[智能体记忆] 已清空")

    print("[能力向量图] 已重绘")
    return 0


if __name__ == "__main__":
    sys.exit(main())
