"""Test helpers for Quant Dashboard API tests."""

from unittest.mock import MagicMock

from freqtrade.rpc.api_server.quant_db import QuantDB


def make_mock_db(
    description: list[tuple] | None = None,
    rows: list[tuple] | None = None,
) -> QuantDB:
    """Create a QuantDB with a mocked connection pool."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cursor.description = description or []
    mock_cursor.fetchall.return_value = rows or []

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn

    db = QuantDB.__new__(QuantDB)
    db._pool = mock_pool
    return db
