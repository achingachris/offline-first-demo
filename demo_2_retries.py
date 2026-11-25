"""Section 2: fail well. Backoff + jitter, Retry-After, and why POST is not retried."""
import requests
from requests.adapters import HTTPAdapter
from tenacity import (retry, stop_after_attempt, wait_random_exponential,
                      retry_if_exception_type)
from urllib3.util.retry import Retry

from server import Chaos, make_server

print("\n1) urllib3.Retry on GET against a flaky server (50% drop)")
srv, api = make_server(Chaos(seed=9, drop=0.5))
retry_cfg = Retry(total=5, backoff_factor=0.5, backoff_jitter=0.3,
                  status_forcelist=[429, 502, 503, 504],
                  respect_retry_after_header=True)
s = requests.Session()
s.mount("http://", HTTPAdapter(max_retries=retry_cfg))
r = s.get(f"{api}/entries", timeout=(3.05, 10))
print("  client got", r.status_code)
srv.shutdown()

print("\n2) 503 + Retry-After: 1 is honoured")
srv, api = make_server(Chaos(seed=1, unavailable=0.6))
r = s.get(f"{api}/entries", timeout=(3.05, 10))
print("  client got", r.status_code)
srv.shutdown()

print("\n3) Same Retry, but a POST whose response is lost: NOT retried by default")
srv, api = make_server(Chaos(lost=1.0))
try:
    s.post(f"{api}/entries", json={"name": "Amina"}, timeout=(3.05, 10))
except requests.ConnectionError as e:
    print("  client raised", type(e).__name__, "-> no retry, but the server saved it")
print("  server stats:", requests.get(f"{api}/stats").json())
srv.shutdown()

print("\n4) tenacity around your own function")
srv, api = make_server(Chaos(seed=7, drop=0.6), verbose=False)
attempts = []

@retry(wait=wait_random_exponential(multiplier=0.5, max=30),
       stop=stop_after_attempt(6),
       retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)))
def fetch_entries():
    attempts.append(1)
    return requests.get(f"{api}/entries", timeout=(3.05, 10)).json()

fetch_entries()
print(f"  succeeded after {len(attempts)} attempt(s)")
srv.shutdown()
