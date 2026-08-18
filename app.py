"""
News Signal - stock terminal.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000

The BUILD constant below is printed on startup, exposed at /api/version,
and shown in the UI header. If the number on screen doesn't match the one
in the terminal, you're looking at a cached or stale page -- that check
exists because "did my new code actually load?" is otherwise invisible.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory
from flask.json.provider import DefaultJSONProvider

from sources import stocks, news, symbols
import finlex
import indicators
import predictor
import volatility as vol

BUILD = "v4.2"

def _json_safe(o):
    """
    Replace NaN / Infinity with null, recursively.

    Python's json.dumps emits bare `NaN` and `Infinity` literals, which are a
    non-standard extension: json.loads accepts them, so this looks fine
    server-side, but a browser's JSON.parse rejects them and the entire
    response fails to parse. Bad market data (a halted session, a zero
    divisor) is therefore enough to break the whole page.

    The upstream fix is to drop bad bars at ingestion, which sources/stocks.py
    now does. This is the backstop so a NaN arising anywhere else -- a new
    indicator, a division by zero in a future model -- degrades to a missing
    value instead of a blank screen.
    """
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o


class SafeJSONProvider(DefaultJSONProvider):
    def dumps(self, obj, **kwargs):
        return super().dumps(_json_safe(obj), **kwargs)


app = Flask(__name__, static_folder="static", static_url_path="")
app.json = SafeJSONProvider(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]

VALID_TICKER = lambda t: 0 < len(t) <= 14 and all(c.isalnum() or c in ".-^" for c in t)


# --------------------------------------------------------------------------
# Watchlist persistence (a plain JSON file - no database needed for this)
# --------------------------------------------------------------------------

def load_watchlist() -> list:
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        tickers = [str(t).upper() for t in data.get("tickers", []) if VALID_TICKER(str(t).upper())]
        return tickers or list(DEFAULT_WATCHLIST)
    except Exception:
        return list(DEFAULT_WATCHLIST)


def save_watchlist(tickers: list) -> bool:
    try:
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as fh:
            json.dump({"tickers": tickers}, fh, indent=2)
        return True
    except Exception:
        app.logger.exception("could not persist watchlist")
        return False


# --------------------------------------------------------------------------

@app.after_request
def no_cache(response):
    # This tool gets edited constantly; never let the browser serve a stale
    # index.html. Without this, a refresh can silently show yesterday's UI.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/version")
def api_version():
    return jsonify({"build": BUILD, "started": APP_STARTED})


@app.get("/api/watchlist")
def api_watchlist():
    return jsonify({"tickers": load_watchlist()})


@app.post("/api/watchlist")
def api_watchlist_edit():
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").lower()
    ticker = (payload.get("ticker") or "").strip().upper()

    if action not in ("add", "remove"):
        return jsonify({"error": "action must be 'add' or 'remove'"}), 400
    if not VALID_TICKER(ticker):
        return jsonify({"error": "invalid ticker"}), 400

    tickers = load_watchlist()
    if action == "add":
        if ticker in tickers:
            return jsonify({"tickers": tickers, "note": "already present"})
        if len(tickers) >= 24:
            return jsonify({"error": "watchlist is full (24 max)"}), 400
        tickers.append(ticker)
    else:
        if ticker not in tickers:
            return jsonify({"tickers": tickers, "note": "not present"})
        if len(tickers) <= 1:
            return jsonify({"error": "keep at least one ticker"}), 400
        tickers.remove(ticker)

    save_watchlist(tickers)
    return jsonify({"tickers": tickers})


@app.get("/api/search")
def api_search():
    """
    Company/ticker lookup. Curated catalog first (instant), then Yahoo's
    live search for the rest of its universe. `live` in the response tells
    the UI whether the live layer answered, so it can say so honestly
    instead of implying the catalog is the whole market.
    """
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify({"results": [], "live": False})
    try:
        return jsonify(symbols.search(q, limit=12))
    except Exception as e:
        app.logger.exception("symbol search failed")
        # Degrade to catalog-only rather than failing the request outright.
        return jsonify({"results": symbols.search_catalog(q, limit=12), "live": False, "error": str(e)})


@app.get("/api/catalog")
def api_catalog():
    return jsonify(symbols.catalog_grouped())


@app.get("/api/indices")
def api_indices():
    try:
        return jsonify({"indices": stocks.get_indices()})
    except Exception as e:
        app.logger.exception("indices fetch failed")
        return jsonify({"error": str(e), "indices": []}), 500


@app.get("/api/quotes")
def api_quotes():
    raw = request.args.get("tickers", "")
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
    if not tickers:
        tickers = load_watchlist()
    tickers = [t for t in tickers if VALID_TICKER(t)][:24]

    try:
        return jsonify({"quotes": stocks.get_quotes_batch(tickers)})
    except Exception as e:
        app.logger.exception("quotes batch failed")
        return jsonify({"error": str(e)}), 500


@app.get("/api/analyze")
def api_analyze():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "missing ?ticker= parameter"}), 400
    if not VALID_TICKER(ticker):
        return jsonify({"error": "invalid ticker format"}), 400

    try:
        # A full year is fetched even though the chart may show a month:
        # SMA200 and the walk-forward backtest need the depth.
        history, price_mode, company_name, currency = stocks.get_price_history(ticker, period="1y")

        ind = indicators.compute_all(history)
        last_close = history[-1]["close"]
        tech = indicators.technical_signal(ind, last_close)

        headlines, news_mode = news.fetch_news(ticker, company_name=company_name, limit=12)
        sentiment = finlex.aggregate(headlines)

        # Score every volatility model out-of-sample, then USE the winner
        # for the live band rather than hardcoding one. The comparison is
        # returned to the UI so the choice is visible, not hidden.
        models = predictor.compare_volatility_models(history)
        if models.get("available"):
            best = models["best_model"]
            sigma_next = vol.forecast_next_sigma(history, best, models.get("garch"))
            prediction = predictor.predict_with_model(
                history=history,
                sigma_forecast=sigma_next,
                k=models["best_k"],
                sentiment_score=sentiment["score"],
                sample_size=sentiment["sample_size"],
                technical_score=tech["score"],
                model_name=best,
            )
        else:
            # Not enough history to calibrate - fall back to the fixed ATR band.
            prediction = predictor.predict_next_session(
                history=history,
                atr=ind["atr"],
                atr_pct=ind["atr_pct"],
                sentiment_score=sentiment["score"],
                sample_size=sentiment["sample_size"],
                technical_score=tech["score"],
            )
            prediction["model"] = "ATR (fallback)"

        bt = predictor.backtest(history)

    except Exception as e:
        # The data sources already isolate + fall back internally, but if
        # anything else in this pipeline throws we return JSON rather than
        # an HTML traceback, which would break the frontend's res.json().
        app.logger.exception("analyze pipeline failed for %s", ticker)
        return jsonify({"error": f"internal error while analyzing {ticker}: {e}"}), 500

    prev_close = history[-2]["close"] if len(history) > 1 else last_close
    change = last_close - prev_close

    return jsonify({
        "build": BUILD,
        "ticker": ticker,
        "company": company_name,
        "currency": currency,
        "currency_symbol": stocks.currency_symbol(currency),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_mode": "live" if (price_mode == "live" and news_mode == "live") else "demo",
        "price_data_mode": price_mode,
        "news_data_mode": news_mode,
        "price_history": history,
        "current_price": last_close,
        "change": round(change, 2),
        "change_pct": round((change / prev_close) if prev_close else 0.0, 4),
        "indicators": ind,
        "technical": tech,
        "news": sentiment["headlines"],
        "sentiment": {
            "score": sentiment["score"],
            "label": sentiment["label"],
            "positive_count": sentiment["positive_count"],
            "negative_count": sentiment["negative_count"],
            "neutral_count": sentiment["neutral_count"],
            "sample_size": sentiment["sample_size"],
        },
        "prediction": prediction,
        "backtest": bt,
        "vol_models": models,
    })


APP_STARTED = datetime.now(timezone.utc).isoformat()

if __name__ == "__main__":
    # Bind to localhost by default. The previous 0.0.0.0 + debug=True combo
    # was a genuine security hole: Werkzeug's debugger allows arbitrary code
    # execution, and 0.0.0.0 exposes it to every machine on the network.
    # Set NEWS_SIGNAL_HOST=0.0.0.0 deliberately if you want LAN access.
    host = os.environ.get("NEWS_SIGNAL_HOST", "127.0.0.1")
    port = int(os.environ.get("NEWS_SIGNAL_PORT", "5000"))

    print("=" * 60)
    print(f"  News Signal terminal   BUILD {BUILD}")
    print(f"  http://{host}:{port}")
    print(f"  Header not showing {BUILD}?  Hard refresh: Ctrl+Shift+R")
    print("=" * 60)

    # use_reloader=False is deliberate and load-bearing:
    #   * the reloader restarts the process on ANY file change in this
    #     directory (watchdog watches the tree), and saving watchlist.json
    #     is a file change - so editing your watchlist would bounce the
    #     server and kill in-flight requests;
    #   * the restart at startup lands exactly when the browser fires its
    #     first requests, which shows up as "Failed to fetch" in the UI.
    # threaded=True so a slow yfinance call can't block every other request.
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
