"""Section 1: the defaults hurt. Run silent_server.py first."""
import sys, time
import httpx, requests

URL = "http://127.0.0.1:8000/entries"

def timed(label, fn):
    start = time.perf_counter()
    try:
        fn()
    except Exception as e:
        print(f"{label}: {type(e).__name__} after {time.perf_counter() - start:.1f}s")

if sys.argv[1:] == ["hang"]:
    print("requests.get(URL) with no timeout... (Ctrl+C to stop)")
    requests.get(URL)
else:
    timed("requests, timeout=(3.05, 5)", lambda: requests.get(URL, timeout=(3.05, 5)))
    timed("httpx, default timeout", lambda: httpx.get(URL))
