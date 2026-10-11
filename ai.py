import json
import os
import re
import urllib.request

NOTES_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    summary TEXT NOT NULL,
    findings_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    actions_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

FAILURE_KB = {
    "System suitability failed (resolution)": (
        "Peaks are not baseline-resolved, so integration areas are unreliable.",
        ["Check column age and theoretical plates; replace if plates dropped >20% from history.",
         "Reduce injection volume or gradient steepness to spread early pairs.",
         "Verify mobile-phase preparation and degassing before re-running suitability."],
    ),
    "System suitability failed (tailing)": (
        "Peak asymmetry indicates column void, active sites or a mismatched mobile phase.",
        ["Guard column / column replacement if tailing >2 on standard.",
         "Adjust pH or add 0.1% acid/base to suppress silanol interactions.",
         "Confirm injection solvent strength is weaker than the mobile phase."],
    ),
    "Retention time shift": (
        "Retention moved, so identification confidence drops — usually flow, temperature or composition drift.",
        ["Check pump flow calibration and leak-tightness.",
         "Verify oven temperature and column thermostat equilibration time.",
         "Compare mobile-phase batch composition with the previous run."],
    ),
    "Baseline drift / noise": (
        "Detector baseline is unstable, which inflates LOQ and destroys quantitation at low level.",
        ["Allow longer lamp/equilibration warm-up; blank until drift < 0.1 mAU/10 min.",
         "Check mobile-phase degassing and mixer volume; replace worn seals.",
         "Switch detector lamp if intensity history is low."],
    ),
    "Calibration outside acceptance": (
        "Calibration failed acceptance, so reported concentrations from this run cannot be trusted.",
        ["Inspect residuals: a single bad standard → remake it; curved response → narrow the range.",
         "Verify standard preparation, expiry and storage.",
         "Re-run with fresh standards and confirm r² and back-calculated levels pass."],
    ),
    "Co-elution / unresolved peaks": (
        "Co-elution means the reported purity of the target peak is suspect.",
        ["Change selectivity: different column chemistry or organic modifier.",
         "Lower temperature or slow the gradient around the critical pair.",
         "Confirm with a second wavelength or MS extracted ion if available."],
    ),
    "Detector saturation": (
        "Signal left the linear range, so both peak shape and area are distorted.",
        ["Dilute the sample and re-inject; keep A below the linear ceiling.",
         "Reduce path/injection or switch to a shorter-path cell.",
         "If saturation persists at trace level, check stray light / lamp intensity."],
    ),
    "Column or consumable fault": (
        "A consumable is the most likely root cause of the observed separation change.",
        ["Record column serial/pressure history; replace if pressure rose >15%.",
         "Inspect frits and pre-column filter for particulates.",
         "Re-establish baseline with a fresh guard column before requalifying."],
    ),
    "Sample preparation error": (
        "The analytical chain is fine up to sample introduction — the sample itself is the suspect step.",
        ["Re-prepare the sample from the original material with fresh volumetrics.",
         "Check filtration, dilution factor and matrix effects.",
         "Run a spiked duplicate to separate preparation from instrument error."],
    ),
    "Instrument hardware fault": (
        "Hardware behaviour, not chemistry, explains this result.",
        ["Pull the instrument error log and service history.",
         "Run the built-in diagnostic/alignment routine.",
         "Quarantine the instrument for the affected method until service clears it."],
    ),
    "Other": (
        "Cause is not classifiable from the recorded metadata alone.",
        ["Compare against the last passing run of the same method.",
         "Escalate with raw data attached to the method owner.",
         "Record the observed anomaly in the learning note so the ledger can correlate later."],
    ),
}


def init(db):
    db.execute(NOTES_SCHEMA)


def _now():
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def provider_info():
    if os.environ.get("XAI_API_KEY"):
        return {"provider": "xai", "model": os.environ.get("XAI_MODEL", "grok-4"), "label": "Grok (xAI)"}
    if os.environ.get("LABLEDGER_AI_KEY") and os.environ.get("LABLEDGER_AI_BASE"):
        return {"provider": "compatible", "model": os.environ.get("LABLEDGER_AI_MODEL", "custom"), "label": os.environ.get("LABLEDGER_AI_BASE")}
    return {"provider": "local", "model": "labledger-expert-v1", "label": "Built-in expert engine (offline)"}


