"""
Technical indicator math.

Pure functions over a `history` list (oldest first) of dicts with
date/open/high/low/close/volume. No network, no side effects -- which
means every function here is directly unit-testable, and the same code
runs for live and demo data.

All indicators return None when there isn't enough history to compute
them honestly, rather than silently returning a value derived from a
short window. A half-computed RSI is worse than no RSI.
"""
from __future__ import annotations


# --------------------------------------------------------------------------
# Moving averages
# --------------------------------------------------------------------------

def sma(values: list, period: int):
    """Simple moving average of the trailing `period` values."""
    if not values or len(values) < period:
        return None
    return sum(values[-period:]) / period


def sma_series(values: list, period: int) -> list:
    """SMA at every index; None where the window isn't full yet."""
    out = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        out.append(running / period if i >= period - 1 else None)
    return out


def ema_series(values: list, period: int) -> list:
    """
    Exponential moving average at every index. Seeded with the SMA of the
    first `period` values (the standard convention) so the series doesn't
    over-weight the very first price.
    """
    if len(values) < period:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    out = [None] * (period - 1)
    seed = sum(values[:period]) / period
    out.append(seed)
    prev = seed
    for v in values[period:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


# --------------------------------------------------------------------------
# Volatility
# --------------------------------------------------------------------------

def true_ranges(history: list) -> list:
    """
    True Range per session: max(high-low, |high-prev_close|, |low-prev_close|).
    Returns len(history)-1 values (first session has no previous close).
    """
    trs = []
    for i in range(1, len(history)):
        prev_close = history[i - 1]["close"]
        high = history[i]["high"]
        low = history[i]["low"]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return trs


def compute_atr(history: list, period: int = 14):
    """
    Average True Range over the trailing `period` sessions.
    Returns (atr_absolute, atr_as_fraction_of_last_close).
    """
    if len(history) < 2:
        return 0.0, 0.0
    trs = true_ranges(history)
    window = trs[-period:] if len(trs) >= period else trs
    atr = sum(window) / len(window) if window else 0.0
    last_close = history[-1]["close"] or 1.0
    return round(atr, 4), round(atr / last_close if last_close else 0.0, 5)


# --------------------------------------------------------------------------
# Momentum
# --------------------------------------------------------------------------

def rsi(closes: list, period: int = 14):
    """
    Relative Strength Index using Wilder's smoothing (the standard method).
    Returns a float in [0, 100], or None if there isn't enough history.

    Reads as: >70 conventionally "overbought", <30 "oversold". Those are
    conventions, not predictions -- a strong trend can sit above 70 for
    weeks.
    """
    if len(closes) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    # Seed with a simple average of the first `period` changes...
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # ...then apply Wilder smoothing across the remainder.
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    MACD line (fast EMA - slow EMA), its signal EMA, and the histogram.
    Returns None if there isn't enough history for the slow EMA + signal.
    """
    if len(closes) < slow + signal:
        return None

    fast_e = ema_series(closes, fast)
    slow_e = ema_series(closes, slow)
    macd_line = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_e, slow_e)
    ]
    valid = [v for v in macd_line if v is not None]
    if len(valid) < signal:
        return None

    signal_e = ema_series(valid, signal)
    signal_now = signal_e[-1]
    macd_now = valid[-1]
    if signal_now is None:
        return None

    hist_now = macd_now - signal_now
    # Previous histogram value, to detect a fresh crossover this session.
    hist_prev = None
    if len(valid) >= 2 and len(signal_e) >= 2 and signal_e[-2] is not None:
        hist_prev = valid[-2] - signal_e[-2]

    if hist_prev is None:
        cross = "none"
    elif hist_prev <= 0 < hist_now:
        cross = "bullish"
    elif hist_prev >= 0 > hist_now:
        cross = "bearish"
    else:
        cross = "none"

    return {
        "macd": round(macd_now, 4),
        "signal": round(signal_now, 4),
        "histogram": round(hist_now, 4),
        "cross": cross,
    }


# --------------------------------------------------------------------------
# Bands & levels
# --------------------------------------------------------------------------

def bollinger(closes: list, period: int = 20, num_std: float = 2.0):
    """
    Bollinger Bands + %B (where price sits within the band: 0 = lower band,
    1 = upper band, >1 = above the band).
    """
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((v - mid) ** 2 for v in window) / period
    sd = variance ** 0.5
    upper = mid + num_std * sd
    lower = mid - num_std * sd
    width = upper - lower
    last = closes[-1]
    pct_b = ((last - lower) / width) if width else 0.5
    return {
        "upper": round(upper, 2),
        "mid": round(mid, 2),
        "lower": round(lower, 2),
        "pct_b": round(pct_b, 3),
        "bandwidth_pct": round((width / mid) if mid else 0.0, 4),
    }


def week52(history: list):
    """
    52-week (or as much as we have) high/low and where price sits in that
    range: 0 = at the low, 1 = at the high.
    """
    if not history:
        return None
    window = history[-252:] if len(history) >= 252 else history
    high = max(h["high"] for h in window)
    low = min(h["low"] for h in window)
    last = history[-1]["close"]
    span = high - low
    return {
        "high": round(high, 2),
        "low": round(low, 2),
        "position": round(((last - low) / span) if span else 0.5, 3),
        "sessions": len(window),
    }


def support_resistance(history: list, lookback: int = 90, pivot_width: int = 3):
    """
    Naive swing-pivot support/resistance: a local low with `pivot_width`
    higher lows on each side is support; the mirror is resistance. We then
    take the nearest such level below (support) and above (resistance) the
    current price.

    This is a rough visual aid, not a precise level -- real S/R is fuzzy and
    traders disagree on it constantly.
    """
    if len(history) < pivot_width * 2 + 5:
        return None
    window = history[-lookback:] if len(history) > lookback else history
    last = window[-1]["close"]

    sup_levels, res_levels = [], []
    for i in range(pivot_width, len(window) - pivot_width):
        lows = [window[j]["low"] for j in range(i - pivot_width, i + pivot_width + 1)]
        highs = [window[j]["high"] for j in range(i - pivot_width, i + pivot_width + 1)]
        if window[i]["low"] == min(lows):
            sup_levels.append(window[i]["low"])
        if window[i]["high"] == max(highs):
            res_levels.append(window[i]["high"])

    below = [v for v in sup_levels if v < last]
    above = [v for v in res_levels if v > last]
    return {
        "support": round(max(below), 2) if below else None,
        "resistance": round(min(above), 2) if above else None,
    }


def volume_profile(history: list, period: int = 20):
    """Latest volume vs its recent average -- a crude 'is today unusual' check."""
    if len(history) < period + 1:
        return None
    vols = [h["volume"] for h in history]
    avg = sum(vols[-period - 1:-1]) / period
    last = vols[-1]
    return {
        "latest": last,
        "avg": int(avg),
        "ratio": round((last / avg) if avg else 1.0, 2),
    }


# --------------------------------------------------------------------------
# Roll-up
# --------------------------------------------------------------------------

def compute_all(history: list) -> dict:
    """Compute the full indicator set for a history series."""
    closes = [h["close"] for h in history]
    atr, atr_pct = compute_atr(history)
    return {
        "atr": atr,
        "atr_pct": atr_pct,
        "rsi": rsi(closes),
        "sma20": round(sma(closes, 20), 2) if sma(closes, 20) is not None else None,
        "sma50": round(sma(closes, 50), 2) if sma(closes, 50) is not None else None,
        "sma200": round(sma(closes, 200), 2) if sma(closes, 200) is not None else None,
        "macd": macd(closes),
        "bollinger": bollinger(closes),
        "week52": week52(history),
        "levels": support_resistance(history),
        "volume": volume_profile(history),
    }


def technical_signal(ind: dict, last_close: float) -> dict:
    """
    Roll the indicators into a single -1..+1 technical lean.

    Deliberately simple and equally weighted: each component votes -1, 0 or
    +1 and we average the votes that are actually available. This is a
    readable summary of "what do the standard indicators say right now",
    NOT a trading model -- the components are correlated with each other
    and none of them is predictive on its own.
    """
    votes = []
    reasons = []

    r = ind.get("rsi")
    if r is not None:
        if r >= 70:
            votes.append(-1); reasons.append(f"RSI {r} overbought")
        elif r <= 30:
            votes.append(1); reasons.append(f"RSI {r} oversold")
        else:
            votes.append(0); reasons.append(f"RSI {r} neutral")

    s20, s50 = ind.get("sma20"), ind.get("sma50")
    if s20 is not None and s50 is not None:
        if s20 > s50:
            votes.append(1); reasons.append("SMA20 above SMA50")
        elif s20 < s50:
            votes.append(-1); reasons.append("SMA20 below SMA50")
        else:
            votes.append(0)
    if s20 is not None:
        if last_close > s20:
            votes.append(1); reasons.append("price above SMA20")
        else:
            votes.append(-1); reasons.append("price below SMA20")

    m = ind.get("macd")
    if m:
        if m["histogram"] > 0:
            votes.append(1); reasons.append("MACD above signal")
        elif m["histogram"] < 0:
            votes.append(-1); reasons.append("MACD below signal")
        else:
            votes.append(0)

    bb = ind.get("bollinger")
    if bb:
        if bb["pct_b"] > 1:
            votes.append(-1); reasons.append("above upper Bollinger band")
        elif bb["pct_b"] < 0:
            votes.append(1); reasons.append("below lower Bollinger band")
        else:
            votes.append(0)

    if not votes:
        return {"score": 0.0, "label": "insufficient data", "reasons": [], "components": 0}

    score = sum(votes) / len(votes)
    label = "bullish" if score >= 0.34 else ("bearish" if score <= -0.34 else "neutral")
    return {
        "score": round(score, 3),
        "label": label,
        "reasons": reasons,
        "components": len(votes),
    }
