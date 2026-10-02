from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg.rows import dict_row


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostGISAdapter:
    """PostGIS-backed spatial adapter skeleton.

    This adapter is intentionally not wired into the Agent yet. It documents and
    centralizes the SQL shape that will replace MockGISAdapter after real data
    tables or customer platform views are available.
    """

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    def list_layers(self) -> list[str]:
        sql = """
        SELECT f_table_name
        FROM geometry_columns
        ORDER BY f_table_name;
        """
        return [row["f_table_name"] for row in self._fetch(sql)]

    def hazards_near_pipes(
        self,
        hazard_table: str,
        pipe_table: str,
        distance: float,
        hazard_domain: str | None = None,
        hazard_level: str | None = None,
    ) -> list[dict[str, Any]]:
        where_sql = []
        params: list[Any] = [distance]
        if hazard_domain:
            where_sql.append("h.domain = %s")
            params.append(hazard_domain)
        if hazard_level:
            where_sql.append("h.level = %s")
            params.append(hazard_level)

        where_clause = f"WHERE {' AND '.join(where_sql)}" if where_sql else ""
        hazard_table_sql = self._identifier(hazard_table)
        pipe_table_sql = self._identifier(pipe_table)
        sql = f"""
        SELECT DISTINCT h.*, ST_AsGeoJSON(h.geom)::json AS geometry
        FROM {hazard_table_sql} h
        JOIN {pipe_table_sql} p
          ON ST_DWithin(h.geom, p.geom, %s)
        {where_clause};
        """
        return self._fetch(sql, params)

    def pipe_length_in_area(
        self,
        pipe_table: str,
        area_table: str,
        area_name: str,
        extra_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        where_sql = ["a.name = %s"]
        params: list[Any] = [area_name]
        for field, value in (extra_filters or {}).items():
            where_sql.append(f"p.{self._identifier(field)} = %s")
            params.append(value)

        pipe_table_sql = self._identifier(pipe_table)
        area_table_sql = self._identifier(area_table)
        sql = f"""
        SELECT
            COUNT(*) AS count,
            COALESCE(SUM(ST_Length(ST_Intersection(p.geom, a.geom))), 0) AS total_length
        FROM {pipe_table_sql} p
        JOIN {area_table_sql} a
          ON ST_Intersects(p.geom, a.geom)
        WHERE {' AND '.join(where_sql)};
        """
        rows = self._fetch(sql, params)
        return rows[0] if rows else {"count": 0, "total_length": 0}

    def line_conflicts(
        self,
        line_table_a: str,
        line_table_b: str,
        distance: float,
    ) -> list[dict[str, Any]]:
        line_table_a_sql = self._identifier(line_table_a)
        line_table_b_sql = self._identifier(line_table_b)
        sql = f"""
        SELECT
            a.id AS line_a_id,
            b.id AS line_b_id,
            ST_Distance(a.geom, b.geom) AS distance
        FROM {line_table_a_sql} a
        JOIN {line_table_b_sql} b
          ON ST_DWithin(a.geom, b.geom, %s);
        """
        return self._fetch(sql, [distance])

    def _fetch(self, sql: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
        with psycopg.connect(self.db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, list(params or []))
                rows = cur.fetchall()
        return [self._normalize_row(row) for row in rows]

    @staticmethod
    def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        for key, value in normalized.items():
            if isinstance(value, str) and key.lower() in {"geometry", "geom", "geojson"}:
                try:
                    normalized[key] = json.loads(value)
                except json.JSONDecodeError:
                    pass
        return normalized

    @staticmethod
    def _identifier(value: str) -> str:
        if not _IDENTIFIER_RE.match(value):
            raise ValueError(f"非法 SQL 标识符：{value}")
        return value
