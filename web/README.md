# GIS 多智能体控制台（Web 前端）

面向本项目「五阶段多智能体任务架构（能力进化版）」的本地 Web 控制台：

- **任务台**：输入口语化 GIS 问题，逐步回放「任务理解 → 精炼拆解 → 能力路由 → DAG 规划 → 工具执行 → 评估进化」完整执行流；可选择用户类别，按表级权限过滤与拦截。
- **能力进化**：雷达图 + 时间轴回放每一次执行后的能力向量变化，支持单步、播放、跳帧、按智能体聚焦、按维度看趋势。
- **执行流历史**：保存每次演示运行的完整轨迹，可随时回放、导出 JSON。
- **技能库**：12 个任务级 skill、10 个 PostGIS 算子，支持关键词过滤与真实余弦检索演示。
- **知识库**：PostGIS 表结构 / 字段 / 样例值、领域知识、表结构检索与上下文注入预览。
- **记忆库**：智能体专属长期记录与短期缓存、共享经验池，可针对某个智能体做相似记忆检索。
- **评测报告**：dev20 基准成绩、逐题路由/工具轨迹/判定结果，并把每题转换成可回放的执行流。
- **安全**：问题不合法即中止执行并给出补充信息清单；系统管理页展示用户权限矩阵与越权审计。

界面不依赖任何 CDN、前端框架或构建步骤，所有图表（雷达、DAG、折线、环形）均为手写 Canvas；后端只使用 Python 标准库。

---

## 快速开始

要求：Python 3.10+（无需 `pip install`）。

```powershell
# 方式一：双击
web\start.bat

# 方式二：命令行
python web\server\app.py --open
# 或指定端口
python web\server\app.py --port 8766 --open
```

浏览器访问 `http://127.0.0.1:8765`。`--open` 会自动打开浏览器；关闭终端即停止服务。

> 直接双击 `web/index.html` 也能浏览（使用 `web/data/snapshot.js` 静态快照），
> 但任务运行、检索演示、重置能力等交互需要本地服务。

服务端零依赖设计：

| 模块 | 作用 |
| --- | --- |
| `server/app.py` | HTTP 服务 + 静态资源 + REST API |
| `server/data_source.py` | 读取项目真实数据、复用项目 TF-IDF 余弦检索 |
| `server/demo_engine.py` | 五阶段执行流演示引擎、能力路由与进化 |
| `server/yaml_lite.py` | 零依赖 YAML 子集解析（读取项目 config） |
| `data/snapshot.js` | 自动生成的静态快照（服务启动时刷新） |

---

## 页面与交互

| 路由 | 页面 | 主要交互 |
| --- | --- | --- |
| `#/overview` | 总览 | 能力雷达、KPIs、智能体分化、最近进化、最新评测、最近运行 |
| `#/workbench` | 任务台 | 提问、参考答案、判定方式、用户类别（数据权限）、记忆写入位置（演示/真实）、五阶段播放/单步/全部展开、复制答案、导出运行 |
| `#/history` | 执行流 | 运行列表、搜索、详情回放、清空记录 |
| `#/capability` | 能力进化 | 时间轴回放、智能体聚焦、维度趋势、能力矩阵、同步真实快照 / 重置所有智能体 |
| `#/skills` | 技能库 | 分组筛选、搜索、skill 详情、余弦检索演示、算子目录 |
| `#/knowledge` | 知识库 | 表结构折叠、字段搜索、检索演示、上下文预览/复制、领域知识 |
| `#/memory` | 记忆库 | 真实/演示记忆切换、智能体切换、记录详情与单条删除、缓存步骤单条删除、记忆检索、共享经验池 |
| `#/benchmark` | 评测报告 | 报告切换、难度/结果筛选、逐题详情、执行流回放 |
| `#/admin` | 系统管理 | 真实能力向量重置、`tie_epsilon` 管理、用户权限矩阵与审计、智能体长期记录/短期缓存清空与删除 |

便捷链接（可分享给他人）：

