# GIS 多智能体任务架构（能力进化版）

一个五阶段的多智能体 GIS 任务求解架构（LLM + LangGraph）。
智能体没有预设专长——它们只有编号，初始能力完全均衡，专长只能通过
"执行 → 成功/失败经验"逐步进化得到，并由一张动态能力向量图呈现。
空间计算由 PostGIS 完成，工具集与 dev20 基准题共用。

系统在阶段①内置两道安全闸门（都不新增流水线阶段）：

- **问题不合法**：领域识别时多一个特殊领域 `invalid`，LLM 判定问题缺要素、
  越权或与 GIS 无关时**直接中止**本次执行，返回追问让用户补充信息，补充后再从阶段①重跑；
- **用户权限表**：`config/user_permissions.yaml` 按用户类别（管理员/分析员/运维/访客）
  定义对具体数据表的增删改查权限，表结构注入与工具执行都按角色校验，越权调用写审计日志。

## 命名规则：按层次看项目

目录 = 架构层次，文件名 = 该层做什么；`pipeline/` 下的 `stage1..stage5` 直接对应五阶段顺序。

| 层次 | 目录 | 文件 | 职责 |
| --- | --- | --- | --- |
| 配置 | `config/` | `settings.py`、`agents_capability.yaml`、`domains_taxonomy.yaml`、`user_permissions.yaml` | 数据库/模型参数、初始能力向量、领域分类与合法性规则、用户权限表 |
| 安全 | `security/` | `question_guard.py`、`permissions.py` | “问题不合法”判定与澄清、用户类别→表级增删改查权限 |
| 检索 | `retrieval/` | `cosine_similarity.py` | 全项目统一的 TF-IDF + 余弦检索 |
| 知识 | `knowledge/` | `db_schema_retriever.py`、`task_skill_library.py` | PostGIS 表结构检索（按角色过滤）、任务级 skill 库 |
| 智能体 | `agents/` | `agent_registry.py`、`capability_store.py`、`capability_router.py` | 编号定义、能力进化、平局随机路由 |
| 工具 | `tools/` | `tool_registry.py`、`postgis_tools.py`、`permission_guard.py` | 工具注册与 schema 绑定、PostGIS 工具适配、调用前权限校验 |
| 记忆 | `memory/` | `agent_memory.py` | 智能体专属记忆（长期记录 + 短期缓存） |
| 经验 | `experience/` | `experience_pool.py`、`experience_retriever.py` | 共享经验池、经验检索 |
| 流水线 | `pipeline/` | `pipeline_state.py`、`llm_client.py`、`pipeline_graph.py`、`stage1_understand.py` … `stage5_evaluate.py` | 五阶段实现与 LangGraph 主图（阶段① 含合法性短路） |
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
| 合法性 | 阶段① 与领域识别同一次 LLM 调用判定；命中即中止并追问，不写能力经验 |
| 权限 | 每个用户类别对每张表有独立的查询/新增/修改/删除权限，未登记的表 fail-closed |
| 结果传递 | 中间几何/要素集不进上下文，改用 `{"$ref": "t1.result.feature_set"}` 引用 |
| 呈现 | `data/capability_vector_chart.html`（可回放动画的雷达图）+ `.png`（当前快照） |

能力维度与业务领域正交：`spatial_compute`（空间计算）、`attribute_query`（属性查询）、
`statistics`（统计分析）、`mapping`（制图可视化）。

## 问题不合法：阶段① 的安全闸门

`config/domains_taxonomy.yaml` 的 `domains.invalid` 是一个**特殊领域**（`special: true`），
不是业务行业，也不参与候选表检索。阶段① 在同一次 LLM 调用里输出
`domain` 与 `is_valid / invalid_reasons / missing_slots / clarification_question`；
主图在 `understand` 之后加一条条件边：不合法 → `END`，合法 → `decompose`。
**没有新增节点**，②~⑤ 不会执行，也不会写能力经验。

判定分两层，**谁更严格听谁的**：

| 层 | 位置 | 作用 |
| --- | --- | --- |
| 规则层 | `security/question_guard.py` | 空问题、过短/过长、纯空泛动词、越权/破坏性/提示词注入、完全没有 GIS 业务锚点 |
| LLM 层 | `pipeline/stage1_understand.py` | 缺分析对象/范围/条件/指标/时间口径、与 GIS 无关、范围超出业务边界 |

命中后返回给用户的追问包含：原问题、不合法原因、缺失信息清单（对象/范围/条件/指标/时间）
和逐条提问；`clarification_template` 与 `required_slots` 都在 YAML 里可改。
CLI 交互终端会自动进入补充循环（最多 `max_clarify_rounds` 轮，默认 3 轮）：

```powershell
python main.py "帮我看看"                 # 打印追问，交互终端可连续补充
python main.py "帮我看看" --no-clarify    # 只打印追问，退出码 2
python main.py "查燃气设备" --clarify-rounds 5
```

