"""查看/重绘能力向量表。

用法：
    python scripts/show_capabilities.py                 # 打印当前能力向量表 + 重绘能力向量图
    python scripts/show_capabilities.py --demo 30        # 演示"能力均等 → 随机抽取"的分布
    python scripts/show_capabilities.py --dim statistics --times 50
    python scripts/show_capabilities.py --open           # 生成后直接打开 HTML
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import agent_registry, capability_router  # noqa: E402
from agents.capability_store import get_default_store  # noqa: E402
from visualization import capability_radar_chart  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="查看智能体能力向量")
    parser.add_argument("--dim", default="statistics", help="用于演示路由的能力维度")
    parser.add_argument("--times", type=int, default=0, help="重复路由次数，观察随机分布")
    parser.add_argument("--seed", type=int, default=None, help="路由随机种子")
    parser.add_argument("--open", action="store_true", help="生成后打开能力向量图")
    args = parser.parse_args()

    store = get_default_store()
    snapshot = store.snapshot()
    print(capability_radar_chart.render_ascii(snapshot))

    if args.times:
        if args.seed is not None:
            capability_router.set_random_seed(args.seed)
        dims = capability_router.normalize_dimensions([args.dim])
        counter: Counter[str] = Counter()
        random_picks = 0
        for _ in range(args.times):
            d = capability_router.route(store, dims)
            counter[d.agent_id] += 1
            random_picks += int(d.random_pick)
        print(f"\n【路由演示】能力维度 {dims}，共 {args.times} 次")
        print(f"  其中因能力均等而随机抽取：{random_picks} 次")
        for aid, n in sorted(counter.items()):
            name = store.name(aid)
            print(f"  智能体 {name}: {n:4d} 次 ({n / args.times:.1%})")

    paths = store.refresh_chart()
    print(f"\n动态能力向量图(HTML)：{paths.get('html')}")
    if paths.get("png"):
        print(f"当前状态快照(PNG)：{paths['png']}")

    if args.open and paths.get("html"):
        os.startfile(paths["html"])  # noqa: S606 - 仅本地演示
    return 0


if __name__ == "__main__":
    sys.exit(main())
