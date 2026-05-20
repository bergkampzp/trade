"""v4.0 AI 辩论分析模块 — A 股辩论 + 数据 API."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, Field

from freqtrade.rpc.api_server.deps import get_quant_db
from freqtrade.rpc.api_server.quant_db import QuantDB


logger = logging.getLogger(__name__)

router = APIRouter(tags=["debate"])

# 外部化 Prompts 路径
PROMPTS_DIR = (
    Path(__file__).resolve().parents[3] / "docker" / "tradingagents" / "config" / "prompts"
)
# fallback: 本地目录
if not PROMPTS_DIR.exists():
    PROMPTS_DIR = Path(__file__).resolve().parent / "debate_prompts"
    PROMPTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class DebateRequest(BaseModel):
    ticker: str = Field(..., description="A 股代码，如 000001")
    date: Optional[str] = Field(None, description="分析日期 YYYY-MM-DD")
    provider: str = Field("deepseek", description="LLM 供应商")
    model: str = Field("deepseek-chat", description="模型名称")
    debate_rounds: int = Field(2, ge=1, le=5, description="辩论轮数")


class TradeSignal(BaseModel):
    action: str = Field(..., description="buy/sell/hold")
    ticker: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    risk_score: float = Field(0.5, ge=0.0, le=1.0)
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    time_horizon: str = "medium"
    reasoning_summary: str = ""


class DebateStep(BaseModel):
    """辩论推理过程的一步"""

    phase: str = Field(..., description="阶段: bull/bear/manager/trader/risk")
    round: int = Field(0, description="辩论轮次")
    agent_name: str = Field(..., description="Agent 名称")
    input_context: str = Field("", description="Agent 看到的输入数据")
    key_data_points: list[str] = Field(default_factory=list, description="引用的关键数据")
    output: str = Field("", description="Agent 的输出")
    summary: str = Field("", description="输出摘要（前200字）")


class DebateResponse(BaseModel):
    status: str = "success"
    ticker: str
    analysis_date: str
    stock_name: str = ""
    latest_price: Optional[float] = None
    input_market_data: str = Field("", description="输入给所有 Agent 的市场数据摘要")
    trade_signal: Optional[TradeSignal] = None
    bull_arguments: list[str] = []
    bear_arguments: list[str] = []
    research_manager_decision: str = ""
    risk_manager_decision: str = ""
    trader_decision: str = ""
    process_log: list[DebateStep] = Field(default_factory=list, description="完整推理过程链")


# A 股数据模型
class CnStockItem(BaseModel):
    stock_code: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    change_pct: Optional[float] = None


class CnStockListResponse(BaseModel):
    stocks: list[dict]


class CnKlineResponse(BaseModel):
    stock_code: str
    data: list[CnStockItem]


# ---------------------------------------------------------------------------
# Prompt 加载器
# ---------------------------------------------------------------------------


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        logger.warning(f"Prompt not found: {path}")
        return ""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("system_prompt", "") or data.get("template", "") or ""


# ---------------------------------------------------------------------------
# LLM 客户端
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """调用 DeepSeek/OpenAI 兼容 API 生成文本。"""
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="LLM API key not configured")

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    import requests

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 4096,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")


def _extract_trade_signal(text: str, ticker: str) -> TradeSignal:
    """从 LLM 输出提取结构化交易信号。"""
    import re

    json_match = re.search(r"```json\s*({.*?})\s*```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            ts = data.get("trade_signal", data)
            return TradeSignal(
                action=ts.get("action", "hold"),
                ticker=ticker,
                confidence=float(ts.get("confidence", 0.5)),
                risk_score=float(ts.get("risk_score", 0.5)),
                target_price=float(ts["target_price"]) if ts.get("target_price") else None,
                stop_loss=float(ts["stop_loss"]) if ts.get("stop_loss") else None,
                time_horizon=ts.get("time_horizon", "medium"),
                reasoning_summary=ts.get("reasoning_summary", ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    # Fallback
    action = "hold"
    if "买入" in text or "**买入**" in text:
        action = "buy"
    elif "卖出" in text or "**卖出**" in text:
        action = "sell"
    return TradeSignal(action=action, ticker=ticker, confidence=0.5, reasoning_summary=text[:200])


# ---------------------------------------------------------------------------
# 核心辩论引擎
# ---------------------------------------------------------------------------


def _run_debate(db: QuantDB | None, req: DebateRequest) -> DebateResponse:
    ticker = req.ticker.strip().zfill(6)
    analysis_date = req.date or datetime.now().strftime("%Y-%m-%d")

    # 1. 从 PG 读取 A 股行情数据
    stock_name = ticker
    latest_price = None
    market_context = f"股票代码: {ticker}\n分析日期: {analysis_date}\n"
    raw_market_data = ""
    key_data_points: list[str] = []

    if db:
        try:
            rows = db.query_rows(
                "SELECT stock_code, trade_date::text, open, high, low, close, volume, change_pct "
                "FROM quant_raw_cn.akshare_daily "
                "WHERE stock_code = %s ORDER BY trade_date DESC LIMIT 60",
                (ticker,),
            )
            if rows:
                latest_price = rows[0]["close"]
                market_context += f"当前价格: ¥{latest_price:.2f}\n"
                market_context += f"最新日期: {rows[0]['trade_date']}\n"
                market_context += f"近60天行情:\n"
                raw_market_data += f"日期,开盘,最高,最低,收盘,成交量,涨跌幅(%)\n"
                for r in rows[:20]:
                    line = (
                        f"  {r['trade_date']} O:{r['open']} H:{r['high']} "
                        f"L:{r['low']} C:{r['close']} V:{r['volume']} "
                        f"Δ:{r.get('change_pct', 0):.2f}%\n"
                    )
                    market_context += line
                    raw_market_data += f"{r['trade_date']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']},{r.get('change_pct', 0)}\n"
                    key_data_points.append(f"{r['trade_date']}: 收盘{r['close']}")

                closes = [r["close"] for r in rows if r.get("close")]
                if len(closes) >= 5:
                    ma5 = sum(closes[:5]) / 5
                    market_context += f"\nMA5(5日均价): {ma5:.2f}\n"
                    key_data_points.append(f"MA5(5日均价): {ma5:.2f}")
                if len(closes) >= 20:
                    ma20 = sum(closes[:20]) / 20
                    market_context += f"MA20(20日均价): {ma20:.2f}\n"
                    market_context += f"趋势判断: 价格在MA20{'之上(偏多)' if closes[0] > ma20 else '之下(偏空)'}\n"
                    key_data_points.append(f"MA20(20日均价): {ma20:.2f}")
                # 涨跌幅统计
                changes = [r.get("change_pct", 0) for r in rows if r.get("change_pct") is not None]
                if changes:
                    avg_change = sum(changes) / len(changes)
                    positive = sum(1 for c in changes if c > 0)
                    negative = sum(1 for c in changes if c < 0)
                    market_context += f"\n近60日涨跌统计:\n"
                    market_context += f"  平均涨跌幅: {avg_change:.2f}%\n"
                    market_context += f"  上涨天数: {positive}, 下跌天数: {negative}\n"
                    key_data_points.append(f"近60日平均涨跌幅: {avg_change:.2f}%")
                    key_data_points.append(f"上涨/下跌天数: {positive}/{negative}")
        except Exception as e:
            logger.warning(f"DB read failed for {ticker}: {e}")

    process_log: list[DebateStep] = []

    # 2. 加载 Prompts
    bull_prompt = load_prompt("bull_researcher")
    bear_prompt = load_prompt("bear_researcher")
    research_mgr_prompt = load_prompt("research_manager")
    trader_prompt = load_prompt("trader")

    # 3. 辩论阶段
    bull_args = []
    bear_args = []
    history = ""
    current_response = ""

    for round_idx in range(req.debate_rounds):
        # 看涨
        msg_bull = (
            bull_prompt.format(
                company_name=ticker,
                ticker=ticker,
                market_type="A股",
                currency="人民币",
                currency_symbol="¥",
                market_research_report=market_context,
                sentiment_report="模拟情绪报告",
                news_report="模拟新闻报告",
                fundamentals_report="模拟基本面报告",
                history=history,
                current_response=current_response,
                past_memory_str="",
            )
            if bull_prompt
            else f"请对 {ticker} 提出看涨观点。当前行情: {market_context}"
        )
        response = _call_llm(msg_bull, temperature=0.3)
        bull_args.append(response)
        history += f"\n看涨分析师: {response}"
        current_response = response
        process_log.append(
            DebateStep(
                phase="bull",
                round=round_idx + 1,
                agent_name="看涨分析师 (Bull Researcher)",
                input_context=market_context,
                key_data_points=key_data_points.copy(),
                output=response,
                summary=response[:300],
            )
        )

        # 看跌
        msg_bear = (
            bear_prompt.format(
                company_name=ticker,
                ticker=ticker,
                market_type="A股",
                currency="人民币",
                currency_symbol="¥",
                market_research_report=market_context,
                sentiment_report="模拟情绪报告",
                news_report="模拟新闻报告",
                fundamentals_report="模拟基本面报告",
                history=history,
                current_response=current_response,
                past_memory_str="",
            )
            if bear_prompt
            else f"请对 {ticker} 提出看跌观点。当前行情: {market_context}"
        )
        response = _call_llm(msg_bear, temperature=0.3)
        bear_args.append(response)
        history += f"\n看跌分析师: {response}"
        current_response = response
        process_log.append(
            DebateStep(
                phase="bear",
                round=round_idx + 1,
                agent_name="看跌分析师 (Bear Researcher)",
                input_context=market_context,
                key_data_points=key_data_points.copy(),
                output=response,
                summary=response[:300],
            )
        )

    # 4. 研究经理裁决
    mgr_msg = (
        research_mgr_prompt.format(
            past_memory_str="",
            instrument_context=market_context,
            market_research_report=market_context,
            sentiment_report="模拟情绪报告",
            news_report="模拟新闻报告",
            fundamentals_report="模拟基本面报告",
            history=history,
        )
        if research_mgr_prompt
        else f"根据以上辩论，对 {ticker} 做出最终投资决策。"
    )
    mgr_decision = _call_llm(mgr_msg, temperature=0.3)
    process_log.append(
        DebateStep(
            phase="manager",
            round=1,
            agent_name="研究经理 (Research Manager)",
            input_context=f"辩论历史:\n{history[:500]}...",
            key_data_points=key_data_points.copy(),
            output=mgr_decision,
            summary=mgr_decision[:300],
        )
    )

    # 5. 交易员最终决策
    trader_msg = (
        trader_prompt.format(
            company_name=ticker,
            ticker=ticker,
            currency="人民币",
            currency_symbol="¥",
            instrument_context=market_context,
            past_memory_str="",
        )
        if trader_prompt
        else f"请对 {ticker} 做出最终交易决策。"
    )
    trader_final = _call_llm(trader_msg, temperature=0.3)
    process_log.append(
        DebateStep(
            phase="trader",
            round=1,
            agent_name="交易员 (Trader)",
            input_context=f"研究经理裁决:\n{mgr_decision[:300]}...\n\n行情数据:\n{market_context[:300]}...",
            key_data_points=key_data_points.copy(),
            output=trader_final,
            summary=trader_final[:300],
        )
    )

    trade_signal = _extract_trade_signal(trader_final, ticker)

    return DebateResponse(
        ticker=ticker,
        analysis_date=analysis_date,
        stock_name=stock_name,
        latest_price=latest_price,
        input_market_data=market_context,
        trade_signal=trade_signal,
        bull_arguments=bull_args,
        bear_arguments=bear_args,
        research_manager_decision=mgr_decision,
        trader_decision=trader_final,
        process_log=process_log,
    )


# ===========================================================================
# A 股数据端点
# ===========================================================================

_CN_STOCKS_SQL = """
    SELECT DISTINCT stock_code FROM quant_raw_cn.akshare_daily
    ORDER BY stock_code
