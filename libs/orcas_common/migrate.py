"""Apply the initial idempotent database schema."""

from pathlib import Path

import psycopg

from .config import database_url


def migrate(url: str | None = None) -> None:
    sql = (Path(__file__).parent / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
    with psycopg.connect(url or database_url()) as connection:
        connection.execute(sql)


if __name__ == "__main__":
    migrate()
