"""Section 5: gzip request bodies and conditional GETs."""
import gzip, json, random
import requests
from server import make_server

rng = random.Random(0)
villages = ["Kilifi", "Malindi", "Watamu", "Mtwapa", "Kwale"]
batch = [{"id": f"hh-{i:04d}", "name": f"Household {i}",
          "village": rng.choice(villages), "members": rng.randint(1, 9)}
         for i in range(200)]

raw = json.dumps(batch).encode()
gz = gzip.compress(raw)
print(f"1) 200 entries: {len(raw):,} bytes raw, {len(gz):,} gzipped "
      f"({100 - 100 * len(gz) // len(raw)}% smaller)")
one = json.dumps(batch[0]).encode()
print(f"   1 entry:     {len(one)} bytes raw, {len(gzip.compress(one))} gzipped (bigger!)")

srv, api = make_server()
r = requests.post(f"{api}/entries", data=gzip.compress(one),
                  headers={"Content-Encoding": "gzip",
                           "Content-Type": "application/json"})
print("2) gzipped POST accepted:", r.status_code)

r1 = requests.get(f"{api}/entries")
print(f"3) first GET:  {r1.status_code}, {len(r1.content)} bytes, ETag {r1.headers['ETag']}")
r2 = requests.get(f"{api}/entries", headers={"If-None-Match": r1.headers["ETag"]})
print(f"   second GET: {r2.status_code}, {len(r2.content)} bytes")
srv.shutdown()

def changed_fields(old: dict, new: dict) -> dict:
    return {k: v for k, v in new.items() if old.get(k) != v}

old = batch[0]
new = {**old, "members": old["members"] + 1}
full, diff = json.dumps(new).encode(), json.dumps(changed_fields(old, new)).encode()
print(f"4) edit one field: full entry {len(full)} bytes, changed fields only {len(diff)} bytes {diff.decode()}")
