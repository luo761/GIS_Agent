# 四文件开发版：项目结构与关键代码说明

本文面向 `app_development/` 四文件合并版，重点说明各文件如何配合，以及阅读源码时需要掌握的关键代码。

本版本由已有代码合并而来，仍使用项目原有的数据、SQL、依赖和配置，不是重新实现的一套 Agent。下面的代码块均为现有代码的关键摘录，省略的上下文请查看对应源文件。

## 1. 项目结构与文件分工

```text
GIS_Agent/
├── app_development/
│   ├── agent.py      # 规划、计划格式、结果引用、执行、日志
│   ├── tool.py       # 图层、工具参数模型、空间工具、注册表
│   ├── db.py         # 配置、数据库连接、标识符校验
│   ├── test.py       # 计划比较、开发题集验收、真实模型评测
│   └── README.md     # 本说明文档
├── data/             # 题目、参考计划、标准答案快照
├── sql/              # 建表、种子数据、独立基准SQL
├── reports/runs/     # 运行日志与批次记录
└── .env              # 本地数据库与模型配置，不应上传
```

目录中仍然只有四个 Python 文件；本说明是额外的 Markdown 文档。

| 文件 | 主要类或函数 | 职责 |
| --- | --- | --- |
| [agent.py](agent.py) | `MultiStepLLMGISAgent` | 请求LLM一次提交完整的多步空间分析计划。 |
| [agent.py](agent.py) | `ExecutionPlan`、`ResultReference`、`ResultStore`、`PlanExecutor` | 定义计划、检查依赖、传递结果、执行工具。 |
| [agent.py](agent.py) | `JsonRunLogger`、`persist_run`、`main` | 保存运行记录，提供多步模型命令入口。 |
| [tool.py](tool.py) | `TargetGeometry`、`FeatureSet`、各类输入模型 | 校验几何、要素集合和工具参数。 |
| [tool.py](tool.py) | `PostGISToolkit`、`FeatureSetToolkit`、`ToolSpec` | 执行空间操作，并把工具说明、参数模型和方法关联起来。 |
| [db.py](db.py) | `Settings`、`get_settings`、`get_connection`、`quote_identifier` | 读取配置、建立连接、校验并引用SQL标识符。 |
| [test.py](test.py) | `compare_plan_runs`、`validate_static`、`validate_postgis`、`run_batch`、`assess` | 比较计划，验收参考路径，以独立SQL评价模型输出。 |

文件内部的“合并来源”“原文件”注释标明了每段代码来自原项目的哪个模块。当前目录仅保留多步规划与评测体系，参数校验、空间SQL和业务判分继续复用已有实现。

## 2. 系统运行流程

### 2.1 多步运行主线

```text
中文问题 + 工具说明 + 计划格式
                 ↓
MultiStepLLMGISAgent：请求模型一次提交完整计划
                 ↓
ExecutionPlan：检查步骤、引用来源、依赖与循环
                 ↓
PlanExecutor：按依赖顺序串行执行
                 ↓
ResultStore替换引用 → 参数模型校验 → 注册表查找工具
                 ↓
tool.py执行预定义空间SQL → db.py连接PostGIS
                 ↓
保存步骤结果 → 解析最终outputs → 本地模板整理回答
                 ↓
按入口配置保存JSON日志；评测入口再与独立SQL核对
```

模型负责组织步骤和选择参数，PostGIS负责计算数值。当前不是“每执行一步就把结果发给模型重新决策”的循环；中间几何由本地仓库传递，回答总结也不再请求模型。

20题模型评测使用 `DevelopmentLLMAgent`，它继承 `MultiStepLLMGISAgent` 并增加题集统一的输出规则。

## 3. agent.py：关键规划与执行代码

### 3.1 用Pydantic定义计划格式

`PlanStep` 描述一个步骤，`ExecutionPlan` 描述完整计划。定义摘录：

```python
class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Identifier
    tool: Identifier
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[Identifier] = Field(default_factory=list)

class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[PlanStep] = Field(min_length=1, max_length=100)
    outputs: dict[Identifier, ResultReference] = Field(min_length=1)
```

