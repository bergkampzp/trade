#!/usr/bin/env python3
"""
Fetch crypto news from RSS feeds, analyze headline sentiment with FinBERT,
and write results to PostgreSQL (quant_raw.news_sentiment).

Part of the quant trading pipeline — macro news sentiment as a trading factor.

Usage:
    python fetch_news_sentiment.py
    python fetch_news_sentiment.py --limit 20 --dry-run
    python fetch_news_sentiment.py --sources "https://example.com/rss,https://other.com/feed"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import psycopg2
import psycopg2.extras


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_FEEDS: list[str] = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]

DEFAULT_DSN = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"
BATCH_SIZE = 32

# ---------------------------------------------------------------------------
# RSS fetching
# ---------------------------------------------------------------------------


def _parse_entry_date(entry) -> datetime:
    """Extract publication date from a feed entry, falling back to now()."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6]).replace(tzinfo=timezone.utc)
        except Exception:
            log.debug("Failed to parse published_parsed for '%s'", entry.get("title", "?"))
    if entry.get("published"):
        try:
            return parsedate_to_datetime(entry.published)
        except Exception:
            log.debug("Failed to parse published string for '%s'", entry.get("title", "?"))
    return datetime.now(timezone.utc)


def fetch_feed(url: str, limit: int) -> list[dict[str, Any]]:
    """Parse an RSS feed and return a list of article dicts."""
    log.info("Fetching %s", url)
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        log.error("Failed to fetch %s: %s", url, exc)
        return []

    if feed.bozo and not feed.entries:
        log.warning("Feed %s returned no entries (bozo: %s)", url, feed.bozo_exception)
        return []

    source = feed.feed.get("title", url)
    articles: list[dict[str, Any]] = []

    for entry in feed.entries[:limit]:
        title = entry.get("title", "").strip()
        if not title:
            continue
        articles.append(
            {
                "headline": title,
                "published_at": _parse_entry_date(entry),
                "source": source,
            }
        )

    log.info("  -> %d articles from %s", len(articles), source)
    return articles


# ---------------------------------------------------------------------------
# FinBERT sentiment
# ---------------------------------------------------------------------------


def load_sentiment_pipeline():
    """Load the FinBERT sentiment-analysis pipeline."""
    log.info("Loading FinBERT model (ProsusAI/finbert) …")
    try:
        from transformers import pipeline as hf_pipeline

        pipe = hf_pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            top_k=None,  # return all 3 label scores
            truncation=True,
        )
        log.info("Model loaded.")
        return pipe
    except Exception as exc:
        log.error("Failed to load FinBERT: %s", exc)
        raise