def chat(system, user, max_tokens=900):
    info = provider_info()
    if info["provider"] == "local":
        return None
    if info["provider"] == "xai":
        base, key = "https://api.x.ai/v1/chat/completions", os.environ["XAI_API_KEY"]
    else:
        base, key = os.environ["LABLEDGER_AI_BASE"].rstrip("/"), os.environ["LABLEDGER_AI_KEY"]
    body = json.dumps({
        "model": info["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(base, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _num(results, *keys):
    for k in keys:
        if k in results:
            try:
                return float(results[k])
            except (TypeError, ValueError):
                return None
    return None


def _run_findings(run, results):
    findings = []
    outcome = run["outcome"] or "success"
    if outcome == "failure" and run["failure_mode"]:
        cause, actions = FAILURE_KB.get(run["failure_mode"], FAILURE_KB["Other"])
        findings.append({"severity": "high", "text": f"Failure mode '{run['failure_mode']}': {cause}"})
        for a in actions[:2]:
            findings.append({"severity": "info", "text": f"Action: {a}"})
    elif outcome == "invalid":
        findings.append({"severity": "high", "text": "Run invalidated — data must not enter reports; investigate before reuse of this sequence."})
    plates = _num(results, "theoretical_plates")
    res = _num(results, "resolution_min")
    tail = _num(results, "tailing_factor", "asymmetry")
    r2 = _num(results, "r_squared")
    rsd = _num(results, "replicate_rsd_pct")
    lam = _num(results, "lambda_max_nm")
    drift = _num(results, "blank_drift_ma")
    if plates is not None and plates < 6000:
        findings.append({"severity": "medium", "text": f"Plate count {plates:.0f} is low — column efficiency has degraded for this method."})
    if res is not None and res < 1.5:
        findings.append({"severity": "high", "text": f"Resolution {res:.2f} < 1.5 — critical pair is not quantifiable."})
    if tail is not None and tail > 1.8:
        findings.append({"severity": "medium", "text": f"Tailing/asymmetry {tail:.2f} > 1.8 — expect biased integration of the target peak."})
    if r2 is not None and r2 < 0.999:
        findings.append({"severity": "medium", "text": f"Calibration r² {r2:.4f} below 0.999 — quantitation range needs review."})
    if rsd is not None and rsd > 2.0:
        findings.append({"severity": "medium", "text": f"Replicate RSD {rsd:.2f}% exceeds typical 2% acceptance — precision problem in this run."})
    if lam is not None and drift is not None and drift > 0.005:
        findings.append({"severity": "low", "text": f"Blank drift {drift} mAU may bias the low end of the calibration."})
    if not findings:
        findings.append({"severity": "info", "text": "All recorded system-suitability values sit inside conventional acceptance limits."})
    return findings


def _ledger_context(db, run):
    rows = db.execute(
        """
        SELECT id, failure_mode FROM runs
        WHERE published = 1 AND outcome != 'success' AND technique = ? AND id != ?
        ORDER BY id DESC LIMIT 40
        """,
        (run["technique"], run["id"]),
    ).fetchall()
    same = [r for r in rows if run["failure_mode"] and r["failure_mode"] == run["failure_mode"]]
    return {
        "published_failures_same_technique": len(rows),
        "same_failure_mode": len(same),
        "similar_run_ids": [r["id"] for r in same[:5]],
    }


def analyze_run(db, run):
    results = json.loads(run["results_json"])
    findings = _run_findings(run, results)
    context = _ledger_context(db, run)
    outcome = run["outcome"] or "no outcome"
    headline = f"{run['technique']} run of {run['method']} on {run['instrument']} recorded as {outcome}."
    if context["same_failure_mode"]:
        findings.append({"severity": "info", "text": f"{context['same_failure_mode']} published run(s) in the ledger share this failure mode (e.g. {', '.join('#' + str(i) for i in context['similar_run_ids'])})."})
    tags = sorted({run["technique"].lower(), (run["outcome"] or "none")})
    if run["failure_mode"]:
        tags.append(run["failure_mode"].split(" (")[0].lower())
    analysis = {
        "summary": headline,
        "findings": findings[:8],
        "tags": tags[:6],
        "actions": [f["text"][8:] for f in findings if f["text"].startswith("Action: ")][:4],
        "context": context,
        "provider": provider_info()["provider"],
    }
    return enrich(analysis, f"Run context: {json.dumps({'technique': run['technique'], 'method': run['method'], 'outcome': run['outcome'], 'failure_mode': run['failure_mode'], 'results': results, 'ledger': context})}")


def analyze_uv(db, m):
    checks = json.loads(m["checks_json"])
    truth = json.loads(m["truth_json"]) if m["truth_json"] else None
    analysis = json.loads(m["analysis_json"])
    errors = json.loads(m["errors_json"]) if m["errors_json"] else []
    findings = []
    failed = [c for c in checks if not c["pass"]]
    for c in failed:
        findings.append({"severity": "high", "text": f"Check '{c['name']}' failed: {c['value']} outside limit {c['limit']}."})
    if not failed:
        findings.append({"severity": "info", "text": f"All {len(checks)} acceptance checks passed (judgment {m['judgment']})."})
    if errors:
        for e in errors:
            findings.append({"severity": "medium", "text": f"Model acknowledged a miss: {e['label']} observed {e['observed']} {e['unit']} vs promised ±{e['promised']} — {e['cause']}; corrected ({e['action']})."})
    if m["source"] == "physical" and any(not c["pass"] and c["name"] == "Absorbance range" for c in checks):
        findings.append({"severity": "high", "text": "Absorbance outside 0.1–2.5 A: dilute the sample (or shorten path) and re-measure before trusting identity or quantitation."})
    if m["source"] == "virtual":
        findings.append({"severity": "info", "text": "Virtual run: Beer–Lambert ground truth was available, so accuracy is verified rather than assumed."})
    tags = [m["mode"].lower(), m["source"]]
    analysis = {
        "summary": f"{m['mode']} on {m['instrument']} ({m['compound']}, {m['source']} source) judged {m['judgment']}.",
        "findings": findings[:8],
        "tags": tags,
        "actions": [],
        "provider": provider_info()["provider"],
    }
    return enrich(analysis, f"UV-Vis measurement context: {json.dumps({'mode': m['mode'], 'checks': checks, 'analysis': analysis, 'truth': truth})}")


def enrich(analysis, context):
    info = provider_info()
    if info["provider"] == "local":
        return analysis
    system = ("You are LabLedger's in-app AI analyst for analytical chemistry (UV-Vis, HPLC, GC). "
              "You receive JSON context. Reply ONLY with JSON: {\"summary\": one paragraph, \"extra\": [up to 2 short findings]}. "
              "Be concrete and conservative; never invent numbers that are not in the context.")
    out = chat(system, context)
    if not out:
        return analysis
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return analysis
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return analysis
    if isinstance(parsed.get("summary"), str) and len(parsed["summary"]) > 20:
        analysis["summary"] = parsed["summary"].strip()
    for extra in (parsed.get("extra") or [])[:2]:
        if isinstance(extra, str) and len(extra) > 15:
            analysis["findings"].append({"severity": "low", "text": extra.strip()})
    analysis["provider"] = info["provider"]
    return analysis


def save_note(db, target_type, target_id, analysis):
    cur = db.execute(
        "INSERT INTO ai_notes (target_type, target_id, provider, summary, findings_json, tags_json, actions_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (target_type, target_id, analysis["provider"], analysis["summary"],
         json.dumps(analysis["findings"]), json.dumps(analysis["tags"]),
         json.dumps(analysis.get("actions", [])), _now()),
    )
    db.commit()
    return cur.lastrowid


def notes_for(db, target_type, target_id):
    return db.execute(
        "SELECT * FROM ai_notes WHERE target_type = ? AND target_id = ? ORDER BY id DESC",
        (target_type, target_id),
    ).fetchall()


def retrieve(db, question):
    q = f"%{question}%"
    runs = db.execute(
        """
        SELECT r.id, r.technique, r.method, r.instrument, r.matrix, r.outcome, r.failure_mode,
               r.learning, r.published, l.name lab_name
        FROM runs r JOIN labs l ON l.id = r.lab_id
        WHERE r.method LIKE ? OR r.matrix LIKE ? OR r.instrument LIKE ?
           OR COALESCE(r.failure_mode,'') LIKE ? OR COALESCE(r.learning,'') LIKE ?
           OR COALESCE(r.project,'') LIKE ?
        ORDER BY r.id DESC LIMIT 8
        """,
        (q, q, q, q, q, q),
    ).fetchall()
    uv = db.execute(
        "SELECT id, mode, instrument, compound, judgment FROM uv_measurements"
        " WHERE compound LIKE ? OR instrument LIKE ? OR mode LIKE ? ORDER BY id DESC LIMIT 6",
        (q, q, q),
    ).fetchall()
    return runs, uv


def ask(db, question):
    runs, uv = retrieve(db, question)
    counts = db.execute(
        "SELECT technique, outcome, COUNT(*) c FROM runs WHERE published = 1 GROUP BY technique, outcome"
    ).fetchall()
    context = {
        "question": question,
        "matching_runs": [dict(r) for r in runs],
        "matching_uv_measurements": [dict(u) for u in uv],
        "ledger_counts": [dict(c) for c in counts],
    }
    info = provider_info()
    if info["provider"] != "local":
        system = ("You are LabLedger's AI analyst. Answer the user's laboratory question using ONLY the JSON records provided. "
                  "Cite run ids like #12. If the records do not contain the answer, say so plainly.")
        out = chat(system, json.dumps(context), max_tokens=700)
        if out:
            return {"answer": out.strip(), "runs": runs, "uv": uv, "provider": info["provider"]}
    lines = []
    if runs:
        lines.append(f"Found {len(runs)} matching record(s):")
        for r in runs:
            line = f"#{r['id']} {r['technique']} {r['method']} ({r['lab_name']}) — {r['outcome'] or 'no outcome'}"
            if r["failure_mode"]:
                line += f", {r['failure_mode']}"
            lines.append("  " + line)
            if r["learning"]:
                lines.append(f"    learned: {r['learning'][:140]}")
    else:
        lines.append("No run record matches those keywords.")
    if uv:
        lines.append(f"UV-Vis measurements: " + ", ".join(f"#{u['id']} {u['compound']} {u['judgment']}" for u in uv))
    tot = {}
    for c in counts:
        tot[c["technique"]] = tot.get(c["technique"], 0) + c["c"]
    lines.append("Ledger totals: " + ", ".join(f"{k} {v}" for k, v in sorted(tot.items())))
    return {"answer": "\n".join(lines), "runs": runs, "uv": uv, "provider": "local"}


def bot_note(db, target, bot):
    if target["type"] == "run":
        analysis = analyze_run(db, target["row"])
    else:
        analysis = analyze_uv(db, target["row"])
    info = provider_info()
    openers = {
        "project": f"[project {bot['scope']}] I reviewed this run against the project's standing concerns.",
        "researcher": f"[for {bot['scope']}] Here is my read of this record.",
        "company": f"[company QA bot {bot['name']}] Compliance-oriented review of this record.",
    }
    body_parts = [openers.get(bot["kind"], bot["name"]), ""]
    body_parts.append(analysis["summary"])
    body_parts.append("")
    for f in analysis["findings"]:
        body_parts.append(f"- ({f['severity']}) {f['text']}")
    if bot["mandate"]:
        body_parts.append("")
        body_parts.append(f"Mandate: {bot['mandate']}")
    body_parts.append("")
    body_parts.append(f"[analysis engine: {info['label']}]")
    if info["provider"] != "local":
        system = (f"You are bot '{bot['name']}' ({bot['kind']} bot, scope '{bot['scope']}'). "
                  f"Mandate: {bot['mandate'] or 'general review'}. Write a short markdown note (max 120 words) "
                  "reviewing this laboratory record. Use only facts from the provided analysis. "
                  "Start with a one-line verdict.")
        out = chat(system, json.dumps({"analysis": analysis}), max_tokens=400)
        if out and len(out.strip()) > 40:
            return out.strip()
    return "\n".join(body_parts).strip()
