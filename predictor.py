"""
Next-session range prediction + an honest backtest of it.

The prediction is a transparent heuristic, not a learned model:

  1. 14-day Average True Range (ATR) gives the baseline expected trading
     range for the next session.
  2. That range is centered on the latest close.
  3. The center is nudged by aggregate news sentiment and by the technical
     lean, each capped at a fraction of the ATR so a "signal" can never
     imply more movement than the stock's own volatility supports.

Why it's built this way: no model reliably predicts tomorrow's exact high
and low. If one did, the edge would be arbitraged away in minutes by firms
with vastly more data and speed. What IS tractable is estimating a
plausible *range* from recent volatility -- that's a well-understood
statistical property, unlike direction, which is close to a coin flip at
this horizon.

The backtest below exists to keep this honest: it measures how often the
volatility band would actually have contained the next session's close,
and reports the band's width alongside, because a wide enough band hits
100% of the time and means nothing.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from indicators import compute_atr
import volatility as vol

# Sentiment and technicals each shift the range center by at most this
# fraction of one ATR.
MAX_SENTIMENT_SHIFT = 0.35
MAX_TECHNICAL_SHIFT = 0.25
# Half-width of the predicted band, in ATRs.
BAND_HALF_WIDTH = 0.6


def _next_session_date(last_date_str: str) -> str:
    d = datetime.strptime(last_date_str, "%Y-%m-%d")
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:  # skip Sat/Sun
        nxt += timedelta(days=1)
    return nxt.strftime("%Y-%m-%d")


def predict_next_session(
    history: list,
    atr: float,
    atr_pct: float,
    sentiment_score: float,
    sample_size: int,
    technical_score: float = 0.0,
):
    last = history[-1]
    close = last["close"]
    session_date = _next_session_date(last["date"])

    if atr <= 0:
        atr = close * 0.015  # degenerate fallback

    half_range = atr * BAND_HALF_WIDTH
    sent_shift = sentiment_score * atr * MAX_SENTIMENT_SHIFT
    tech_shift = technical_score * atr * MAX_TECHNICAL_SHIFT
    shift = sent_shift + tech_shift
    center = close + shift

    predicted_low = max(0.01, round(center - half_range, 2))
    predicted_high = round(center + half_range, 2)
    if predicted_high <= predicted_low:
        predicted_high = predicted_low + max(0.01, atr * 0.1)

    combined = (sentiment_score + technical_score) / 2
    if combined >= 0.15:
        lean = "bullish"
    elif combined <= -0.15:
        lean = "bearish"
    else:
        lean = "neutral"

    confidence = "low" if sample_size < 4 else ("medium" if sample_size < 8 else "moderate")

    return {
        "session_date": session_date,
        "predicted_low": predicted_low,
        "predicted_high": predicted_high,
        "predicted_close_center": round(center, 2),
        "lean": lean,
        "confidence": confidence,
        "band_width_pct": round((predicted_high - predicted_low) / close, 4) if close else 0,
        "shift_breakdown": {
            "sentiment": round(sent_shift, 3),
            "technical": round(tech_shift, 3),
            "total": round(shift, 3),
        },
        "note": (
            f"Band = +/-{BAND_HALF_WIDTH} ATR (ATR is {round(atr_pct * 100, 2)}% of price), "
            f"center shifted {'+' if shift >= 0 else ''}{round(shift, 2)} "
            f"({'+' if sent_shift >= 0 else ''}{round(sent_shift, 2)} from {sample_size} headlines, "
            f"{'+' if tech_shift >= 0 else ''}{round(tech_shift, 2)} from technicals). "
            f"Volatility + signal heuristic, not a forecast."
        ),
    }


def backtest(history: list, atr_period: int = 14, min_history: int = 30) -> dict:
    """
    Walk-forward test of the volatility band.

    For each past session t (with at least `min_history` sessions before
    it), compute the ATR band as it would have looked using ONLY data up
    to t, then check it against what actually happened on t+1. No future
    data leaks into any prediction -- that's the whole point.

    IMPORTANT LIMITATION, stated plainly: this tests the *volatility
    baseline only*. We have no archive of historical news sentiment, so
    the sentiment/technical nudge is NOT included here. Do not read this
    hit rate as evidence that the news scoring works -- it says nothing
    about it either way.

    Returns hit rate alongside mean band width, because those two numbers
    are only meaningful together: a band twice as wide trivially hits more
    often while saying less.
    """
    if len(history) < min_history + 5:
        return {"available": False, "reason": "not enough history to backtest"}

    # Test several band widths at once. Showing the tradeoff explicitly is
    # the point: a wider band always hits more often, so a hit rate quoted
    # without its width is meaningless.
    widths = [BAND_HALF_WIDTH, 1.0, 1.5]
    hits = {w: 0 for w in widths}
    width_sum = {w: 0.0 for w in widths}
    total = 0
    abs_move_sum = 0.0

    for t in range(min_history, len(history) - 1):
        window = history[: t + 1]
        atr, _ = compute_atr(window, atr_period)
        close = window[-1]["close"]
        if atr <= 0 or close <= 0:
            continue

        nxt = history[t + 1]
        total += 1
        abs_move_sum += abs(nxt["close"] - close) / close

        for w in widths:
            half = atr * w
            if close - half <= nxt["close"] <= close + half:
                hits[w] += 1
            width_sum[w] += (2 * half) / close

    if total == 0:
        return {"available": False, "reason": "no valid backtest windows"}

    curve = [
        {
            "half_width_atr": w,
            "hit_pct": round(100.0 * hits[w] / total, 1),
            "band_width_pct": round(100.0 * width_sum[w] / total, 2),
        }
        for w in widths
    ]

    return {
        "available": True,
        "sessions_tested": total,
        "close_in_band_pct": curve[0]["hit_pct"],
        "mean_band_width_pct": curve[0]["band_width_pct"],
        "mean_abs_move_pct": round(100.0 * abs_move_sum / total, 2),
        "width_curve": curve,
        "caveat": (
            "Volatility baseline only - no archive of historical news sentiment exists "
            "here, so the sentiment/technical nudge is excluded. This says nothing about "
            "whether the news scoring works. Read any hit rate together with its band width."
        ),
    }


# ==========================================================================
# Volatility model comparison
# ==========================================================================

def _quantile(sorted_vals: list, q: float) -> float:
    """Linear-interpolated quantile of an already-sorted list."""
    if not sorted_vals:
        return 0.0
    if q <= 0:
        return sorted_vals[0]
    if q >= 1:
        return sorted_vals[-1]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def compare_volatility_models(history: list, target: float = 0.68,
                              train_frac: float = 0.6, min_train: int = 80) -> dict:
    """
    Score every volatility model on the SAME footing and pick a winner.

    Method, and why each step matters:

    1. Split the series into train / test. Nothing from test is used to
       build anything.
    2. Fit GARCH parameters on TRAIN RETURNS ONLY. Fitting on the whole
       series would leak the future and flatter GARCH specifically.
    3. Calibrate each model's band multiplier k on TRAIN, as the `target`
       quantile of |r| / sigma. This is the key fairness step: every model
       is tuned to aim at the same coverage, so none can win just by being
       wider.
    4. Evaluate out-of-sample on TEST: realised coverage, mean band width,
       and the Winkler interval score.

    The Winkler score is the decisive number. For a central (1-a) interval
    it charges you the width of the interval, plus a penalty of (2/a) times
    how far outside the observation landed. A model can lower it only by
    being narrow AND still containing the outcome — so it cannot be gamed
    by widening (that raises width) or by shrinking (that raises misses).
    Lower is better. It is a proper scoring rule, which is exactly why it's
    used here instead of a raw hit rate.

    All figures are in percent of price.
    """
    rets = vol.log_returns(history)
    n = len(rets)
    if n < min_train + 40:
        return {"available": False, "reason": f"need ~{min_train + 40} sessions, have {n}"}

    split = max(min_train, int(n * train_frac))
    if n - split < 25:
        return {"available": False, "reason": "test window too small"}

    # GARCH fitted on training returns only - no peeking at the test half.
    gparams = vol.fit_garch11(rets[:split])
    sigmas = vol.all_sigmas(history, garch_params=gparams)

    alpha = 1.0 - target
    rows = []
    for name in vol.MODELS:
        s = sigmas.get(name) or []
        if len(s) != n:
            continue

        ratios = sorted(abs(rets[i]) / s[i] for i in range(split) if s[i] > 0)
        if not ratios:
            continue
        k = _quantile(ratios, target)

        hits = cnt = 0
        width_sum = wink_sum = 0.0
        for i in range(split, n):
            if s[i] <= 0:
                continue
            half = k * s[i]
            r = rets[i]
            cnt += 1
            width_sum += 2 * half
            w = 2 * half
            if abs(r) <= half:
                hits += 1
            else:
                w += (2.0 / alpha) * (abs(r) - half)   # Winkler miss penalty
            wink_sum += w
        if cnt == 0:
            continue

        rows.append({
            "model": name,
            "k": round(k, 3),
            "coverage_pct": round(100.0 * hits / cnt, 1),
            "mean_width_pct": round(100.0 * width_sum / cnt, 3),
            "winkler": round(100.0 * wink_sum / cnt, 4),
            "calib_error": round(abs(100.0 * hits / cnt - 100.0 * target), 1),
            "sessions": cnt,
        })

    if not rows:
        return {"available": False, "reason": "no model produced a usable series"}

    rows.sort(key=lambda r: r["winkler"])          # lower is better
    best = rows[0]
    baseline = next((r for r in rows if r["model"] == "ATR"), None)
    improvement = None
    if baseline and baseline["winkler"] > 0 and best["model"] != "ATR":
        improvement = round(100.0 * (baseline["winkler"] - best["winkler"]) / baseline["winkler"], 1)

    return {
        "available": True,
        "target_coverage_pct": round(100.0 * target, 0),
        "train_sessions": split,
        "test_sessions": n - split,
        "rows": rows,
        "best_model": best["model"],
        "best_k": best["k"],
        "vs_atr_pct": improvement,
        "garch": gparams,
        "method": (
            "Each model's band multiplier was calibrated on the training half to aim at the "
            "same coverage, then scored out-of-sample. Ranked by Winkler interval score "
            "(width + penalty for misses; lower is better) so a model cannot win by simply "
            "being wider. GARCH parameters were fitted on training returns only."
        ),
    }


def predict_with_model(history: list, sigma_forecast: float, k: float,
                       sentiment_score: float, sample_size: int,
                       technical_score: float = 0.0, model_name: str = "EWMA") -> dict:
    """
    Build the next-session band from a calibrated volatility forecast.

    sigma_forecast is a per-session standard deviation expressed as a
    fraction of price; k is the multiplier calibrated for the desired
    coverage. Sentiment and technicals shift the CENTRE only, never the
    width - tone should not be allowed to masquerade as certainty.
    """
    last = history[-1]
    close = last["close"]
    half = max(k * sigma_forecast, 1e-6) * close

    sent_shift = sentiment_score * half * MAX_SENTIMENT_SHIFT
    tech_shift = technical_score * half * MAX_TECHNICAL_SHIFT
    shift = sent_shift + tech_shift
    centre = close + shift

    lo = max(0.01, round(centre - half, 2))
    hi = round(centre + half, 2)
    if hi <= lo:
        hi = lo + 0.01

    combined = (sentiment_score + technical_score) / 2
    lean = "bullish" if combined >= 0.15 else ("bearish" if combined <= -0.15 else "neutral")
    confidence = "low" if sample_size < 4 else ("medium" if sample_size < 8 else "moderate")

    return {
        "session_date": _next_session_date(last["date"]),
        "predicted_low": lo,
        "predicted_high": hi,
        "predicted_close_center": round(centre, 2),
        "lean": lean,
        "confidence": confidence,
        "band_width_pct": round((hi - lo) / close, 4) if close else 0,
        "model": model_name,
        "sigma_daily_pct": round(sigma_forecast * 100, 3),
        "sigma_annual_pct": round(vol.annualize(sigma_forecast) * 100, 1),
        "k": round(k, 3),
        "shift_breakdown": {
            "sentiment": round(sent_shift, 3),
            "technical": round(tech_shift, 3),
            "total": round(shift, 3),
        },
        "note": (
            f"Band from {model_name} volatility: sigma {round(sigma_forecast * 100, 2)}%/session "
            f"(~{round(vol.annualize(sigma_forecast) * 100, 1)}% annualised), multiplier k={round(k, 2)} "
            f"calibrated on this stock's own history. Centre shifted "
            f"{'+' if shift >= 0 else ''}{round(shift, 2)} "
            f"({'+' if sent_shift >= 0 else ''}{round(sent_shift, 2)} from {sample_size} headlines, "
            f"{'+' if tech_shift >= 0 else ''}{round(tech_shift, 2)} technical). "
            f"Width reflects volatility only — sentiment moves the centre, never the width."
        ),
    }
