from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from app.config.settings import get_settings


@contextmanager
def get_connection(database_url: str | None = None) -> Iterator[Connection]:
    """Open a psycopg connection with dict rows."""

    url = database_url or get_settings().database_url
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn
