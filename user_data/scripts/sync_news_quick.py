#!/usr/bin/env python3
"""Quick RSS news fetch + keyword sentiment → PostgreSQL. No heavy ML deps."""

import feedparser, json, sys
from datetime import datetime, timezone
import psycopg2

FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://www.theblock.co/rss",
    "https://cryptonews.com/news/feed.rss",
    "https://cryptoslate.com/feed/",
]

POSITIVE = [
    "surge",
    "rally",
    "bull",
    "gain",
    "rise",
    "soar",
    "jump",
    "green",
    "record high",
    "breakout",
    "boost",
    "approve",
    "adopt",
    "launch",
    "boom",
    "buy",
    "long",
    "outperform",
    "beat",
    "upgrade",
    "favorable",
    "win",
    "milestone",
    "breakthrough",
    "partnership",
    "integrate",
    "institutional",
    "etf",
    "approval",
    "halving",
    "accumulate",
]

NEGATIVE = [
    "crash",
    "plunge",
    "drop",
    "fall",
    "bear",
    "loss",
    "sell-off",
    "decline",
    "downturn",
    "ban",
    "crackdown",
    "hack",
    "exploit",
    "sue",
    "lawsuit",
    "fine",
    "penalty",
    "delay",
    "reject",
    "deny",
    "warning",
    "fear",
    "liquidate",
    "depeg",
    "insolvent",
    "bankrupt",
    "downgrade",
    "underperform",
    "miss",
    "tariff",
    "inflation",
]


def sentiment(text):
    t = text.lower()
    p = sum(1 for kw in POSITIVE if kw in t)
    n = sum(1 for kw in NEGATIVE if kw in t)
    if p > n:
        return "positive", round(p / (p + n), 4)
    if n > p:
        return "negative", round(n / (p + n), 4)
    return "neutral", 0.5


def fetch(url, limit=8):
    try:
        import socket

        socket.setdefaulttimeout(8)
        f = feedparser.parse(url)
        src = f.feed.get("title", url) if f.feed else url
        arts = []
        for e in f.entries[:limit]:
            t = e.get("title", "").strip()
            if not t:
                continue
            pub = e.get("published_parsed")
            dt = (
                datetime(*pub[:6]).replace(tzinfo=timezone.utc)
                if pub
                else datetime.now(timezone.utc)
            )
            s, sc = sentiment(t)
            arts.append(
                {
                    "published_at": dt,
                    "source": src,
                    "headline": t,
                    "sentiment": s,
                    "score": sc,
                    "raw_scores": {
                        "positive": sc if s == "positive" else 0.3,
                        "negative": sc if s == "negative" else 0.3,
                        "neutral": sc if s == "neutral" else 0.3,
                    },
                }
            )
        return arts
    except Exception as e:
        print(f"  Error {url}: {e}")
        return []


all_arts = []
for u in FEEDS:
    a = fetch(u)
    print(f"  {u[:45]:45s} -> {len(a)} articles")
    all_arts.extend(a)

print(f"\nTotal: {len(all_arts)} articles")

dsn = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"
conn = psycopg2.connect(dsn)
conn.cursor().execute("""
    CREATE TABLE IF NOT EXISTS quant_raw.news_sentiment (
        id BIGSERIAL PRIMARY KEY, published_at TIMESTAMPTZ NOT NULL,
        source TEXT NOT NULL, headline TEXT NOT NULL, sentiment TEXT NOT NULL,
        score DOUBLE PRECISION NOT NULL, raw_scores JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (headline, source)
    )
""")
conn.commit()

n = 0
for a in all_arts:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO quant_raw.news_sentiment (published_at, source, headline, sentiment, score, raw_scores) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (headline, source) DO UPDATE SET sentiment=EXCLUDED.sentiment, score=EXCLUDED.score",
                (
                    a["published_at"],
                    a["source"],
                    a["headline"],
                    a["sentiment"],
                    a["score"],
                    json.dumps(a["raw_scores"]),
                ),
            )
        n += 1
    except Exception as e:
        conn.rollback()
conn.commit()
conn.close()
print(f"Written: {n} rows")

# Show top 10
conn2 = psycopg2.connect(dsn)
rows = conn2.cursor()
rows.execute(
    "SELECT headline, source, sentiment, score, published_at FROM quant_raw.news_sentiment ORDER BY ABS(score-0.5) DESC, published_at DESC LIMIT 10"
)
print("\n=== TOP 10 IMPORTANT NEWS ===")
for i, (h, src, s, sc, d) in enumerate(rows.fetchall(), 1):
    e = {"positive": "UP", "negative": "DN", "neutral": "--"}.get(s, "??")
    print(f"  {i:2d}. [{e} {sc * 100:3.0f}%] {h[:75]}")
    print(f"      {src} | {d}")
conn2.close()