def analyze_sentiment(pipe, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run FinBERT on article headlines in batches."""
    headlines = [a["headline"] for a in articles]
    all_results: list[list[dict]] = []

    for start in range(0, len(headlines), BATCH_SIZE):
        batch = headlines[start : start + BATCH_SIZE]
        try:
            batch_results = pipe(batch)
            all_results.extend(batch_results)
        except Exception as exc:
            log.error("Inference failed on batch %d–%d: %s", start, start + len(batch), exc)
            # Fill with neutral placeholders so indices stay aligned
            for _ in batch:
                all_results.append(
                    [
                        {"label": "neutral", "score": 1.0},
                        {"label": "positive", "score": 0.0},
                        {"label": "negative", "score": 0.0},
                    ]
                )

    for article, scores in zip(articles, all_results, strict=True):
        # scores is a list of dicts: [{"label": "positive", "score": 0.9}, ...]
        raw_scores = {s["label"]: round(s["score"], 6) for s in scores}
        best = max(scores, key=lambda s: s["score"])
        article["sentiment"] = best["label"]
        article["score"] = round(best["score"], 6)
        article["raw_scores"] = raw_scores

    return articles


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

DDL = """
CREATE SCHEMA IF NOT EXISTS quant_raw;

CREATE TABLE IF NOT EXISTS quant_raw.news_sentiment (
    id              BIGSERIAL PRIMARY KEY,
    published_at    TIMESTAMPTZ NOT NULL,
    source          TEXT        NOT NULL,
    headline        TEXT        NOT NULL,
    sentiment       TEXT        NOT NULL,
    score           DOUBLE PRECISION NOT NULL,
    raw_scores      JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (headline, source)
);

CREATE INDEX IF NOT EXISTS idx_news_sentiment_published
    ON quant_raw.news_sentiment (published_at DESC);
"""


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    log.info("Table quant_raw.news_sentiment ready.")


def deduplicate(conn, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove articles whose (headline, source) already exist in PG."""
    if not articles:
        return articles

    with conn.cursor() as cur:
        pairs = [(a["headline"], a["source"]) for a in articles]
        # Use VALUES list to check existing rows in one query
        cur.execute(
            """
            SELECT headline, source
            FROM quant_raw.news_sentiment
            WHERE (headline, source) IN %s
            """,
            (tuple(pairs),),
        )
        existing = {(row[0], row[1]) for row in cur.fetchall()}

    new_articles = [a for a in articles if (a["headline"], a["source"]) not in existing]
    skipped = len(articles) - len(new_articles)
    if skipped:
        log.info("Skipped %d duplicate articles.", skipped)
    return new_articles


def insert_articles(conn, articles: list[dict[str, Any]]) -> int:
    """Bulk-insert articles into PG. Returns count inserted."""
    if not articles:
        return 0

    rows = [
        (
            a["published_at"],
            a["source"],
            a["headline"],
            a["sentiment"],
            a["score"],
            json.dumps(a["raw_scores"]),
        )
        for a in articles
    ]

    insert_sql = """
        INSERT INTO quant_raw.news_sentiment
            (published_at, source, headline, sentiment, score, raw_scores)
        VALUES %s
        ON CONFLICT (headline, source) DO NOTHING
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, insert_sql, rows, page_size=200)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(articles: list[dict[str, Any]], inserted: int, dry_run: bool) -> None:
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for a in articles:
        by_source[a["source"]][a["sentiment"]] += 1

    print("\n" + "=" * 70)
    print("  NEWS SENTIMENT SUMMARY")
    print("=" * 70)
    for source, dist in sorted(by_source.items()):
        total = sum(dist.values())
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(dist.items()))
        print(f"  {source}")
        print(f"    articles: {total}  |  {parts}")
    print("-" * 70)
    if dry_run:
        print(f"  DRY RUN — {len(articles)} articles analyzed, nothing written.")
    else:
        print(f"  Inserted {inserted} new rows into quant_raw.news_sentiment")
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch crypto news RSS, run FinBERT sentiment, write to PG."
    )
    p.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max articles per feed (default: 50)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze but do not write to PG",
    )
    p.add_argument(
        "--sources",
        type=str,
        default=None,
        help="Comma-separated RSS URLs (overrides defaults)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    feeds = args.sources.split(",") if args.sources else DEFAULT_FEEDS
    dsn = os.environ.get("QUANT_PG_DSN", DEFAULT_DSN)

    # -- 1. Fetch RSS --
    all_articles: list[dict[str, Any]] = []
    for url in feeds:
        all_articles.extend(fetch_feed(url.strip(), args.limit))

    if not all_articles:
        log.warning("No articles fetched from any source. Exiting.")
        sys.exit(0)

    log.info("Total articles fetched: %d", len(all_articles))

    # -- 2. Sentiment analysis --
    try:
        pipe = load_sentiment_pipeline()
    except Exception:
        log.error("Cannot proceed without the sentiment model.")
        sys.exit(1)

    all_articles = analyze_sentiment(pipe, all_articles)

    # -- 3. Write to PG (unless dry-run) --
    inserted = 0
    if not args.dry_run:
        try:
            conn = psycopg2.connect(dsn)
        except Exception as exc:
            log.error("PG connection failed: %s", exc)
            sys.exit(1)

        try:
            ensure_table(conn)
            new_articles = deduplicate(conn, all_articles)
            inserted = insert_articles(conn, new_articles)
        finally:
            conn.close()
    else:
        log.info("Dry-run mode — skipping PG write.")

    # -- 4. Summary --
    print_summary(all_articles, inserted, args.dry_run)


if __name__ == "__main__":
    main()