```
#/workbench?q=<URL 编码的问题>&autorun=1          # 自动执行
#/workbench?q=<问题>&autorun=1&verdict=failure    # 演示失败经验导致能力回落
#/capability?source=real                          # 查看项目真实能力状态（只读）
#/benchmark?case=D01                              # 直接打开某题详情
#/overview?theme=dark                             # 深色主题
```

键盘：

- `Ctrl/⌘ + Enter`：任务台内运行任务
- `Ctrl/⌘ + K`：全局检索（skill / 表 / 记忆）
- `Esc`：关闭抽屉或确认弹窗

---

## 数据来源与安全边界

页面数据全部来自项目本身：

| 数据 | 来源 |
| --- | --- |
| 能力向量 / 进化历史 | `data/agent_capabilities.json` |
| 维度、标签、进化与路由参数 | `config/agents_capability.yaml` |
| 领域分类 / 问题合法性规则 | `config/domains_taxonomy.yaml`（与 `security/question_guard.py` 同源） |
| 用户权限表 | `config/user_permissions.yaml`（与 `security/permissions.py` 同源） |
| skill 库与领域知识 | `knowledge/task_skill_library.py`（用 `ast` 静态读取，不执行模块） |
| 共享经验 | `data/experience.json` |
| 智能体专属记忆 | `data/memory/<agent>/record/*.json`、`cache.json` |
| 基准评测 | `reports/dev20/*.json` |
| 表结构 | 内置示例（字段定义与项目知识库一致；未安装 psycopg 时不再连库） |

**判定规则**：

- 判定方式为「自动」且**未填写参考答案** → 结果按「未判定（未知）」处理：不写入成功/失败经验，能力向量保持不变；
- 判定方式为「自动」且填写了参考答案 → 与答案中的数值比对，匹配为成功、不匹配为失败；
- 手动选择「判成功 / 判失败」→ 直接按该结论产生成功/失败经验，用于演示能力进化。

**问题不合法（阶段① 的安全闸门）**：

- 演示引擎在运行前调用 `security/question_guard.py` 的规则层（与真实流水线同一份实现）：
  空问题、过短、纯空泛动词、越权/破坏性/提示词注入、完全没有 GIS 业务锚点，直接判为不合法；
- 命中后本次运行**不拆解、不规划、不调用任何算子、不修改能力向量**，
  `understand` 标记为 `blocked`，`decompose/plan/execute` 标记为 `skipped`，
  评估阶段返回 `clarification`，页面按「需要用户补充信息」展示澄清文本；
- 追问里列出缺失信息（分析对象 / 空间范围 / 筛选条件 / 输出指标 / 时间口径），
  用户补充后重新提交即可；运行记录可在执行流页面回放。
- 结果区同时渲染「补充信息后重跑」卡片：五个槽位各一个输入框（缺失项标「缺失」、
  其余标「可选」），填写后点「追加说明并重跑」会把
  `（补充说明：分析对象=…；空间范围=…）` 追加到原问题并立即重跑；
  「复制追问」可拿走完整追问文本。

**用户权限（表级增删改查）**：

- 权限表在 `config/user_permissions.yaml`，角色包括 `admin` / `analyst` / `operator` / `viewer`；
- 任务台的「用户类别」决定本次运行的角色，`/api/run` 也会把 `role` 传给演示引擎；
- 阶段① 的表结构检索只返回该角色可查询的表；执行阶段按 `layer_name` 校验，
  越权步骤不执行，返回「权限拒绝」并记录在本次运行的 `permission_denials`；
  真实流水线的越权/写操作会写入 `data/permission_audit.jsonl`，演示会话不写项目数据；
- 示例：以 `viewer` 运行「查询 invalid_geometry_cases 里的所有无效几何」会被拦截，
  执行流中 `execute.status = failed`，`permission_denials` 记录表名、操作与原因。

**记忆容量**：智能体记忆的容量上限（缓存 5 条、长期记录 10 条、注入条数）直接读取
`config/settings.py`。项目只在**写入时**执行 FIFO 裁剪，因此磁盘文件可能保留旧配置下
超过上限的数据；记忆库页面默认按上限展示（并提供「查看全部」），同时标注磁盘实际条数，
不会修改项目 `data/memory`。

