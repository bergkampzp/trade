"""
A 股分析模块 - 后端 Proxy 路由

提供以下端点:
- GET  /astock/stocks       - 选股列表
- GET  /astock/stocks/:code - 个股详情
- POST /astock/debate        - 辩论分析（代理到 TradingAgents-CN Docker）
- GET  /astock/portfolio    - 持仓列表
- POST /astock/portfolio    - 添加持仓
- GET  /astock/reports     - 报告列表
"""

import logging
import os
from datetime import datetime
from typing import Optional

import asyncpg
import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel


logger = logging.getLogger("freqtrade.rpc.api_server.astock")

# =============================================================================
# Router
# =============================================================================
bp = APIRouter(prefix="/astock", tags=["AStock"])
router = bp

# =============================================================================
# DB Pool
# =============================================================================
DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/warehouse")


async def get_raw_cn_pool():
    """获取 quant_raw_cn schema 的 DB 连接池"""
    return await asyncpg.create_pool(
        DB_URL,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )


async def get_trade_pool():
    """获取 quant schema 的 DB 连接池（paper_trades 等）"""
    return await asyncpg.create_pool(
        DB_URL,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )


# =============================================================================
# Pydantic Models
# =============================================================================
class DebateRequest(BaseModel):
    stock_code: str
    rounds: int = 2
    llm_model: str = "deepseek-chat"
    risk_profile: str = "moderate"


class DebateResponse(BaseModel):
    signal: str  # BUY / SELL / HOLD
    confidence: float  # 0.0 ~ 1.0
    target_price: Optional[float]
    stop_loss: Optional[float]
    bull_points: list[str]
    bear_points: list[str]
    verdict: str
    risk_level: str  # low / medium / high
    analyst_name: str = "多空辩论引擎 v1.0"


class PortfolioItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    quantity: int
    cost_price: float
    current_price: Optional[float]
    unrealized_pnl: Optional[float]
    unrealized_pct: Optional[float]
    debate_signal: Optional[str]
    added_at: str


class ReportItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    signal: str
    confidence: float
    verdict: str
    created_at: str


# =============================================================================
# Helper: 调用 TradingAgents-CN Docker
# =============================================================================
TACN_HOST = os.getenv("TACN_HOST", "localhost")
TACN_PORT = int(os.getenv("TACN_PORT", "19000"))
TACN_BASE_URL = f"http://{TACN_HOST}:{TACN_PORT}"


