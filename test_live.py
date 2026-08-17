"""
Standalone diagnostic — run this directly to test whether yfinance and the
news RSS feeds can reach the internet from your machine, completely outside
the Flask app. This isolates "is it yfinance/curl_cffi itself" from "is it
something in app.py".

Run:
    python test_live.py
"""
import sys
import traceback


def test_yfinance():
    print("=" * 60)
    print("Testing yfinance...")
    print("=" * 60)
    try:
        import yfinance as yf
        print(f"yfinance version: {yf.__version__}")
        tk = yf.Ticker("AAPL")
        hist = tk.history(period="5d", interval="1d")
        if hist is None or hist.empty:
            print("RESULT: yfinance ran without crashing, but returned no data.")
            print("        (Could be rate-limiting or a Yahoo Finance API change.)")
        else:
            print("RESULT: SUCCESS - got live data:")
            print(hist.tail(3))
    except Exception:
        print("RESULT: yfinance raised a Python exception (this is the GOOD kind of failure")
        print("        - it means the app's fallback would have caught it):")
        traceback.print_exc()
    except BaseException:
        print("RESULT: something more severe than a normal exception happened.")
        traceback.print_exc()


def test_feedparser():
    print()
    print("=" * 60)
    print("Testing feedparser (news RSS)...")
    print("=" * 60)
    try:
        import feedparser
        url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US"
        parsed = feedparser.parse(url)
        print(f"bozo (parse error flag): {getattr(parsed, 'bozo', None)}")
        print(f"entries found: {len(parsed.entries)}")
        if parsed.entries:
            print("RESULT: SUCCESS - sample headline:")
            print(" -", parsed.entries[0].get("title"))
        else:
            print("RESULT: feedparser ran without crashing, but got 0 entries.")
            print("        (Feed URL may have changed or be blocked.)")
    except Exception:
        print("RESULT: feedparser raised a Python exception:")
        traceback.print_exc()


if __name__ == "__main__":
    print(f"Python: {sys.version}")
    print()
    test_yfinance()
    test_feedparser()
    print()
    print("Send me everything printed above.")