**重置所有智能体能力向量**：

- 入口：能力进化页顶部「重置所有智能体」、总览「智能体分化状态」卡片右上角；
- 弹窗会列出每个智能体、每个能力维度的当前值（红色表示高于初始值），确认后把**全部智能体**的
  所有维度恢复为初始值 `0.500`，并清空进化历史、执行统计与工具偏好；
- 可勾选「同时清空演示运行记录」，默认不勾选；
- 只作用于演示会话 `web/data/demo_state.json`，不会改写项目 `data/agent_capabilities.json`。

**演示会话的写入范围**：只写 `web/data/demo_state.json`、`web/data/demo_runs.json`，
不会修改项目 `data/` 下的能力、经验、记忆文件。能力进化页「重置均衡 / 同步真实快照」
也只操作演示副本。

**系统管理页（`#/admin`）**：直接管理项目真实文件，操作均有二次确认：

- 能力向量表：把 `data/agent_capabilities.json` 中全部智能体的所有维度重置为 `0.5`，
  同时清空进化历史、执行统计与工具偏好；
- 路由参数：修改 `config/agents_capability.yaml` 的 `routing.tie_epsilon`，写回时保留原文件注释，
  保存后服务端立即重新读取配置；
- 记忆空间：可在「真实记忆 `data/memory`」与「演示记忆 `web/data/memory`」之间切换，
  对每个智能体的长期记录（`record/`）和短期缓存（`cache.json`）分别执行「清空」（保留目录/文件容器）
  或「删除」（移除目录/文件本身），也可以重置该智能体全部记忆；
  展开「单条长期记录 / 单条短期缓存」后，还可以逐条删除指定记录或缓存步骤。

**关于执行流**：真实链路需要 LLM、LangGraph、PostGIS 与外部工具集。为了让界面在任何
机器上可交互，任务台使用 `server/demo_engine.py` 做本地模拟：

- 表结构 / skill / 经验 / 记忆的检索：**真实调用** `retrieval/cosine_similarity.py`
- 能力路由得分、并列随机抽取、能力进化公式与边界：**严格按项目配置和实现**
- 计划 DAG 与工具参数：按检索到的 skill / 问题语义生成
- 工具返回值与最终答案：模拟值（页面会标注「本地演示引擎」）

因此它适合演示架构与交互，不应被当作真实空间计算结果。接入真实流水线时，只需在
`server/app.py` 中把 `/api/run` 转发给 `pipeline.pipeline_graph.ask`（需在具备项目依赖的
Python 环境运行），前端渲染的数据结构可保持不变。

任务台的「记忆写入」可选演示记忆或真实记忆：演示记忆落到 `web/data/memory`，真实记忆落到
`data/memory`。每次运行都会写短期缓存；只有判定明确（成功/失败）时才写长期记录，自动模式
未填参考答案的「未知」结果不会归档长期记录。

---

## 数据文件与重置

| 文件 | 说明 |
| --- | --- |
| `web/data/demo_state.json` | 演示会话能力向量与进化历史；首次启动从项目真实快照初始化 |
| `web/data/demo_runs.json` | 演示运行记录（最多 40 条） |
| `web/data/snapshot.js` | 静态快照，服务启动时自动生成；也可手动执行 `python web/server/data_source.py` |

重置方式：

- 演示会话：能力进化 → 「同步真实快照」或「重置均衡」；或删除 `web/data/demo_state.json`、`web/data/demo_runs.json` 后重启服务
- 项目真实数据：系统管理 → 重置能力向量 / 清空或删除智能体记忆

