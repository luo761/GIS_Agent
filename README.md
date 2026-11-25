# GIS 多智能体任务架构（能力进化版）

一个五阶段的多智能体 GIS 任务求解架构（LLM + LangGraph）。
智能体没有预设专长——它们只有编号，初始能力完全均衡，专长只能通过
"执行 → 成功/失败经验"逐步进化得到，并由一张动态能力向量图呈现。
空间计算由 PostGIS 完成，工具集与 dev20 基准题共用。

## 命名规则：按层次看项目

目录 = 架构层次，文件名 = 该层做什么；`pipeline/` 下的 `stage1..stage5` 直接对应五阶段顺序。

| 层次 | 目录 | 文件 | 职责 |
| --- | --- | --- | --- |
| 配置 | `config/` | `settings.py`、`agents_capability.yaml`、`domains_taxonomy.yaml` | 数据库/模型参数、初始能力向量、领域分类 |
| 检索 | `retrieval/` | `cosine_similarity.py` | 全项目统一的 TF-IDF + 余弦检索 |
| 知识 | `knowledge/` | `db_schema_retriever.py`、`task_skill_library.py` | PostGIS 表结构检索、任务级 skill 库 |
| 智能体 | `agents/` | `agent_registry.py`、`capability_store.py`、`capability_router.py` | 编号定义、能力进化、平局随机路由 |
| 工具 | `tools/` | `tool_registry.py`、`postgis_tools.py`、`gis_toolkit.py`、`db.py` | 工具注册与 schema 绑定、PostGIS 算子与数据库连接 |
| 记忆 | `memory/` | `agent_memory.py` | 智能体专属记忆（长期记录 + 短期缓存） |
| 经验 | `experience/` | `experience_pool.py`、`experience_retriever.py` | 共享经验池、经验检索 |
| 流水线 | `pipeline/` | `pipeline_state.py`、`llm_client.py`、`pipeline_graph.py`、`stage1_understand.py` … `stage5_evaluate.py` | 五阶段实现与 LangGraph 主图 |
| 可视化 | `visualization/` | `capability_radar_chart.py` | 动态能力向量图（HTML/PNG/文本表） |
| 评测 | `benchmark/` | `dev20.py`、`report.py` | dev20 题集加载、判分与报告渲染 |
| 脚本 | `scripts/` | `run_dev20_benchmark.py`、`show_capability_table.py`、`demo_capability_evolution.py`、`reset_agent_state.py` | 基准评测与运维入口 |

## 核心设定

| 设定 | 说明 |
| --- | --- |
| 命名 | 智能体只有编号：`agent_01`…`agent_04`（显示为 `01`…`04`），无"擅长…"描述 |
| 初始能力 | 每个智能体的每个能力维度经验值都是 **0.5**，四个智能体完全等价 |
| 路由 | 按所需能力维度计算得分，取最高分；**能力均等则随机抽取** |
| 进化 | 执行成功/失败后，只更新该子任务**所需维度**的经验值（成功升、失败降） |
| 检索 | 表结构、skill、共享经验、专属记忆**全部用余弦相似度**检索 |
| 工具 | 10 个 PostGIS 工具启动时 `bind_tools` 绑定到模型，提示词不罗列算子 |
| 结果传递 | 中间几何/要素集不进上下文，改用 `{"$ref": "t1.result.feature_set"}` 引用 |
| 呈现 | `data/capability_vector_chart.html`（可回放动画的雷达图）+ `.png`（当前快照） |

能力维度与业务领域正交：`spatial_compute`（空间计算）、`attribute_query`（属性查询）、
`statistics`（统计分析）、`mapping`（制图可视化）。

## 能力进化规则

```
成功：v ← v + g_success × (v_max − v)      # g_success = 0.10，v_max = 0.99
失败：v ← v − g_failure × (v − v_min)      # g_failure = 0.08，v_min = 0.05
```

- 只改**本次子任务声明所需**的维度，其余维度保持不变；
- 越接近上限增量越小、越接近下限回落越小，能力值始终落在 `[0.05, 0.99]`；
- 一次子任务执行 = 一次经验；同一子任务的多维需求会同时更新多个维度；
- 成功执行过的算子会沉淀为该智能体的"工具偏好"（最多 5 个）。

参数都在 `config/agents_capability.yaml` 的 `evolution` / `routing` 段，可直接改。

## 路由：编号 + 能力向量

