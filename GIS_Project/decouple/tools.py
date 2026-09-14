# tools.py

from langchain.tools import tool
from langgraph.prebuilt import ToolNode, ToolRuntime
from langgraph.types import Command
from langchain_core.messages import HumanMessage, ToolMessage

@tool(parse_docstring=True)
def buffer_analysis(domain: str, layer: str, buffer_distance: float, runtime: ToolRuntime) -> Command:
    """
    GIS缓冲区分析算子，对应课题关键技术，生成要素周边缓冲区范围

    Args:
        domain: 业务领域，燃气/水务
        layer: 图层名称，例如燃气管线、水务隐患点
        buffer_distance: 缓冲距离，单位米
    """
    res = f"""【模拟缓冲区分析结果】
    领域:{domain},图层:{layer},缓冲距离:{buffer_distance}米
    生成缓冲区面要素共12个，缓冲区总面积2.36平方公里，已完成图层预处理坐标归一化。"""
    tool_call_id = runtime.tool_call_id
    tool_msg = ToolMessage(tool_call_id=tool_call_id, content=res)
    return Command(
        update={
            "messages": [tool_msg]
        }
    )

@tool(parse_docstring=True)
def pipe_length_stat(domain: str, runtime: ToolRuntime, filter_condition: str = "" ) -> Command:
    """
    管线长度统计算子，统计指定领域管线总长度

    Args:
        domain: 业务领域，燃气/水务
        filter_condition: 筛选条件，如"高压管线"、"隐患管线"
    """
    if domain == "燃气":
        total = 128.72
    elif domain == "水务":
        total = 246.15
    else:
        total = 88.2
    res = f"""【模拟管线统计结果】
    领域:{domain},筛选条件:{filter_condition}
    管线总长度：{total} KM"""
    tool_call_id = runtime.tool_call_id
    tool_msg = ToolMessage(tool_call_id=tool_call_id, content=res)
    return Command(
        update={
            "messages": [tool_msg]
        }
    )

@tool(parse_docstring=True)
def hazard_query(domain: str,runtime: ToolRuntime, hazard_type: str = "all",):
    """
    隐患筛查查询算子，查询领域内空间隐患分布

    Args:
        domain: 业务领域：燃气/水务
        hazard_type: 隐患类型，all全部，泄漏、腐蚀、破损
    """
    mock_data = {
        "燃气": ["阀门腐蚀隐患 3处", "管线泄漏风险点 2处"],
        "水务": ["管网破损点 5处", "排水淤积隐患4处"]
    }
    items = mock_data.get(domain, [])
    res = f"""【模拟隐患查询结果】
    领域:{domain},隐患类型:{hazard_type}
    隐患列表：{items}
    隐患空间分布范围已完成图层加载。"""
    tool_call_id = runtime.tool_call_id
    tool_msg = ToolMessage(tool_call_id=tool_call_id, content=res)
    return Command(
        update={
            "messages": [tool_msg]
        }
    )

@tool(parse_docstring=True)
def overlay_analysis(domain: str, layer_a: str, layer_b: str, runtime: ToolRuntime):
    """
    GIS叠加分析算子，图层叠加，用于管线交叉冲突检测

    Args:
        domain:业务领域
        layer_a:图层A
        layer_b:图层B
    """
    res = f"""【模拟叠加分析结果】
    领域:{domain},图层A:{layer_a},图层B:{layer_b}
    检测到图层交叉冲突位置共4处，已输出冲突空间坐标。"""
    tool_call_id = runtime.tool_call_id
    tool_msg = ToolMessage(tool_call_id=tool_call_id, content=res)
    return Command(
        update={
            "messages": [tool_msg]
        }
    )

# 装配GIS工具
gis_tools = [buffer_analysis, pipe_length_stat, hazard_query, overlay_analysis]
model_with_gis_tools = None

