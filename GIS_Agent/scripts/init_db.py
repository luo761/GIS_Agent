from __future__ import annotations

import argparse
from pathlib import Path

import psycopg

from app.config.settings import get_settings


ROOT = Path(__file__).resolve().parents[1]
SQL_FILES = [
    ROOT / "sql" / "001_extensions_and_schema.sql",
    ROOT / "sql" / "002_seed_mock_data.sql",
]


def run_sql_file(conn: psycopg.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize PostGIS lab database.")
    parser.add_argument(
        "--database-url",
        default=get_settings().database_url,
        help="PostgreSQL connection URL. Defaults to DATABASE_URL.",
    )
    args = parser.parse_args()

    with psycopg.connect(args.database_url) as conn:
        for sql_file in SQL_FILES:
            run_sql_file(conn, sql_file)
        conn.commit()

    print("PostGIS lab schema and mock data initialized.")


if __name__ == "__main__":
    main()