```
1. 子任务所需维度 dims（由阶段②的 LLM 标注，缺失时按任务类型回退）
2. 每个智能体得分 score = mean(capability[d] for d in dims)
3. 取最高分；与最高分相差 ≤ tie_epsilon 的智能体进入并列组
4. 并列组只有 1 个 → 选中；多于 1 个 → 在并列组内随机抽取
```

初始状态四个智能体都是 `[0.5, 0.5, 0.5, 0.5]`，得分完全相同，所以**每次路由都是随机抽取**——
不会因为编号靠前就总是被选中、抢先积累经验。等某个智能体在某个维度上积累了几次成功经验，
它才会在该维度上稳定胜出。路由过程（各智能体得分、是否随机）记录在子任务的 `routing` 字段里。

## 检索：全部走余弦相似度

`retrieval/cosine_similarity.py` 是唯一的相似度实现：

```
文本 → 中文单字 + 相邻二字（英文按单词）→ TF-IDF 加权 → L2 归一化 → 点积 = 余弦相似度
```

四个检索点都复用它：

| 检索点 | 文件 | 检索对象 |
| --- | --- | --- |
| 相关数据表 | `knowledge/db_schema_retriever.py` | 从 PostGIS `information_schema` 读取的表、字段与样例值 |
| 相关 skill | `knowledge/task_skill_library.py` | 任务级 skill（名称/做法/步骤/算子） |
| 共享经验 | `experience/experience_pool.py` | 经验签名 + 问题特征 + 失败教训 |
| 专属记忆 | `memory/agent_memory.py` | 该智能体自己完成过的任务 |

检索后还会做**相对截断**：只保留相似度 ≥ 最高分 × `RETRIEVAL_RELATIVE_CUTOFF`（默认 0.4）的命中。

## skill 是什么：任务级套路，不是算子手册

- **单算子小任务**：例如「空间范围筛选计数」→ `query_features`（带 `target` + `relation`）；
- **几个算子的典型任务**：例如「裁剪后量测」→ `query_features` → `clip_features` → `measure_features`，
  「缓冲合并后裁剪」→ `query_features` → `buffer_features` → `union_features` → `clip_features` → `measure_features`。

skill 描述"这类问题通常怎么做、按什么顺序做"，规划阶段据此组织 DAG。
`knowledge/task_skill_library.py` 里有 12 个这样的 skill，每次只检索最相关的 top-k 个（默认 4 个）。

## 工具：PostGIS 算子注册与模型绑定

PostGIS 实现位于 `tools/gis_toolkit.py`，由 `tools/postgis_tools.py`
接入本项目的注册表。默认 `POSTGIS_TOOLSET=advanced`，共 10 个工具：

| 单几何工具 | 要素集工具 |
| --- | --- |
| `buffer_geometry`、`intersection_geometry`、`measure_geometry` | `query_features`、`buffer_features`、`union_features`、`clip_features`、`measure_features`、`summarize_features`、`calculate_ratio` |

- 参数模型（Pydantic）与 JSON Schema 由本地 `tools/gis_toolkit.py` 提供，内联 `$ref` 后交给模型；
- `tools/db.py` 统一读取 `config/settings.py` 的数据库配置；
- 导入工具模块时完成注册，执行器首次调用工具模型时执行 `bind_tools`；
- `POSTGIS_TOOLSET=composable` 可切换为表中 3 个单几何工具；
- 模型直接发起 `tool_calls`，执行器把结果保存进结果仓库，只回填压缩视图；
- 下游参数写 `{"$ref": "t1.result.feature_set"}`，执行器在调用前解析；
- 工具报错会回填给模型，由模型调整参数重试。

## 数据源与基准评测

数据通过 Docker 本地 PostGIS 加载（dev20 题集）：

题集与 SQL 种子数据需另行准备。以下命令中的 `sql/` 指 dev20 数据包中的 SQL 目录。

```powershell
docker run -d --name gis-postgis -p 5433:5432 `
  -e POSTGRES_USER=gis_user -e POSTGRES_PASSWORD=123456 `
  -e POSTGRES_DB=gis_agent postgis/postgis:16-3.4-alpine
docker cp sql gis-postgis:/tmp/sql
docker exec -e PGPASSWORD=123456 gis-postgis psql -U gis_user -d gis_agent -f /tmp/sql/001_extensions_and_schema.sql
docker exec -e PGPASSWORD=123456 gis-postgis psql -U gis_user -d gis_agent -f /tmp/sql/002_seed_mock_data.sql
```

> 注意：Debian 版 `postgis/postgis:16-3.4` 镜像带的是 GEOS 3.9.0，存在
> "线完全落在面内时 `ST_Intersection` 返回空"的问题；请使用 **alpine** 版（GEOS 3.12+）。

