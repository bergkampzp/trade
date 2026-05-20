"""
数据库适配器 - 从量研 PostgreSQL 读取数据
"""

import os
from datetime import date
from typing import Optional

import asyncpg
from loguru import logger
from pydantic import BaseModel


class StockDataRow(BaseModel):
    """股票数据行"""

    symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = None


class DBConfig(BaseModel):
    """数据库配置"""

    host: str = "localhost"
    port: int = 5432
    database: str = "warehouse"
    user: str = "postgres"
    password: str = "postgres"
    schema: str = "quant_raw_cn"


def get_db_config() -> DBConfig:
    """从环境变量获取数据库配置"""
    return DBConfig(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        database=os.getenv("PG_DATABASE", "quant_research"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", "postgres"),
        schema=os.getenv("PG_SCHEMA", "public"),
    )


class DBAdapter:
    """PostgreSQL 数据库适配器"""

    def __init__(self, config: Optional[DBConfig] = None):
        self.config = config or get_db_config()
        self._pool: Optional[asyncpg.Pool] = None
        logger.info(f"DBAdapter initialized with host={self.config.host}:{self.config.port}")

    async def connect(self) -> None:
        """建立数据库连接池"""
        if self._pool is not None:
            return
        try:
            self._pool = await asyncpg.create_pool(
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
                user=self.config.user,
                password=self.config.password,
                min_size=1,
                max_size=5,
            )
            logger.info(f"Connected to PostgreSQL at {self.config.host}:{self.config.port}")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    async def disconnect(self) -> None:
        """关闭数据库连接"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Disconnected from PostgreSQL")

    async def fetch_stock_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        limit: int = 100,
    ) -> list[StockDataRow]:
        """获取股票历史数据

        Args:
            symbol: 股票代码
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            limit: 最大返回行数

        Returns:
            股票数据行列表
        """
        await self.connect()
        table = f"{self.config.schema}.akshare_daily"

        query = f"""
            SELECT stock_code, trade_date, open, high, low, close, volume, amount
            FROM {table}
            WHERE stock_code = $1 AND trade_date >= $2 AND trade_date <= $3
            ORDER BY trade_date DESC
            LIMIT $4
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, start_date, end_date, limit)

        return [
            StockDataRow(
                symbol=row["stock_code"],
                trade_date=row["trade_date"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                amount=float(row["amount"]) if row["amount"] else None,
            )
            for row in rows
        ]

    async def fetch_fundamentals(
        self,
        symbol: str,
    ) -> dict:
        """获取股票基本面数据

        Args:
            symbol: 股票代码

        Returns:
            基本面数据字典
        """
        await self.connect()
        table = f"{self.config.schema}.fundamentals_snapshot"

        query = f"""
            SELECT *
            FROM {table}
            WHERE stock_code = $1
            ORDER BY report_date DESC
            LIMIT 1
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, symbol)

        if not row:
            logger.warning(f"No fundamentals found for {symbol}")
            return {}

        return dict(row)

    async def fetch_latest_price(self, symbol: str) -> Optional[float]:
        """获取股票最新价格

        Args:
            symbol: 股票代码

        Returns:
            最新收盘价
        """
        await self.connect()
        table = f"{self.config.schema}.akshare_daily"

        query = f"""
            SELECT close
            FROM {table}
            WHERE stock_code = $1
            ORDER BY trade_date DESC
            LIMIT 1
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, symbol)

        if row:
            return float(row["close"])
        return None


# 单例
_db_adapter: Optional[DBAdapter] = None


def get_db_adapter() -> DBAdapter:
    """获取全局 DBAdapter 单例"""
    global _db_adapter
    if _db_adapter is None:
        _db_adapter = DBAdapter()
    return _db_adapter
