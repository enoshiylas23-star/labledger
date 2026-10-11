"""LabLedger test suite.

Runs the Flask app through its test client against a throwaway SQLite file, so
no running server or real data is required:

    python -m unittest discover -s tests -v
"""

import os
import re
import sqlite3
import tempfile
import unittest

_TMPDIR = tempfile.mkdtemp(prefix="labledger-tests-")
os.environ["LABLEDGER_DB"] = os.path.join(_TMPDIR, "test.db")
os.environ["LABLEDGER_SECRET"] = "test-secret"

import app as labledger  # noqa: E402  (must import after env is set)


SPECTRUM_FORM = {
    "mode": "Spectrum", "compound": "Caffeine", "instrument": "UV-1900i",
    "source": "virtual", "conc_uM": "100", "path_cm": "1", "wl_start": "200",
    "wl_end": "800", "step_nm": "2", "speed": "medium", "baseline": "endpoint",
    "peak_threshold": "4", "min_peak_span": "4", "active_peak": "auto",
    "operator": "tester", "smoothing": "5", "bandwidth_nm": "1",
}

QUANT_FORM = {
    "mode": "Quantitative", "compound": "Caffeine", "instrument": "UV-1900i",
    "source": "virtual", "conc_uM": "100", "path_cm": "1", "wl_start": "200",
    "wl_end": "800", "step_nm": "2", "speed": "medium", "baseline": "blank",
    "cal_type": "linear", "weighting": "1/x", "meas_type": "area", "units": "mg/L",
    "reps": "3", "n_unknowns": "2", "std_levels": "", "use_calibration": "",
    "operator": "tester",
}


def _mid_from(resp):
    match = re.search(r"/uvvis/m/(\d+)", resp.headers.get("Location", ""))
    return int(match.group(1)) if match else None


class LabLedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        labledger.app.config.update(TESTING=True)
        cls.client = labledger.app.test_client()

    def test_healthz(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("counts", body)
        self.assertIn("model_revision", body)

    def test_index_and_pages(self):
        for path in ("/", "/ledger", "/world", "/instruments", "/ai", "/bots", "/uvvis/model"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_uvvis_console_has_five_tabs(self):
        r = self.client.get("/uvvis")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for tab in ("tab-params", "tab-baseline", "tab-cal", "tab-quant", "tab-peak"):
            self.assertIn(f'id="{tab}"', html)

    def test_quant_preview(self):
        r = self.client.post("/uvvis/quantpreview", data=QUANT_FORM)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        for key in ("standards", "unknowns", "calibration", "summary", "chart"):
            self.assertIn(key, body)
        self.assertIn("<svg", body["chart"])
        self.assertTrue(len(body["standards"]) >= 2)

    def test_quant_preview_deterministic(self):
        a = self.client.post("/uvvis/quantpreview", data=QUANT_FORM).get_json()
        b = self.client.post("/uvvis/quantpreview", data=QUANT_FORM).get_json()
        self.assertEqual(a["standards"], b["standards"])
        self.assertEqual(a["unknowns"], b["unknowns"])

    def test_all_baseline_and_weighting_combos_run(self):
        for baseline in ("none", "blank", "endpoint", "autozero"):
            for weighting in ("none", "1/x", "1/x2"):
                form = dict(QUANT_FORM, baseline=baseline, weighting=weighting)
                with self.subTest(baseline=baseline, weighting=weighting):
                    r = self.client.post("/uvvis/run", data=form)
                    self.assertEqual(r.status_code, 302)
                    mid = _mid_from(r)
                    self.assertIsNotNone(mid)
                    detail = self.client.get(f"/api/uvvis/{mid}").get_json()
                    rec = [u for u in detail["data"]["unknowns"] if u.get("recovery_pct") is not None]
                    self.assertTrue(rec)
                    for u in rec:
                        self.assertLess(abs(u["recovery_pct"] - 100), 5)

    def test_spectrum_run_and_api_detail(self):
        r = self.client.post("/uvvis/run", data=SPECTRUM_FORM)
        self.assertEqual(r.status_code, 302)
        mid = _mid_from(r)
        self.assertIsNotNone(mid)

        listing = self.client.get("/api/uvvis").get_json()
        self.assertTrue(any(m["id"] == mid for m in listing["measurements"]))

        detail = self.client.get(f"/api/uvvis/{mid}")
        self.assertEqual(detail.status_code, 200)
        body = detail.get_json()
        self.assertEqual(body["compound"], "Caffeine")
        self.assertIn(body["judgment"], ("PASS", "FAIL"))
        self.assertGreaterEqual(body["chain"]["length"], 1)
        self.assertTrue(body["checks"])
        self.assertIn("/uvvis/m/%d" % mid, body["links"]["html"])

    def test_api_uvvis_unknown_is_404(self):
        self.assertEqual(self.client.get("/api/uvvis/999999").status_code, 404)

    def test_peak_reanalyze_keeps_judgment_and_appends_log(self):
        mid = _mid_from(self.client.post("/uvvis/run", data=SPECTRUM_FORM))
        before = self.client.get(f"/api/uvvis/{mid}").get_json()

        r = self.client.post(f"/uvvis/m/{mid}/peak", data={"manual_wl": "240"})
        self.assertEqual(r.status_code, 302)

        after = self.client.get(f"/api/uvvis/{mid}").get_json()
        self.assertEqual(after["judgment"], before["judgment"])
        self.assertEqual(after["chain"]["length"], before["chain"]["length"] + 1)
        self.assertTrue(after["analysis"].get("reanalyzed"))
        self.assertIn("eps_ratio", after["analysis"])
        self.assertEqual(after["analysis"]["active_peak_nm"], 240)

    def test_peak_reanalyze_requires_a_selection(self):
        mid = _mid_from(self.client.post("/uvvis/run", data=SPECTRUM_FORM))
        before = self.client.get(f"/api/uvvis/{mid}").get_json()
        self.client.post(f"/uvvis/m/{mid}/peak", data={})
        after = self.client.get(f"/api/uvvis/{mid}").get_json()
        self.assertEqual(after["chain"]["length"], before["chain"]["length"])

    def test_print_report_renders_chain(self):
        mid = _mid_from(self.client.post("/uvvis/run", data=SPECTRUM_FORM))
        r = self.client.get(f"/uvvis/m/{mid}/print")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Chain tail", html)
        self.assertIn("Caffeine", html)

    def test_quantitative_run_saves_calibration(self):
        mid = _mid_from(self.client.post("/uvvis/run", data=QUANT_FORM))
        detail = self.client.get(f"/api/uvvis/{mid}").get_json()
        cid = detail["analysis"].get("saved_calibration_id")
        self.assertTrue(cid)

        con = sqlite3.connect(labledger.DB_PATH)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM calibrations WHERE id = ?", (cid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["weighting"], "1/x")
        self.assertEqual(row["units"], "mg/L")
        self.assertEqual(row["meas_type"], "area")

        self.assertEqual(self.client.get(f"/uvvis?use={cid}").status_code, 200)
        self.client.post(f"/uvvis/calibration/{cid}/delete", data={})
        left = con.execute("SELECT COUNT(*) FROM calibrations WHERE id = ?", (cid,)).fetchone()[0]
        con.close()
        self.assertEqual(left, 0)

    def test_run_creation_and_ledger_publish(self):
        form = {"technique": "HPLC", "method": "RP-C18 gradient", "instrument": "LC-2050",
                "matrix": "plasma", "operator": "tester", "outcome": "failure",
                "failure_mode": "peak tailing", "learning": "re-equilibrate longer",
                "project": "STUDY-1"}
        r = self.client.post("/runs/new", data=form)
        self.assertEqual(r.status_code, 302)
        run_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
        self.assertEqual(self.client.post(f"/runs/{run_id}/publish", data={}).status_code, 302)
        ledger = self.client.get("/api/ledger").get_json()
        self.assertTrue(any(str(row["id"]) == str(run_id) for row in ledger))

    def test_bridge_ingest_requires_valid_key(self):
        r = self.client.post("/api/ingest", json={"instrument": "nope", "api_key": "bad", "points": []})
        self.assertIn(r.status_code, (400, 401))


if __name__ == "__main__":
    unittest.main(verbosity=2)
