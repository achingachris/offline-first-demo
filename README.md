# Offline First: demo repo

Companion code for the PyCon Tanzania 2026 talk by Chris Achinga, "Offline First: Building Python Tools for Low-Connectivity Environments".

An offline data-entry tool (household records: name, village, members) plus a stdlib-only API server with a seeded network-failure simulator, so every failure in the talk can be reproduced.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Files

| File | What it is |
|---|---|
| `server.py` | Demo API with a failure simulator: `drop`, `lost`, `unavailable` (503 + Retry-After), `slow`; seeded |
| `client.py` | Offline data-entry client: SQLite first, outbox, idempotent sync |
| `silent_server.py` | Accepts connections, never replies |
| `demo_1_timeouts.py` | The defaults hurt: requests hangs, httpx times out |
| `demo_2_retries.py` | Backoff + jitter, Retry-After, POST not retried, tenacity |
| `demo_3_offline.py` | Save offline, outbox waits, sync when back |
| `demo_4_safe_sync.py` | Naive retries duplicate; idempotency keys don't; resumable sync |
| `demo_5_conflicts.py` | Version numbers with If-Match → 412 |
| `demo_6_less_data.py` | gzip, ETag/304, changed fields only |

## Run

```bash
# Section 1 (two terminals)
python silent_server.py
python demo_1_timeouts.py hang   # hangs: Ctrl+C
python demo_1_timeouts.py        # both time out after 5s

# Sections 2–5 (each starts its own server)
python demo_2_retries.py
python demo_3_offline.py
python demo_4_safe_sync.py
python demo_5_conflicts.py
python demo_6_less_data.py

# Play with it by hand
python server.py --seed 42 --lost 0.3 --unavailable 0.1
python client.py add "Amina Said" Kilifi 5
python client.py sync http://127.0.0.1:8000
```

Tested with Python 3.13, requests 2.34, urllib3 2.8, httpx 0.28, tenacity 9.2.
