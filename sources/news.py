"""
News data source.

Pulls free, no-key-required RSS feeds and keeps only the entries that
actually mention the ticker or one of its company-name aliases. Broad
market feeds (CNBC front page, MarketWatch top stories) are included
because a ticker-specific feed alone is often thin -- the alias filter is
what makes them useful rather than noisy.

Headlines are deduplicated across feeds (the same wire story routinely
appears in three of them, which would otherwise triple-count its sentiment
and fake a stronger signal than exists).

Fallback: clearly-labeled synthetic demo headlines when feeds are
unreachable. Never presented as real news.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone

from proc_isolate import run_with_timeout, SubprocessCallFailed

RSS_FEEDS = [
    # Ticker-specific (best signal)
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
    # Broad market feeds, filtered by alias match
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",        # CNBC top news
    "https://www.cnbc.com/id/15839135/device/rss/rss.html",        # CNBC markets
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",   # MarketWatch
    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",  # MarketWatch pulse
    "https://www.investing.com/rss/news_25.rss",                    # Investing.com stocks
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",  # ET Markets (India)
    "https://www.business-standard.com/rss/markets-106.rss",        # Business Standard (India)
]

TICKER_ALIASES = {
    "AAPL": ["Apple"],
    "MSFT": ["Microsoft"],
    "GOOGL": ["Google", "Alphabet"], "GOOG": ["Google", "Alphabet"],
    "AMZN": ["Amazon"],
    "TSLA": ["Tesla"],
    "META": ["Meta Platforms", "Facebook"],
    "NVDA": ["Nvidia", "NVIDIA"],
    "NFLX": ["Netflix"],
    "JPM": ["JPMorgan", "JP Morgan"],
    "AMD": ["AMD", "Advanced Micro"],
    "INTC": ["Intel"],
    "MU": ["Micron"],
    # India
    "RELIANCE.NS": ["Reliance Industries", "Reliance"],
    "TCS.NS": ["Tata Consultancy", "TCS"],
    "INFY": ["Infosys"], "INFY.NS": ["Infosys"],
    "HDFCBANK.NS": ["HDFC Bank", "HDFC"],
    "ICICIBANK.NS": ["ICICI Bank", "ICICI"],
    "TATASTEEL.NS": ["Tata Steel"],
    "SBIN.NS": ["State Bank of India", "SBI"],
    "WIPRO.NS": ["Wipro"],
    "ITC.NS": ["ITC"],
    "BHARTIARTL.NS": ["Bharti Airtel", "Airtel"],
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_title(title: str) -> str:
    """Normalized key for dedup - lowercase alphanumeric words only."""
    return " ".join(_WORD_RE.findall(title.lower()))


def _synthetic_headlines(ticker: str, company_name: str, n: int = 8):
    rng = random.Random(f"{ticker.upper()}-{datetime.now(timezone.utc).date()}")
    templates = [
        ("{c} beats quarterly earnings expectations, shares rise in pre-market trading", 0.6),
        ("Analysts raise price target on {c} citing strong demand outlook", 0.5),
        ("{c} announces new product line, investors optimistic", 0.4),
        ("{c} faces regulatory scrutiny over recent business practices", -0.5),
        ("Supply chain concerns weigh on {c} shares", -0.4),
        ("{c} stock steady as broader market awaits Fed decision", 0.0),
        ("{c} expands into new international markets", 0.3),
        ("Analysts downgrade {c} on valuation concerns", -0.4),
        ("{c} CEO discusses growth strategy in investor call", 0.2),
        ("Market volatility drags {c} lower despite no company-specific news", -0.2),
    ]
    picks = rng.sample(templates, k=min(n, len(templates)))
    now = datetime.now(timezone.utc)
    return [
        {
            "title": tmpl.format(c=company_name),
            "source": "Demo Feed",
            "published": (now - timedelta(hours=i * 3 + rng.randint(0, 2))).isoformat(),
            "url": None,
            "_demo_sentiment_hint": hint,
        }
        for i, (tmpl, hint) in enumerate(picks)
    ]


def _fetch_news_worker(ticker_u: str, aliases_lower: list, limit: int):
    """Runs isolated; must stay plain, picklable and module-level."""
    import feedparser

    matched = []
    seen = set()
    for feed_url in RSS_FEEDS:
        url = feed_url.format(ticker=ticker_u)
        try:
            parsed = feedparser.parse(url)
        except Exception:
            continue
        if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", None):
            continue

        feed_title = getattr(getattr(parsed, "feed", None), "title", "RSS")
        for entry in parsed.entries[:50]:
            title = (getattr(entry, "title", "") or "").strip()
            if not title:
                continue
            summary = getattr(entry, "summary", "") or ""
            haystack = f"{title} {summary}".lower()
            if not any(a in haystack for a in aliases_lower):
                continue

            key = _norm_title(title)
            if key in seen:      # same wire story syndicated across feeds
                continue
            seen.add(key)

            matched.append({
                "title": title,
                "summary": summary[:300],
                "source": feed_title,
                "published": getattr(entry, "published", None) or getattr(entry, "updated", None),
                "url": getattr(entry, "link", None),
            })
        if len(matched) >= limit:
            break

    if not matched:
        raise ValueError("no matching live headlines found")
    return matched[:limit]


def fetch_news(ticker: str, company_name: str | None = None, limit: int = 12, timeout: int = 18):
    """Returns (headlines, data_mode)."""
    ticker_u = ticker.upper()
    aliases = [ticker_u, ticker_u.split(".")[0]] + TICKER_ALIASES.get(ticker_u, [])
    if company_name:
        # Strip common corporate suffixes so "Apple Inc." also matches "Apple"
        cleaned = re.sub(r"\b(inc|ltd|limited|corp|corporation|plc|co|company|nv|sa|ag)\b\.?",
                         "", company_name, flags=re.I).strip(" ,.")
        if cleaned and cleaned not in aliases:
            aliases.append(cleaned)
    aliases_lower = [a.lower() for a in aliases if a and len(a) >= 2]

    try:
        matched = run_with_timeout(
            _fetch_news_worker, args=(ticker_u, aliases_lower, limit), timeout=timeout
        )
        return matched, "live"
    except (SubprocessCallFailed, Exception):
        return _synthetic_headlines(ticker_u, company_name or ticker_u, n=limit), "demo"