---

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务 / 数据库端口 / LLM 配置状态 |
| GET | `/api/bootstrap` | 引导数据（能力、skill、知识、记忆、报告摘要） |
| GET | `/api/capability?source=demo\|real` | 能力快照与历史 |
| POST | `/api/capability/reset` | `{confirm:true, seed:"initial"\|"real", clear_runs}` |
| GET | `/api/admin` | 系统管理页数据：真实能力、`tie_epsilon`、记忆空间 |
| POST | `/api/admin/capability/reset` | `{confirm:true}`，真实能力全部重置为 0.5 |
| POST | `/api/admin/routing` | `{confirm:true, tie_epsilon}`，写回 `agents_capability.yaml` |
| POST | `/api/admin/memory` | `{confirm:true, agent_id, scope:"records"\|"cache"\|"all", mode:"clear"\|"delete", source:"real"\|"demo"}` |
| POST | `/api/admin/memory/record` | `{confirm:true, agent_id, record_id, source:"real"\|"demo"}`，删除单条长期记录 |
| POST | `/api/admin/memory/cache` | `{confirm:true, agent_id, index, source:"real"\|"demo"}`，删除单条短期缓存 |
| POST | `/api/run` | `{question, truth, verdict:"auto"\|"success"\|"failure", memory_target:"demo"\|"real", role:"analyst", user}` |
| POST | `/api/validate` | `{question}`，只跑合法性规则层，返回 `is_valid / reasons / missing_info / clarification` |
| GET | `/api/permissions?role=viewer` | 权限表：角色、操作、表级矩阵、最近审计记录 |
| GET / DELETE | `/api/runs` | 运行列表 / 清空 |
| GET | `/api/runs/<id>` | 单次运行完整数据 |
| POST | `/api/retrieve` | `{query, kind:"skills"\|"tables"\|"experience"\|"memory", agent, source:"real"\|"demo"}` |
| GET | `/api/memory?source=real\|demo` | 指定来源的记忆与共享经验 |
| GET | `/api/skills` | skill 与算子目录 |
| GET | `/api/reports` | 评测报告索引 |
| GET | `/api/reports/<name>` | 单份报告完整结果 |
| GET | `/artifact/capability-chart.html` | 项目自动生成的原始动态能力图 |
| GET | `/artifact/report.md` | dev20 Markdown 报告 |

---

## 目录结构

```
web/
├── index.html                  # 单页应用外壳（图标 sprite / 布局 / 脚本装载）
├── assets/
│   ├── app.css                 # 设计系统、组件、响应式、明暗主题
│   └── js/
│       ├── core.js             # 命名空间、API、主题、Toast、抽屉、全局检索
│       ├── charts.js           # 雷达 / 折线 / 环形 / DAG / 迷你趋势（Canvas）
│       ├── flow.js             # 五阶段执行流渲染 + 播放控制 + 基准适配
│       ├── views/              # 9 个页面视图
│       │   ├── overview.js
│       │   ├── workbench.js
│       │   ├── history.js
│       │   ├── capability.js
│       │   ├── skills.js
│       │   ├── knowledge.js
│       │   ├── memory.js
│       │   ├── benchmark.js
│       │   └── admin.js
│       └── app.js              # hash 路由、导航、主题切换、初始化
├── server/                     # 零依赖本地服务
├── data/                       # 快照与演示运行数据
├── start.bat / start.ps1 / start.sh
└── README.md
```

---

## 定制

- **主题**：`assets/app.css` 顶部的 `:root` / `[data-theme="dark"]` 变量。
- **页面标题与文案**：各 `views/*.js` 的 `title` / `subtitle` / 渲染内容。
- **示例问题**：`server/data_source.py` 的 `bootstrap()` 中 `examples`。
- **模拟策略**：`server/demo_engine.py`（领域/任务类型关键词、过滤条件、DAG 生成）。
- **问题合法性规则**：`config/domains_taxonomy.yaml` 的 `invalid_question` 段；
  规则实现与真实流水线共用 `security/question_guard.py`。
- **用户权限**：`config/user_permissions.yaml`（角色、表级 CRUD、工具→操作映射、审计）；
  逻辑与真实流水线共用 `security/permissions.py`。
- **智能体颜色**：`server/data_source.py` 的 `AGENT_COLORS`（需与前端一致；前端会读取接口返回值）。

修改 `assets/` 下静态资源后刷新页面即可；若浏览器缓存了旧脚本，更新 `index.html` 中
`?v=N` 的版本号（或服务端已对 html/css/js 设置 `no-store`）。
