"""
TradingAgents-CN Adapter API - FastAPI 应用

提供三个端点：
- GET /health - 健康检查
- POST /analyze - 单股票分析
- POST /debate - 多 agent 辩论分析
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from adapter.db_adapter import DBAdapter, get_db_adapter
from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field


# 配置路径
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/app/config"))
PROMPTS_DIR = CONFIG_DIR / "prompts"


# ===== Pydantic Models =====


class AnalyzeRequest(BaseModel):
    """分析请求"""

    ticker: str = Field(..., description="股票代码，如 000001.SZ 或 AAPL")
    date: Optional[str] = Field(None, description="分析日期 YYYY-MM-DD，默认为当天")
    provider: str = Field("openai", description="LLM 供应商")
    model: str = Field("gpt-4o-mini", description="模型名称")
    api_key: Optional[str] = Field(None, description="API Key")
    base_url: Optional[str] = Field(None, description="API 地址")


class DebateRequest(BaseModel):
    """辩论请求"""

    ticker: str = Field(..., description="股票代码")
    date: Optional[str] = Field(None, description="分析日期")
    provider: str = Field("openai", description="LLM 供应商")
    model: str = Field("gpt-4o-mini", description="模型名称")
    api_key: Optional[str] = Field(None, description="API Key")
    base_url: Optional[str] = Field(None, description="API 地址")
    debate_rounds: int = Field(2, description="辩论轮数", ge=1, le=5)


class TradeSignal(BaseModel):
    """结构化交易信号"""

    action: str = Field(..., description="交易动作: buy/sell/hold")
    ticker: str = Field(..., description="股票代码")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")
    risk_score: float = Field(..., ge=0.0, le=1.0, description="风险评分 0-1")
    target_price: Optional[float] = Field(None, description="目标价")
    stop_loss: Optional[float] = Field(None, description="止损价")
    time_horizon: str = Field("medium", description="时间范围: short/medium/long")
    reasoning_summary: str = Field("", description="决策理由摘要")


class AnalyzeResponse(BaseModel):
    """分析响应"""

    status: str = "success"
    ticker: str
    analysis_date: str
    trade_signal: Optional[TradeSignal] = None
    summary: str = ""
    raw_output: Optional[str] = None


class DebateResponse(BaseModel):
    """辩论响应"""

    status: str = "success"
    ticker: str
    analysis_date: str
    trade_signal: Optional[TradeSignal] = None
    bull_arguments: list[str] = []
    bear_arguments: list[str] = []
    research_manager_decision: str = ""
    risk_manager_decision: str = ""
    trader_decision: str = ""


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str = "ok"
    version: str = "1.0.0"
    timestamp: str = ""


# ===== Prompt Loader =====


def load_prompt(name: str) -> str:
    """从 YAML 文件加载 prompt 模板

    Args:
        name: prompt 名称 (不含 .yaml 后缀)

    Returns:
        prompt 模板字符串
    """
    prompt_path = PROMPTS_DIR / f"{name}.yaml"
    if not prompt_path.exists():
        logger.warning(f"Prompt file not found: {prompt_path}")
        return ""
    with open(prompt_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    template = data.get("template", "") or data.get("system_template", "")
    return template


# ===== LLM Client =====


class SimpleLLMClient:
    """简易 LLM 客户端封装"""

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        from openai import OpenAI

        self.provider = provider
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "")

        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = OpenAI(**client_kwargs)
        logger.info(f"LLM client created: provider={provider}, model={model}")

    def chat(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 4096) -> str:
        """调用 LLM chat completion

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            响应文本
        """
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""


def extract_trade_signal(text: str) -> Optional[TradeSignal]:
    """从 LLM 输出中提取结构化交易信号

    尝试解析 JSON trade_signal 块，否则 fallback 到启发式提取

    Args:
        text: LLM 输出文本

    Returns:
        TradeSignal 或 None
    """
    # 尝试提取 JSON 块
    import re

    json_match = re.search(r"```json\s*({.*?})\s*```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            ts = data.get("trade_signal", data)
            return TradeSignal(
                action=ts.get("action", "hold"),
                ticker=ts.get("ticker", ""),
                confidence=float(ts.get("confidence", 0.5)),
                risk_score=float(ts.get("risk_score", 0.5)),
                target_price=float(ts["target_price"]) if ts.get("target_price") else None,
                stop_loss=float(ts["stop_loss"]) if ts.get("stop_loss") else None,
                time_horizon=ts.get("time_horizon", "medium"),
                reasoning_summary=ts.get("reasoning_summary", ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse trade_signal JSON: {e}")

    # Fallback: 启发式提取
    action = "hold"
    if "买入" in text or "**买入**" in text:
        action = "buy"
    elif "卖出" in text or "**卖出**" in text:
        action = "sell"

    return TradeSignal(
        action=action,
        ticker="",
        confidence=0.5,
        risk_score=0.5,
        reasoning_summary=text[:200] if text else "",
    )


# ===== Analysis Engine =====


class AnalysisEngine:
    """分析引擎 - 协调 LLM 调用和数据处理"""

    def __init__(self, db: Optional[DBAdapter] = None):
        self.db = db or get_db_adapter()

    async def analyze(self, req: AnalyzeRequest) -> AnalyzeResponse:
        """执行单股票分析

        流程: 加载 prompt -> 获取数据 -> LLM 分析 -> 提取交易信号
        """
        ticker = req.ticker.upper()
        analysis_date = req.date or datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Starting analysis for {ticker} on {analysis_date}")

        # 创建 LLM 客户端
        llm = SimpleLLMClient(
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
            base_url=req.base_url,
        )

        # 加载 prompts
        trader_prompt = load_prompt("trader")
        fundamentals_prompt = load_prompt("fundamentals_analyst")

        # 尝试从 PG 获取数据
        try:
            stock_data = await self.db.fetch_stock_data(
                ticker, "2024-01-01", analysis_date, limit=60
            )
            latest_price = await self.db.fetch_latest_price(ticker)
            price_str = f"${latest_price:.2f}" if latest_price else "N/A"
            logger.info(f"Fetched {len(stock_data)} rows for {ticker}, latest price: {price_str}")
        except Exception as e:
            logger.warning(f"DB fetch failed, using fallback: {e}")
            stock_data = []
            latest_price = None
            price_str = "N/A"

        # 构建市场上下文
        market_context = f"股票代码: {ticker}\n当前价格: {price_str}\n分析日期: {analysis_date}\n"

        # 调用 LLM 进行分析
        messages = [
            {
                "role": "system",
                "content": trader_prompt.format(
                    company_name=ticker,
                    currency="人民币",
                    currency_symbol="¥",
                    instrument_context=market_context,
                    past_memory_str="暂无历史记忆",
                    ticker=ticker,
                )
                if trader_prompt
                else "你是一位专业交易员，请分析以下股票并给出交易建议。",
            },
            {
                "role": "user",
                "content": f"请分析股票 {ticker} 在 {analysis_date} 的交易机会。给出明确的买卖持有建议和结构化 trade_signal。",
            },
        ]

        raw_output = llm.chat(messages)
        trade_signal = extract_trade_signal(raw_output)
        if trade_signal:
            trade_signal.ticker = ticker

        logger.info(
            f"Analysis complete for {ticker}: action={trade_signal.action if trade_signal else 'N/A'}"
        )

        return AnalyzeResponse(
            ticker=ticker,
            analysis_date=analysis_date,
            trade_signal=trade_signal,
            summary=trade_signal.reasoning_summary if trade_signal else raw_output[:500],
            raw_output=raw_output,
        )

    async def debate(self, req: DebateRequest) -> DebateResponse:
        """执行多 Agent 辩论分析

        流程: 多轮辩论 -> 研究经理决策 -> 风险辩论 -> 交易员决策
        """
        ticker = req.ticker.upper()
        analysis_date = req.date or datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Starting debate for {ticker} on {analysis_date}, rounds={req.debate_rounds}")

        llm = SimpleLLMClient(
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
            base_url=req.base_url,
        )

        # 加载 prompts
        bull_prompt = load_prompt("bull_researcher")
        bear_prompt = load_prompt("bear_researcher")
        research_mgr_prompt = load_prompt("research_manager")
        risk_safe_prompt = load_prompt("risk_safe")
        risk_neutral_prompt = load_prompt("risk_neutral")
        risk_risky_prompt = load_prompt("risk_risky")
        risk_judge_prompt = load_prompt("risk_judge")
        trader_prompt = load_prompt("trader")

        market_context = f"股票代码: {ticker}\n分析日期: {analysis_date}\n"

        # Phase 1: 看涨 vs 看跌辩论
        bull_args = []
        bear_args = []
        history = ""
        current_response = ""

        for round_idx in range(req.debate_rounds):
            # 看涨发言
            bull_msg = (
                bull_prompt.format(
                    company_name=ticker,
                    ticker=ticker,
                    market_type="A股",
                    currency="人民币",
                    currency_symbol="¥",
                    market_research_report="市场报告（模拟）",
                    sentiment_report="情绪报告（模拟）",
                    news_report="新闻报告（模拟）",
                    fundamentals_report="基本面报告（模拟）",
                    history=history,
                    current_response=current_response,
                    past_memory_str="",
                )
                if bull_prompt
                else f"请对 {ticker} 提出看涨观点。"
            )
            response = llm.chat([{"role": "user", "content": bull_msg}])
            bull_args.append(response)
            history += f"\n看涨分析师: {response}"
            current_response = response

            # 看跌发言
            bear_msg = (
                bear_prompt.format(
                    company_name=ticker,
                    ticker=ticker,
                    market_type="A股",
                    currency="人民币",
                    currency_symbol="¥",
                    market_research_report="市场报告（模拟）",
                    sentiment_report="情绪报告（模拟）",
                    news_report="新闻报告（模拟）",
                    fundamentals_report="基本面报告（模拟）",
                    history=history,
                    current_response=current_response,
                    past_memory_str="",
                )
                if bear_prompt
                else f"请对 {ticker} 提出看跌观点。"
            )
            response = llm.chat([{"role": "user", "content": bear_msg}])
            bear_args.append(response)
            history += f"\n看跌分析师: {response}"
            current_response = response

        # Phase 2: 研究经理决策
        mgr_msg = (
            research_mgr_prompt.format(
                past_memory_str="",
                instrument_context=market_context,
                market_research_report="市场报告（模拟）",
                sentiment_report="情绪报告（模拟）",
                news_report="新闻报告（模拟）",
                fundamentals_report="基本面报告（模拟）",
                history=history,
            )
            if research_mgr_prompt
            else f"请根据以上辩论对 {ticker} 做出投资决策。"
        )
        research_mgr_decision = llm.chat([{"role": "user", "content": mgr_msg}])

        # Phase 3: 风险管理辩论
        risk_history = ""
        risk_current_responses = {"safe": "", "neutral": "", "risky": ""}

        for round_idx in range(req.debate_rounds):
            # 保守分析师
            safe_msg = (
                risk_safe_prompt.format(
                    trader_decision=research_mgr_decision,
                    market_research_report="市场报告（模拟）",
                    sentiment_report="情绪报告（模拟）",
                    news_report="新闻报告（模拟）",
                    fundamentals_report="基本面报告（模拟）",
                    history=risk_history,
                    current_risky_response=risk_current_responses["risky"],
                    current_neutral_response=risk_current_responses["neutral"],
                )
                if risk_safe_prompt
                else f"请从保守角度分析 {ticker}。"
            )
            response = llm.chat([{"role": "user", "content": safe_msg}])
            risk_current_responses["safe"] = response
            risk_history += f"\n保守分析师: {response}"

            # 中性分析师
            neutral_msg = (
                risk_neutral_prompt.format(
                    trader_decision=research_mgr_decision,
                    market_research_report="市场报告（模拟）",
                    sentiment_report="情绪报告（模拟）",
                    news_report="新闻报告（模拟）",
                    fundamentals_report="基本面报告（模拟）",
                    history=risk_history,
                    current_risky_response=risk_current_responses["risky"],
                    current_safe_response=risk_current_responses["safe"],
                )
                if risk_neutral_prompt
                else f"请从中性角度分析 {ticker}。"
            )
            response = llm.chat([{"role": "user", "content": neutral_msg}])
            risk_current_responses["neutral"] = response
            risk_history += f"\n中性分析师: {response}"

            # 激进分析师
            risky_msg = (
                risk_risky_prompt.format(
                    trader_decision=research_mgr_decision,
                    market_research_report="市场报告（模拟）",
                    sentiment_report="情绪报告（模拟）",
                    news_report="新闻报告（模拟）",
                    fundamentals_report="基本面报告（模拟）",
                    history=risk_history,
                    current_safe_response=risk_current_responses["safe"],
                    current_neutral_response=risk_current_responses["neutral"],
                )
                if risk_risky_prompt
                else f"请从激进角度分析 {ticker}。"
            )
            response = llm.chat([{"role": "user", "content": risky_msg}])
            risk_current_responses["risky"] = response
            risk_history += f"\n激进分析师: {response}"

        # Phase 4: 风控主席决策
        judge_msg = (
            risk_judge_prompt.format(
                trader_plan=research_mgr_decision,
                past_memory_str="",
                instrument_context=market_context,
                history=risk_history,
            )
            if risk_judge_prompt
            else f"请根据风险辩论对 {ticker} 做出最终决策。"
        )
        risk_judge_decision = llm.chat([{"role": "user", "content": judge_msg}])

        # Phase 5: 交易员最终决策
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
        trader_final = llm.chat([{"role": "user", "content": trader_msg}])

        trade_signal = extract_trade_signal(trader_final)
        if trade_signal:
            trade_signal.ticker = ticker

        logger.info(
            f"Debate complete for {ticker}: {len(bull_args)} bull rounds, {len(bear_args)} bear rounds"
        )

        return DebateResponse(
            ticker=ticker,
            analysis_date=analysis_date,
            trade_signal=trade_signal,
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            research_manager_decision=research_mgr_decision,
            risk_manager_decision=risk_judge_decision,
            trader_decision=trader_final,
        )


# ===== FastAPI App =====
engine: Optional[AnalysisEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global engine
    logger.info("Starting TradingAgents Adapter API...")
    engine = AnalysisEngine()
    try:
        await engine.db.connect()
        logger.info("Database connection established")
    except Exception as e:
        logger.warning(f"Database connection failed (non-fatal): {e}")
    yield
    logger.info("Shutting down TradingAgents Adapter API...")
    if engine:
        await engine.db.disconnect()


app = FastAPI(
    title="TradingAgents-CN Adapter API",
    description="TradingAgents 适配器 API - AI 驱动的股票分析系统",
    version="1.0.0",
    lifespan=lifespan,
)


# ===== API Endpoints =====


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查端点"""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        timestamp=datetime.now().isoformat(),
    )


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """单股票分析端点

    对一个股票进行 AI 分析，返回交易信号和分析摘要。
    """
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        result = await engine.analyze(req)
        return result
    except Exception as e:
        logger.error(f"Analysis failed for {req.ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/debate", response_model=DebateResponse)
async def debate(req: DebateRequest):
    """多 Agent 辩论分析端点

    启动多轮看涨/看跌辩论，经研究经理和风险管理后，由交易员做出最终决策。
    """
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        result = await engine.debate(req)
        return result
    except Exception as e:
        logger.error(f"Debate failed for {req.ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
