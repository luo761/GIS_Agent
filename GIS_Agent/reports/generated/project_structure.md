# 项目目录与文件作用说明

本文说明当前 `GIS_Agent` 项目的目录职责，以及各目录下主要文件的用途。当前项目同时包含正式主线代码、早期原型、PostGIS 学习资料、评测资产和报告产物。主线代码目前仍以 `app/` 为核心。

## 根目录

| 文件 / 目录 | 作用 |
| --- | --- |
| `.gitignore` | Git 忽略规则，控制虚拟环境、缓存、临时文件等是否进入版本管理。 |
| `LICENSE` | 项目许可证。 |
| `README.md` | 项目入口说明，包含项目目标、快速开始、配置项和阶段文档入口。当前文件存在编码显示异常，后续可单独修复。 |
| `requirements.txt` | Python 依赖包清单。当前包含 FastAPI、PostGIS/psycopg、LangChain、LangGraph、DeepSeek、pytest、geopandas 等依赖。 |
| `app/` | 当前正式主线代码，包含配置、数据库连接、PostGIS Tool、Agent 和 LangGraph 流程。 |
| `data/` | 模拟 GIS 数据文件，目前主要是 mock city GeoJSON。 |
| `evaluation/` | 后续 L0-L4 分层评测资产目录，用于存放测试集、标准 SQL 和运行结果。 |
| `GIS_Project/` | 早期原型和实验代码，暂时保留，不作为当前主线入口。 |
| `knowledge/` | GIS 语义词表和算子知识库。 |
| `reports/` | 报告图片素材和已生成报告。 |
| `research/` |研究资料。 |
| `scripts/` | 命令行辅助脚本，例如初始化数据库、运行 LLM 对比、生成周报。 |
| `sql/` | PostGIS 数据库初始化 SQL 和模拟数据 SQL。 |

## `app/` - 当前主线应用代码

`app/` 是当前项目的正式运行代码。它封装了环境配置、数据库连接、PostGIS 工具、确定性 Agent、LLM Agent 和 LangGraph 流程。

### `app/__init__.py`

Python 包标记文件，使 `app` 可以被测试和脚本作为包导入。

### `app/config/`

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | 配置模块包标记。 |
| `settings.py` | 读取运行配置。包含 `Settings` 数据类、`.env` 简单加载逻辑和 `get_settings()`。主要配置项包括 `DATABASE_URL`、`APP_SCHEMA`、`LLM_API_KEY`、`LLM_MODEL`、`OVERPASS_API_URL`、`TRUSTED_GEOJSON_URLS`。 |

### `app/db/`

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | 数据库模块包标记。 |
| `connection.py` | 提供 `get_connection()` 上下文管理器，用 `psycopg` 连接 PostgreSQL/PostGIS，并默认返回字典行。 |
| `identifiers.py` | 提供 `quote_identifier()`，用于校验并安全引用 PostgreSQL 标识符，降低 SQL 注入风险。 |

### `app/tools/`

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | Tool 模块包标记。 |
| `layers.py` | 定义允许访问的空间图层白名单和字段配置。`LayerSpec` 描述 schema、表名、几何字段、标识字段和公开属性字段；`ALLOWED_LAYERS` 包含 `construction_areas`、`gas_pipelines`、`gas_devices`、`water_pipelines`、`demo_roads`，`get_layer_spec()` 负责获取配置并拒绝白名单外的图层。 |
| `schemas.py` | 定义 Tool 入参的 Pydantic 模型。包含 `ListSpatialLayersInput`、`DescribeSpatialLayerInput`、`SpatialFilterInput`、`BufferQueryInput`、`ClipAndMeasureInput`、`NearestFeaturesInput`，以及共用的 `TargetGeometry`。校验空间关系取值、距离和结果数量等参数约束，并要求目标使用已有图层对象或传入的 GeoJSON 几何之一。 |
| `registry.py` | 统一注册 6 个 PostGIS Tool。`ToolSpec` 和 `TOOL_REGISTRY` 定义工具名称、对应方法、入参模型、说明和调用方式；`get_tool_spec()` 查询工具并拒绝未知名称，`postgis_tool_names()` 返回工具名称集合，`postgis_tool_definitions()` 生成供 LLM 使用的函数调用定义，并在参数 JSON Schema 中补充图层白名单枚举。 |
| `postgis_tools.py` | 实现实际访问数据库的 `PostGISToolkit`，提供图层列表、图层描述、空间关系筛选、缓冲区查询、裁剪测量和最近邻查询 6 项能力。通过参数化 SQL、图层白名单和标识符校验执行查询，返回包含状态、工具名、耗时和结果的统一结构。 |