规则层先于 LLM 执行：明显的空泛/越权问题即使模型不可用也会被拦下。

Web 任务台同样覆盖这条交互：判定不合法时，结果区会出现「补充信息后重跑」卡片，
列出五类槽位（缺失项标红、其余可选）；填写后点击“追加说明并重跑”，
系统把 `（补充说明：分析对象=…；空间范围=…）` 追加到原问题，从阶段① 重新判定。

## 用户权限表：按用户类别控制表级增删改查

`config/user_permissions.yaml` 把“用户类别（角色）× 数据表 × CRUD”写成一张显式权限表：

| 角色 | 定位 | 典型权限 |
| --- | --- | --- |
| `admin` | 系统管理员 | 全部业务表可增删改查 |
| `analyst` | 业务分析员 | 查询 + 新增 + 修改，不可删除 |
| `operator` | 运维操作员 | 查询 + 修改（设备/管线状态） |
| `viewer` | 访客（只读） | 只查询公开业务表 |

- 表级权限逐张列出；**未登记的表一律拒绝**（fail-closed），敏感表（`import_batches`、
  `invalid_geometry_cases`、`srid_input_examples`）只有管理员可读；
- 三道防线：① 阶段① 只把当前角色可查询的表注入提示词；
  ② 工具执行前 `tools/permission_guard.py` 按 `layer_name` 校验，越权不执行；
  ③ Web 任务台可选择用户类别，演示引擎同样过滤表并拦截越权步骤；
- 拒绝与写操作写入 `data/permission_audit.jsonl`，默认只保留最近 500 条，
  拒绝事件优先保留；
- `principals` 可把用户标识映射到角色（演示用），生产环境应替换为统一身份认证。

```powershell
python main.py "统计 A001 内正常燃气设备数量" --role viewer
python main.py "查询导入批次" --user guest      # guest → viewer
```

权限查询/展示：

```python
from security import permissions
t = permissions.get_table()
t.check("viewer", "gas_devices", "delete")   # CheckResult(allowed=False, ...)
t.render_matrix()                            # Markdown 权限矩阵
```

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

## 工具：PostGIS 算子，启动即绑定

`tools/postgis_tools.py` 把 dev20 项目的 PostGIS 工具集（`app_development/tool.py`，只读调用）
接入本项目的注册表，共 10 个工具：

| 单几何工具 | 要素集工具 |
| --- | --- |
| `buffer_geometry`、`intersection_geometry`、`measure_geometry` | `query_features`、`buffer_features`、`union_features`、`clip_features`、`measure_features`、`summarize_features`、`calculate_ratio` |

- 参数模型（Pydantic）与 JSON Schema 由外部工具集提供，本项目内联 `$ref` 后交给模型；
- 模型直接发起 `tool_calls`，执行器把结果保存进结果仓库，只回填压缩视图；
- 下游参数写 `{"$ref": "t1.result.feature_set"}`，执行器在调用前解析；
- 工具报错会回填给模型，由模型调整参数重试。

## 数据源与基准评测

数据通过 Docker 本地 PostGIS 加载（dev20 题集）：

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
① 任务理解 Understand：领域识别（含“问题不合法”判定）+ 用户权限注入
     + PostGIS 表结构余弦检索（按角色过滤）+ skill 余弦检索
      │
      ├── 问题不合法 ──→ 立即结束：返回澄清追问（不拆分/不执行/不进化）
      ▼
② 精炼与拆解 Decompose：专业精炼 → 拆分 → 标注所需能力维度
      │                    → 代码按能力向量路由（均等 → 随机）
      ▼
③ 规划 Plan（编号智能体）：专属记忆 + 共享经验 + 当前能力向量 + 相关 skill + 表级权限 → 计划表 / DAG
      │
      ▼
④ 执行 Execute：模型直接发起绑定工具的 tool_calls（调用前按角色校验），$ref 传递中间几何
      │
      ▼
⑤ 评估 Evaluate：与标准答案/正确答案对比 → 失败回溯重规划（可配置）
      │             → 成功/失败经验写入能力向量（进化）+ 经验池
      ▼
   汇总输出 + 动态能力向量图更新
