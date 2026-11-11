"""全局配置"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
AGENT_MEMORY_BASE = DATA_DIR / "memory"      # 各智能体专属记忆空间根目录

# 能力向量与进化状态
AGENTS_CONFIG_PATH = BASE_DIR / "config" / "agents_capability.yaml"
CAPABILITY_PATH = DATA_DIR / "agent_capabilities.json"      # 运行期能力向量（进化结果）
CAPABILITY_INITIAL = 0.5                              # 初始经验值：能力完全均衡

# 动态能力向量图
CAPABILITY_CHART_ENABLED = True
CAPABILITY_CHART_HTML = DATA_DIR / "capability_vector_chart.html"
CAPABILITY_CHART_PNG = DATA_DIR / "capability_vector_chart.png"

# 能力路由
ROUTING_TIE_EPSILON = 0.0        # 得分差 <= 该容差视为能力均等 → 随机抽取
ROUTING_RANDOM_SEED = None       # None 表示真随机

# 经验池配置
EXPERIENCE_PATH = DATA_DIR / "experience.json"
EXPERIENCE_MAX_SIZE = 100          # 经验池容量上限
EXPERIENCE_SIMILAR_THRESHOLD = 0.85  # 相似度超过该值视为同类任务，只更新不新增
EXPERIENCE_TOP_K = 3               # 规划时检索最相关经验条数

# 上下文注入配置（表结构与 skill 都按余弦相似度检索）
SCHEMA_TOP_K = 5                   # 注入 prompt 的相关表数量上限
SKILL_TOP_K = 4                    # 检索并注入的任务级 skill 数量上限
RETRIEVAL_MIN_SCORE = 0.0          # 余弦相似度低于该值视为不相关（0 表示只要 >0 就保留）
RETRIEVAL_RELATIVE_CUTOFF = 0.4    # 只保留相似度 >= 最高分 × 该比例的命中，过滤凑数的低相关项

# 拆解配置
MAX_SUBTASKS = 5                   # 单次拆解最大子问题数

# ---------------------------------------------------------------------------
# PostGIS 数据源（dev20 基准）
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://gis_user:123456@localhost:5433/gis_agent"
)
APP_SCHEMA = os.getenv("APP_SCHEMA", "gis_lab")
# 表结构来源：postgis=从数据库 information_schema 现场读取；demo=使用内置示例
SCHEMA_SOURCE = os.getenv("SCHEMA_SOURCE", "postgis")
# 外部 PostGIS 工具集（dev20 项目的 app_development/tool.py）
POSTGIS_TOOLKIT_ROOT = Path(os.getenv(
    "POSTGIS_TOOLKIT_ROOT",
    str(BASE_DIR / "GIS_Agent-jiang_gis_tools_develop" / "GIS_Agent"),
))
POSTGIS_TOOLSET = os.getenv("POSTGIS_TOOLSET", "advanced")

# ---------------------------------------------------------------------------
# 基准题集（开发用 20 题）
# ---------------------------------------------------------------------------
BENCHMARK_DIR = Path(os.getenv(
    "BENCHMARK_DIR",
    str(BASE_DIR / "GIS_Agent-jiang_gis_tools_develop" / "GIS_Agent" / "data" / "benchmarks"),
))
BENCHMARK_ABS_TOL = 1e-6
REPORTS_DIR = BASE_DIR / "reports"
