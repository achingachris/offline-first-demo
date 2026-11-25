"""Demo API with a seeded network-failure simulator (stdlib only).

Endpoints
  POST   /entries         create an entry (honours Idempotency-Key, accepts gzip bodies)
  PUT    /entries/<id>    update with If-Match: "<version>"  -> 412 on conflict
  GET    /entries         list, with ETag / If-None-Match -> 304
  GET    /stats           {"rows": n, "unique_ids": m}
  DELETE /entries         reset (demo only)

Chaos (applied to GET/POST/PUT /entries), each a probability:
  drop         close the connection before the server reads the request
  lost         commit, then close without a response  (the ambiguous failure)
  unavailable  503 with Retry-After: 1
  slow         sleep before answering
"""
import argparse
import gzip
import hashlib
import json
import random
import socket
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  id      TEXT NOT NULL,              -- not UNIQUE on purpose: a naive API
  data    TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS idempotency (
  key    TEXT PRIMARY KEY,
  status INTEGER NOT NULL,
  body   TEXT NOT NULL
);
"""


class Chaos:
    def __init__(self, seed=None, drop=0.0, lost=0.0, unavailable=0.0,
                 slow=0.0, slow_seconds=3.0):
        self.rng = random.Random(seed)
        self.p = {"drop": drop, "lost": lost,
                  "unavailable": unavailable, "slow": slow}
        self.slow_seconds = slow_seconds
        self.lock = threading.Lock()

    def pick(self):
        with self.lock:
            roll = self.rng.random()
        for name, p in self.p.items():
            if roll < p:
                return name
            roll -= p
        return None


class App:
    def __init__(self, chaos, db_path=":memory:", verbose=True):
        self.chaos = chaos
        self.verbose = verbose
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()
        self.started = time.monotonic()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app: App  # set by make_server

    # ---------- helpers ----------
    def log_message(self, *args):
        pass

    def say(self, msg):
        if self.app.verbose:
            t = time.monotonic() - self.app.started
            print(f"  [server +{t:5.1f}s] {self.command} {self.path}: {msg}")

    def send_json(self, status, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def hang_up(self):
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def read_json(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw)

    def apply_chaos(self):
        """Returns 'lost' if the response must be dropped after commit,
        True if the request was already handled, else None."""
        event = self.app.chaos.pick()
        if event == "drop":
            self.say("chaos=drop (connection closed, nothing saved)")
            self.hang_up()
            return True
        if event == "unavailable":
            self.say("chaos=503 Retry-After: 1")
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_json(503, {"error": "unavailable"}, {"Retry-After": "1"})
            return True
        if event == "slow":
            self.say(f"chaos=slow ({self.app.chaos.slow_seconds}s)")
            time.sleep(self.app.chaos.slow_seconds)
        return event

    # ---------- routes ----------
    def do_POST(self):
        if self.path != "/entries":
            return self.send_json(404, {"error": "not found"})
        event = self.apply_chaos()
        if event is True:
            return
        entry = self.read_json()
        key = self.headers.get("Idempotency-Key")
        db = self.app.db
        with self.app.lock, db:
            if key:
                row = db.execute("SELECT status, body FROM idempotency WHERE key = ?",
                                 (key,)).fetchone()
                if row:
                    self.say(f"replay for key {key[:8]}… (no new row)")
                    return self.send_json(row[0], json.loads(row[1]),
                                          {"Idempotent-Replayed": "true"})
            entry_id = entry.get("id") or str(uuid.uuid4())
            db.execute("INSERT INTO entries (id, data) VALUES (?, ?)",
                       (entry_id, json.dumps(entry)))
            result = {"id": entry_id, "version": 1}
            if key:
                db.execute("INSERT INTO idempotency VALUES (?, ?, ?)",
                           (key, 201, json.dumps(result)))
        if event == "lost":
            self.say("chaos=lost (saved, response dropped)")
            return self.hang_up()
        self.say("201 created")
        self.send_json(201, result, {"ETag": '"1"'})

    def do_PUT(self):
        if not self.path.startswith("/entries/"):
            return self.send_json(404, {"error": "not found"})
        event = self.apply_chaos()
        if event is True:
            return
        entry_id = self.path.rsplit("/", 1)[1]
        entry = self.read_json()
        if_match = self.headers.get("If-Match", "").strip('"')
        if not if_match.isdigit():
            return self.send_json(428, {"error": "If-Match required"})
        db = self.app.db
        with self.app.lock, db:
            cur = db.execute(
                "UPDATE entries SET data = ?, version = version + 1"
                " WHERE id = ? AND version = ?",
                (json.dumps(entry), entry_id, int(if_match)))
            row = db.execute("SELECT data, version FROM entries WHERE id = ?",
                             (entry_id,)).fetchone()
        if row is None:
            return self.send_json(404, {"error": "not found"})
        current = {"id": entry_id, "version": row[1], "data": json.loads(row[0])}
        if cur.rowcount == 0:
            self.say(f"412 (client had v{if_match}, server has v{row[1]})")
            return self.send_json(412, current, {"ETag": f'"{row[1]}"'})
        if event == "lost":
            self.say("chaos=lost (saved, response dropped)")
            return self.hang_up()
        self.say(f"200 updated to v{row[1]}")
        self.send_json(200, current, {"ETag": f'"{row[1]}"'})

    def do_GET(self):
        db = self.app.db
        if self.path == "/stats":
            with self.app.lock:
                rows, unique = db.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT json_extract(data, '$.name'))"
                    " FROM entries").fetchone()
            return self.send_json(200, {"rows": rows, "unique_names": unique})
        if self.path != "/entries":
            return self.send_json(404, {"error": "not found"})
        event = self.apply_chaos()
        if event is True:
            return
        if event == "lost":
            self.say("chaos=lost (response dropped)")
            return self.hang_up()
        with self.app.lock:
            rows = db.execute("SELECT id, data, version FROM entries ORDER BY seq").fetchall()
        body = [{"id": i, "version": v, **json.loads(d)} for i, d, v in rows]
        etag = '"' + hashlib.sha256(json.dumps(body).encode()).hexdigest()[:16] + '"'
        if self.headers.get("If-None-Match") == etag:
            self.say("304 not modified")
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        self.say(f"200 ({len(body)} entries)")
        self.send_json(200, body, {"ETag": etag})

    def do_DELETE(self):
        with self.app.lock, self.app.db:
            self.app.db.execute("DELETE FROM entries")
            self.app.db.execute("DELETE FROM idempotency")
        self.send_json(200, {"reset": True})


def make_server(chaos=None, port=0, verbose=True):
    """Start in a background thread; returns (server, base_url)."""
    app = App(chaos or Chaos(), verbose=verbose)
    handler = type("BoundHandler", (Handler,), {"app": app})
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--seed", type=int)
    for name in ("drop", "lost", "unavailable", "slow"):
        ap.add_argument(f"--{name}", type=float, default=0.0)
    a = ap.parse_args()
    srv, url = make_server(Chaos(a.seed, a.drop, a.lost, a.unavailable, a.slow), a.port)
    print(f"Serving on {url}  chaos={vars(a)}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