- `id`：步骤名称；`tool`：工具名称；`arguments`：输入参数。
- `depends_on`：必须先完成哪些步骤；`outputs`：最终返回哪些步骤结果。
- `Identifier` 限制名称的字符和长度；`extra="forbid"` 禁止多余字段。
- `validate_dependencies()` 检查重复ID、缺失依赖、自身依赖、引用来源和循环依赖。

`ordered_steps()` 做稳定拓扑排序，核心判断为：

```python
ready = next(
    (step for step in pending if set(step.depends_on) <= completed),
    None
)
```

只有全部依赖已排在前面的步骤才可以被选中。这里的 `completed` 是排序时的集合，不表示工具已经实际执行成功。

### 3.2 告诉模型完整计划应当长什么样

`execution_plan_definition()` 将计划模型转为JSON Schema，作为 `submit_execution_plan` 的输入格式：

```python
"parameters": ExecutionPlan.model_json_schema(by_alias=True)
```

`MultiStepLLMGISAgent._generate_plan()` 中的关键代码：

```python
self.planner = self.model.bind_tools(
    [execution_plan_definition()], tool_choice=PLAN_TOOL_NAME
)
response = self.planner.invoke([
    SystemMessage(content=self.system_prompt()),
    HumanMessage(content=question)
])
```

模型在这个接口上提交的是完整计划，不是直接运行空间工具。步骤中可使用的内部工具及其参数说明由 `system_prompt()` 提供。

`_plan_arguments()` 要求恰好提交一次 `submit_execution_plan`；随后校验计划。在高级工具组中，集合操作的 `features` 还必须引用合法上游的 `result.feature_set`，不能由模型手填集合坐标。

提示词位置：多步版在 `MultiStepLLMGISAgent.system_prompt()`；20题评测额外规则在 `test.py` 的 `DevelopmentLLMAgent.system_prompt()`。

### 3.3 用ResultStore传递中间结果

例如后续步骤写入：

```json
{"left": {"$ref": "buf.result.geometry"}}
```

`ResultReference` 负责校验引用格式；`ResultStore` 负责真正读取数据。执行器先解析引用：

```python
resolved = store.resolve(step.arguments)
```

于是 `left` 从引用对象变成前一步实际返回的几何和SRID。`get()` 只沿字典键、非负列表下标逐层访问，不执行任意表达式。

`put()` 拒绝重复步骤ID；存取都使用深拷贝。每次执行器 `run()` 创建独立仓库，不复用上一轮请求的结果。

### 3.4 执行器按约定调用工具

`PlanExecutor.run()` 在替换引用后校验参数，再选择调用方式：

```python
arguments = spec.validate_arguments(resolved)
record["normalized_arguments"] = arguments.model_dump()
method = getattr(self.toolkit, spec.method_name)
if spec.invocation == "none":
    result = method()
elif spec.invocation == "kwargs":
    result = method(**arguments.model_dump(exclude_none=True))
else:
    result = method(arguments)
```

三种方式分别对应无业务参数、关键字参数、完整参数模型对象，是执行器保留的通用调用接口；当前两个工具集的工具均采用参数模型对象方式。成功结果才写入仓库，供下游引用。

| 记录字段 | 含义 |
| --- | --- |
| `arguments` | 计划中原始参数，可能含有 `$ref`。 |
| `resolved_arguments` | 引用替换后的实际参数。 |
| `normalized_arguments` | 参数校验并补齐默认值后的内容。 |
| `result`、`error`、`elapsed_ms` | 工具返回值、错误、步骤耗时。 |

执行器默认采用 `stop`，失败后跳过所有剩余步骤；多步 Agent 使用 `skip_dependents`，失败的下游跳过，独立分支继续。两者均串行执行、不自动重试；任何步骤失败都不发布部分最终输出，但保留步骤记录。

### 3.5 日志与计算错误分别记录

`JsonRunLogger.write()` 将一次运行保存为 `<run_id>.json`，检查32位小写十六进制ID，并使用创建新文件模式：

```python
with path.open("x", encoding="utf-8") as stream:
    stream.write(encoded + "\n")
```

文件已存在就报错，不覆盖历史记录。`persist_run()` 将保存失败写入 `logging_error`，不会把它伪装成空间计算失败。