"""

_CN_DAILY_SQL = """
    SELECT stock_code, trade_date::text, open, high, low, close, volume, amount, change_pct
    FROM quant_raw_cn.akshare_daily
    WHERE stock_code = %s
    ORDER BY trade_date DESC
    LIMIT %s
"""

_CN_LATEST_SQL = """
    SELECT stock_code, trade_date::text, open, high, low, close, volume, amount, change_pct
    FROM quant_raw_cn.akshare_daily
    WHERE stock_code = %s
    ORDER BY trade_date DESC
    LIMIT 1
"""

# A股代码→名称映射
_CN_STOCK_NAMES = {
    "000001": "平安银行",
    "000002": "万科A",
    "300750": "宁德时代",
    "600519": "贵州茅台",
    "300152": "安诺其",
}


@router.get("/quant/a-stocks", response_model=CnStockListResponse)
def api_cn_stock_list(db=Depends(get_quant_db)):
    """获取已同步 A 股列表"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    rows = db.query_rows(_CN_STOCKS_SQL)
    stocks = []
    for r in rows:
        code = r["stock_code"]
        stocks.append(
            {
                "stock_code": code,
                "stock_name": _CN_STOCK_NAMES.get(code, code),
            }
        )
    return CnStockListResponse(stocks=stocks)


@router.get("/quant/a-stocks/{stock_code}")
def api_cn_stock_kline(
    stock_code: str, limit: int = Query(60, ge=10, le=500), db=Depends(get_quant_db)
):
    """获取 A 股 K 线数据"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    rows = db.query_rows(_CN_DAILY_SQL, (stock_code.zfill(6), limit))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Stock {stock_code} not found")
    return {
        "stock_code": stock_code,
        "stock_name": _CN_STOCK_NAMES.get(stock_code, stock_code),
        "data": rows,
    }


@router.get("/quant/a-stocks/{stock_code}/latest")
def api_cn_stock_latest(stock_code: str, db=Depends(get_quant_db)):
    """获取 A 股最新行情"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    rows = db.query_rows(_CN_LATEST_SQL, (stock_code.zfill(6),))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Stock {stock_code} not found")
    return rows[0]


# ===========================================================================
# 辩论端点
# ===========================================================================


@router.post("/quant/debate", response_model=DebateResponse)
def api_debate(req: DebateRequest, db=Depends(get_quant_db)):
    """运行多 Agent 辩论分析"""
    return _run_debate(db, req)
