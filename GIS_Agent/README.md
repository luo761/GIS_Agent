# GIS Agent Lab

基于 Python、PostgreSQL/PostGIS、LangChain 和 LangGraph 的 GIS Agent 研究原型。项目以燃气、水务、施工区等模拟空间数据为基础，探索自然语言驱动的空间查询与分析，并验证大模型理解业务问题、选择工具和生成分析参数的能力。

当前重点是建立可复现的 PostGIS 工具调用基线，后续扩展到复杂问题的多步规划、中间结果传递、分支统计和独立结果评测。

## 当前功能与研究目标

| 状态 | 内容 |
| --- | --- |
| 已实现 | PostGIS 实验数据库初始化、模拟数据与空间索引。 |
| 已实现 | 六个空间分析工具，以及图层白名单、参数模型和工具注册表。 |
| 已实现 | 基于规则的确定性 Agent 与基于 DeepSeek 的 LLM Agent。 |
| 已实现 | 工具名称、标准化参数和关键结果的同题对比。 |
| 已实现 | `plan → execute_tools → summarize` 的最小 LangGraph 流程。 |
| 规划中 | 可组合工具、多步依赖、中间结果引用和多分支分析。 |
| 规划中 | 20 道开发调试题、60 道正式任务的题集建设、独立标准 SQL 和完整评分。 |

当前 LLM 规划器每次只保留一个工具调用。工具内部执行多个 PostGIS 函数，并不代表模型已经自主规划了这些步骤；多步复杂问题验证按研究方案逐步推进。

## 文件结构

以下结构对应当前 `GIS_Agent/` 目录，省略 Python 缓存、Office 临时锁文件等运行产物。

```text
GIS_Agent/
├── app/                              # 应用代码
│   ├── __init__.py
│   ├── config/                       # 配置读取
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── db/                           # 数据库连接与标识符校验
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   └── identifiers.py
│   ├── tools/                        # 空间分析工具与注册信息
│   │   ├── __init__.py
│   │   ├── layers.py
│   │   ├── schemas.py
│   │   ├── registry.py
│   │   └── postgis_tools.py
│   └── agent/                        # 规划、执行、流程与对比
│       ├── __init__.py
│       ├── state.py
│       ├── deterministic.py
│       ├── llm_agent.py
│       ├── graph.py
│       └── compare.py
├── data/                             # 数据文件预留目录，当前为空
├── reports/
│   ├── generated/                    # 已生成的方案文档
│   │   └── GIS_Agent_Test_Plan_PostGIS_2026_v2.docx
│   ├── pictures/                     # 根据种子 SQL 绘制的空间分布图
│   │   ├── seed_mock_data_overview.png
│   │   └── seed_mock_data_details.png
│   └── weekly_report/                # 周报预留目录，当前为空
├── research/                         # 项目需求与研究资料
│   └── gis_agent项目需求.docx
├── scripts/                          # 命令行入口
│   ├── init_db.py
│   └── compare_llm_agent.py
├── sql/                              # 建表与模拟数据
│   ├── 001_extensions_and_schema.sql
│   └── 002_seed_mock_data.sql
├── .env                              # 本地运行配置，不提交 Git
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt
```

空目录不会被 Git 自动保存；上面的 `data/`、`weekly_report/` 描述的是当前本地目录。

## 核心文件的功能与目的

| 文件 | 功能与目的 |
| --- | --- |
| [settings.py](app/config/settings.py) | 定义 `Settings`，读取环境变量和项目根目录的 `.env`；已设置的环境变量优先于 `.env`。 |
| [connection.py](app/db/connection.py) | 提供 `get_connection()` 上下文管理器，通过 psycopg 连接 PostgreSQL，并使用字典形式返回记录。 |
| [identifiers.py](app/db/identifiers.py) | 校验并引用表名、字段名等 SQL 标识符，配合参数化 SQL 限制不受控输入。 |
| [layers.py](app/tools/layers.py) | 用 `LayerSpec` 描述表名、几何字段和公开属性；通过 `ALLOWED_LAYERS` 限定允许访问的业务图层。 |
| [schemas.py](app/tools/schemas.py) | 定义各工具的 Pydantic 输入模型，校验参数结构、范围和目标来源，并补齐默认值。 |
| [registry.py](app/tools/registry.py) | 用 `ToolSpec` 和 `TOOL_REGISTRY` 注册工具名称、实现方法、参数模型及调用方式，生成供 LLM 使用的工具定义。 |
| [postgis_tools.py](app/tools/postgis_tools.py) | 实现 `PostGISToolkit`，执行预定义的参数化空间 SQL，返回查询和分析结果。 |
| [state.py](app/agent/state.py) | 定义 `ToolCallRecord` 和 `AgentState`，记录问题、计划、调用参数、结果、耗时与错误。 |
| [deterministic.py](app/agent/deterministic.py) | 用关键词规则生成 `PlannedToolCall`，执行工具并按模板整理回答，作为基础任务的对照基线。 |
| [llm_agent.py](app/agent/llm_agent.py) | 向模型提供注册工具和系统提示词，提取工具名称及参数，再封装为 `PlannedToolCall`；复用确定性 Agent 的执行与回答整理逻辑。 |
| [graph.py](app/agent/graph.py) | 构建 LangGraph 的规划、执行和总结流程，提供 `run_agent()`；默认使用确定性 Agent。 |
| [compare.py](app/agent/compare.py) | 对同一批问题分别运行两种 Agent，比较第一次调用的工具、标准化参数和关键结果。 |
| [init_db.py](scripts/init_db.py) | 按顺序执行两个 SQL 文件，重建实验 schema 并写入模拟数据。 |
| [compare_llm_agent.py](scripts/compare_llm_agent.py) | 命令行运行默认的五道对比问题，打印工具选择、参数比较和回答结果。 |

