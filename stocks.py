"""
Stock price data source.

Primary path: yfinance (free, no API key, reads Yahoo Finance).
Fallback path: a seeded synthetic random-walk generator, used only when
the live call fails (offline, rate-limited, or a native crash inside a
compiled dependency). Fallback data is ALWAYS tagged data_mode="demo" so
the UI can badge it -- fake prices are never presented as real.

Every network call runs inside an isolated subprocess with a timeout (see
proc_isolate.py) so a hang or hard crash in yfinance/curl_cffi can't take
the Flask server down with it.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

from proc_isolate import run_with_timeout, SubprocessCallFailed
from indicators import compute_atr  # re-exported for callers

# Currency code -> display symbol. Anything not listed falls back to the
# bare code (e.g. "SGD 12.40"), which is clearer than guessing wrong.
CURRENCY_SYMBOLS = {
    "USD": "$", "INR": "₹", "EUR": "€", "GBP": "£",
    "JPY": "¥", "CNY": "¥", "HKD": "HK$", "AUD": "A$",
    "CAD": "C$", "CHF": "CHF ", "SGD": "S$", "KRW": "₩",
}

# Market indices for the top strip. Indian indices are included because
# a .NS/.BO ticker is a first-class case for this app, not an afterthought.
MARKET_INDICES = [
    {"symbol": "^GSPC",  "label": "S&P 500"},
    {"symbol": "^IXIC",  "label": "NASDAQ"},
    {"symbol": "^DJI",   "label": "DOW"},
    {"symbol": "^NSEI",  "label": "NIFTY 50"},
    {"symbol": "^BSESN", "label": "SENSEX"},
]


def currency_symbol(code: str | None) -> str:
    if not code:
        return "$"
    return CURRENCY_SYMBOLS.get(code.upper(), code.upper() + " ")


def _guess_currency(ticker: str) -> str:
    """Offline heuristic for demo mode - Indian suffixes imply INR."""
    t = ticker.upper()
    if t.endswith(".NS") or t.endswith(".BO") or t in ("^NSEI", "^BSESN"):
        return "INR"
    if t.endswith(".L"):
        return "GBP"
    if t.endswith(".T"):
        return "JPY"
    return "USD"


def _seeded_rng(ticker: str) -> random.Random:
    # Deterministic per ticker + calendar day, so demo mode is stable
    # within a day instead of jittering on every refresh.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seed = int(hashlib.sha256(f"{ticker.upper()}-{today}".encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed)


def _weekday_dates(count: int) -> list:
    """The most recent `count` weekday dates, oldest first."""
    d = datetime.now(timezone.utc).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    dates, cur = [], d
    while len(dates) < count:
        if cur.weekday() < 5:
            dates.append(cur)
        cur -= timedelta(days=1)
    dates.reverse()
    return dates


def _synthetic_history(ticker: str, days: int = 260):
    rng = _seeded_rng(ticker)
    price = 40 + (rng.random() * 260)
    history = []
    for dt in _weekday_dates(days):
        drift = rng.gauss(0.0004, 0.018)
        open_p = price
        close_p = max(0.5, open_p * (1 + drift))
        high_p = max(open_p, close_p) * (1 + abs(rng.gauss(0, 0.006)))
        low_p = min(open_p, close_p) * (1 - abs(rng.gauss(0, 0.006)))
        history.append({
            "date": dt.isoformat(),
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": int(rng.uniform(1e6, 3e7)),
        })
        price = close_p
    return history


# --------------------------------------------------------------------------
# Live workers (each runs in its own subprocess)
# --------------------------------------------------------------------------

def _fetch_history_worker(ticker: str, period: str):
    """Must stay a plain, picklable, module-level function."""
    import yfinance as yf

    tk = yf.Ticker(ticker)
    hist = tk.history(period=period, interval="1d")
    if hist is None or hist.empty:
        raise ValueError("empty history from yfinance")

    # Yahoo returns NaN OHLC rows for halted / no-trade sessions. Those must
    # be dropped at ingestion: a single NaN bar propagates through returns,
    # ATR, RSI and the backtest, and Python's json.dumps then emits a bare
    # `NaN` literal, which is NOT valid JSON and makes the browser reject the
    # entire response.
    history = []
    skipped = 0
    for idx, row in hist.iterrows():
        try:
            o, h, l, c = (float(row["Open"]), float(row["High"]),
                          float(row["Low"]), float(row["Close"]))
        except (TypeError, ValueError):
            skipped += 1
            continue
        # NaN is the only value that isn't equal to itself.
        if not (o == o and h == h and l == l and c == c):
            skipped += 1
            continue
        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            skipped += 1
            continue
        v = row["Volume"]
        history.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(o, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(c, 2),
            "volume": int(v) if (v == v and v >= 0) else 0,
        })

    if not history:
        raise ValueError("no usable rows after dropping incomplete sessions")

    company_name = ticker.upper()
    currency = None

    # fast_info is far more reliable (and quicker) than .info, which
    # frequently rate-limits or changes shape. Try it first.
    try:
        fi = tk.fast_info
        currency = fi.get("currency") if hasattr(fi, "get") else getattr(fi, "currency", None)
    except Exception:
        pass

    try:
        info = tk.info
        company_name = info.get("shortName") or info.get("longName") or company_name
        currency = currency or info.get("currency")
    except Exception:
        pass

    return history, company_name, currency


def _fetch_quotes_worker(tickers: list):
    """One batched download for many symbols - far faster than N calls."""
    import yfinance as yf

    data = yf.download(
        tickers=" ".join(tickers), period="3mo", interval="1d",
        group_by="ticker", threads=True, progress=False, auto_adjust=False,
    )
    multi = len(tickers) > 1
    results = {}
    for t in tickers:
        try:
            sub = data[t] if multi else data
            closes = sub["Close"].dropna()
            if len(closes) < 2:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            change = last - prev
            results[t] = {
                "price": round(last, 2),
                "change": round(change, 2),
                "change_pct": round((change / prev) if prev else 0.0, 4),
                "spark": [round(float(v), 2) for v in closes.tail(20).tolist()],
            }
        except Exception:
            continue
    return results


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def get_price_history(ticker: str, period: str = "1y", timeout: int = 20):
    """
    Returns (history, data_mode, company_name, currency_code).
    history is oldest-first daily bars. A long period is fetched on purpose:
    indicators like SMA200 and the walk-forward backtest need real depth,
    even though the chart may only display a slice of it.
    """
    try:
        history, company_name, currency = run_with_timeout(
            _fetch_history_worker, args=(ticker, period), timeout=timeout
        )
        return history, "live", company_name, (currency or _guess_currency(ticker))
    except (SubprocessCallFailed, Exception):
        return _synthetic_history(ticker), "demo", ticker.upper(), _guess_currency(ticker)


def get_quotes_batch(tickers: list, timeout: int = 25):
    """
    {ticker: {price, change, change_pct, spark, data_mode}} for many symbols.
    A symbol missing from the live result falls back to synthetic on its own,
    so one bad ticker can't blank the whole watchlist.
    """
    tickers = [t.upper() for t in tickers]
    if not tickers:
        return {}
    try:
        live = run_with_timeout(_fetch_quotes_worker, args=(tickers,), timeout=timeout)
    except Exception:
        live = {}

    out = {}
    for t in tickers:
        if t in live:
            out[t] = {**live[t], "data_mode": "live"}
        else:
            # Generate the SAME full-length series the detail view uses, then
            # take its tail. Generating a shorter walk here would produce a
            # different price for the same ticker, so the watchlist card and
            # the detail panel would disagree - which reads as a bug even
            # though both are clearly labelled demo data.
            hist = _synthetic_history(t, days=260)
            closes = [h["close"] for h in hist]
            last, prev = closes[-1], (closes[-2] if len(closes) > 1 else closes[-1])
            change = last - prev
            out[t] = {
                "price": round(last, 2),
                "change": round(change, 2),
                "change_pct": round((change / prev) if prev else 0.0, 4),
                "spark": [round(c, 2) for c in closes[-20:]],
                "data_mode": "demo",
            }
    return out


def get_indices(timeout: int = 25):
    """Market index strip: label + price + change for each major index."""
    symbols = [i["symbol"] for i in MARKET_INDICES]
    quotes = get_quotes_batch(symbols, timeout=timeout)
    out = []
    for meta in MARKET_INDICES:
        q = quotes.get(meta["symbol"])
        if not q:
            continue
        out.append({
            "symbol": meta["symbol"],
            "label": meta["label"],
            "price": q["price"],
            "change": q["change"],
            "change_pct": q["change_pct"],
            "data_mode": q["data_mode"],
        })
    return out
