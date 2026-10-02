# GIS_Agent

面向燃气、水务等多行业 GIS 平台的智能 Agent 原型。

当前阶段目标不是接入甲方真实接口，而是在无真实数据条件下，通过模拟市政 GIS 沙盘证明：

- 自然语言问题可以解析为标准 GIS 任务；
- GIS 任务可以拆解为空间计算步骤；
- 空间计算步骤可以在模拟数据或 PostGIS 上执行；
- 后续接入真实平台时，只需要替换 adapter，不重构 Agent 主流程。

## 目录

- `GIS_Project/decouple/`: 当前主线代码。
- `GIS_Project/decouple/adapters/`: GIS 数据适配层。
- `GIS_Project/decouple/schemas/gis_task.py`: 标准 GIS 任务和执行计划 schema。
- `GIS_Project/decouple/eval/`: 语义解析评测样例和评测脚本。
- `data/mock_city/`: 模拟市政 GIS GeoJSON 数据。
- `knowledge/`: 业务语义词典和空间算子目录。

## 快速验证

运行规则基线评测：

```powershell
py GIS_Project\decouple\eval\run_eval.py
```

直接验证 MockGISAdapter：

```powershell
py -c "import sys; sys.path.insert(0, r'D:\code\GIS_Agent\GIS_Project\decouple'); from adapters.mock_adapter import MockGISAdapter; a=MockGISAdapter(); print(a.length_statistics(a.select_layer('gas_pipes')))"
```

完整 LangGraph Agent 运行前需要安装依赖并配置模型、Postgres：

```powershell
py -m pip install -r requirements.txt
py GIS_Project\decouple\persistence.py
py GIS_Project\decouple\main.py
```

## 后续接入真实 GIS

生产级空间计算建议通过 `PostGISAdapter` 调用 PostGIS：

- `ST_Buffer`: 缓冲区分析
- `ST_DWithin`: 邻近查询
- `ST_Intersects`: 相交判断
- `ST_Intersection`: 裁剪/重叠区域
- `ST_Length`: 管线长度
- `ST_Area`: 面积统计

Agent 层只暴露业务工具和标准任务，不直接实现底层几何算法。