注意：日志类本身不会自动脱敏，它会尝试序列化传入的 `run`；调用方仍需防止将密钥、连接字符串或客户端对象放入记录。

## 4. tool.py：工具注册、输入输出与空间计算

### 4.1 注册表是模型说明与本地方法之间的桥梁

`ToolSpec` 保存工具名称、对应方法、参数模型、说明和调用方式。参数校验的核心为：

```python
def validate_arguments(self, arguments: dict[str, Any] | None) -> BaseModel:
    return self.args_schema(**(arguments or {}))
```

模型中定义的默认值由Pydantic补齐；缺少必填字段或范围不合法时抛出异常。`llm_definition()` 将同一参数模型转成工具JSON Schema，避免说明与校验分别维护。

| 工具集 | 内容 | 实现类 |
| --- | --- | --- |
| `composable` | 三个单几何工具：缓冲、求交、量测。 | `PostGISToolkit` |
| `advanced` | 三个组合工具，加七个查询、批量处理和统计工具。 | `FeatureSetToolkit` |

默认工具集为 `composable`；`advanced` 包含这三个组合工具和七个高级工具，共十个。`create_toolkit()` 按工具集选择实现类，`get_tool_spec()` 按相应白名单查找工具。

### 4.2 单个几何与要素集合不能混用

| 数据类型或引用路径 | 用途 |
| --- | --- |
| `TargetGeometry` | 引用数据库中的已有要素，或传入GeoJSON几何及SRID。 |
| `步骤.result.geometry` | 单个几何包装对象，包含 `geometry` 与 `srid`，可整体传给 `target`、`left`、`right`、`clip_target`。 |
| `步骤.result.feature_set` | 完整要素集合，传给批量工具的 `features`。 |
| `measure_geometry步骤.result` | 单几何的完整量测结果。 |
| `measure_features步骤.result.summary` | 要素集合的量测汇总。 |

`FeatureSet` 保留来源编码、属性、统一SRID和完整性标记，数量必须与明细一致。完整查询超过安全上限会报错，不把截断结果冒充完整集合。

### 4.3 空间操作与业务语义

`PostGISToolkit` 执行预定义空间SQL；`FeatureSetToolkit` 在其基础上提供完整集合的查询、缓冲、裁剪、合并、测量和分组统计。

- 相交查询只选择完整对象，不会裁掉对象的区外部分；测区内长度还需裁剪。
- `buffer_features` 逐个缓冲，不自动去重；覆盖面积需要先 `union_features` 合并。
- `measure_features` 汇总各源对象的量测值，不自动做空间合并。
- `clip_features` 默认去掉空交集，但保留非空的零长度接触。
- `calculate_ratio` 接受完整量测对象，检查单位、SRID和非零分母，不接受随意拼出的裸数值。

当前模拟实验采用EPSG:3857平面量测；这不意味着真实地理数据可以忽略分析投影和精度要求。

## 5. db.py：配置、连接与SQL边界

`get_settings()` 读取项目根目录 `.env`，已设置的环境变量优先。模型密钥从 `LLM_API_KEY` 或 `DEEPSEEK_API_KEY` 读取；配置不应直接写进文档或上传。

数据库连接使用上下文管理器：

```python
@contextmanager
def get_connection(database_url: str | None = None) -> Iterator[Connection]:
    url = database_url or get_settings().database_url
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn
```

`dict_row` 让查询行可以按字段名访问；`with` 负责连接生命周期。

SQL安全分为两部分：表名、字段名先经过白名单与 `quote_identifier()` 校验；业务值使用SQL参数绑定，不能把用户文本直接拼成SQL。

只读保护由命令入口和验收连接选项设置，`get_connection()` 本身不会无条件强制只读。直接通过Python接口调用时，需要自行传入带只读保护的连接信息。

## 6. test.py：如何检验结果与过程

`test.py` 是比较、验收和评测入口，不是把原 `tests/` 中的所有pytest用例复制到这个文件。

### 6.1 先验收当前工具与人工计划

`validate_static()` 检查题集、参考计划、SQL和答案快照等资料；`validate_postgis()` 用只读数据库核对：

