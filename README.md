# News Signal — Stock Terminal

**BUILD v3.1**

A local terminal-style dashboard that combines three things for a stock: recent
**price volatility**, a set of standard **technical indicators**, and the
**sentiment of recent news headlines** — and turns them into a next-session
predicted price band with a bullish/bearish lean.

---

## Read this first

No tool can reliably predict tomorrow's exact high and low. If one could, that
edge would be arbitraged away in minutes by firms with vastly more data and
speed. Direction at a one-day horizon is close to a coin flip, and markets price
in public news very quickly.

What *is* tractable is estimating a plausible **range** from recent volatility —
that's a well-understood statistical property, unlike direction.

So this app does two honest things instead of one dishonest one:

1. It shows the range as **±0.6 × ATR** around the last close, nudged by
   sentiment and technicals, with each nudge **capped** so a "signal" can never
   imply more movement than the stock's own volatility supports.
2. It **backtests that band against real history** and shows you the result —
   including the uncomfortable part.

### The backtest is the point

The Backtest panel walks forward through the stock's history. At each past
session it computes the band using **only data available at that point** (no
lookahead), then checks whether the next session's close actually landed inside
it. It reports the hit rate at three band widths:

| Band | Typical hit rate | Typical width |
|---|---|---|
| ±0.6 ATR | ~55% | ~2.9% of price |
| ±1.0 ATR | ~79% | ~4.9% of price |
| ±1.5 ATR | ~95% | ~7.3% of price |

That table is the most useful thing in the app. **A wider band always hits more
often and tells you less.** Any "prediction accuracy" number quoted without its
band width is meaningless — including any you see on commercial stock-prediction
sites.

**Limitation, stated plainly:** the backtest covers the **volatility baseline
only**. There's no archive of historical news sentiment here, so the
sentiment/technical nudge is excluded from it. The backtest says nothing about
whether the news scoring works, in either direction.

---

## What's in it

**Finding companies**
- **Search by name or ticker** — type "Tata", "Apple", "hindustan unilever" or a raw
  symbol. Autocomplete with arrow-key navigation.
- Two search layers: a **bundled catalog of 229 major companies** (instant, works
  offline) plus **live Yahoo Finance symbol search**, which covers its entire
  universe — roughly 100,000+ listed securities across global exchanges.
- **Browse panel** grouped by market and sector: United States (133), India/NSE (66),
  Global ADRs (22), ETFs (8). Click to analyze, `+` to add to watchlist.

The catalog is a convenience shortlist, **not** a restriction: any listed company
Yahoo carries can be analyzed, whether or not it appears in the bundled list.

**Market data**
- Index strip: S&P 500, NASDAQ, Dow, NIFTY 50, SENSEX
- Editable watchlist (persists to `watchlist.json`) with sparklines
- Top movers, computed from your watchlist

**Per-stock analysis**
- Candlestick + volume chart with SMA20/SMA50 overlays; 1M/3M/6M/1Y timeframes
  (auto-switches to a line chart past 120 sessions, where candles stop being legible)
- Technical indicators: RSI(14), SMA 20/50/200, MACD + crossover, Bollinger %B,
  52-week range position, nearest swing support/resistance, volume vs average, ATR
- Combined signal panel: technical lean, news sentiment, and the merged view,
  each with its reasoning shown
- Next-session predicted band + the backtest above
- Headline feed with per-headline sentiment and recency weight

**Currency aware** — `.NS`/`.BO` tickers display in ₹, US tickers in $, etc.
Detected from the exchange, not guessed from the number.

---

## Setup

Requires Python 3.9+. **A virtual environment is recommended** — it isolates
this project from anything else installed on your system Python.

```powershell
cd stock-predictor
python -m venv venv
.\venv\Scripts\Activate.ps1     # Windows PowerShell
# source venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
python app.py
```

If PowerShell blocks the activate script, run once:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

