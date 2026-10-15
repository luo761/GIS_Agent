# GIS Agent Lab

面向学习和研究的 GIS Agent + PostGIS 最小可运行系统。项目目标是用 Python、PostgreSQL/PostGIS、LangGraph 和 FastAPI 逐步实现空间分析 Tool、Skill 和 Agent 工作流。

当前已完成阶段一到阶段四的核心内容：工程骨架、PostGIS 初始化、模拟数据、6 个核心空间分析 Tool、最小 LangGraph Agent、真实 LLM 规划对比和 pytest 验证。

## 当前结构

- `app/`：后端应用代码，后续放 API、Agent、Tools、数据源适配器。
- `sql/`：PostGIS 初始化与模拟数据 SQL。
- `scripts/`：初始化和辅助脚本。
- `tests/`：pytest 自动化测试。
- `docs/`：阶段说明和学习文档。
- `GIS_Project/`、`data/mock_city/`、`knowledge/`：已有原型与资料，暂时保留。

## 快速开始

本项目按本机 PostgreSQL/PostGIS 优先配置。先确认本机已有 PostgreSQL 且安装了 PostGIS 扩展。

```powershell
python -m pip install -r requirements.txt
$env:DATABASE_URL="postgresql://gis_user:你的密码@localhost:5432/gis_agent"
python scripts\init_db.py
$env:GIS_AGENT_RUN_DB_TESTS="1"
python -m pytest
```

只运行不依赖数据库的静态测试：

```powershell
python -m pytest tests\test_phase1_static.py tests\test_phase2_tools_static.py tests\test_phase3_agent_static.py
```

## 配置

复制 `.env.example` 为 `.env`，按需修改：

- `DATABASE_URL`：PostgreSQL/PostGIS 连接字符串。
- `APP_SCHEMA`：默认 `gis_lab`。
- `LLM_API_KEY`、`LLM_MODEL`：后续 LangGraph Agent 使用。
- `OVERPASS_API_URL`：OSM Overpass API 地址。
- `TRUSTED_GEOJSON_URLS`：允许导入的可信 GeoJSON URL 白名单。
- `GIS_AGENT_RUN_DB_TESTS`：是否运行本机 PostGIS 集成测试，`1` 表示运行。
- `GIS_AGENT_RUN_LLM_TESTS`：是否运行真实 LLM 集成测试，`1` 表示运行。

不要提交真实 API Key。

## 阶段文档

- [阶段一说明](docs/phase1.md)
- [阶段二说明](docs/phase2.md)
- [阶段三说明](docs/phase3.md)
- [阶段四说明](docs/phase4.md)
