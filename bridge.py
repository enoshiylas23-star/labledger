import csv
import io
import json
import os
import socket
import sqlite3
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "labledger.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    vendor TEXT,
    model TEXT,
    serial TEXT,
    connection TEXT NOT NULL DEFAULT 'tcp',
    host TEXT,
    port INTEGER,
    api_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bridge_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER REFERENCES instruments(id),
    kind TEXT NOT NULL DEFAULT 'spectrum',
    compound TEXT,
    payload_json TEXT NOT NULL,
    raw_csv TEXT,
    consumed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

_state = {"thread": None, "port": None, "host": None, "last_error": None, "connections": 0}


def connect_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init(db):
    for stmt in SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            db.execute(stmt)


def parse_csv(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("empty CSV")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("CSV needs at least a header and one data row")
    start = 0
    header = rows[0]
    try:
        float(header[0].strip())
        header = None
    except ValueError:
        start = 1
    points = []
    for r in rows[start:]:
        if len(r) < 2:
            continue
        try:
            x = float(r[0].strip().replace(",", ""))
            y = float(r[1].strip().replace(",", ""))
        except ValueError:
            continue
        points.append([x, y])
    if len(points) < 5:
        raise ValueError("need at least 5 numeric x/y rows")
    kind = "spectrum" if points[-1][0] > points[0][0] else "series"
    return {"kind": kind, "points": points, "header": [h.strip() for h in header] if header else []}


def auth(db, api_key):
    if not api_key:
        return None
    return db.execute("SELECT * FROM instruments WHERE api_key = ?", (api_key,)).fetchone()


def enqueue(db, inst, kind, compound, payload, raw_csv):
    cur = db.execute(
        "INSERT INTO bridge_queue (instrument_id, kind, compound, payload_json, raw_csv, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (inst["id"], kind, compound, json.dumps(payload), raw_csv, _now()),
    )
    db.commit()
    return cur.lastrowid


def handle_payload(db, data):
    inst = auth(db, data.get("api_key"))
    if inst is None:
        raise PermissionError("unknown instrument or bad API key")
    if data.get("points"):
        payload = {"kind": data.get("kind", "spectrum"), "points": data["points"]}
    else:
        payload = parse_csv(data.get("csv", ""))
    kind = data.get("kind") or payload.get("kind", "spectrum")
    qid = enqueue(db, inst, kind, data.get("compound"), payload, data.get("csv"))
    return {"queue_id": qid, "instrument": inst["name"], "points": len(payload["points"])}


def take_latest(db, instrument_id):
    row = db.execute(
        "SELECT q.* FROM bridge_queue q WHERE q.instrument_id = ? AND q.consumed = 0 ORDER BY q.id DESC LIMIT 1",
        (instrument_id,),
    ).fetchone()
    if row:
        db.execute("UPDATE bridge_queue SET consumed = 1 WHERE id = ?", (row["id"],))
        db.commit()
    return row


def queue_stats(db):
    total = db.execute("SELECT COUNT(*) c FROM bridge_queue").fetchone()["c"]
    pending = db.execute("SELECT COUNT(*) c FROM bridge_queue WHERE consumed = 0").fetchone()["c"]
    return {"total": total, "pending": pending}


def status():
    return dict(_state)


def _now():
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _client(sock, addr):
    try:
        sock.settimeout(10)
        buf = b""
        while b"\n" not in buf and len(buf) < 4 * 1024 * 1024:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        raw = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            sock.sendall(b'{"ok": false, "error": "send one JSON object per line"}')
            return
        db = connect_db()
        try:
            init(db)
            result = handle_payload(db, data)
            result["ok"] = True
            sock.sendall(json.dumps(result).encode())
            _state["connections"] += 1
        except PermissionError as e:
            sock.sendall(json.dumps({"ok": False, "error": str(e)}).encode())
        except ValueError as e:
            sock.sendall(json.dumps({"ok": False, "error": str(e)}).encode())
        finally:
            db.close()
    except OSError as e:
        _state["last_error"] = str(e)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def start_tcp(host="127.0.0.1", port=5056):
    if _state.get("thread") and _state["thread"].is_alive():
        return _state
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((host, port))
    except OSError as e:
        _state["last_error"] = str(e)
        return _state
    server.listen(8)

    def loop():
        while True:
            try:
                sock, addr = server.accept()
            except OSError:
                break
            threading.Thread(target=_client, args=(sock, addr), daemon=True).start()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    _state.update({"thread": t, "host": host, "port": port})
    time.sleep(0.05)
    return _state
