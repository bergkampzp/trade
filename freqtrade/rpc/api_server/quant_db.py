"""PostgreSQL connection pool for the Quant Dashboard API."""

from __future__ import annotations

import logging
import re
from typing import Any

import psycopg2
import psycopg2.pool


logger = logging.getLogger(__name__)

_DSN_PASSWORD_RE = re.compile(r"(password\s*=\s*)\S+", re.IGNORECASE)
_URI_PASSWORD_RE = re.compile(r"://([^:]+):[^@]+@")


def _redact_dsn(dsn: str) -> str:
    """Remove password from DSN for safe logging."""
    dsn = _DSN_PASSWORD_RE.sub(r"\1***", dsn)
    dsn = _URI_PASSWORD_RE.sub(r"://\1:***@", dsn)
    return dsn


class QuantDB:
    """Thin wrapper around a psycopg2 ThreadedConnectionPool."""

    def __init__(self, dsn: str, minconn: int = 1, maxconn: int = 4) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn)
        logger.info("QuantDB: connection pool created (%s)", _redact_dsn(dsn))

    def query_rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a query and return rows as list of dicts. Handles both SELECT and UPDATE/INSERT."""
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                # UPDATE/INSERT have no description, only SELECT does
                if cur.description is None:
                    conn.commit()
                    return []
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        self._pool.closeall()