`BENCHMARK_DIR` 配置基准数据目录，默认使用本项目 `data/benchmarks`，也可在 `.env` 中覆盖。
原 20 题使用 `dev20.json` / `dev20_expected.json`；50 题实验使用 `dev50.json` / `dev50_expected.json`。
普通工具调用只需数据库；基准评测同时需要题集与完整的标准答案。

评测入口：

```powershell
python scripts/run_dev20_benchmark.py                 # 20 题全量
python scripts/run_dev20_benchmark.py --case D09      # 单题
python scripts/run_dev20_benchmark.py --cases D04,D05 # 指定题
```

每题一次作答（`MAX_REPLANS=0`），失败会写入失败经验；结果保存到
`reports/dev20/dev20_test_report.md` 与 `reports/dev20/dev20_run_*.json`，
Word 版报告为 `reports/dev20/dev20_test_report.docx`。

本次实测结果（deepseek-chat，2026-11-06）：**18/20（90%）**，L1 4/4、L2 8/9、L3 6/7；
平均 12.9 秒/题、3.8 次工具调用/题。未通过的两题分别源于
“空几何 vs 零长度边界接触”的裁剪判断和“严格包含 vs 相交”的边界语义选择。

## 五阶段流程

```
用户口语化问题
      │
      ▼
① 任务理解 Understand：领域识别 + PostGIS 表结构余弦检索 + skill 余弦检索
      │
      ▼
② 精炼与拆解 Decompose：专业精炼 → 拆分 → 标注所需能力维度
      │                    → 代码按能力向量路由（均等 → 随机）
      ▼
③ 规划 Plan（编号智能体）：专属记忆 + 共享经验 + 当前能力向量 + 相关 skill → 计划表 / DAG
      │
      ▼
④ 执行 Execute：模型直接发起绑定工具的 tool_calls，$ref 传递中间几何
      │
      ▼
⑤ 评估 Evaluate：与标准答案/正确答案对比 → 失败回溯重规划（可配置）
      │             → 成功/失败经验写入能力向量（进化）+ 经验池
      ▼
   汇总输出 + 动态能力向量图更新
```

## 目录结构

```
GIS_Agent/
├── main.py                              # 端到端入口（打印路由、进化与能力表）
├── config/
│   ├── settings.py                      # 路径、数据库、容量、检索参数
│   ├── agents_capability.yaml           # 初始能力向量（全 0.5）+ 进化/路由参数
│   └── domains_taxonomy.yaml            # 领域分类 + 任务类型→能力维度回退映射
├── retrieval/
│   └── cosine_similarity.py             # TF-IDF + 余弦相似度（全项目统一检索）
├── knowledge/
│   ├── db_schema_retriever.py           # PostGIS 表结构读取与检索
│   └── task_skill_library.py            # 任务级 skill 库（1~多算子）
├── agents/
│   ├── agent_registry.py                # 编号智能体定义
│   ├── capability_store.py              # 能力向量存储 + 经验进化 + 落盘
│   └── capability_router.py             # 能力打分路由 + 平局随机
├── tools/
│   ├── tool_registry.py                 # 工具注册 + function-calling schema
│   ├── postgis_tools.py                 # 本地 PostGIS 工具集适配（10 个工具）
│   ├── gis_toolkit.py                   # 图层白名单、参数模型、空间 SQL 与 ToolSpec
│   └── db.py                            # 数据库配置、连接与标识符引用
├── memory/
│   └── agent_memory.py                  # 智能体专属记忆
├── experience/
│   ├── experience_pool.py               # 共享经验池（余弦检索/同类更新/容量淘汰）
│   └── experience_retriever.py          # 规划前的经验检索与渲染
├── pipeline/
│   ├── pipeline_state.py                # 共享状态（含路由/进化/输出契约字段）
│   ├── llm_client.py                    # LLM 封装（延迟建模型、bind_tools）
│   ├── pipeline_graph.py                # LangGraph 主图（五阶段 + 失败回溯）
│   ├── stage1_understand.py             # ① 领域识别 + 上下文注入 + skill 检索
│   ├── stage2_decompose.py              # ② 精炼/拆解 + 标注能力维度 + 路由
│   ├── stage3_plan.py                   # ③ 记忆/经验检索 + 计划表/DAG
│   ├── stage4_execute.py                # ④ 工具调用 + $ref 结果传递
│   └── stage5_evaluate.py               # ⑤ 评估 + 能力进化 + 经验入库
├── visualization/
│   └── capability_radar_chart.py        # 动态能力向量图（HTML 雷达图 + PNG）
├── benchmark/
│   ├── dev20.py                         # 题集加载、JSON 提取、判分、输出契约
│   └── report.py                        # Markdown 测试报告
├── scripts/
│   ├── run_dev20_benchmark.py           # dev20 评测入口
│   ├── show_capability_table.py         # 查看能力表 / 演示随机路由
│   ├── demo_capability_evolution.py     # 离线演示（不调 LLM）
│   └── reset_agent_state.py             # 复位为初始均衡状态
├── tests/
│   ├── test_capability_evolution.py     # 能力进化、路由与流水线测试
│   └── test_postgis_toolkit.py          # 本地工具迁移、注册、绑定与结果引用测试
├── data/                                # agent_capabilities.json、capability_vector_chart.*
├── docs/                                # 演示图表
└── reports/dev20/                       # 评测报告与原始结果
```

