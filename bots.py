import datetime

import ai

SCHEMA = """
CREATE TABLE IF NOT EXISTS bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    scope TEXT NOT NULL,
    mandate TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL REFERENCES bots(id),
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

KINDS = ["project", "researcher", "company"]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def init(db):
    for stmt in SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            db.execute(stmt)


def create(db, name, kind, scope, mandate):
    cur = db.execute(
        "INSERT INTO bots (name, kind, scope, mandate, created_at) VALUES (?, ?, ?, ?, ?)",
        (name.strip(), kind, scope.strip(), mandate.strip(), _now()),
    )
    db.commit()
    return cur.lastrowid


def delete(db, bot_id):
    db.execute("DELETE FROM bot_notes WHERE bot_id = ?", (bot_id,))
    db.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
    db.commit()


def all(db):
    bots = db.execute("SELECT * FROM bots ORDER BY id").fetchall()
    out = []
    for b in bots:
        n = db.execute("SELECT COUNT(*) c FROM bot_notes WHERE bot_id = ?", (b["id"],)).fetchone()["c"]
        d = dict(b)
        d["note_count"] = n
        out.append(d)
    return out


def get(db, bot_id):
    return db.execute("SELECT * FROM bots WHERE id = ?", (bot_id,)).fetchone()


def feed(db, bot_id, limit=50):
    return db.execute(
        "SELECT * FROM bot_notes WHERE bot_id = ? ORDER BY id DESC LIMIT ?",
        (bot_id, limit),
    ).fetchall()


def matching(db, target):
    bots = db.execute("SELECT * FROM bots WHERE active = 1").fetchall()
    out = []
    for b in bots:
        if b["kind"] == "company":
            if target.get("lab_name") == b["scope"]:
                out.append(b)
        elif b["kind"] == "researcher":
            if (target.get("operator") or "").lower() == b["scope"].lower():
                out.append(b)
        elif b["kind"] == "project":
            if target.get("project") and target["project"].lower() == b["scope"].lower():
                out.append(b)
    return out


def run_target(db, run_id):
    row = db.execute(
        "SELECT r.*, l.name lab_name FROM runs r JOIN labs l ON l.id = r.lab_id WHERE r.id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "type": "run",
        "row": row,
        "id": row["id"],
        "lab_name": row["lab_name"],
        "operator": row["operator"],
        "project": row["project"] if "project" in row.keys() else None,
    }


def uv_target(db, mid):
    row = db.execute(
        "SELECT m.*, l.name lab_name FROM uv_measurements m JOIN labs l ON l.id = m.lab_id WHERE m.id = ?",
        (mid,),
    ).fetchone()
    if row is None:
        return None
    return {
        "type": "uv",
        "row": row,
        "id": row["id"],
        "lab_name": row["lab_name"],
        "operator": row["operator"] or "",
        "project": None,
    }


def review(db, target):
    notes = []
    for bot in matching(db, target):
        existing = db.execute(
            "SELECT id FROM bot_notes WHERE bot_id = ? AND target_type = ? AND target_id = ?",
            (bot["id"], target["type"], target["id"]),
        ).fetchone()
        if existing:
            continue
        body = ai.bot_note(db, target, bot)
        cur = db.execute(
            "INSERT INTO bot_notes (bot_id, target_type, target_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (bot["id"], target["type"], target["id"], body, _now()),
        )
        notes.append({"bot_id": bot["id"], "name": bot["name"], "note_id": cur.lastrowid})
    db.commit()
    return notes


def notes_for(db, target_type, target_id):
    rows = db.execute(
        """
        SELECT n.*, b.name bot_name, b.kind, b.scope
        FROM bot_notes n JOIN bots b ON b.id = n.bot_id
        WHERE n.target_type = ? AND n.target_id = ?
        ORDER BY n.id DESC
        """,
        (target_type, target_id),
    ).fetchall()
    return rows
