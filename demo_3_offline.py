"""Section 3: local-first. Saving works with no network; the outbox waits."""
import os, tempfile
import client
from server import make_server

db = client.open_db(os.path.join(tempfile.mkdtemp(), "entries.db"))
for name, village, members in [("Amina Said", "Kilifi", 5),
                               ("Juma Mwangi", "Malindi", 3),
                               ("Rehema Ali", "Watamu", 7)]:
    client.save(db, {"name": name, "village": village, "members": members})

def status():
    e = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    o = db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    print(f"  local: {e} entries, {o} in outbox")

print("1) Saved 3 entries with no server running")
status()

print("2) Try to sync while offline")
s = client.make_session(backoff_factor=0.1)
client.sync(db, s, "http://127.0.0.1:9")   # nothing listens on port 9
status()

print("3) Network is back")
srv, api = make_server()
print("  synced", client.sync(db, s, api))
status()
srv.shutdown()
