from __future__ import annotations

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