各级 `__init__.py` 用于标记和组织 Python 包。

## 已注册的空间分析工具

| 工具 | 功能 | 主要输入 |
| --- | --- | --- |
| `list_spatial_layers` | 列出白名单图层的几何类型、SRID 和记录数。 | 无业务参数。 |
| `describe_spatial_layer` | 查看指定图层的字段、空间参考和样例要素。 | 图层名称、样例数量。 |
| `spatial_filter` | 按 `ST_Intersects`、`ST_Within` 或 `ST_Contains` 筛选要素。 | 待查询图层、目标对象、空间关系。 |
| `buffer_query` | 为目标生成缓冲区，查询与缓冲区相交的要素。 | 目标对象、缓冲距离、待查询图层。 |
| `clip_and_measure` | 计算与目标的几何交集，统计裁剪后的长度或面积。 | 图层、裁剪目标、测量方式。 |
| `nearest_features` | 查询距离指定坐标点最近的若干要素，可限制搜索距离。 | 图层、坐标、SRID、返回数量。 |

分析目标通过 `TargetGeometry` 指定，可以引用数据库中已有要素的 ID 或业务编码，也可以直接传入 GeoJSON 几何及其 SRID。当前尚未提供通用的跨步骤结果引用协议。

工具成功返回的统一字段为 `status`、`tool`、`elapsed_ms`、`result` 和 `error`。其中 `elapsed_ms` 是该工具从开始到结果封装时的耗时，包含连接、查询和结果处理，不包含此前的 LLM 规划时间。

## 运行流程

```text
用户自然语言问题
        ↓
规则规划器 / LLM 规划器
        ↓
PlannedToolCall(name, arguments)
        ↓
注册表查找工具，Pydantic 校验并补齐默认参数
        ↓
PostGISToolkit 执行空间 SQL
        ↓
PostGIS 返回结果，Agent 记录调用并按模板整理回答
```

LLM 通过注册表生成的工具说明了解可选工具及其参数格式，实际数据库查询仍由本地 Python 工具执行。当前的区域编码和业务图层映射主要写在规则代码和系统提示词中。

## 数据库与模拟数据

数据库初始化使用 [建表脚本](sql/001_extensions_and_schema.sql) 和 [种子数据脚本](sql/002_seed_mock_data.sql)，当前不从 `data/` 目录导入数据。

| 表 | 用途 | 种子记录数 |
| --- | --- | --- |
| `gis_lab.construction_areas` | 施工区，包含共边、重叠和带孔洞等场景。 | 10 |
| `gis_lab.gas_pipelines` | 燃气管线，覆盖跨区、边界接触和交叉等场景。 | 12 |
| `gis_lab.gas_devices` | 阀门、调压站和监测点，覆盖内部、边界、孔洞和告警场景。 | 12 |
| `gis_lab.water_pipelines` | 给水与排水管线，用于跨图层分析。 | 10 |
| `gis_lab.demo_roads` | 模拟道路，用于空间关系示例。 | 3 |
| `gis_lab.invalid_geometry_cases` | 自相交面、重复点线等几何异常案例。 | 2 |
| `gis_lab.srid_input_examples` | 不同坐标系的输入几何示例。 | 2 |
| `gis_lab.import_batches` | 数据来源、坐标系和导入数量等批次元数据，不包含几何。 | 1 |

