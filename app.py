import datetime
import hashlib
import json
import os
import random
import secrets
import sqlite3

from flask import Flask, Response, flash, g, jsonify, redirect, render_template, request, url_for

import ai
import bots
import bridge
import uvsim

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("LABLEDGER_DB") or os.path.join(BASE, "labledger.db")
HOST = os.environ.get("LABLEDGER_HOST", "127.0.0.1")
PORT = int(os.environ.get("LABLEDGER_PORT", "5000"))
VERSION = "0.2.0"
STARTED_AT = datetime.datetime.now(datetime.timezone.utc)

app = Flask(__name__)
app.secret_key = os.environ.get("LABLEDGER_SECRET", secrets.token_hex(16))
app.jinja_env.globals["json"] = json

SCHEMA = """
CREATE TABLE IF NOT EXISTS labs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'research',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_id INTEGER NOT NULL REFERENCES labs(id),
    technique TEXT NOT NULL,
    method TEXT NOT NULL,
    instrument TEXT NOT NULL,
    matrix TEXT NOT NULL,
    operator TEXT NOT NULL,
    outcome TEXT,
    failure_mode TEXT,
    learning TEXT,
    results_json TEXT NOT NULL,
    trace_json TEXT NOT NULL,
    published INTEGER NOT NULL DEFAULT 0,
    published_at TEXT,
    anon INTEGER NOT NULL DEFAULT 0,
    chain_hash TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    ts TEXT NOT NULL,
    prev_hash TEXT,
    event_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uv_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_id INTEGER NOT NULL REFERENCES labs(id),
    mode TEXT NOT NULL,
    instrument TEXT NOT NULL,
    source TEXT NOT NULL,
    compound TEXT NOT NULL,
    operator TEXT,
    params_json TEXT NOT NULL,
    data_json TEXT NOT NULL,
    truth_json TEXT,
    analysis_json TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    judgment TEXT NOT NULL,
    chart TEXT NOT NULL,
    log_json TEXT NOT NULL,
    errors_json TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL,
    wl_cal REAL NOT NULL DEFAULT 0,
    stray_corr INTEGER NOT NULL DEFAULT 0,
    noise_scale REAL NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_claims (
    metric TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    promised REAL NOT NULL,
    observed_mae REAL NOT NULL DEFAULT 0,
    n INTEGER NOT NULL DEFAULT 0,
    unit TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement_id INTEGER REFERENCES uv_measurements(id),
    metric TEXT NOT NULL,
    promised REAL NOT NULL,
    observed REAL NOT NULL,
    severity TEXT NOT NULL,
    revision INTEGER NOT NULL,
    cause TEXT,
    action TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calibrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_id INTEGER NOT NULL REFERENCES labs(id),
    instrument TEXT NOT NULL,
    compound TEXT NOT NULL,
    method_wl REAL NOT NULL,
    cal_type TEXT NOT NULL,
    coeffs_json TEXT NOT NULL,
    standards_json TEXT NOT NULL,
    equation TEXT,
    r2 REAL,
    sy_x REAL,
    lod REAL,
    loq REAL,
    weighting TEXT,
    meas_type TEXT,
    units TEXT,
    created_at TEXT NOT NULL
);
"""

TECHNIQUES = ["UV-Vis", "HPLC", "GC"]
OUTCOMES = ["success", "failure", "invalid"]
FAILURE_MODES = [
    "System suitability failed (resolution)",
    "System suitability failed (tailing)",
    "Retention time shift",
    "Baseline drift / noise",
    "Calibration outside acceptance",
    "Co-elution / unresolved peaks",
    "Detector saturation",
    "Column or consumable fault",
    "Sample preparation error",
    "Instrument hardware fault",
    "Other",
]


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = connect()
    db.executescript(SCHEMA)
    run_cols = [r["name"] for r in db.execute("PRAGMA table_info(runs)").fetchall()]
    if "project" not in run_cols:
        db.execute("ALTER TABLE runs ADD COLUMN project TEXT")
    cal_cols = [r["name"] for r in db.execute("PRAGMA table_info(calibrations)").fetchall()]
    for col, decl in (("weighting", "TEXT"), ("meas_type", "TEXT"), ("units", "TEXT")):
        if col not in cal_cols:
            db.execute(f"ALTER TABLE calibrations ADD COLUMN {col} {decl}")
    bridge.init(db)
    ai.init(db)
    bots.init(db)
    if db.execute("SELECT COUNT(*) c FROM labs").fetchone()["c"] == 0:
        db.execute(
            "INSERT INTO labs (name, kind, created_at) VALUES (?, ?, ?)",
            ("Northwind Analytical (demo)", "research", now()),
        )
        db.execute(
            "INSERT INTO labs (name, kind, created_at) VALUES (?, ?, ?)",
            ("Kestrel QC Lab (demo)", "qc", now()),
        )
    if db.execute("SELECT COUNT(*) c FROM model_state").fetchone()["c"] == 0:
        db.execute(
            "INSERT INTO model_state (id, revision, wl_cal, stray_corr, noise_scale, updated_at)"
            " VALUES (1, 1, 0, 0, 1, ?)",
            (now(),),
        )
    default_claims = [
        ("wavelength_nm", "Wavelength accuracy", 1.0, "nm"),
        ("recovery_pct", "Assay recovery", 2.0, "%"),
        ("rsd_pct", "Photometric repeatability", 2.0, "%"),
        ("kinetic_pct", "Kinetic rate accuracy", 5.0, "%"),
    ]
    for metric, label, promised, unit in default_claims:
        db.execute(
            "INSERT OR IGNORE INTO model_claims (metric, label, promised, unit, updated_at) VALUES (?, ?, ?, ?, ?)",
            (metric, label, promised, unit, now()),
        )
    db.commit()
    db.close()


