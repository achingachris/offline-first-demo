"""Section 4: naive retries create duplicates; idempotency keys don't."""
import os, tempfile
import requests
import client
from server import Chaos, make_server

N = 20
CHAOS = dict(seed=42, lost=0.3)   # 30% of responses are lost AFTER the save

print(f"1) Naive client: POST {N} entries, retry on error (like a user tapping again)")
srv, api = make_server(Chaos(**CHAOS), verbose=False)
for i in range(N):
    for attempt in range(5):
        try:
            requests.post(f"{api}/entries", json={"name": f"person-{i}"},
                          timeout=(3.05, 10))
            break
        except requests.ConnectionError:
            continue
print("  server:", requests.get(f"{api}/stats").json(), f"(expected {N})")
srv.shutdown()

print(f"\n2) Outbox + idempotency keys, same chaos")
srv, api = make_server(Chaos(**CHAOS), verbose=False)
db = client.open_db(os.path.join(tempfile.mkdtemp(), "entries.db"))
for i in range(N):
    client.save(db, {"name": f"person-{i}", "village": "Kilifi", "members": 1})
s = client.make_session(backoff_factor=0.05)
total = client.sync(db, s, api)
print(f"  synced {total}")
print("  server:", requests.get(f"{api}/stats").json(), f"(expected {N})")
srv.shutdown()

print("\n3) Resumable: connection drops halfway, next sync carries on")
srv, api = make_server(Chaos(seed=5, drop=0.1), verbose=False)
db = client.open_db(os.path.join(tempfile.mkdtemp(), "entries.db"))
for i in range(N):
    client.save(db, {"name": f"person-{i}", "village": "Kilifi", "members": 1})
no_retry = requests.Session()           # no retries: show the outbox resuming
round_ = 0
while db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]:
    round_ += 1
    n = client.sync(db, no_retry, api)
    left = db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    print(f"  sync run {round_}: +{n} confirmed, {left} left")
print("  server:", requests.get(f"{api}/stats").json(), f"(expected {N})")
srv.shutdown()
