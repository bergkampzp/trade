"""翻译模块 - 为API返回字段提供中文翻译"""

from __future__ import annotations


_ZH_CN: dict[str, dict[str, str]] = {
    "macros": {
        "CPIAUCSL": "CPI (消费者物价指数)",
        "FEDFUNDS": "联邦基金利率",
        "VIXCLS": "VIX (波动率指数)",
        "DTWEXBGS": "DXY (美元指数)",
        "T10Y2Y": "国债利差 (10Y-2Y)",
        "INDPRO": "工业产出",
    },
    "factors": {
        "momentum_24h": "24小时动量",
        "momentum_7d": "7天动量",
        "momentum_30d": "30天动量",
        "lowvol_24h": "24小时低波动",
        "lowvol_7d": "7天低波动",
        "volume_zscore_24h": "24小时成交量",
        "reversal_1h": "1小时反转",
        "reversal_24h": "24小时反转",
        "rsi_14": "14小时 RSI",
        "bollinger_pos_24h": "布林带位置",
        "amihud_24h": "Amihud 非流动性",
        "garman_klass_24h": "Garman-Klass 波动率",
        "vol_price_divergence_24h": "量价背离",
        "mfi_14": "14小时 MFI (资金流量)",
        "cpi_yoy": "CPI 同比",
        "fed_rate": "联邦基金利率",
        "yield_spread": "国债利差",
        "vix": "VIX 波动率指数",
        "dxy": "DXY (美元指数)",
        "pmi": "工业产出 (PMI 代理)",
        "news_sentiment": "新闻情感",
        "news_volume": "新闻数量",
    },
    "buckets": {
        "A": "经典因子",
        "B": "宏观因子",
        "C": "微观结构",
    },
    "signals": {
        "bullish": "看多",
        "bearish": "看空",
        "neutral": "中性",
        "positive": "正面",
        "negative": "负面",
    },
    "frequencies": {
        "daily": "每日",
        "monthly": "月度",
    },
    "sync": {
        "idle": "空闲",
        "running": "同步中",
        "success": "成功",
        "failed": "失败",
        "news": "新闻数据",
        "macro": "宏观经济",
        "crypto": "数字货币行情",
        "dbt": "因子模型",
    },
}

_EN_US: dict[str, dict[str, str]] = {
    "macros": {
        "CPIAUCSL": "CPI (Consumer Price Index)",
        "FEDFUNDS": "Fed Funds Rate",
        "VIXCLS": "VIX (Volatility Index)",
        "DTWEXBGS": "DXY (US Dollar Index)",
        "T10Y2Y": "10Y-2Y Treasury Spread",
        "INDPRO": "Industrial Production",
    },
    "factors": {
        "momentum_24h": "24h Momentum",
        "momentum_7d": "7d Momentum",
        "momentum_30d": "30d Momentum",
        "lowvol_24h": "24h Low Volatility",
        "lowvol_7d": "7d Low Volatility",
        "volume_zscore_24h": "24h Volume Z-Score",
        "reversal_1h": "1h Reversal",
        "reversal_24h": "24h Reversal",
        "rsi_14": "14h RSI",
        "bollinger_pos_24h": "Bollinger Position",
        "amihud_24h": "Amihud Illiquidity",
        "garman_klass_24h": "Garman-Klass Vol",
        "vol_price_divergence_24h": "Vol-Price Divergence",
        "mfi_14": "14h MFI",
        "cpi_yoy": "CPI YoY",
        "fed_rate": "Fed Rate",
        "yield_spread": "Yield Spread",
        "vix": "VIX",
        "dxy": "DXY",
        "pmi": "Industrial Production (PMI prox)",
        "news_sentiment": "News Sentiment",
        "news_volume": "News Volume",
    },
    "buckets": {"A": "Classic", "B": "Macro", "C": "Micro"},
    "signals": {
        "bullish": "Bullish",
        "bearish": "Bearish",
        "neutral": "Neutral",
        "positive": "Positive",
        "negative": "Negative",
    },
    "frequencies": {"daily": "Daily", "monthly": "Monthly"},
    "sync": {
        "idle": "Idle",
        "running": "Running",
        "success": "Success",
        "failed": "Failed",
        "news": "News",
        "macro": "Macro",
        "crypto": "Crypto",
        "dbt": "dbt Models",
    },
}

_TRANSLATIONS = {"zh_CN": _ZH_CN, "en_US": _EN_US}


def t(key: str, lang: str = "zh_CN", category: str = "macros") -> str:
    """翻译单个字段"""
    return _TRANSLATIONS.get(lang, _ZH_CN).get(category, {}).get(key, key)


def translate_indicators(indicators: list[dict], lang: str = "zh_CN") -> list[dict]:
    """翻译宏观指标列表"""
    cat = _TRANSLATIONS.get(lang, _ZH_CN)
    macros = cat.get("macros", {})
    freqs = cat.get("frequencies", {})
    for ind in indicators:
        if ind.get("name") in macros:
            ind["name"] = macros[ind["name"]]
        if ind.get("frequency") in freqs:
            ind["frequency"] = freqs[ind["frequency"]]
    return indicators


def translate_factors(factors: list[dict], lang: str = "zh_CN") -> list[dict]:
    """翻译因子列表"""
    cat = _TRANSLATIONS.get(lang, _ZH_CN)
    fmap = cat.get("factors", {})
    bmap = cat.get("buckets", {})
    for f in factors:
        if f.get("name") in fmap:
            f["description"] = fmap[f["name"]]
        if f.get("bucket") in bmap:
            f["bucket"] = bmap[f["bucket"]]
    return factors


def translate_sync_status(sources: list[dict], lang: str = "zh_CN") -> list[dict]:
    """翻译同步状态（只翻译 source 用于显示，status/last_result 保留英文供前端匹配）"""
    cat = _TRANSLATIONS.get(lang, _ZH_CN)
    smap = cat.get("sync", {})
    for s in sources:
        s["id"] = s.get("source")  # 保留原始英文ID供前端匹配
        if s.get("source") in smap:
            s["source"] = smap[s["source"]]
    return sources