def hash_event(prev, run_id, actor, action, detail, ts):
    payload = "|".join([str(prev or ""), str(run_id), actor, action, detail, ts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_audit(db, run_id, actor, action, detail):
    ts = now()
    last = db.execute(
        "SELECT event_hash FROM audit WHERE run_id = ? ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    prev = last["event_hash"] if last else None
    h = hash_event(prev, run_id, actor, action, detail, ts)
    db.execute(
        "INSERT INTO audit (run_id, actor, action, detail, ts, prev_hash, event_hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, actor, action, detail, ts, prev, h),
    )
    return h


def gaussian(x, mu, sigma):
    return pow(2.718281828459045, -((x - mu) ** 2) / (2 * sigma * sigma))


def make_trace(technique, outcome, seed):
    rng = random.Random(seed)
    if technique == "UV-Vis":
        points = []
        for wl in range(200, 801, 4):
            base = 0.05 + 0.4 * gaussian(wl, 272, 26) + 0.55 * gaussian(wl, 480, 40)
            if outcome == "failure":
                base += 0.25 * gaussian(wl, 620, 60)
            base += rng.uniform(-0.004, 0.004)
            points.append({"x": wl, "y": round(base, 4)})
        return {"kind": "spectrum", "xlabel": "Wavelength (nm)", "ylabel": "Absorbance (AU)", "points": points}
    n = 480
    duration = 30.0 if technique == "HPLC" else 25.0
    if technique == "HPLC":
        peaks = [
            ("Solvent front", 2.1, 0.55),
            ("Caffeine", 6.4, 1.00),
            ("Paracetamol", 9.8, 0.85),
            ("Impurity A", 14.2, 0.28),
            ("Impurity B", 18.6, 0.18),
        ]
    else:
        peaks = [
            ("Acetone", 2.6, 0.70),
            ("Toluene", 7.9, 1.00),
            ("Ethylbenzene", 11.4, 0.62),
            ("o-Xylene", 15.8, 0.44),
        ]
    points = []
    for i in range(n):
        t = duration * i / (n - 1)
        y = 0.01 + rng.uniform(-0.004, 0.004)
        for _name, rt, h in peaks:
            w = 0.16 if technique == "HPLC" else 0.12
            if outcome == "failure" and rt > duration * 0.5:
                w *= 1.9
            y += h * gaussian(t, rt, w)
        if outcome == "failure":
            y += 0.00035 * t * t + 0.0002 * t
        points.append({"x": round(t, 3), "y": round(y, 4)})
    peak_rows = []
    for name, rt, h in peaks:
        jitter = rng.uniform(-0.05, 0.05)
        peak_rows.append(
            {
                "name": name,
                "rt": round(rt + (jitter if outcome == "failure" else 0), 2),
                "area": round(h * rng.uniform(900, 1400), 1),
                "height": round(h, 3),
                "area_pct": round(h / sum(p[2] for p in peaks) * 100, 1),
            }
        )
    return {
        "kind": "chromatogram",
        "xlabel": "Time (min)",
        "ylabel": "Response (mAU)",
        "points": points,
        "peaks": peak_rows,
        "duration": duration,
    }


def make_results(technique, outcome, seed):
    rng = random.Random(seed + 7)
    if technique == "UV-Vis":
        return {
            "lambda_max_nm": 480 if outcome != "failure" else 505,
            "abs_at_max": round(rng.uniform(0.9, 1.2) if outcome != "failure" else rng.uniform(0.3, 0.6), 3),
            "concentration_mg_l": round(rng.uniform(5, 25), 2),
            "replicate_rsd_pct": round(rng.uniform(0.4, 1.5) if outcome != "failure" else rng.uniform(4.5, 9.0), 2),
            "blank_drift_ma": round(rng.uniform(0.001, 0.006), 4),
        }
    if technique == "HPLC":
        return {
            "theoretical_plates": int(rng.uniform(9000, 15000) if outcome != "failure" else rng.uniform(2500, 5500)),
            "resolution_min": round(rng.uniform(2.1, 4.0) if outcome != "failure" else rng.uniform(0.6, 1.3), 2),
            "tailing_factor": round(rng.uniform(0.9, 1.2) if outcome != "failure" else rng.uniform(1.9, 3.4), 2),
            "pressure_bar": int(rng.uniform(145, 185)),
            "r_squared": round(rng.uniform(0.9990, 0.9999) if outcome != "failure" else rng.uniform(0.9820, 0.9940), 4),
        }
    return {
        "theoretical_plates": int(rng.uniform(6000, 11000) if outcome != "failure" else rng.uniform(1800, 4000)),
        "resolution_min": round(rng.uniform(2.0, 5.0) if outcome != "failure" else rng.uniform(0.5, 1.2), 2),
        "asymmetry": round(rng.uniform(0.9, 1.3) if outcome != "failure" else rng.uniform(1.8, 3.0), 2),
        "oven_c": 110.0,
        "carrier_flow_ml_min": 1.6,
        "r_squared": round(rng.uniform(0.9990, 0.9999) if outcome != "failure" else rng.uniform(0.9800, 0.9930), 4),
    }


def trace_svg(trace, width=760, height=250, pad=38):
    pts = trace["points"]
    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = 0.0, max(ys) * 1.08
    span_x = xmax - xmin or 1
    span_y = ymax - ymin or 1

    def sx(x):
        return pad + (x - xmin) / span_x * (width - 2 * pad)

    def sy(y):
        return height - pad - (y - ymin) / span_y * (height - 2 * pad)

    path = " ".join(("M" if i == 0 else "L") + f"{sx(p['x']):.1f},{sy(p['y']):.1f}" for i, p in enumerate(pts))
    grid = []
    for i in range(5):
        xv = xmin + span_x * i / 4
        yv = ymin + span_y * i / 4
        gx = sx(xv)
        gy = sy(yv)
        grid.append(f'<line x1="{gx:.1f}" y1="{pad}" x2="{gx:.1f}" y2="{height - pad}" class="grid"/>')
        grid.append(f'<line x1="{pad}" y1="{gy:.1f}" x2="{width - pad}" y2="{gy:.1f}" class="grid"/>')
        grid.append(f'<text x="{gx:.1f}" y="{height - pad + 16}" class="axis">{xv:.1f}</text>')
        grid.append(f'<text x="{pad - 6}" y="{gy:.1f}" class="axis" text-anchor="end">{yv:.2f}</text>')
    markers = ""
    if trace["kind"] == "chromatogram":
        for pk in trace.get("peaks", []):
            mx = sx(pk["rt"])
            markers += (
                f'<line x1="{mx:.1f}" y1="{pad}" x2="{mx:.1f}" y2="{height - pad}" class="peakline"/>'
                f'<text x="{mx:.1f}" y="{pad - 6}" class="peaklabel">{pk["name"]}</text>'
            )
    return (
        f'<svg viewBox="0 0 {width} {height}" class="trace" role="img">'
        + "".join(grid)
        + markers
        + f'<path d="{path}" class="tracepath"/>'
        + "</svg>"
    )


def outcome_counts(db, lab_id=None):
    if lab_id:
        rows = db.execute(
            "SELECT outcome, COUNT(*) c FROM runs WHERE lab_id = ? GROUP BY outcome", (lab_id,)
        ).fetchall()
    else:
        rows = db.execute("SELECT outcome, COUNT(*) c FROM runs GROUP BY outcome").fetchall()
    return {r["outcome"]: r["c"] for r in rows}


def technique_stats(db):
    rows = db.execute(
        """
        SELECT technique,
               COUNT(*) total,
               SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) ok,
               SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) fail,
               SUM(CASE WHEN outcome = 'invalid' THEN 1 ELSE 0 END) inv,
               SUM(published) pub
        FROM runs GROUP BY technique ORDER BY technique
        """
    ).fetchall()
    return [dict(r) for r in rows]


def current_lab(db):
    lab_id = request.cookies.get("lab_id")
    row = db.execute("SELECT * FROM labs WHERE id = ?", (lab_id,)).fetchone() if lab_id else None
    if row is None:
        row = db.execute("SELECT * FROM labs ORDER BY id LIMIT 1").fetchone()
    return row


def verify_chain(db, run_id):
    rows = db.execute("SELECT * FROM audit WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    prev = None
    for r in rows:
        if r["prev_hash"] != prev:
            return False
        expect = hash_event(r["prev_hash"], run_id, r["actor"], r["action"], r["detail"], r["ts"])
        if expect != r["event_hash"]:
            return False
        prev = r["event_hash"]
    return True


@app.context_processor
def inject_globals():
    db = get_db()
    return {
        "labs": db.execute("SELECT * FROM labs ORDER BY id").fetchall(),
        "active_lab": current_lab(db),
        "TECHNIQUES": TECHNIQUES,
    }


@app.route("/")
def index():
    db = get_db()
    lab = current_lab(db)
    recent = db.execute(
        """
        SELECT r.*, l.name lab_name FROM runs r JOIN labs l ON l.id = r.lab_id
        ORDER BY r.id DESC LIMIT 8
        """
    ).fetchall()
    tstats = technique_stats(db)
    totals = outcome_counts(db)
    published = db.execute("SELECT COUNT(*) c FROM runs WHERE published = 1").fetchone()["c"]
    return render_template(
        "index.html",
        recent=recent,
        tstats=tstats,
        totals=totals,
        published=published,
        lab=lab,
    )


@app.route("/runs/new", methods=["GET", "POST"])
def run_new():
    db = get_db()
    lab = current_lab(db)
    if request.method == "POST":
        technique = request.form.get("technique", "")
        method = request.form.get("method", "").strip()
        instrument = request.form.get("instrument", "").strip()
        matrix = request.form.get("matrix", "").strip()
        operator = request.form.get("operator", "").strip() or "anonymous"
        outcome = request.form.get("outcome", "")
        failure_mode = request.form.get("failure_mode", "").strip()
        learning = request.form.get("learning", "").strip()
        notes = request.form.get("notes", "").strip()
        project = request.form.get("project", "").strip()
        if technique not in TECHNIQUES or outcome not in OUTCOMES:
            flash("Technique and outcome are required.", "error")
        elif not method or not instrument or not matrix:
            flash("Method, instrument and matrix are required.", "error")
        elif outcome != "success" and not learning:
            flash("A failure or invalid run must record what was learned.", "error")
        else:
            seed = secrets.randbelow(2**31)
            trace = make_trace(technique, outcome, seed)
            results = make_results(technique, outcome, seed)
            if notes:
                results["analyst_notes"] = notes
            cur = db.execute(
                """
                INSERT INTO runs (lab_id, technique, method, instrument, matrix, operator,
                                  outcome, failure_mode, learning, results_json, trace_json,
                                  project, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lab["id"], technique, method, instrument, matrix, operator,
                    outcome, failure_mode if outcome != "success" else "",
                    learning, json.dumps(results), json.dumps(trace), project, now(),
                ),
            )
            run_id = cur.lastrowid
            h = append_audit(db, run_id, operator, "run.created", f"{technique} run recorded with outcome {outcome}")
            if learning:
                append_audit(db, run_id, operator, "outcome.learning", learning)
            db.execute("UPDATE runs SET chain_hash = ? WHERE id = ?", (h, run_id))
            db.commit()
            flash("Run recorded.", "ok")
            target = bots.run_target(db, run_id)
            notes_made = bots.review(db, target) if target else []
            if notes_made:
                flash(f"{len(notes_made)} bot note(s) posted: " + ", ".join(n["name"] for n in notes_made), "ok")
            return redirect(url_for("run_detail", run_id=run_id))
    return render_template("run_new.html", failure_modes=FAILURE_MODES)


@app.route("/runs/<int:run_id>")
def run_detail(run_id):
    db = get_db()
    run = db.execute(
        "SELECT r.*, l.name lab_name FROM runs r JOIN labs l ON l.id = r.lab_id WHERE r.id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        flash("Run not found.", "error")
        return redirect(url_for("index"))
    events = db.execute("SELECT * FROM audit WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    chain_ok = verify_chain(db, run_id)
    trace = json.loads(run["trace_json"])
    results = json.loads(run["results_json"])
    return render_template(
        "run_detail.html",
        run=run,
        events=events,
        chain_ok=chain_ok,
        trace_svg=trace_svg(trace),
        trace=trace,
        results=results,
        ai_notes=ai.notes_for(db, "run", run_id),
        ai_provider=ai.provider_info(),
        bot_notes=bots.notes_for(db, "run", run_id),
        matching_bots=[dict(b) for b in bots.matching(db, bots.run_target(db, run_id) or {"type": "run", "project": None})],
    )


@app.route("/runs/<int:run_id>/publish", methods=["POST"])
def run_publish(run_id):
    db = get_db()
    run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        flash("Run not found.", "error")
        return redirect(url_for("index"))
    if run["published"]:
        flash("Already published.", "ok")
        return redirect(url_for("run_detail", run_id=run_id))
    if not run["outcome"]:
        flash("Set an outcome before publishing.", "error")
        return redirect(url_for("run_detail", run_id=run_id))
    if run["outcome"] != "success" and not run["learning"]:
        flash("A failure or invalid run must record what was learned before publishing.", "error")
        return redirect(url_for("run_detail", run_id=run_id))
    anon = 1 if request.form.get("anon") else 0
    db.execute(
        "UPDATE runs SET published = 1, published_at = ?, anon = ?, lab_id = lab_id WHERE id = ?",
        (now(), anon, run_id),
    )
    append_audit(db, run_id, run["operator"], "run.published", "Published to shared ledger" + (" (anonymized)" if anon else ""))
    h = db.execute("SELECT event_hash FROM audit WHERE run_id = ? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()[0]
    db.execute("UPDATE runs SET chain_hash = ? WHERE id = ?", (h, run_id))
    db.commit()
    flash("Published to the shared ledger.", "ok")
    return redirect(url_for("ledger"))


@app.route("/ledger")
def ledger():
    db = get_db()
    q = request.args.get("q", "").strip()
    technique = request.args.get("technique", "")
    outcome = request.args.get("outcome", "")
    sql = [
        """
        SELECT r.*, CASE WHEN r.anon = 1 THEN 'Anonymous lab' ELSE l.name END AS lab_name,
               l.kind lab_kind
        FROM runs r JOIN labs l ON l.id = r.lab_id
        WHERE r.published = 1
        """
    ]
    args = []
    if technique in TECHNIQUES:
        sql.append("AND r.technique = ?")
        args.append(technique)
    if outcome in OUTCOMES:
        sql.append("AND r.outcome = ?")
        args.append(outcome)
    if q:
        sql.append("AND (r.method LIKE ? OR r.matrix LIKE ? OR r.instrument LIKE ? OR COALESCE(r.learning,'') LIKE ?)")
        like = f"%{q}%"
        args.extend([like, like, like, like])
    sql.append("ORDER BY r.published_at DESC, r.id DESC LIMIT 100")
    rows = db.execute(" ".join(sql), args).fetchall()
    counts = outcome_counts(db)
    return render_template("ledger.html", rows=rows, q=q, technique=technique, outcome=outcome, counts=counts)


@app.route("/api/ledger")
def api_ledger():
    db = get_db()
    rows = db.execute(
        """
        SELECT r.id, r.technique, r.method, r.instrument, r.matrix, r.outcome,
               r.failure_mode, r.learning, r.published_at, r.chain_hash,
               CASE WHEN r.anon = 1 THEN 'Anonymous lab' ELSE l.name END AS lab
        FROM runs r JOIN labs l ON l.id = r.lab_id
        WHERE r.published = 1 ORDER BY r.id DESC LIMIT 500
        """
    ).fetchall()
    return app.response_class(
        json.dumps([dict(r) for r in rows], indent=2),
        mimetype="application/json",
    )


@app.route("/lab/<int:lab_id>", methods=["POST"])
def set_lab(lab_id):
    resp = redirect(request.referrer or url_for("index"))
    resp.set_cookie("lab_id", str(lab_id), max_age=86400 * 30)
    return resp


MODES = ["Spectrum", "Quantitative", "Photometric", "Time course"]


def model_state(db):
    row = db.execute("SELECT * FROM model_state WHERE id = 1").fetchone()
    return dict(row) if row else {"revision": 1, "wl_cal": 0, "stray_corr": 0, "noise_scale": 1}


def apply_state(db, st):
    db.execute(
        "UPDATE model_state SET revision = ?, wl_cal = ?, stray_corr = ?, noise_scale = ?, updated_at = ? WHERE id = 1",
        (st["revision"], st["wl_cal"], st["stray_corr"], st["noise_scale"], now()),
    )


def evaluate_model(db, measurement_id, result, mode):
    st = model_state(db)
    claims = {r["metric"]: dict(r) for r in db.execute("SELECT * FROM model_claims").fetchall()}
    logged = []
    signed = None
    if not result.get("truth"):
        return [], st, "no_truth"
    for c in result.get("checks", []):
        if c["name"] in ("Signal level", "Absorbance range") and not c["pass"]:
            return [], st, "outside_model_scope"
    if mode == "Spectrum":
        signed = result["analysis"]["lambda_max_nm"] - result["truth"]["lambda_max_nm"]
    for metric, _label, fn in uvsim.METRICS.get(mode, []):
        observed = round(fn(result), 3)
        claim = claims.get(metric)
        if not claim:
            continue
        n = claim["n"] + 1
        mae = round((claim["observed_mae"] * claim["n"] + observed) / n, 3)
        promised = claim["promised"]
        if observed > promised:
            cause, action = uvsim.CAUSES[metric]
            st["revision"] += 1
            if metric == "wavelength_nm" and signed is not None:
                st["wl_cal"] = round(max(-1.5, min(1.5, st["wl_cal"] + signed * 0.8)), 3)
            if metric == "recovery_pct":
                st["stray_corr"] = 1
            if metric == "rsd_pct":
                st["noise_scale"] = round(min(3.0, st["noise_scale"] * 1.25), 2)
            promised = round(min(claim["promised"] * 2.5, max(promised, observed * 1.15)), 2)
            severity = "high" if observed > claim["promised"] * 2 else "medium"
            note_action = f"{action} (model revision {st['revision']})"
            db.execute(
                """
                INSERT INTO model_errors (measurement_id, metric, promised, observed, severity,
                                          revision, cause, action, acknowledged, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (measurement_id, metric, claim["promised"], observed, severity,
                 st["revision"], cause, note_action, now()),
            )
            logged.append({"metric": metric, "label": claim["label"], "promised": claim["promised"],
                           "observed": observed, "unit": claim["unit"], "cause": cause, "action": note_action,
                           "severity": severity})
        db.execute(
            "UPDATE model_claims SET promised = ?, observed_mae = ?, n = ?, updated_at = ? WHERE metric = ?",
            (promised, mae, n, now(), metric),
        )
    apply_state(db, st)
    return logged, st, None


def cal_spark(c, w=180, h=56):
    stds = c.get("standards") or []
    coeffs = c.get("coeffs") or []
    if not stds or not coeffs:
        return ""
    xs = [float(s["conc_uM"]) for s in stds]
    ys = [float(s["abs"]) for s in stds]
    cal = {"type": c.get("cal_type") or "linear", "coeffs": coeffs}
    lo, hi = min(xs), max(xs)
    if cal["type"] == "quadratic":
        curve_x = [lo + (hi - lo) * i / 24 for i in range(25)]
    else:
        curve_x = [lo, hi]
    pts = [(x, uvsim.cal_value(cal, x)) for x in curve_x]
    all_y = ys + [y for _, y in pts]
    xmin, xmax = lo, (hi if hi > lo else lo + 1)
    ymin, ymax = min(all_y), max(all_y)
    spanx = xmax - xmin or 1
    spany = (ymax - ymin) or 1
    pad = 6

    def sx(x):
        return pad + (x - xmin) / spanx * (w - 2 * pad)

    def sy(y):
        return h - pad - (y - ymin) / spany * (h - 2 * pad)

    d = " ".join(("M" if i == 0 else "L") + f"{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(pts))
    dots = "".join(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="2.2"/>' for x, y in zip(xs, ys))
    return (f'<svg viewBox="0 0 {w} {h}" class="spark" aria-hidden="true">'
            f'<path d="{d}" fill="none" stroke="#4cc2ff" stroke-width="1.6"/>{dots}</svg>')


def method_form_params(form, db):
    params = {
        "mode": form.get("mode", "Spectrum"),
        "instrument": form.get("instrument", "UV-1900i"),
        "source": form.get("source", "virtual"),
        "compound": form.get("compound", "Caffeine"),
        "conc_uM": form.get("conc_uM") or None,
        "path_cm": form.get("path_cm") or 1.0,
        "wl_start": form.get("wl_start") or 200,
        "wl_end": form.get("wl_end") or 800,
        "step_nm": form.get("step_nm") or 2,
        "speed": form.get("speed", "medium"),
        "bandwidth_nm": form.get("bandwidth_nm") or 1.0,
        "method_wl": form.get("method_wl") or None,
        "readings": form.get("readings") or 10,
        "interval_s": form.get("interval_s") or 30,
        "t_end_min": form.get("t_end_min") or 10,
        "baseline": form.get("baseline", "none"),
        "smoothing": int(form.get("smoothing") or 5),
        "peak_threshold": float(form.get("peak_threshold") or 4) / 1000.0,
        "min_peak_span": float(form.get("min_peak_span") or 4),
        "active_peak": form.get("active_peak", "auto"),
        "active_peak_nm": form.get("active_peak_nm") or None,
        "cal_type": form.get("cal_type", "linear"),
        "std_levels": (form.get("std_levels") or "").strip(),
        "n_unknowns": int(form.get("n_unknowns") or 1),
        "reps": int(form.get("reps") or 3),
        "weighting": form.get("weighting") if form.get("weighting") in ("none", "1/x", "1/x2") else "none",
        "no_intercept": (form.get("no_intercept") or "").lower() in ("on", "1", "true", "yes"),
        "meas_type": form.get("meas_type") if form.get("meas_type") in ("height", "area") else "height",
        "units": form.get("units") if form.get("units") in ("uM", "mg/L", "ppm") else "uM",
    }
    if params["instrument"] not in uvsim.INSTRUMENTS:
        params["instrument"] = "UV-1900i"
    comp = uvsim.compound(params["compound"])
    if not params["conc_uM"]:
        params["conc_uM"] = round(uvsim.default_conc(comp), 1)
    if not params["method_wl"]:
        params["method_wl"] = comp["method_wl"]
    cal_id = (form.get("use_calibration") or "").strip()
    if cal_id.isdigit():
        crow = db.execute("SELECT * FROM calibrations WHERE id = ?", (int(cal_id),)).fetchone()
        if crow is not None:
            params["calibration"] = {
                "saved_id": crow["id"], "instrument": crow["instrument"], "compound": crow["compound"],
                "cal_type": crow["cal_type"], "coeffs": json.loads(crow["coeffs_json"]),
                "equation": crow["equation"], "r2": crow["r2"], "syx": crow["sy_x"],
                "lod": crow["lod"], "loq": crow["loq"],
                "standards": json.loads(crow["standards_json"]),
                "weighting": crow["weighting"] or "none",
            }
    return params, comp


@app.route("/uvvis")
def uvvis_console():
    db = get_db()
    preset_compound = request.args.get("compound", "Caffeine")
    preset_mode = request.args.get("mode", "Spectrum")
    comp = uvsim.compound(preset_compound)
    recent = db.execute(
        """
        SELECT id, mode, instrument, compound, judgment, source, created_at
        FROM uv_measurements ORDER BY id DESC LIMIT 8
        """
    ).fetchall()
    cals = []
    for crow in db.execute("SELECT * FROM calibrations ORDER BY id DESC LIMIT 20").fetchall():
        c = dict(crow)
        try:
            c["coeffs"] = json.loads(c["coeffs_json"])
            c["standards"] = json.loads(c["standards_json"])
        except (TypeError, ValueError):
            c["coeffs"], c["standards"] = [], []
        c["curve_svg"] = cal_spark(c)
        cals.append(c)
    peak_source = None
    for row in db.execute(
        "SELECT id, mode, compound, created_at, data_json FROM uv_measurements ORDER BY id DESC LIMIT 6"
    ).fetchall():
        d = json.loads(row["data_json"] or "{}")
        if d.get("peaks"):
            peak_source = {
                "mid": row["id"], "mode": row["mode"], "compound": row["compound"],
                "created_at": row["created_at"], "peaks": d["peaks"],
            }
            break
    return render_template(
        "uvvis.html",
        modes=MODES,
        instruments=uvsim.INSTRUMENTS,
        compounds=uvsim.COMPOUNDS,
        default_conc=round(uvsim.default_conc(comp), 1),
        preset_compound=comp["name"],
        preset_mode=preset_mode if preset_mode in MODES else "Spectrum",
        state=model_state(db),
        recent=recent,
        bridge_instruments=db.execute("SELECT * FROM instruments ORDER BY name").fetchall(),
        calibrations=cals,
        baseline_options=uvsim.BASELINE_OPTIONS,
        unit_labels=uvsim.UNIT_LABELS,
        peak_source=peak_source,
        use_id=(request.args.get("use") or "").strip(),
    )


@app.route("/uvvis/run", methods=["POST"])
def uvvis_run():
    db = get_db()
    lab = current_lab(db)
    mode = request.form.get("mode", "Spectrum")
    if mode not in MODES:
        flash("Unknown measurement mode.", "error")
        return redirect(url_for("uvvis_console"))
    params, comp = method_form_params(request.form, db)
    params["mode"] = mode
    st = model_state(db)
    import time as _time
    t0 = _time.perf_counter()
    result = None
    bridge_receipt = None
    if params["source"] == "bridge":
        inst_row = db.execute(
            "SELECT * FROM instruments WHERE id = ?", (request.form.get("bridge_instrument") or 0,)
        ).fetchone()
        if inst_row is None:
            flash("Register an instrument on the Instruments page first.", "error")
            return redirect(url_for("uvvis_console"))
        queued = bridge.take_latest(db, inst_row["id"])
        if queued is None:
            flash(f"No pending data from {inst_row['name']} — send a spectrum from the driver first.", "error")
            return redirect(url_for("uvvis_console"))
        payload = json.loads(queued["payload_json"])
        pts = [(float(x), float(y)) for x, y in payload["points"]]
        pts.sort()
        result = uvsim.spectrum_from_points(pts, comp)
        mode = "Spectrum"
        bridge_receipt = {"queue_id": queued["id"], "instrument": inst_row["name"],
                          "received_at": queued["created_at"]}
        params["bridge"] = bridge_receipt
        params["instrument"] = inst_row["name"]
        params["compound"] = comp["name"]
    if result is None:
        result = uvsim.run_measurement(params, st, random.Random())
    dur = int((_time.perf_counter() - t0) * 1000)
    analysis_row = dict(result["analysis"])
    if mode == "Quantitative" and result.get("calibration"):
        cp = result["calibration"]
        ccur = db.execute(
            """
            INSERT INTO calibrations (lab_id, instrument, compound, method_wl, cal_type,
                                       coeffs_json, standards_json, equation, r2, sy_x, lod, loq,
                                       weighting, meas_type, units, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lab["id"], cp["instrument"], cp["compound"], cp["method_wl"], cp["cal_type"],
                json.dumps(cp["coeffs"]), json.dumps(cp["standards"]), cp["equation"],
                cp["r2"], cp["syx"], cp["lod"], cp["loq"],
                cp.get("weighting", "none"), cp.get("meas_type", "height"), cp.get("units", "uM"),
                now(),
            ),
        )
        analysis_row["saved_calibration_id"] = ccur.lastrowid
    judgments = [c["pass"] for c in result["checks"]]
    judgment = "PASS" if all(judgments) else "FAIL"
    cur = db.execute(
        """
        INSERT INTO uv_measurements (lab_id, mode, instrument, source, compound, operator,
                                     params_json, data_json, truth_json, analysis_json, checks_json,
                                     judgment, chart, log_json, duration_ms, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lab["id"], mode, params["instrument"], params["source"], comp["name"],
            request.form.get("operator", "").strip() or "anonymous",
            json.dumps(params), json.dumps(result["data"]), json.dumps(result["truth"]),
            json.dumps(analysis_row), json.dumps(result["checks"]), judgment,
            result["chart"], json.dumps(result["log"]), dur, now(),
        ),
    )
    mid = cur.lastrowid
    logged, st2, scope = evaluate_model(db, mid, result, mode)
    db.execute("UPDATE uv_measurements SET errors_json = ? WHERE id = ?", (json.dumps(logged), mid))
    db.commit()
    if logged:
        flash(
            f"Model acknowledged {len(logged)} accuracy mistake(s): "
            + "; ".join(f"{e['label']} observed {e['observed']} {e['unit']} vs promised ±{e['promised']}" for e in logged)
            + f" — corrected, now at model revision {st2['revision']}.",
            "error",
        )
    elif scope == "no_truth":
        flash(f"Measurement complete ({result['summary']}) — instrument data logged; no ground truth available, so accuracy was not scored.", "ok")
    elif scope:
        flash(f"Measurement complete ({result['summary']}) — signal outside the calibrated range, so the run was not scored against the model's promised accuracy.", "ok")
    else:
        flash(f"Measurement complete ({result['summary']}) — within the model's promised accuracy.", "ok")
    return redirect(url_for("uvvis_result", mid=mid))


@app.route("/uvvis/m/<int:mid>")
def uvvis_result(mid):
    db = get_db()
    m = db.execute(
        "SELECT m.*, l.name lab_name FROM uv_measurements m JOIN labs l ON l.id = m.lab_id WHERE m.id = ?",
        (mid,),
    ).fetchone()
    if m is None:
        flash("Measurement not found.", "error")
        return redirect(url_for("uvvis_console"))
    return render_template(
        "uvvis_result.html",
        m=m,
        params=json.loads(m["params_json"]),
        data=json.loads(m["data_json"]),
        truth=json.loads(m["truth_json"]) if m["truth_json"] else None,
        analysis=json.loads(m["analysis_json"]),
        checks=json.loads(m["checks_json"]),
        events=json.loads(m["log_json"]),
        errors=json.loads(m["errors_json"] or "[]"),
        state=model_state(db),
        ai_notes=ai.notes_for(db, "uv", mid),
        ai_provider=ai.provider_info(),
        bot_notes=bots.notes_for(db, "uv", mid),
    )


@app.route("/uvvis/m/<int:mid>/csv")
def uvvis_csv(mid):
    db = get_db()
    m = db.execute("SELECT * FROM uv_measurements WHERE id = ?", (mid,)).fetchone()
    if m is None:
        return Response("not found", status=404)
    params = json.loads(m["params_json"])
    data = json.loads(m["data_json"])
    analysis = json.loads(m["analysis_json"])
    truth = json.loads(m["truth_json"] or "{}")
    lines = [
        f"LabLedger UV-Vis export,measurement {m['id']},{m['mode']},{m['instrument']},{m['source']}",
        f"compound,{m['compound']},judgment,{m['judgment']},recorded,{m['created_at']}",
        "parameters," + ",".join(f"{k}={v}" for k, v in params.items()),
        "analysis," + ",".join(f"{k}={v}" for k, v in analysis.items()),
        "truth," + ",".join(f"{k}={v}" for k, v in truth.items()),
        "",
    ]
    if m["mode"] == "Spectrum":
        lines.append("wavelength_nm,absorbance_A")
        lines += [f"{x},{y}" for x, y in data["points"]]
        if data.get("baseline", {}).get("applied"):
            lines.append("")
            lines.append("baseline_method," + str(data["baseline"].get("method")))
        if data.get("peaks"):
            lines.append("")
            lines.append("peak,wl_nm,height_A,area_A_nm,width_nm,fwhm_nm,purity,active")
            for i, pk in enumerate(data["peaks"]):
                lines.append(f"{i + 1},{pk['wl']},{pk['height_A']},{pk['area_A_nm']},"
                             f"{pk['width_nm']},{pk.get('fwhm_nm', '')},{pk['purity']},{pk.get('active', False)}")
    elif m["mode"] == "Quantitative":
        cal = data.get("calibration")
        if cal:
            lines.append(f"calibration_type,{cal.get('type')}")
            lines.append(f"calibration_equation,{cal.get('eq')}")
            lines.append(f"r2,{cal.get('r2')}")
            lines.append(f"sy_x,{cal.get('syx')}")
            lines.append(f"lod_uM,{cal.get('lod')}")
            lines.append(f"loq_uM,{cal.get('loq')}")
            lines.append("")
        lines.append("standard,conc_uM,absorbance_A,accepted")
        lines += [f"{s.get('level', '')},{s['conc_uM']},{s['abs']},{s.get('accepted', '')}" for s in data["standards"]]
        lines.append("")
        lines.append("replicate,absorbance_A")
        lines += [f"{i + 1},{a}" for i, a in enumerate(data["replicates"])]
        for u in data.get("unknowns", []):
            lines.append("")
            lines.append(f"unknown,{u['sample']},active_peak_nm,{u.get('active_peak_nm', '')}")
            lines.append(f"unknown_mean_abs,{u['mean_abs']},sd,{u['sd']},rsd_pct,{u['rsd_pct']}")
            lines.append(f"unknown_found_uM,{u['found_uM']},recovery_pct,{u['recovery_pct']},accepted,{u.get('accepted', '')}")
            lines.append(f"unknown_replicates,{','.join(str(r) for r in u['rpts'])}")
    elif m["mode"] == "Photometric":
        lines.append("time_s,absorbance_A")
        lines += [f"{r['t_s']},{r['abs']}" for r in data["readings"]]
    else:
        lines.append("time_s,absorbance_A")
        lines += [f"{r['t_s']},{r['abs']}" for r in data["kinetic"]]
    return Response("\n".join(lines), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=uvvis_{m['id']}_{m['mode']}.csv"})


@app.route("/uvvis/quantpreview", methods=["POST"])
def uvvis_quantpreview():
    db = get_db()
    params, _comp = method_form_params(request.form, db)
    params["mode"] = "Quantitative"
    params.pop("calibration", None)
    try:
        prev = uvsim.quant_preview(params)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(prev)


@app.route("/uvvis/m/<int:mid>/peak", methods=["POST"])
def uvvis_peak(mid):
    db = get_db()
    m = db.execute("SELECT * FROM uv_measurements WHERE id = ?", (mid,)).fetchone()
    if m is None:
        flash("Measurement not found.", "error")
        return redirect(url_for("uvvis_console"))
    if m["mode"] not in ("Spectrum", "Quantitative"):
        flash("Active peak re-analysis applies to Spectrum and Quantitative runs only.", "error")
        return redirect(url_for("uvvis_result", mid=mid))
    manual = (request.form.get("manual_wl") or "").strip()
    peak_wl = (request.form.get("peak_wl") or "").strip()
    wl_s = manual or peak_wl
    if not wl_s:
        flash("Pick a detected peak or enter a wavelength to re-analyze.", "error")
        return redirect(url_for("uvvis_result", mid=mid))
    try:
        wl = float(wl_s)
    except ValueError:
        flash("Wavelength must be a number.", "error")
        return redirect(url_for("uvvis_result", mid=mid))
    params = json.loads(m["params_json"])
    data = json.loads(m["data_json"])
    analysis = json.loads(m["analysis_json"])
    comp = uvsim.compound(m["compound"])
    old_wl = analysis.get("active_peak_nm") or params.get("method_wl")
    ndata, nanalysis, nchart = uvsim.reanalyze(data, analysis, params, comp, m["mode"], wl)
    if ndata is data and nanalysis is analysis:
        flash("This measurement has no spectrum or peak list to re-analyze.", "error")
        return redirect(url_for("uvvis_result", mid=mid))
    log = json.loads(m["log_json"])
    action = "peak.reanalyze"
    detail = f"active peak {old_wl} nm -> {wl:g} nm ({m['mode']})"
    prev = log[-1]["hash"] if log else None
    ts = random.randint(0, 10 ** 9)
    h = hashlib.sha256(f"{prev}|{action}|{detail}|{ts}".encode()).hexdigest()
    log.append({"action": action, "detail": detail, "hash": h, "prev": prev})
    db.execute(
        "UPDATE uv_measurements SET data_json = ?, analysis_json = ?, log_json = ? WHERE id = ?",
        (json.dumps(ndata), json.dumps(nanalysis), json.dumps(log), mid),
    )
    if nchart:
        db.execute("UPDATE uv_measurements SET chart = ? WHERE id = ?", (nchart, mid))
    db.commit()
    flash(f"Re-analyzed at {wl:g} nm — {nanalysis.get('reanalyze_note', 'peak list updated.')}", "ok")
    return redirect(url_for("uvvis_result", mid=mid))


@app.route("/uvvis/m/<int:mid>/print")
def uvvis_print(mid):
    db = get_db()
    m = db.execute(
        "SELECT m.*, l.name lab_name FROM uv_measurements m JOIN labs l ON l.id = m.lab_id WHERE m.id = ?",
        (mid,),
    ).fetchone()
    if m is None:
        flash("Measurement not found.", "error")
        return redirect(url_for("uvvis_console"))
    events = json.loads(m["log_json"])
    return render_template(
        "uvvis_print.html",
        m=m,
        params=json.loads(m["params_json"]),
        data=json.loads(m["data_json"]),
        truth=json.loads(m["truth_json"]) if m["truth_json"] else None,
        analysis=json.loads(m["analysis_json"]),
        checks=json.loads(m["checks_json"]),
        events=events,
        errors=json.loads(m["errors_json"] or "[]"),
        state=model_state(db),
        chain_tail=events[-1]["hash"] if events else "",
    )


@app.route("/uvvis/calibration/<int:cid>/delete", methods=["POST"])
def uvvis_cal_delete(cid):
    db = get_db()
    crow = db.execute("SELECT id, compound FROM calibrations WHERE id = ?", (cid,)).fetchone()
    if crow is None:
        flash("Calibration not found.", "error")
    else:
        db.execute("DELETE FROM calibrations WHERE id = ?", (cid,))
        db.commit()
        flash(f"Calibration #{cid} ({crow['compound']}) deleted.", "ok")
    return redirect(request.referrer or url_for("uvvis_console"))


@app.route("/uvvis/model")
def uvvis_model():
    db = get_db()
    claims = [dict(r) for r in db.execute("SELECT * FROM model_claims ORDER BY metric").fetchall()]
    errors = db.execute(
        """
        SELECT e.*, m.mode, m.instrument, m.compound FROM model_errors e
        LEFT JOIN uv_measurements m ON m.id = e.measurement_id
        ORDER BY e.id DESC LIMIT 100
        """
    ).fetchall()
    st = model_state(db)
    n_meas = db.execute("SELECT COUNT(*) c FROM uv_measurements").fetchone()["c"]
    n_err = db.execute("SELECT COUNT(*) c FROM model_errors").fetchone()["c"]
    return render_template("uvvis_model.html", claims=claims, errors=errors, state=st,
                           n_meas=n_meas, n_err=n_err)


@app.route("/world")
def world():
    db = get_db()
    totals = outcome_counts(db)
    tech = technique_stats(db)
    stats = {
        "runs": db.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"],
        "published": db.execute("SELECT COUNT(*) c FROM runs WHERE published = 1").fetchone()["c"],
        "labs": db.execute("SELECT COUNT(*) c FROM labs").fetchone()["c"],
        "measurements": db.execute("SELECT COUNT(*) c FROM uv_measurements").fetchone()["c"],
        "model_errors": db.execute("SELECT COUNT(*) c FROM model_errors").fetchone()["c"],
        "compounds": len(uvsim.COMPOUNDS),
        "instruments": len(uvsim.INSTRUMENTS),
    }
    preview = uvsim.line_chart(
        [{"label": f"{c['name']} reference", "pts": uvsim.library_shape(c, 200, 800, 2),
          "color": "#4cc2ff" if i % 2 == 0 else "#ffc857", "w": 1.2}
         for i, c in enumerate(uvsim.COMPOUNDS[:4])],
        "Wavelength (nm)", "Normalised absorbance",
    )
    return render_template("world.html", stats=stats, totals=totals, tech=tech,
                           instruments=uvsim.INSTRUMENTS, compounds=uvsim.COMPOUNDS,
                           preview=preview)


@app.route("/world/compound/<name>")
def world_compound(name):
    comp = uvsim.compound(name)
    if comp["name"] != name and name:
        flash("Compound not in reference library; showing nearest entry.", "error")
    chart = uvsim.line_chart(
        [{"label": "Reference spectrum (scaled)", "pts": uvsim.spectrum_points(comp, 200, 800, 1, 1e-5, 1),
          "color": "#4cc2ff", "marker": (comp["lambda_max"], f"{comp['lambda_max']} nm")}],
        "Wavelength (nm)", "Absorbance (A)",
    )
    return render_template("compound.html", c=comp, chart=chart, bands=comp["bands"])


@app.route("/instruments", methods=["GET", "POST"])
def instruments_page():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        vendor = request.form.get("vendor", "").strip()
        model = request.form.get("model", "").strip()
        serial = request.form.get("serial", "").strip()
        connection = request.form.get("connection", "tcp")
        host = request.form.get("host", "127.0.0.1").strip() or "127.0.0.1"
        try:
            port = int(request.form.get("port") or 5056)
        except ValueError:
            port = 5056
        if not name:
            flash("Instrument name is required.", "error")
        elif db.execute("SELECT 1 FROM instruments WHERE name = ?", (name,)).fetchone():
            flash("An instrument with that name already exists.", "error")
        else:
            db.execute(
                "INSERT INTO instruments (name, vendor, model, serial, connection, host, port, api_key, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, vendor, model, serial, connection, host, port,
                 secrets.token_urlsafe(24), now()),
            )
            db.commit()
            flash(f"Instrument {name} registered.", "ok")
            return redirect(url_for("instruments_page"))
    rows = db.execute("SELECT * FROM instruments ORDER BY id").fetchall()
    stats = bridge.queue_stats(db)
    queue_rows = db.execute(
        """
        SELECT q.*, i.name instrument FROM bridge_queue q
        LEFT JOIN instruments i ON i.id = q.instrument_id
        ORDER BY q.id DESC LIMIT 30
        """
    ).fetchall()
    return render_template("instruments.html", rows=rows, stats=stats, queue_rows=queue_rows,
                           bridge=bridge.status())


@app.route("/instruments/<int:inst_id>/delete", methods=["POST"])
def instrument_delete(inst_id):
    db = get_db()
    db.execute("DELETE FROM bridge_queue WHERE instrument_id = ?", (inst_id,))
    db.execute("DELETE FROM instruments WHERE id = ?", (inst_id,))
    db.commit()
    flash("Instrument removed.", "ok")
    return redirect(url_for("instruments_page"))


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    db = get_db()
    data = request.get_json(silent=True) or {}
    if not data:
        csv_text = request.form.get("csv", "")
        data = {"api_key": request.form.get("api_key"), "instrument": request.form.get("instrument"),
                "compound": request.form.get("compound"), "kind": request.form.get("kind"), "csv": csv_text}
    try:
        result = bridge.handle_payload(db, data)
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 401
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, **result})


@app.route("/api/queue")
def api_queue():
    db = get_db()
    rows = db.execute(
        """
        SELECT q.id, i.name instrument, q.kind, q.compound, q.consumed, q.created_at
        FROM bridge_queue q LEFT JOIN instruments i ON i.id = q.instrument_id
        ORDER BY q.id DESC LIMIT 50
        """
    ).fetchall()
    return jsonify({"stats": bridge.queue_stats(db), "rows": [dict(r) for r in rows]})


@app.route("/healthz")
def healthz():
    db = get_db()
    uptime = (datetime.datetime.now(datetime.timezone.utc) - STARTED_AT).total_seconds()
    counts = {
        "labs": db.execute("SELECT COUNT(*) c FROM labs").fetchone()["c"],
        "runs": db.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"],
        "uv_measurements": db.execute("SELECT COUNT(*) c FROM uv_measurements").fetchone()["c"],
        "calibrations": db.execute("SELECT COUNT(*) c FROM calibrations").fetchone()["c"],
        "instruments": db.execute("SELECT COUNT(*) c FROM instruments").fetchone()["c"],
    }
    return jsonify({
        "ok": True, "service": "labledger", "version": VERSION,
        "db": os.path.basename(DB_PATH), "uptime_s": round(uptime, 1),
        "model_revision": model_state(db)["revision"], "counts": counts,
    })


@app.route("/api/uvvis")
def api_uvvis_list():
    db = get_db()
    limit = min(max(int(request.args.get("limit", 50)), 1), 500)
    rows = db.execute(
        """
        SELECT id, mode, instrument, source, compound, operator, judgment, created_at
        FROM uv_measurements ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return jsonify({"version": VERSION, "count": len(rows), "measurements": [dict(r) for r in rows]})


@app.route("/api/uvvis/<int:mid>")
def api_uvvis_measurement(mid):
    db = get_db()
    m = db.execute(
        "SELECT m.*, l.name lab_name FROM uv_measurements m JOIN labs l ON l.id = m.lab_id WHERE m.id = ?",
        (mid,),
    ).fetchone()
    if m is None:
        return jsonify({"error": "measurement not found"}), 404
    events = json.loads(m["log_json"])
    payload = {
        "id": m["id"], "lab": m["lab_name"], "mode": m["mode"], "instrument": m["instrument"],
        "source": m["source"], "compound": m["compound"], "operator": m["operator"],
        "judgment": m["judgment"], "created_at": m["created_at"], "duration_ms": m["duration_ms"],
        "params": json.loads(m["params_json"]),
        "data": json.loads(m["data_json"]),
        "analysis": json.loads(m["analysis_json"]),
        "checks": json.loads(m["checks_json"]),
        "truth": json.loads(m["truth_json"]) if m["truth_json"] else None,
        "errors": json.loads(m["errors_json"] or "[]"),
        "chain": {"length": len(events), "tail": events[-1]["hash"] if events else None},
        "links": {"html": url_for("uvvis_result", mid=mid, _external=True),
                  "report": url_for("uvvis_print", mid=mid, _external=True),
                  "csv": url_for("uvvis_csv", mid=mid, _external=True)},
    }
    return jsonify(payload)


@app.route("/ai")
def ai_page():
    db = get_db()
    question = request.args.get("q", "").strip()
    answer = None
    if question:
        answer = ai.ask(db, question)
    notes = db.execute(
        """
        SELECT n.*, 'run' t FROM ai_notes n WHERE n.target_type = 'run'
        UNION ALL
        SELECT n.*, 'uv' t FROM ai_notes n WHERE n.target_type = 'uv'
        ORDER BY id DESC LIMIT 20
        """
    ).fetchall()
    runs = db.execute(
        "SELECT id, technique, method, outcome, project, operator FROM runs ORDER BY id DESC LIMIT 8"
    ).fetchall()
    return render_template("ai.html", answer=answer, question=question, notes=notes,
                           provider=ai.provider_info(), runs=runs)


@app.route("/ai/analyze/run/<int:run_id>", methods=["POST"])
def ai_analyze_run(run_id):
    db = get_db()
    run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        flash("Run not found.", "error")
        return redirect(url_for("ai_page"))
    analysis = ai.analyze_run(db, run)
    ai.save_note(db, "run", run_id, analysis)
    flash("AI analysis saved to the run.", "ok")
    return redirect(url_for("run_detail", run_id=run_id))


@app.route("/ai/analyze/uv/<int:mid>", methods=["POST"])
def ai_analyze_uv(mid):
    db = get_db()
    m = db.execute("SELECT * FROM uv_measurements WHERE id = ?", (mid,)).fetchone()
    if m is None:
        flash("Measurement not found.", "error")
        return redirect(url_for("ai_page"))
    analysis = ai.analyze_uv(db, m)
    ai.save_note(db, "uv", mid, analysis)
    flash("AI analysis saved to the measurement.", "ok")
    return redirect(url_for("uvvis_result", mid=mid))


@app.route("/bots", methods=["GET", "POST"])
def bots_page():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        kind = request.form.get("kind", "project")
        scope = request.form.get("scope", "").strip()
        mandate = request.form.get("mandate", "").strip()
        if not name or not scope:
            flash("Bot name and scope are required.", "error")
        elif kind not in bots.KINDS:
            flash("Unknown bot kind.", "error")
        else:
            bots.create(db, name, kind, scope, mandate)
            flash(f"Bot {name} is live — it reviews new matching runs.", "ok")
            return redirect(url_for("bots_page"))
    projects = [r["project"] for r in db.execute(
        "SELECT DISTINCT project FROM runs WHERE project IS NOT NULL AND project != ''"
    ).fetchall()]
    return render_template("bots.html", bots=bots.all(db), kinds=bots.KINDS,
                           projects=projects, provider=ai.provider_info())


@app.route("/bots/<int:bot_id>")
def bot_detail(bot_id):
    db = get_db()
    bot = bots.get(db, bot_id)
    if bot is None:
        flash("Bot not found.", "error")
        return redirect(url_for("bots_page"))
    return render_template("bot_detail.html", bot=bot, feed=bots.feed(db, bot_id),
                           provider=ai.provider_info())


@app.route("/bots/<int:bot_id>/delete", methods=["POST"])
def bot_delete(bot_id):
    db = get_db()
    bots.delete(db, bot_id)
    flash("Bot deleted.", "ok")
    return redirect(url_for("bots_page"))


@app.route("/bots/review/<kind>/<int:target_id>", methods=["POST"])
def bots_review(kind, target_id):
    db = get_db()
    target = bots.run_target(db, target_id) if kind == "run" else bots.uv_target(db, target_id)
    if target is None:
        flash("Record not found.", "error")
        return redirect(url_for("bots_page"))
    made = bots.review(db, target)
    if made:
        flash(f"{len(made)} bot note(s): " + ", ".join(n["name"] for n in made), "ok")
    else:
        flash("No bots match this record (create a project/researcher/company bot first).", "error")
    if kind == "run":
        return redirect(url_for("run_detail", run_id=target_id))
    return redirect(url_for("uvvis_result", mid=target_id))


init_db()

if __name__ == "__main__":
    import os as _os

    bridge.start_tcp(host=_os.environ.get("BRIDGE_HOST", "127.0.0.1"),
                     port=int(_os.environ.get("BRIDGE_PORT", "5056")))
    app.run(host=HOST, port=PORT, debug=False)
