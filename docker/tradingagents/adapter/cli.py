#!/usr/bin/env python3
"""
TradingAgents-CN CLI Tool

Usage:
    trading-tool analyze --ticker AAPL
    trading-tool debate --ticker 000001.SZ --rounds 3
    trading-tool health
    trading-tool server --port 8000
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


# 确保能找到 adapter 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from loguru import logger


API_BASE = os.getenv("TRADING_API_BASE", "http://localhost:8000")


def setup_logging():
    """配置日志"""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )


def cmd_health(args):
    """健康检查"""
    url = f"{API_BASE}/health"
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"\n✓ API Status: {data['status']}")
        return 0
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return 1


def cmd_analyze(args):
    """分析股票"""
    url = f"{API_BASE}/analyze"
    payload = {
        "ticker": args.ticker,
        "date": args.date or datetime.now().strftime("%Y-%m-%d"),
        "provider": args.provider,
        "model": args.model,
        "api_key": args.api_key,
        "base_url": args.base_url,
    }

    try:
        logger.info(f"Analyzing {args.ticker}...")
        resp = httpx.post(url, json=payload, timeout=args.timeout)
        resp.raise_for_status()
        data = resp.json()

        # 结构化输出
        if args.json_output:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"\n{'=' * 60}")
            print(f"  股票分析报告: {data['ticker']}")
            print(f"  分析日期: {data['analysis_date']}")
            print(f"{'=' * 60}")

            ts = data.get("trade_signal")
            if ts:
                action_colors = {"buy": "🟢 买入", "sell": "🔴 卖出", "hold": "🟡 持有"}
                action_display = action_colors.get(ts["action"], ts["action"])
                print(f"\n  交易建议: {action_display}")
                print(f"  置信度: {ts['confidence']:.2f}")
                print(f"  风险评分: {ts['risk_score']:.2f}")
                if ts.get("target_price"):
                    print(f"  目标价: {ts['target_price']}")
                if ts.get("stop_loss"):
                    print(f"  止损价: {ts['stop_loss']}")
                if ts.get("reasoning_summary"):
                    print(f"\n  理由: {ts['reasoning_summary']}")

            if args.verbose and data.get("raw_output"):
                print(f"\n{'─' * 60}")
                print("  LLM 原始输出:")
                print(f"{'─' * 60}")
                print(data["raw_output"])

            print(f"\n{'=' * 60}\n")

        logger.info("Analysis complete")
        return 0

    except httpx.HTTPStatusError as e:
        logger.error(f"API error: {e.response.status_code} - {e.response.text}")
        return 1
    except Exception as e:
        logger.error(f"Request failed: {e}")
        return 1


def cmd_debate(args):
    """多 Agent 辩论分析"""
    url = f"{API_BASE}/debate"
    payload = {
        "ticker": args.ticker,
        "date": args.date or datetime.now().strftime("%Y-%m-%d"),
        "provider": args.provider,
        "model": args.model,
        "api_key": args.api_key,
        "base_url": args.base_url,
        "debate_rounds": args.rounds,
    }

    try:
        logger.info(f"Starting debate for {args.ticker} ({args.rounds} rounds)...")
        resp = httpx.post(url, json=payload, timeout=args.timeout)
        resp.raise_for_status()
        data = resp.json()

        if args.json_output:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"\n{'=' * 60}")
            print(f"  多 Agent 辩论分析: {data['ticker']}")
            print(f"  分析日期: {data['analysis_date']}")
            print(f"{'=' * 60}")

            # 看涨观点
            print(f"\n{'─' * 30} 看涨观点 {'─' * 30}")
            for i, arg in enumerate(data.get("bull_arguments", []), 1):
                print(f"\n[第{i}轮]")
                print(arg[:300] + "..." if len(arg) > 300 else arg)

            # 看跌观点
            print(f"\n{'─' * 30} 看跌观点 {'─' * 30}")
            for i, arg in enumerate(data.get("bear_arguments", []), 1):
                print(f"\n[第{i}轮]")
                print(arg[:300] + "..." if len(arg) > 300 else arg)

            # 研究经理决策
            print(f"\n{'─' * 30} 研究经理决策 {'─' * 30}")
            print(data.get("research_manager_decision", "")[:500])

            # 风控主席决策
            print(f"\n{'─' * 30} 风控主席决策 {'─' * 30}")
            print(data.get("risk_manager_decision", "")[:500])

            # 交易员最终决策
            print(f"\n{'─' * 30} 交易员最终决策 {'─' * 30}")
            print(data.get("trader_decision", "")[:500])

            # 交易信号
            ts = data.get("trade_signal")
            if ts:
                print(f"\n{'─' * 30} 交易信号 {'─' * 30}")
                print(json.dumps(ts, indent=2, ensure_ascii=False))

            print(f"\n{'=' * 60}\n")

        logger.info("Debate complete")
        return 0

    except httpx.HTTPStatusError as e:
        logger.error(f"API error: {e.response.status_code} - {e.response.text}")
        return 1
    except Exception as e:
        logger.error(f"Request failed: {e}")
        return 1


def cmd_server(args):
    """启动本地 FastAPI 服务器"""
    import uvicorn

    logger.info(f"Starting TradingAgents API server on port {args.port}...")
    uvicorn.run(
        "adapter.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level.lower(),
    )
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="TradingAgents-CN CLI - AI 驱动的股票分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  trading-tool health                                    # 健康检查
  trading-tool analyze --ticker AAPL                     # 分析美股
  trading-tool analyze --ticker 000001.SZ --json          # 分析A股 (JSON输出)
  trading-tool debate --ticker TSLA --rounds 3            # 多Agent辩论
  trading-tool server --port 8000                         # 启动API服务器
        """,
    )
    parser.add_argument("--api-base", help=f"API base URL (default: {API_BASE})")
    parser.add_argument("--log-level", default="INFO", help="Log level (DEBUG/INFO/WARNING)")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # health 命令
    subparsers.add_parser("health", help="检查 API 健康状态")

    # analyze 命令
    analyze_parser = subparsers.add_parser("analyze", help="单股票分析")
    analyze_parser.add_argument("--ticker", required=True, help="股票代码")
    analyze_parser.add_argument("--date", help="分析日期 (YYYY-MM-DD)")
    analyze_parser.add_argument("--provider", default="openai", help="LLM 供应商")
    analyze_parser.add_argument("--model", default="gpt-4o-mini", help="模型名称")
    analyze_parser.add_argument("--api-key", help="API Key")
    analyze_parser.add_argument("--base-url", help="API 地址")
    analyze_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="JSON 格式输出"
    )
    analyze_parser.add_argument("--verbose", "-v", action="store_true", help="显示完整 LLM 输出")
    analyze_parser.add_argument("--timeout", type=int, default=120, help="请求超时时间（秒）")

    # debate 命令
    debate_parser = subparsers.add_parser("debate", help="多 Agent 辩论分析")
    debate_parser.add_argument("--ticker", required=True, help="股票代码")
    debate_parser.add_argument("--date", help="分析日期 (YYYY-MM-DD)")
    debate_parser.add_argument("--rounds", type=int, default=2, help="辩论轮数 (1-5)")
    debate_parser.add_argument("--provider", default="openai", help="LLM 供应商")
    debate_parser.add_argument("--model", default="gpt-4o-mini", help="模型名称")
    debate_parser.add_argument("--api-key", help="API Key")
    debate_parser.add_argument("--base-url", help="API 地址")
    debate_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="JSON 格式输出"
    )
    debate_parser.add_argument("--timeout", type=int, default=300, help="请求超时时间（秒）")

    # server 命令
    server_parser = subparsers.add_parser("server", help="启动本地 API 服务器")
    server_parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    server_parser.add_argument("--port", type=int, default=8000, help="监听端口")
    server_parser.add_argument("--reload", action="store_true", help="热重载（开发模式）")

    args = parser.parse_args()
    setup_logging()

    # 设置 API base
    global API_BASE
    if args.api_base:
        API_BASE = args.api_base

    # 路由命令
    command_map = {
        "health": cmd_health,
        "analyze": cmd_analyze,
        "debate": cmd_debate,
        "server": cmd_server,
    }

    if args.command in command_map:
        return command_map[args.command](args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
