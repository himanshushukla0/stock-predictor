"""
Volatility forecasting models.

WHY THIS MODULE EXISTS
----------------------
Short-term price *direction* is very close to unpredictable — that's the
efficient-market result, and no amount of engineering changes it.

Short-term *volatility* is a completely different story. Volatility
clusters: big moves are followed by big moves, quiet days by quiet days.
This is one of the most robust empirical facts in finance (Engle won the
2003 Nobel for modelling it with ARCH). It is genuinely forecastable.

So the honest way to make this app "more accurate" is not to predict
direction better — it's to predict the *range* better. That's what these
models do.

MODELS
------
  ATR      - the previous approach: Average True Range / price.
             Equal weight on the last N sessions, ignores clustering.
  STDEV    - rolling standard deviation of log returns. Same flat-window
             weakness, but a cleaner statistical baseline than ATR.
  EWMA     - RiskMetrics exponentially-weighted variance, lambda 0.94.
             Recent squared returns weigh more, so it reacts to regime
             changes instead of averaging through them.
  GARCH11  - GARCH(1,1) with variance targeting. Adds mean reversion to a
             long-run variance, which EWMA lacks (EWMA is the special case
             omega=0, alpha+beta=1).

NO LOOKAHEAD
------------
Every function returns a series where element i is the forecast for
return i, computed using only returns strictly before i. That property is
what makes the walk-forward comparison in predictor.py meaningful, and it
is asserted in the tests.
"""
from __future__ import annotations

import math

TRADING_DAYS = 252


def log_returns(history: list) -> list:
    """Daily log returns. len = len(history) - 1."""
    out = []
    for i in range(1, len(history)):
        p0, p1 = history[i - 1]["close"], history[i]["close"]
        out.append(math.log(p1 / p0) if (p0 > 0 and p1 > 0) else 0.0)
    return out


def _seed_var(rets: list, n: int = 20) -> float:
    w = rets[:n] if len(rets) >= n else rets
    if not w:
        return 1e-6
    return max(sum(r * r for r in w) / len(w), 1e-10)


# --------------------------------------------------------------------------
# Each model: returns sigma_forecast[i] for return i, using only rets[:i]
# --------------------------------------------------------------------------

def sigma_stdev(rets: list, window: int = 20) -> list:
    out, n = [], len(rets)
    for i in range(n):
        past = rets[max(0, i - window):i]
        if len(past) < 5:
            out.append(math.sqrt(_seed_var(rets)))
            continue
        m = sum(past) / len(past)
        var = sum((r - m) ** 2 for r in past) / (len(past) - 1)
        out.append(math.sqrt(max(var, 1e-10)))
    return out


def sigma_ewma(rets: list, lam: float = 0.94) -> list:
    """
    RiskMetrics EWMA:  var_t = lam*var_{t-1} + (1-lam)*r_{t-1}^2
    Appended BEFORE absorbing r_i, so the forecast never sees its own target.
    """
    var = _seed_var(rets)
    out = []
    for r in rets:
        out.append(math.sqrt(max(var, 1e-10)))
        var = lam * var + (1 - lam) * r * r
    return out


def _garch_loglik(rets: list, omega: float, alpha: float, beta: float,
                  seed_var: float, burn: int = 20) -> float:
    """
    Gaussian log-likelihood of GARCH(1,1) params (higher = better fit).

    Two details that matter more than they look:
      * the recursion is seeded at the UNCONDITIONAL variance, not at a
        short trailing average - a crude seed biases the fit toward
        whatever the first few sessions happened to do;
      * the first `burn` observations are excluded from the score, so the
        remaining seed sensitivity doesn't drive parameter selection.
    Without these, the fit recovers roughly the right persistence but
    splits it badly between alpha and beta, which makes the forecast
    over-react to single shocks.
    """
    var = seed_var
    ll = 0.0
    for i, r in enumerate(rets):
        if i >= burn:
            ll += -0.5 * (math.log(var) + (r * r) / var)
        var = max(omega + alpha * r * r + beta * var, 1e-12)
    return ll


def fit_garch11(rets: list):
    """
    Fit GARCH(1,1) by maximum likelihood using *variance targeting*:
    omega is pinned so the model's long-run variance equals the sample
    variance, leaving a 2-D search over (alpha, beta). That's standard
    practice — it's more stable than a free 3-D fit on a few hundred
    points, which is all daily data gives us.

    Coarse grid, then a local refine. Deliberately not scipy: this keeps
    the dependency list small and the search is tiny.
    """
    if len(rets) < 60:
        return None
    m = sum(rets) / len(rets)
    uncond = sum((r - m) ** 2 for r in rets) / len(rets)
    if uncond <= 0:
        return None

    best = None
    def try_pair(a, b):
        nonlocal best
        if a <= 0 or b <= 0 or a + b >= 0.999:
            return
        omega = uncond * (1 - a - b)
        if omega <= 0:
            return
        ll = _garch_loglik(rets, omega, a, b, seed_var=uncond)
        if best is None or ll > best[0]:
            best = (ll, omega, a, b)

    for a in [i / 100 for i in range(2, 41, 2)]:          # 0.02 .. 0.40
        for b in [i / 100 for i in range(60, 98, 2)]:      # 0.60 .. 0.96
            try_pair(a, b)
    if best is None:
        return None

    _, _, a0, b0 = best
    for da in (-0.01, -0.005, 0, 0.005, 0.01):
        for db in (-0.01, -0.005, 0, 0.005, 0.01):
            try_pair(a0 + da, b0 + db)

    ll, omega, alpha, beta = best
    return {"omega": omega, "alpha": alpha, "beta": beta,
            "persistence": round(alpha + beta, 4), "loglik": round(ll, 2)}


