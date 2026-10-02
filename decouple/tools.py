# tools.py —— GIS 工具导入（Skill 库优先）与模型工具绑定

from langchain.tools import tool
from loguru import logger

from models import model

# =====================================================================
# 3. 内置演示工具（gis_skill_library 不可用时的回退）
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

# GIS 工具优先从独立 Skill 库（gis_skill_library.py）导入：主程序与算子库解耦，
# 算子的定义、模拟数据与使用说明统一在 Skill 库中维护。
try:
    from gis_skill_library import ATOMIC_TOOLS as gis_tools, SKILL_USAGE_DOCS
except ImportError:
    logger.warning("未能导入 gis_skill_library，回退到内置4个演示工具")
    gis_tools = [buffer_analysis, pipe_length_stat, hazard_query, overlay_analysis]
    SKILL_USAGE_DOCS = {}

model_with_gis_tools = model.bind_tools(gis_tools)