async def call_tacn_debate(
    stock_code: str, rounds: int, llm_model: str, risk_profile: str
) -> DebateResponse:
    """
    代理辩论请求到 TradingAgents-CN Docker 容器
    超时: 5 分钟 (5个Agent串行执行可能较慢)
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        try:
            resp = await client.post(
                f"{TACN_BASE_URL}/debate",
                json={
                    "stock_code": stock_code,
                    "rounds": rounds,
                    "llm_model": llm_model,
                    "risk_profile": risk_profile,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return DebateResponse(**data)
        except httpx.TimeoutException:
            logger.error(f"TACN /debate 超时: stock={stock_code}")
            raise HTTPException(status_code=504, detail="辩论分析超时(5分钟)，请稍后重试")
        except httpx.HTTPStatusError as e:
            logger.error(f"TACN /debate HTTP错误: {e.response.status_code} {e.response.text}")
            raise HTTPException(status_code=502, detail=f"辩论引擎错误: {e.response.status_code}")
        except Exception as e:
            logger.error(f"TACN /debate 调用失败: {e}")
            raise HTTPException(status_code=502, detail=f"辩论引擎连接失败: {str(e)}")


# =============================================================================
# Routes
# =============================================================================


# -----------------------------------------------------------------------------
# GET /astock/stocks — 选股列表
# -----------------------------------------------------------------------------
@bp.get("/stocks")
async def list_stocks(
    industry: Optional[str] = None,
    pe_min: Optional[float] = None,
    pe_max: Optional[float] = None,
):
    """
    获取 A 股列表，支持行业/PE筛选
    数据来源: quant_raw_cn.stock_info
    """
    pool = await get_raw_cn_pool()
    async with pool.acquire() as conn:
        # 基础查询：获取股票基本信息
        query = """
            SELECT
                stock_code    AS code,
                stock_name    AS name,
                industry,
                pe_ttm,
                pb,
                total_market_cap AS market_cap
            FROM quant_raw_cn.stock_info
            WHERE 1=1
        """
        params = []
        if industry:
            query += " AND industry = $${len(params)+1}$$"
            params.append(industry)
        if pe_min is not None:
            query += f" AND pe_ttm >= $${len(params) + 1}$$"
            params.append(pe_min)
        if pe_max is not None:
            query += f" AND pe_ttm <= $${len(params) + 1}$$"
            params.append(pe_max)

        query += " ORDER BY stock_code"

        rows = await conn.fetch(query, *params)

        # 获取最新行情 (从 akshare_daily)
        result = []
        for r in rows:
            latest = await conn.fetchrow(
                """
                SELECT close AS price, change_pct
                FROM quant_raw_cn.akshare_daily
                WHERE stock_code = $1
                ORDER BY trade_date DESC
                LIMIT 1
            """,
                r["code"],
            )

            result.append(
                {
                    "code": r["code"],
                    "name": r["name"],
                    "industry": r["industry"] or "未知",
                    "pe": r["pe_ttm"],
                    "pb": r["pb"],
                    "market_cap": r["market_cap"],
                    "price": latest["price"] if latest else None,
                    "change_pct": latest["change_pct"] if latest else None,
                }
            )

        await pool.close()
        return {"stocks": result, "total": len(result)}


# -----------------------------------------------------------------------------
# GET /astock/stocks/{code} — 个股详情
# -----------------------------------------------------------------------------
@bp.get("/stocks/{code}")
async def stock_detail(code: str):
    """
    获取单只股票的详细信息
    - 基本信息: quant_raw_cn.stock_info
    - 日线数据: quant_raw_cn.akshare_daily (最近 N 条)
    - 基本面: quant_raw_cn.fundamentals_snapshot (如有)
    """
    pool = await get_raw_cn_pool()
    async with pool.acquire() as conn:
        # 基本信息
        info = await conn.fetchrow(
            """
            SELECT stock_code AS code, stock_name AS name, industry,
                   pe_ttm, pb, roe, revenue_growth, profit_growth,
                   total_market_cap AS market_cap, float_market_cap
            FROM quant_raw_cn.stock_info
            WHERE stock_code = $1
        """,
            code,
        )

        if not info:
            await pool.close()
            raise HTTPException(status_code=404, detail=f"股票 {code} 未找到")

        # 最新行情
        latest = await conn.fetchrow(
            """
            SELECT trade_date, open, high, low, close,
                   volume, amount, change_pct
            FROM quant_raw_cn.akshare_daily
            WHERE stock_code = $1
            ORDER BY trade_date DESC
            LIMIT 1
        """,
            code,
        )

        # 最近 60 天日线
        daily_rows = await conn.fetch(
            """
            SELECT trade_date, open, high, low, close,
                   volume, amount, change_pct
            FROM quant_raw_cn.akshare_daily
            WHERE stock_code = $1
            ORDER BY trade_date DESC
            LIMIT 60
        """,
            code,
        )

        # 基本面 (最新一期)
        fund = await conn.fetchrow(
            """
            SELECT report_date, pe_ttm, pb, roe,
                   revenue_yoy, net_profit_yoy, gross_margin
            FROM quant_raw_cn.fundamentals_snapshot
            WHERE stock_code = $1
            ORDER BY report_date DESC
            LIMIT 1
        """,
            code,
        )

        await pool.close()

        return {
            "code": info["code"],
            "name": info["name"],
            "industry": info["industry"] or "未知",
            "pe": info["pe_ttm"],
            "pb": info["pb"],
            "roe": info["roe"],
            "revenue_growth": info["revenue_growth"],
            "profit_growth": info["profit_growth"],
            "market_cap": info["market_cap"],
            "float_market_cap": info["float_market_cap"],
            "latest": {
                "date": str(latest["trade_date"]) if latest else None,
                "open": float(latest["open"]) if latest else None,
                "high": float(latest["high"]) if latest else None,
                "low": float(latest["low"]) if latest else None,
                "close": float(latest["close"]) if latest else None,
                "volume": int(latest["volume"]) if latest else None,
                "change_pct": float(latest["change_pct"]) if latest else None,
            }
            if latest
            else None,
            "daily": [
                {
                    "date": str(r["trade_date"]),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": int(r["volume"]),
                    "change_pct": float(r["change_pct"]),
                }
                for r in reversed(daily_rows)  # 从旧到新排序
            ],
            "fundamentals": {
                "report_date": str(fund["report_date"]) if fund else None,
                "pe_ttm": float(fund["pe_ttm"]) if fund else None,
                "pb": float(fund["pb"]) if fund else None,
                "roe": float(fund["roe"]) if fund else None,
                "revenue_yoy": float(fund["revenue_yoy"]) if fund else None,
                "net_profit_yoy": float(fund["net_profit_yoy"]) if fund else None,
                "gross_margin": float(fund["gross_margin"]) if fund else None,
            }
            if fund
            else None,
        }


# -----------------------------------------------------------------------------
# POST /astock/debate — 辩论分析
# -----------------------------------------------------------------------------
@bp.post("/debate", response_model=DebateResponse)
async def debate_analysis(body: DebateRequest, background_tasks: BackgroundTasks):
    """
    代理辩论请求到 TradingAgents-CN Docker 容器
    返回结构化信号: BUY/SELL/HOLD + 置信度 + 目标价 + 止损
    """
    logger.info(
        f"辩论分析请求: stock={body.stock_code} rounds={body.rounds} model={body.llm_model}"
    )

    result = await call_tacn_debate(
        stock_code=body.stock_code,
        rounds=body.rounds,
        llm_model=body.llm_model,
        risk_profile=body.risk_profile,
    )

    # 后置：写入报告记录（异步，不阻塞返回）
    background_tasks.add_task(
        save_debate_report,
        stock_code=body.stock_code,
        signal=result.signal,
        confidence=result.confidence,
        verdict=result.verdict,
    )

    return result


async def save_debate_report(stock_code: str, signal: str, confidence: float, verdict: str):
    """后台任务：将辩论结果写入 daily_reports 表"""
    try:
        trade_pool = await get_trade_pool()
        async with trade_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO quant.daily_reports
                    (report_date, report_type, stock_code, signal,
                     confidence, summary, created_at)
                VALUES (CURRENT_DATE, 'debate', $1, $2, $3, $4, NOW())
            """,
                stock_code,
                signal,
                confidence,
                verdict,
            )
        await trade_pool.close()
        logger.info(f"辩论报告已存档: {stock_code} {signal} ({confidence:.2f})")
    except Exception as e:
        logger.error(f"保存辩论报告失败: {e}")