## 运行

```bash
pip install -r requirements.txt
# 在项目根目录创建或编辑 .env，填写 DATABASE_URL、DEEPSEEK_API_KEY、LLM_MODEL
# 使用其他题集目录时，可通过 BENCHMARK_DIR 覆盖默认的 data/benchmarks

# 普通模式
python main.py "统计与施工区 A001 相交的燃气设备数量"

# 测试模式：给出参考答案（由 LLM 判定对错并进化）
python main.py "问题" --truth "参考答案"

# 基准评测（20 题，生成报告）
python scripts/run_dev20_benchmark.py

# 能力表 / 随机路由分布
python scripts/show_capability_table.py --times 100

# 复位能力与经验
python scripts/reset_agent_state.py --yes
```

测试：

```bash
python -m pytest tests -q
```

## 50 题重规划对比实验

`data/benchmarks/dev50.json` 保留原 D01–D20，并扩展 D21–D50。新增题目的标准答案由独立的 PostGIS SQL 计算；
缺失数据库或标准答案时，实验显示 `blocked`，不把未运行题目记为答错。

```powershell
# 检查题集与答案完整性，不访问模型或数据库
python scripts/run_dev50_comparison.py --validate-only

# 用已导入的基准数据计算新增题目的标准答案
python scripts/build_dev50_suite.py --compute-expected

# 检查答案、PostGIS 图层及模型服务，并重新用独立 SQL 核对答案与当前数据一致
python scripts/run_dev50_comparison.py --preflight-only

# 同一50题，分别关闭重规划（0次）和开启重规划（最多额外2次）
python scripts/run_dev50_comparison.py --max-replans 2 --workers 4

# 服务中断后，按相同配置续跑；或先用 --limit 2 进行小批验证
python scripts/run_dev50_comparison.py --max-replans 2 --workers 4 --resume
```

每道题、每种模式使用新的进程和空的能力/经验/记忆目录，保持相同模型参数、题集、数据和路由种子；
题目之间不共享学习状态，题内重规划保留反馈与经验。原项目 `data/` 下的运行状态不被清空。
评估反馈只暴露出错字段路径，不向重规划提供标准答案值。重规划只重跑阶段③–⑤，工具执行器内部的报错调整在两组中保持一致。

结果写入 `reports/dev50_comparison/`：`records/` 保存每题每模式的全部评估轮次、工具调用、耗时及 LLM token 统计；
`comparison_report.md` / `comparison.json` 比较整体及分难度正确率、首轮正确率、题内挽回、配对增益/退化、总工具调用和耗时。
服务未返回 token 用量时标记为未报告。断点签名包含模型/参数、代码、题集/答案与数据库指纹；配置变化需使用新输出目录。
一次配对实验只作描述性比较，固定路由种子不保证模型输出完全确定。
`--workers` 默认 1，可同时处理多个题目，每题的两种模式仍顺序执行；服务异常时停止分发新题，保留已完成结果并等待在途题目结束。

## 说明

- 五阶段状态统一放在 `PipelineState`；节点返回字段更新字典；
- 正确答案通过 `PipelineState.ground_truth` 传入；基准评测用确定性判分器
  （`stage5.set_verifier`）替代 LLM 判卷，保证分数可复现；
- 经验值只存于 `data/agent_capabilities.json`，删掉即可回到全 0.5；
- PostGIS 工具实现位于本项目 `tools/gis_toolkit.py`，数据库连接由 `DATABASE_URL` 配置；
- dev20 题集数据独立配置于 `BENCHMARK_DIR`；
- 运行环境：Python 3.11+、psycopg、langgraph、langchain-deepseek；数据库需 PostGIS。