`PostGISToolkit` 的主要公开方法：

| 方法 | 作用 |
| --- | --- |
| `list_spatial_layers()` | 查询白名单内空间图层的 schema、几何字段、几何类型、SRID 和行数。 |
| `describe_spatial_layer()` | 查询指定图层的字段、空间参考和少量样例数据。 |
| `spatial_filter()` | 用 `ST_Intersects`、`ST_Within` 或 `ST_Contains` 执行空间关系筛选。 |
| `buffer_query()` | 对目标对象创建米制缓冲区，并查询与缓冲区相交的要素。 |
| `clip_and_measure()` | 将线或面要素按目标区域裁剪，并统计长度或面积。 |
| `nearest_features()` | 基于给定点查询最近要素，并返回距离排序结果。 |

### `app/agent/`

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | Agent 模块包标记。 |
| `state.py` | 定义 LangGraph/Agent 状态结构。包含 `ToolCallRecord` 和 `AgentState`。 |
| `deterministic.py` | 确定性 GIS Agent。用规则把常见中文问题映射为 Tool 调用，适合做回归测试和 LLM 对照基准。包含 `PlannedToolCall` 和 `DeterministicGISAgent`。 |
| `llm_agent.py` | 真实 LLM 规划器。使用 `ChatDeepSeek` 和结构化输出，让 LLM 只负责选择 Tool 与生成参数，数据库查询仍由 `PostGISToolkit` 执行。 |
| `graph.py` | LangGraph 流程定义。构建 `plan -> execute_tools -> summarize` 三段式 Agent 图，并提供 `run_agent()` 入口。 |
| `compare.py` | 确定性 Agent 与 LLM Agent 的同题对比逻辑，用于比较 Tool 选择、参数和关键结果。 |

## `data/` - 用来存放数据

## `reports/` - 报告和图片素材

| 目录 / 文件         | 作用    |
|-----------------|-------|
| `pictures/`     | 生成的的图片素材。 |
| `weekly_report` | 周报    |
| `generated/`    | 已生成的报告文档。 |


## `research/` - 研究资料和学习材料

该目录存放研究方案、学习笔记和周报，不参与主程序运行。

## `scripts/` - 辅助脚本

| 文件 | 作用 |
| --- | --- |
| `init_db.py` | 数据库初始化脚本。按顺序执行 `sql/001_extensions_and_schema.sql` 和 `sql/002_seed_mock_data.sql`，创建 PostGIS schema 和模拟数据。 |
| `compare_llm_agent.py` | 命令行对比脚本。运行真实 LLM Agent 与确定性 Agent 的同题对比，输出 Tool、参数和关键结果差异。 |
| `generate_learning_weekly_report.py` | 生成学习周报的脚本。读取学习资料并手工构造 docx 所需 XML，输出 Word 报告。 |

## `sql/` - 数据库初始化脚本

| 文件 | 作用 |
| --- | --- |
| `001_extensions_and_schema.sql` | 创建 PostGIS 扩展、`gis_lab` schema、业务表、辅助学习表和空间索引。 |
| `002_seed_mock_data.sql` | 写入可手工校验的模拟数据，包括施工区、燃气管线、燃气设备、水务管线、道路、非法几何和 SRID 示例等。 |
