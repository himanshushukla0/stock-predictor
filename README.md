# News Signal — Stock Terminal

**BUILD v4.0**

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

### Why not rewrite it in C or C++?

Because it would change nothing that matters here. Language choice affects
*speed*, not *predictive accuracy* — and speed isn't the bottleneck anyway.
Measured on this machine, for one `/api/analyze` request:

| Stage | Time |
|---|---|
| yfinance history fetch (network) | ~800–2000 ms |
| RSS news fetch (network) | ~600–2500 ms |
| subprocess isolation ×2 | ~12 ms |
| **all Python math** (indicators + backtest + sentiment + GARCH fit) | **~31 ms** |

The math is roughly **0.4% of a request**. A C++ rewrite at a generous 30×
speedup would take ~31 ms down to ~1 ms — saving 30 ms out of ~2800 ms, which
no user could perceive. The remaining 99.6% is waiting on Yahoo's servers, and
C++ waits exactly as long as Python does.

C++ *is* the right tool in finance when the workload is compute-bound:
high-frequency trading where microseconds are money, tick-level feeds at
millions of events/second, Monte-Carlo option pricing, or backtesting thousands
of symbols across decades. A personal dashboard analysing one stock of daily
bars at a time is none of those.

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

## Volatility model bake-off (v4.0)

Direction is near-unpredictable. **Volatility is not** — it clusters, and that
clustering is one of the most robust empirical facts in finance (Engle won the
2003 Nobel for modelling it). So the honest way to make this "more accurate" is
to forecast the *range* better, and to prove the improvement rather than claim it.

Four models compete on every stock:

| Model | What it does |
|---|---|
| **ATR** | Average True Range / price — flat window, ignores clustering |
| **STDEV** | rolling standard deviation of log returns |
| **EWMA** | RiskMetrics exponentially-weighted variance (λ = 0.94) |
| **GARCH(1,1)** | MLE fit with variance targeting; adds mean reversion EWMA lacks |

**The comparison method matters more than the models.** Each is calibrated on a
training window to aim at the *same* coverage, then scored out-of-sample by
**Winkler interval score** — band width plus a penalty proportional to how far
outside the interval the outcome landed. Because all models target identical
coverage, none can win by being wider; because misses are penalised, none can
win by shrinking. Lower is better. GARCH parameters are fitted on training
returns only. The winner drives the live band, and the full table is shown in
the SIGNALS tab so the choice is visible.

### How this was verified

Claims about a forecasting method are worth nothing without a test that could
have failed. Three were run:

1. **Does it detect real structure?** On synthetic data *with* volatility
   clustering, GARCH wins with a **narrower** band (1.77% vs ATR's 1.88%).
   On a constant-volatility control series, all four collapse to within 0.5% of
   each other and GARCH fits α ≈ 0.01 — correctly reporting there is nothing to
   exploit. A harness that "finds" an improvement in both cases would be measuring noise.
2. **No lookahead.** Corrupting all returns after index 300 leaves every model's
   forecasts at or before index 300 bit-identical.
3. **Parameter recovery.** Fitting known GARCH series recovers α = 0.125 against
   a true 0.12. (An earlier version returned 0.39 — the likelihood was seeded on
   a short trailing average instead of the unconditional variance. Fixing the
   seed and adding a burn-in fixed the fit.)

A 30-series stability sweep produced no invalid metrics, correctly declined
short histories, and spread wins across all four models — no model dominates,
which is what an honest selector looks like.

**Expect modest gains.** On the test data the winner beat ATR by roughly 0.6–1.7%
on Winkler score. That is a real improvement, not a transformative one, and it is
reported as measured rather than inflated.

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

## Interface

**Tabbed workspace.** Five panels — OVERVIEW, CHART, SIGNALS, INTEL, MARKETS.
All panels are rendered once when a ticker loads, so switching between them is a
pure CSS toggle: **zero latency, zero refetch**. The TARGET bar above the tabs
stays pinned, so the ticker, price and day change are always on screen no matter
which panel you're in.

**Four themes**, switchable from the swatches in the header (persists between
sessions):

| Theme | Feel |
|---|---|
| **Tactical** | deep navy + cyan/amber HUD — the default ops-room look |
| **Hazard** | blackout + amber/red, alert-console styling |
| **Matrix** | classic terminal green |
| **Frost** | slate + ice blue, lower intensity for long sessions |

### Keyboard shortcuts

| Key | Action |
|---|---|
| `1` – `5` | jump to tab (instant) |
| `/` | focus the search box |
| `↑` `↓` | move through search results |
| `Enter` | analyze |
| `R` | sync everything |

Plus an `AUTO 60s` toggle in the header for hands-off refreshing.

### A note on the chart colors

The series colors weren't picked by eye — they were run through a
colorblindness/contrast validator. Two findings worth recording:

- Cyan / amber / violet (price, SMA20, SMA50) pass every check with worst-case
  CVD separation ΔE 19.3.
- **Red and green at equal lightness measure ΔE 3.2 under deuteranopia** — that
  is, effectively identical to roughly 8% of men. The up-candle is therefore kept
  deliberately brighter than its "correct" band position, which lifts separation
  to ΔE 12.6. Direction is also redundantly encoded with ▲/▼ arrows everywhere,
  so color is never the only signal.

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
volatility.py       ATR / rolling-σ / EWMA / GARCH(1,1) forecasters, no lookahead
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