def sigma_garch(rets: list, params: dict | None = None) -> list:
    """
    Filter a GARCH(1,1) variance path. `params` should be fitted on a
    TRAINING slice only when this is used for out-of-sample evaluation —
    passing params fitted on the whole series would leak the future.
    """
    if params is None:
        params = fit_garch11(rets)
    if params is None:
        return sigma_ewma(rets)
    omega, alpha, beta = params["omega"], params["alpha"], params["beta"]
    # Seed the filter at the model's own long-run variance for consistency
    # with how the parameters were fitted.
    denom = 1.0 - alpha - beta
    var = (omega / denom) if denom > 1e-6 else _seed_var(rets)
    out = []
    for r in rets:
        out.append(math.sqrt(max(var, 1e-10)))
        var = max(omega + alpha * r * r + beta * var, 1e-12)
    return out


def sigma_atr(history: list, period: int = 14) -> list:
    """
    ATR expressed as a comparable per-session sigma (fraction of price), so
    the old approach can be scored on the same axis as the return-based
    models. Element i aligns with return i (i.e. bar i+1 in `history`).
    """
    out = []
    trs = []
    for i in range(1, len(history)):
        prev_c = history[i - 1]["close"]
        # ATR available BEFORE bar i is computed from bars up to i-1
        window = trs[-period:] if len(trs) >= period else trs
        if window and prev_c > 0:
            out.append(max(sum(window) / len(window) / prev_c, 1e-10))
        else:
            out.append(0.015)  # bootstrap before any TR exists
        tr = max(history[i]["high"] - history[i]["low"],
                 abs(history[i]["high"] - prev_c),
                 abs(history[i]["low"] - prev_c))
        trs.append(tr)
    return out


MODELS = ("ATR", "STDEV", "EWMA", "GARCH11")


def all_sigmas(history: list, garch_params: dict | None = None) -> dict:
    """Every model's aligned sigma-forecast series for one history."""
    rets = log_returns(history)
    return {
        "ATR": sigma_atr(history),
        "STDEV": sigma_stdev(rets),
        "EWMA": sigma_ewma(rets),
        "GARCH11": sigma_garch(rets, garch_params),
    }


def annualize(sigma_daily: float) -> float:
    return sigma_daily * math.sqrt(TRADING_DAYS)


def forecast_next_sigma(history: list, model: str = "EWMA",
                        garch_params: dict | None = None) -> float:
    """
    One-step-ahead sigma for the session AFTER the last bar in `history`,
    as a fraction of price.

    The series functions above stop at the last observed return; this steps
    the recursion one further so there is an actual forward forecast rather
    than reusing the last in-sample value.
    """
    rets = log_returns(history)
    if not rets:
        return 0.015

    if model == "ATR":
        trs = []
        for i in range(1, len(history)):
            prev_c = history[i - 1]["close"]
            trs.append(max(history[i]["high"] - history[i]["low"],
                           abs(history[i]["high"] - prev_c),
                           abs(history[i]["low"] - prev_c)))
        w = trs[-14:] if len(trs) >= 14 else trs
        close = history[-1]["close"] or 1.0
        return max((sum(w) / len(w)) / close, 1e-6) if w else 0.015

    if model == "STDEV":
        past = rets[-20:]
        if len(past) < 5:
            return math.sqrt(_seed_var(rets))
        m = sum(past) / len(past)
        return math.sqrt(max(sum((r - m) ** 2 for r in past) / (len(past) - 1), 1e-10))

    if model == "GARCH11":
        p = garch_params or fit_garch11(rets)
        if p:
            denom = 1.0 - p["alpha"] - p["beta"]
            var = (p["omega"] / denom) if denom > 1e-6 else _seed_var(rets)
            for r in rets:
                var = max(p["omega"] + p["alpha"] * r * r + p["beta"] * var, 1e-12)
            return math.sqrt(var)
        model = "EWMA"  # fall through

    # EWMA (also the fallback)
    var = _seed_var(rets)
    for r in rets:
        var = 0.94 * var + 0.06 * r * r
    return math.sqrt(max(var, 1e-10))