前五张业务表在工具白名单内，共有 47 个模拟要素；辅助表未加入当前业务工具白名单。业务几何使用 EPSG:3857，SRID 输入示例表允许不同坐标系。

当前长度、距离和面积主要采用 EPSG:3857 平面量测，适合本项目模拟坐标实验；真实地理数据需要按精度要求明确分析投影和测量口径。

数据示意图：

- [空间分布总览](reports/pictures/seed_mock_data_overview.png)
- [空间关系与异常案例细节](reports/pictures/seed_mock_data_details.png)

## 本地运行

### 环境准备

使用项目配置的 Python 环境，当前开发环境为 Python 3.12。请先安装 PostgreSQL/PostGIS，创建实验数据库和数据库账号，并确保账号具备初始化扩展及 schema 所需的权限。

在 `GIS_Agent` 目录执行后续命令，并在项目环境中安装依赖：

```powershell
python -m pip install -r requirements.txt
```

### 运行配置

在项目根目录的 `.env` 中配置连接信息和 LLM 参数，例如：

```dotenv
DATABASE_URL=postgresql://gis_user:your_password@localhost:5432/gis_agent
LLM_API_KEY=your_deepseek_api_key
LLM_MODEL=deepseek-chat
```

- 仅运行确定性 Agent 时，需要可用的数据库连接；LLM 对比还需要有效的模型服务密钥。
- 模型密钥也可以通过 `DEEPSEEK_API_KEY` 提供，`LLM_API_KEY` 为配置读取的优先选项。
- `APP_SCHEMA` 默认是 `gis_lab`，但当前 SQL、图层配置和部分查询固定使用该 schema，不能仅修改环境变量就切换整个项目的 schema。
- `OVERPASS_API_URL` 和 `TRUSTED_GEOJSON_URLS` 是预留配置，当前主线没有对应的外部数据导入入口。
- `.env` 已被 `.gitignore` 忽略，请将真实密钥保留在本地配置中。

### 初始化数据库

```powershell
python -m scripts.init_db
```

初始化脚本会执行 `DROP SCHEMA IF EXISTS gis_lab CASCADE`，删除并重建现有 `gis_lab` 及其中对象，再写入种子数据。请仅对准备重置的实验数据库执行；脚本不会创建 PostgreSQL 数据库本身或数据库账号。

### 运行规则 Agent 与 LLM 对比

```powershell
python -m scripts.compare_llm_agent
```

默认比较图层列表、施工区内设备、区域内管线长度、相交管线和最近邻设备五类问题。此命令会实际访问数据库并调用模型服务。

| 输出字段 | 含义 |
| --- | --- |
| `same_tool` | 两种 Agent 第一次调用的工具名称是否相同。 |
| `same_arguments` | 原始参数分别经对应模型校验、补齐默认值并转为字典后，是否相同。需结合 `same_tool` 判断。 |
| `same_key_result` | 当前比较器抽取的关键编码、顺序或汇总值是否相同，不代表所有输出字段都一致。 |

### 在 Python 中调用

```python
from app.agent.deterministic import DeterministicGISAgent

agent = DeterministicGISAgent()
result = agent.run("查询与施工一区相交的燃气管线")
print(result["plan"])
print(result["answer"])
```

使用 LangGraph 包装流程：

```python
from app.agent.graph import run_agent

result = run_agent("统计施工一区内燃气管线总长度")
print(result["answer"])
```

`run_agent()` 默认使用确定性 Agent；如需使用 LLM，可通过 `agent=LLMGISAgent()` 显式传入对应实例。当前主要入口为上述脚本和 Python 接口，尚未提供独立的 FastAPI 服务入口。

## 复杂问题验证规划

详细方案见 [GIS Agent 大模型复杂空间问题验证方案](reports/generated/GIS_Agent_Test_Plan_PostGIS_2026_v2.docx)。当前研究按以下顺序推进：

1. 明确数据、空间关系、单位和各工具的输入输出合同，用独立 SQL 建立标准结果。
2. 补齐可组合操作、完整中间结果、结果句柄与依赖解析，先让人工编写的计划通过执行器验证。
3. 用 20 道开发题调试，再冻结数据、提示词、工具和评分规则，建设 60 道独立正式任务。
4. 分别报告规划正确性、执行结果、异常处理和语言稳定性，重点分析 L2 多约束任务与 L3 多分支任务。

单工具对比、业务工具内部计算、多步自主规划与真实跨平台适配分别验证。联合覆盖、重复计数、边界语义、坐标统一和中间结果复用是后续评测重点；正式题库建设和完整评测结果仍属于后续工作。
