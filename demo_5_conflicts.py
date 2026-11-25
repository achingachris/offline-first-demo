"""Section 4: conflicts with version numbers (If-Match -> 412)."""
import requests
from server import make_server

srv, api = make_server()
created = requests.post(f"{api}/entries",
                        json={"id": "hh-001", "name": "Amina Said", "members": 5}).json()
print("created", created)

# Two field officers both downloaded version 1 while offline
officer_a = {"name": "Amina Said", "members": 6}
officer_b = {"name": "Amina Said", "members": 4}

r = requests.put(f"{api}/entries/hh-001", json=officer_a, headers={"If-Match": '"1"'})
print("officer A:", r.status_code, r.json())

r = requests.put(f"{api}/entries/hh-001", json=officer_b, headers={"If-Match": '"1"'})
print("officer B:", r.status_code, "-> server has", r.json())
print("B now merges or asks the user, then retries with If-Match:", r.headers["ETag"])
srv.shutdown()
