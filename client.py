"""Offline data-entry client: SQLite first, outbox, idempotent sync.

  python client.py add "Amina Said" Kilifi 5
  python client.py status
  python client.py sync http://127.0.0.1:8000
"""
import json
import sqlite3
import sys
import uuid

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id      TEXT PRIMARY KEY,           -- uuid4 made on the device
  name    TEXT NOT NULL,
  village TEXT NOT NULL,
  members INTEGER NOT NULL,
  version INTEGER NOT NULL DEFAULT 0  -- set by the server
);
CREATE TABLE IF NOT EXISTS outbox (
  seq             INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT UNIQUE NOT NULL,
  entry_id        TEXT NOT NULL,
  payload         TEXT NOT NULL,      -- JSON
  created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def open_db(path="entries.db"):
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def save(db, entry: dict) -> str:
    entry = {"id": str(uuid.uuid4()), **entry}
    with db:  # one transaction: both rows or neither
        db.execute(
            "INSERT INTO entries (id, name, village, members)"
            " VALUES (:id, :name, :village, :members)"
            " ON CONFLICT(id) DO UPDATE SET"
            " name = :name, village = :village, members = :members",
            entry)
        db.execute(
            "INSERT INTO outbox (idempotency_key, entry_id, payload)"
            " VALUES (?, ?, ?)",
            (str(uuid.uuid4()), entry["id"], json.dumps(entry)))
    return entry["id"]


def make_session(backoff_factor=0.5):
    retry = Retry(
        total=5,
        backoff_factor=backoff_factor,
        backoff_jitter=0.3,
        status_forcelist=[429, 502, 503, 504],
        # POST is safe to retry ONLY because every request carries an idempotency key
        allowed_methods=Retry.DEFAULT_ALLOWED_METHODS | {"POST"},
        respect_retry_after_header=True,
    )
    s = requests.Session()
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def sync(db, s, api, batch_size=50) -> int:
    """Push the outbox in order. Returns how many rows were confirmed."""
    rows = db.execute(
        "SELECT seq, idempotency_key, entry_id, payload FROM outbox"
        " ORDER BY seq LIMIT ?", (batch_size,)).fetchall()
    done = 0
    for seq, key, entry_id, payload in rows:
        try:
            r = s.post(f"{api}/entries", data=payload, timeout=(3.05, 10),
                       headers={"Idempotency-Key": key,
                                "Content-Type": "application/json"})
        except requests.RequestException as e:
            print(f"  offline ({type(e).__name__}); {len(rows) - done} left in outbox")
            return done
        if not r.ok:
            print(f"  server said {r.status_code}; will retry later")
            return done
        with db:
            db.execute("UPDATE entries SET version = ? WHERE id = ?",
                       (r.json()["version"], entry_id))
            db.execute("DELETE FROM outbox WHERE seq = ?", (seq,))
        done += 1
    return done


if __name__ == "__main__":
    db = open_db()
    cmd, *args = sys.argv[1:] or ["status"]
    if cmd == "add":
        name, village, members = args
        print("saved", save(db, {"name": name, "village": village,
                                  "members": int(members)}))
    elif cmd == "sync":
        api = args[0] if args else "http://127.0.0.1:8000"
        print("synced", sync(db, make_session(), api))
    n_entries = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    n_pending = db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    print(f"{n_entries} entries saved locally, {n_pending} waiting to sync")