Then open **http://127.0.0.1:5000**

No API keys needed — yfinance and the RSS feeds are free and keyless.

### Confirming you're running the current code

The build number is printed in the terminal on startup, shown in the UI header,
and served at `/api/version`. **If the header doesn't match the terminal, you're
looking at a cached page** — hard refresh with `Ctrl+Shift+R`. (The app sends
no-cache headers, so this shouldn't happen, but the stamp makes it verifiable
rather than a guess.)

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `/` | focus the ticker box |
| `Enter` | analyze |
| `r` | refresh everything |

Plus an `auto: 60s` toggle in the header for hands-off refreshing.

---

## Where the data comes from

- **Prices** — Yahoo Finance via `yfinance` (free, keyless)
- **News** — free RSS: Yahoo Finance per-ticker, CNBC, MarketWatch,
  Investing.com, Economic Times, Business Standard. Headlines are filtered to
  ones mentioning the ticker or a company alias, and **deduplicated** across
  feeds (the same wire story appearing in three feeds would otherwise
  triple-count its sentiment and fake a stronger signal than exists).

**Demo fallback:** if live feeds are unreachable, the app generates clearly
labelled synthetic data so nothing breaks. Watch the `LIVE` / `DEMO DATA` badge —
fake prices are never presented as real.

---

## Architecture

```
app.py              Flask routes, build stamp, no-cache headers, watchlist persistence
proc_isolate.py     runs network calls in a subprocess with a timeout
sources/stocks.py   prices, batch quotes, indices, currency detection
sources/news.py     RSS fetching, alias filtering, dedup
sources/symbols.py  company catalog + merged catalog/live symbol search
indicators.py       RSI, SMA/EMA, MACD, Bollinger, ATR, 52w, S/R  (pure functions)
finlex.py           finance sentiment lexicon: phrases, negation, intensifiers, recency
predictor.py        band construction + walk-forward backtest
static/index.html   the whole UI, single self-contained file, zero CDN deps
```

**Why the subprocess isolation:** `yfinance` reaches the network through compiled
dependencies (`curl_cffi`). Those can hang or hard-crash the interpreter on some
platform/Python combinations — and a plain `try/except` cannot catch a native
crash, so it would take the whole server down with it. Running each fetch in its
own short-lived subprocess means a crash or hang kills only that subprocess; the
server stays up and falls back to demo data.

**Why a custom sentiment lexicon** instead of VADER/TextBlob: general-purpose
sentiment models systematically misread financial language. "Beats estimates" is
strongly bullish but contains no generically positive word. "Volatile" is neutral
in everyday English and negative in markets. "Profit warning" contains "profit."
The lexicon here scores multi-word phrases *before* single words and masks their
span, so `profit warning` scores −0.60 rather than +0.50. It also handles
negation ("did not rise") and intensifiers on both sides ("falls sharply",
"sharply lower").

It is still a keyword model. It can't read sarcasm, nuance, or a number in a
table. Treat the score as a rough tone gauge, not comprehension.

---

## Ideas for extending it

- **Log predictions daily** and score them later — the only way to learn whether
  the sentiment nudge helps or hurts. Right now the backtest can't test it.
- **Swap in a trained model** for `predictor.py`, but keep the ATR band as a
  sanity floor. Be very skeptical of backtests that look great; that's usually
  lookahead bias or overfitting, not an edge.
- **Better news** via NewsAPI.org or GNews free tiers (~100 req/day) for
  proper ticker-targeted search instead of RSS filtering.
- **Alerts** — a scheduled job hitting `/api/analyze` and pinging you when a
  stock crosses a threshold you care about.

---

## Disclaimer

Personal/educational project. **Not investment advice.** The predictions are not
guaranteed to be accurate — treat any output as one input among many, never as a
reason to trade. Markets are influenced by far more than recent headlines, and
short-term price movement is notoriously hard to predict with far more
sophisticated tools than this.
