"""PostGIS 工具集的数据库连接与 SQL 标识符处理。"""
from __future__ import annotations

import re

import psycopg

from config import settings


def get_connection(database_url: str | None = None) -> psycopg.Connection:
    """按项目配置创建连接；由调用方的 with 语句关闭连接。"""
    return psycopg.connect(database_url or settings.DATABASE_URL)


def quote_identifier(identifier: str) -> str:
    """校验单个表/字段标识符并加引号；具体查询值仍通过参数绑定。"""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise ValueError(f"非法 SQL 标识符: {identifier}")
    return f'"{identifier}"'