```text
独立SQL结果 ↔ 标准答案快照
人工计划经执行器得到的输出 ↔ 独立SQL结果
```

独立SQL绕过项目的工具实现与执行器，但仍使用同一个PostGIS，并非另一种空间计算引擎。人工计划验收通过，不代表真实模型已经答对。

### 6.2 再评价真实模型

`DevelopmentLLMAgent` 在多步提示词后追加统一输出要求。模型只接收题目、输出要求和工具说明，不接收参考计划、独立SQL或标准答案。

`run_batch()` 每题请求一次，先预检基准、检查数据指纹，再执行和评分；保留批次协议、原始回复、逐题结果与汇总，不自动重试失败题。

`assess()` 的关键判定：

```python
execution_success = execution.get("status") == "ok"
differences = compare_outputs(run.get("outputs", {}), answer,
                              abs_tol=load_suite().default_abs_tol,
                              tolerances=case.tolerances)
correct = run.get("status") == "ok" and execution_success and not differences
```

它比较完整业务输出，包括字段、单位、数值、数量、分组和顺序，而不只是检查一个总和。

### 6.3 计划一致不等于唯一正确解

`compare_plan_runs()` 可以对比工具次数、标准化计划和最终输出，分别给出 `same_tools`、`same_plan`、`same_outputs`；补默认值、步骤改名、独立步骤排列等差异会进行相应标准化处理。

20题业务评分不以 `same_plan` 为必要条件，因为可能存在不同但等价的路径。执行器主要检查过程是否合法，业务约束是否完整还需要复核计划和中间结果。例如漏掉A001裁剪的计划可能正常执行，却算入区外长度。

## 7. 一个贯穿示例：D09缓冲区裁剪

问题：以设备D011为中心建立700米缓冲区，计算其位于A001内的面积。

| 步骤 | 工具 | 输入与结果传递 |
| --- | --- | --- |
| `buf` | `buffer_geometry` | 使用D011，生成700米缓冲区。 |
| `inter` | `intersection_geometry` | 引用 `buf.result.geometry`，与A001求交；声明依赖 `buf`。 |
| `area` | `measure_geometry` | 引用 `inter.result.geometry`，测面积；声明依赖 `inter`。 |

最终输出引用 `area.result`。执行时，中间坐标由工具计算并保存在仓库，模型只写引用；评测时再与该题独立SQL核对。

## 8. 运行方式与建议阅读顺序

在 `GIS_Agent` 目录、使用已配置的项目Python环境运行，采用模块方式而不是直接执行文件路径。

以下命令不调用模型：

```powershell
# 20题资料静态检查，不连接数据库。
python -m app_development.test

# 只读验收20题人工计划与独立SQL。
python -m app_development.test --postgis

# 只验收指定题，或查看Agent参数。
python -m app_development.test --postgis --case D09
python -m app_development.agent --help
```

以下命令会调用真实模型，可能产生费用，需明确使用 `--live`：

```powershell
python -m app_development.agent "计算施工一区与施工二区公共边界的长度" --live --toolset advanced
python -m app_development.test --live --case D09 --limit 1
```

单题模型入口默认日志位于 `reports/runs/`；批量评测位于 `reports/runs/dev20/<batch_id>/`。批次协议记录当前四文件实现哈希，不能把修改后的代码或提示词混入旧批次继续统计。

建议先按下面顺序阅读，不必从文件第一行逐段读完：

1. `agent.py`：`MultiStepLLMGISAgent.run()`，先理解主流程。
2. `agent.py`：`ExecutionPlan` → `PlanExecutor.run()` → `ResultStore`，理解计划如何执行。
3. `tool.py`：`ToolSpec` → `get_tool_spec()` → 具体工具方法，理解调用如何落到空间SQL。
4. `db.py`：`get_settings()` 与 `get_connection()`，理解配置和连接。
5. `test.py`：`validate_postgis()` → `assess()` → `run_batch()`，理解验收和模型成绩的区别。

相关资料：[项目总说明](../README.md)、[20题清单](../data/benchmarks/dev20.json)、[人工计划](../data/plans/dev20/)、[独立SQL](../sql/dev20/)。