```

## 目录结构

```
Test/
├── main.py                              # 端到端入口（打印路由、进化与能力表）
├── config/
│   ├── settings.py                      # 路径、数据库、容量、检索参数
│   ├── agents_capability.yaml           # 初始能力向量（全 0.5）+ 进化/路由参数
│   ├── domains_taxonomy.yaml            # 领域分类 + 合法性判定规则 + 任务类型→能力维度回退
│   └── user_permissions.yaml            # 用户权限表：角色 × 数据表 × 增删改查
├── security/
│   ├── question_guard.py                # “问题不合法”规则层、缺失信息与澄清文本
│   └── permissions.py                   # 权限表加载/校验/审计/矩阵渲染
├── retrieval/
│   └── cosine_similarity.py             # TF-IDF + 余弦相似度（全项目统一检索）
├── knowledge/
│   ├── db_schema_retriever.py           # PostGIS 表结构读取与检索（按角色过滤）
│   └── task_skill_library.py            # 任务级 skill 库（1~多算子）
├── agents/
│   ├── agent_registry.py                # 编号智能体定义
│   ├── capability_store.py              # 能力向量存储 + 经验进化 + 落盘
│   └── capability_router.py             # 能力打分路由 + 平局随机
├── tools/
│   ├── tool_registry.py                 # 工具注册 + function-calling schema
│   ├── postgis_tools.py                 # dev20 PostGIS 工具集适配（10 个工具）
│   └── permission_guard.py              # 工具调用前的表级权限校验
├── memory/
│   └── agent_memory.py                  # 智能体专属记忆
├── experience/
│   ├── experience_pool.py               # 共享经验池（余弦检索/同类更新/容量淘汰）
│   └── experience_retriever.py          # 规划前的经验检索与渲染
├── pipeline/
│   ├── pipeline_state.py                # 共享状态（含合法性/权限/路由/进化/输出契约字段）
│   ├── llm_client.py                    # LLM 封装（延迟建模型、bind_tools）
│   ├── pipeline_graph.py                # LangGraph 主图（五阶段 + 不合法短路 + 失败回溯）
│   ├── stage1_understand.py             # ① 合法性判定 + 领域识别 + 权限注入 + skill 检索
│   ├── stage2_decompose.py              # ② 精炼/拆解 + 标注能力维度 + 路由
│   ├── stage3_plan.py                   # ③ 记忆/经验检索 + 计划表/DAG
│   ├── stage4_execute.py                # ④ 权限校验 + 工具调用 + $ref 结果传递
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
│   ├── test_capability_evolution.py     # 能力/路由/进化/检索/端到端
│   └── test_security_and_validity.py    # 问题合法性、权限表、检索过滤、越权拦截
├── data/                                # agent_capabilities.json、capability_vector_chart.*、permission_audit.jsonl
├── docs/                                # 演示图表
├── reports/dev20/                       # 评测报告与原始结果
└── web/                                 # Web 控制台（零依赖前端 + 本地演示服务）
```

## 运行

```bash
pip install -r requirements.txt
cp .env.example .env   # 必填 DEEPSEEK_API_KEY；按需填写 DATABASE_URL / LLM_MODEL / POSTGIS_TOOLKIT_ROOT

# 普通模式
python main.py "统计与施工区 A001 相交的燃气设备数量"

# 指定用户类别（决定表级权限）
python main.py "统计与施工区 A001 相交的燃气设备数量" --role viewer

# 问题不合法：只打印追问
python main.py "帮我看看" --no-clarify

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

## Web 控制台（可视化演示）

`web/` 下提供零依赖的本地 Web 控制台，用于交互式演示五阶段执行流、能力进化与知识资产：

```powershell
# Windows
web\start.bat
# 或
python web/server/app.py --open
```

浏览器打开 `http://127.0.0.1:8765`，包含：总览、任务台、执行流回放、能力进化、
技能库、知识库、记忆库、dev20 评测报告、系统管理。执行流与工具返回值由本地模拟引擎生成，
但检索（TF-IDF 余弦）、路由得分/并列随机、能力进化公式、问题合法性规则、用户权限校验
均直接复用项目实现；演示数据只写入 `web/data/`，不会修改 `data/` 下的能力、经验与记忆。

- 任务台新增“用户类别”选择：只注入该角色有权查询的表，越权步骤会被拦截并标注；
- 输入空泛/越权问题会直接展示“问题不合法”的判定原因与缺失信息清单；
- 系统管理页新增权限矩阵与最近审计记录；
- 新增接口：`GET /api/permissions?role=viewer`、`POST /api/validate`。
详细说明见 [`web/README.md`](web/README.md)。

## 说明

- 五阶段状态统一放在 `PipelineState`；节点返回字段更新字典；
- `is_valid / invalid_reasons / missing_info / clarification` 是阶段① 的合法性字段，
  `user_role / permission_context / permission_denials` 是权限字段；
- 正确答案通过 `PipelineState.ground_truth` 传入；基准评测用确定性判分器
  （`stage5.set_verifier`）替代 LLM 判卷，保证分数可复现；
- 经验值只存于 `data/agent_capabilities.json`，删掉即可回到全 0.5；
- 权限表是 `config/user_permissions.yaml`，改完无需重启（`PermissionTable.reload()`）；
  审计日志在 `data/permission_audit.jsonl`，可随时删除；
- 外部 PostGIS 工具集只读调用，路径由 `POSTGIS_TOOLKIT_ROOT` 配置（默认相对项目根 `tools/`，找不到时回退到 `tools/app_development`）；dev20 题集同理走 `BENCHMARK_DIR`（默认 `data/benchmarks`）；
- 运行环境：Python 3.11+、psycopg、langgraph、langchain-deepseek；数据库需 PostGIS。