# -----------------------------------------------------------------------------
# GET /astock/portfolio — 持仓列表
# -----------------------------------------------------------------------------
@bp.get("/portfolio", response_model=list[PortfolioItem])
async def get_portfolio():
    """
    获取当前虚拟持仓列表
    数据来源: quant.paper_trades
    """
    pool = await get_trade_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, stock_code, stock_name, quantity,
                   cost_price, current_price,
                   unrealized_pnl, unrealized_pct,
                   debate_signal, added_at
            FROM quant.paper_trades
            WHERE status = 'open'
            ORDER BY added_at DESC
        """)
        await pool.close()

        return [
            PortfolioItem(
                id=r["id"],
                stock_code=r["stock_code"],
                stock_name=r["stock_name"] or r["stock_code"],
                quantity=r["quantity"],
                cost_price=float(r["cost_price"]),
                current_price=float(r["current_price"]) if r["current_price"] else None,
                unrealized_pnl=float(r["unrealized_pnl"]) if r["unrealized_pnl"] else None,
                unrealized_pct=float(r["unrealized_pct"]) if r["unrealized_pct"] else None,
                debate_signal=r["debade_signal"] if r["debade_signal"] else None,
                added_at=str(r["added_at"]),
            )
            for r in rows
        ]


# -----------------------------------------------------------------------------
# POST /astock/portfolio — 添加持仓
# -----------------------------------------------------------------------------
class AddPortfolioRequest(BaseModel):
    stock_code: str
    stock_name: str
    quantity: int
    cost_price: float
    debate_signal: Optional[str] = None


@bp.post("/portfolio")
async def add_portfolio(body: AddPortfolioRequest):
    """添加虚拟持仓（模拟买入）"""
    pool = await get_trade_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO quant.paper_trades
                (stock_code, stock_name, quantity, cost_price,
                 current_price, status, debate_signal, added_at)
            VALUES ($1, $2, $3, $4, $4, 'open', $5, NOW())
        """,
            body.stock_code,
            body.stock_name,
            body.quantity,
            body.cost_price,
            body.debate_signal,
        )
        await pool.close()
    return {"ok": True, "stock_code": body.stock_code}


# -----------------------------------------------------------------------------
# GET /astock/reports — 辩论报告列表
# -----------------------------------------------------------------------------
@bp.get("/reports", response_model=list[ReportItem])
async def get_reports(limit: int = 50):
    """获取辩论历史报告"""
    pool = await get_trade_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT id, stock_code,
                   COALESCE(stock_name, stock_code) AS stock_name,
                   signal, confidence, summary, created_at
            FROM quant.daily_reports
            WHERE report_type = 'debate'
            ORDER BY created_at DESC
            LIMIT {limit}
        """)
        await pool.close()
        return [
            ReportItem(
                id=r["id"],
                stock_code=r["stock_code"],
                stock_name=r["stock_name"],
                signal=r["signal"],
                confidence=float(r["confidence"]),
                verdict=r["summary"] or "",
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]
