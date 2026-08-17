"""
Run a function in a short-lived subprocess with a hard timeout.

Why this exists: yfinance and feedparser both make outbound network calls
through compiled dependencies (curl_cffi, lxml) that have occasionally been
seen to hang or hard-crash the interpreter on some platforms/Python
versions (e.g. a very new Python release without prebuilt wheels yet for a
compiled dependency). A plain try/except in the request thread can't catch
a native crash or an indefinite hang -- it takes the whole Flask process
(and every other request) down with it.

Isolating the call in its own subprocess means: if that subprocess hangs,
we just stop waiting on it and terminate it; if it crashes outright, only
that subprocess dies. Either way the Flask server and the rest of the app
keep running, and the caller gets a normal Python exception it can catch
and fall back to demo data for.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor


class SubprocessCallFailed(Exception):
    pass


def run_with_timeout(fn, args=(), timeout=15):
    """
    Runs fn(*args) in a fresh single-use subprocess. Returns fn's return
    value on success. Raises SubprocessCallFailed on timeout, crash, or any
    exception raised inside fn.
    """
    ex = ProcessPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(fn, *args)
        try:
            result = fut.result(timeout=timeout)
        except Exception as e:
            raise SubprocessCallFailed(str(e)) from e
        ex.shutdown(wait=False)
        return result
    except SubprocessCallFailed:
        _kill_lingering(ex)
        raise
    except Exception as e:
        _kill_lingering(ex)
        raise SubprocessCallFailed(str(e)) from e


def _kill_lingering(ex: ProcessPoolExecutor):
    # Best-effort: forcefully terminate any worker process still running
    # after a timeout/crash so it doesn't linger in the background, then
    # abandon the executor without blocking on it.
    try:
        for proc in ex._processes.values():
            try:
                proc.terminate()
            except Exception:
                pass
    except Exception:
        pass
    try:
        ex.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
