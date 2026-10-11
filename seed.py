import json
import random

from app import append_audit, connect, make_results, make_trace, now

RUNS = [
    (1, "HPLC", "USP Assay-1 caffeine gradient", "Shimadzu LC-2030C Nexera", "Tablet extract", "m.okafor",
     "success", "", "System suitability passed first attempt after 2-week column conditioning."),
    (1, "HPLC", "USP Assay-1 caffeine gradient", "Shimadzu LC-2030C Nexera", "Tablet extract (hot room)", "m.okafor",
     "failure", "System suitability failed (resolution)",
     "Resolution fell below 2.0 when the lab reached 32 °C; thermostatting the column at 40 °C restores resolution on this matrix."),
    (1, "UV-Vis", "Colorimetric assay 480 nm", "Shimadzu UV-1900", "Dye intermediate", "s.ravi",
     "success", "", "Replicate RSD 0.8 %; calibration linear to 25 mg/L."),
    (1, "UV-Vis", "Colorimetric assay 480 nm", "Shimadzu UV-1900", "Turbid river water", "s.ravi",
     "failure", "Baseline drift / noise",
     "Scattering from unfiltered sample inflates absorbance; 0.45 µm filtration before reading removes the drift."),
    (2, "GC", "Headspace residual solvents", "Shimadzu GC-2030", "Lyophilized vial", "j.tran",
     "success", "", "All ICH Q3C solvents within limits, tailing 1.05."),
    (2, "GC", "Headspace residual solvents", "Shimadzu GC-2030", "Lyophilized vial, aged liner", "j.tran",
     "failure", "Co-elution / unresolved peaks",
     "Active liner site retained ethanol and co-eluted with acetone; replacing the liner after 140 injections fixed it."),
    (2, "HPLC", "Impurity gradient C18 150 mm", "Agilent 1260 (imported data)", "API intermediate", "j.tran",
     "invalid", "Sample preparation error",
     "Wrong diluent used (ACN instead of mobile phase A) — peak shapes unusable; prep checklist updated."),
    (1, "GC", "Fatty acid methyl esters", "Shimadzu GC-2030", "Biodiesel blend", "m.okafor",
     "failure", "Column or consumable fault",
     "Column bleed doubled after 600 runs; bake-out did not help. Trim 0.5 m or replace — plates dropped from 9000 to 3200."),
]

db = connect()
PROJECTS = ["MKT-77 stability study", "MKT-77 stability study", "", "EPA river survey",
            "Q3 release testing", "Q3 release testing", "Q3 release testing", "BIO-12 biodiesel"]
seed = 1000
for idx, (lab_id, tech, method, instr, matrix, op, outcome, mode, learning) in enumerate(RUNS):
    seed += random.randint(11, 999)
    trace = make_trace(tech, outcome, seed)
    results = make_results(tech, outcome, seed)
    cur = db.execute(
        """
        INSERT INTO runs (lab_id, technique, method, instrument, matrix, operator,
                          outcome, failure_mode, learning, results_json, trace_json,
                          published, published_at, anon, project, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lab_id, tech, method, instr, matrix, op, outcome, mode, learning,
            json.dumps(results), json.dumps(trace), 1, now(),
            1 if lab_id == 2 else 0, PROJECTS[idx], now(),
        ),
    )
    run_id = cur.lastrowid
    h = append_audit(db, run_id, op, "run.created", f"{tech} run recorded with outcome {outcome}")
    if learning:
        h = append_audit(db, run_id, op, "outcome.learning", learning)
    h = append_audit(db, run_id, op, "run.published", "Published to shared ledger" + (" (anonymized)" if lab_id == 2 else ""))
    db.execute("UPDATE runs SET chain_hash = ? WHERE id = ?", (h, run_id))

db.commit()
n = db.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"]
db.close()
print(f"seeded, {n} runs total")
