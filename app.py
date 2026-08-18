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
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

from sources import stocks, news
import companies
import finlex
import indicators
import predictor

BUILD = "v3.0"

app = Flask(__name__, static_folder="static", static_url_path="")

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


@app.get("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    return jsonify(companies.search(q))


@app.get("/api/companies")
def api_companies():
    return jsonify(companies.catalog_grouped())



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

        prediction = predictor.predict_next_session(
            history=history,
            atr=ind["atr"],
            atr_pct=ind["atr_pct"],
            sentiment_score=sentiment["score"],
            sample_size=sentiment["sample_size"],
            technical_score=tech["score"],
        )
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
    })


APP_STARTED = datetime.now(timezone.utc).isoformat()

if __name__ == "__main__":
    print("=" * 58)
    print(f"  News Signal terminal  BUILD {BUILD}")
    print(f"  If the UI header doesn't show {BUILD}, you're seeing a")
    print("  cached page - hard refresh with Ctrl+Shift+R.")
    print("=" * 58)
    app.run(host="0.0.0.0", port=5000, debug=True)
