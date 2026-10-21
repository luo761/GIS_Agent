"""配置、SQL 标识符与数据库连接；由原有模块顺序合并，仅调整导入和 .env 定位。"""
from __future__ import annotations

# ===== 来源：app/config/settings.py =====

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables.

    第一阶段只依赖标准库读取环境变量，避免为了配置引入额外复杂度。
    """

    database_url: str
    app_schema: str
    llm_api_key: str | None
    llm_model: str
    overpass_api_url: str
    trusted_geojson_urls: tuple[str, ...]


def _load_dotenv() -> None:
    """Load simple KEY=VALUE lines from project .env if they are not already set."""

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_settings() -> Settings:
    _load_dotenv()
    trusted_urls = os.getenv("TRUSTED_GEOJSON_URLS", "")
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://gis_user:123456@localhost:5432/gis_agent",
        ),
        app_schema=os.getenv("APP_SCHEMA", "gis_lab"),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
        overpass_api_url=os.getenv(
            "OVERPASS_API_URL",
            "https://overpass-api.de/api/interpreter",
        ),
        trusted_geojson_urls=tuple(
            item.strip() for item in trusted_urls.split(",") if item.strip()
        ),
    )


# ===== 来源：app/db/identifiers.py =====

import re


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_identifier(identifier: str) -> str:
    """Validate and quote a PostgreSQL identifier.

    Tool 层后续会用白名单校验表名和字段名；这里先提供基础防线，
    防止把任意文本拼进 SQL 标识符位置。
    """

    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"非法 SQL 标识符: {identifier}")
    return f'"{identifier}"'


# ===== 来源：app/db/connection.py =====

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row



@contextmanager
def get_connection(database_url: str | None = None) -> Iterator[Connection]:
    """Open a psycopg connection with dict rows."""

    url = database_url or get_settings().database_url
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn

