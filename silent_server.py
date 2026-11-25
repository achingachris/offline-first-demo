"""Accepts TCP connections and never replies: simulates a stalled network."""
import socket

HOST, PORT = "127.0.0.1", 8000

with socket.create_server((HOST, PORT)) as srv:
    print(f"Silent server on http://{HOST}:{PORT} (accepts, never answers)")
    conns = []
    while True:
        conn, addr = srv.accept()
        conns.append(conn)  # keep it open, say nothing
        print("connection from", addr)
