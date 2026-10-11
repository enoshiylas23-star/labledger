# LabLedger — Design Notes

This document explains *why* LabLedger is built the way it is, what the current
prototype actually implements, and the concrete path from here to something a
regulated lab could run. For the competitive teardown see
[ANALYSIS.md](ANALYSIS.md); for market and positioning see
[MARKETING.md](MARKETING.md).

## 1. Principles

1. **Failures are data.** A failed run that nobody records is a failure every
   other lab repeats. Every run — success, failure or invalid — can be published
   to a shared, searchable, citable ledger. Non-success outcomes must carry a
   "what we learned" note.
2. **The audit trail is the product.** Laboratory software earns trust by being
   able to prove *what happened, in what order, and that it was not altered*.
   That property should not require a server licence or a Windows client.
3. **Honest, self-critical instrumentation.** The backend scores its own output
   against the accuracy it promised and, when it misses, writes an acknowledged
   mistake with cause and corrective action into the record. A tool that hides
   its errors is not a measurement tool.
4. **No build step, no lock-in.** Plain Python, Flask and SQLite, one required
   dependency. Anyone can read the whole system in an afternoon, run it from a
   laptop, and containerise it without a toolchain.
5. **Fast, legible UI over feature-checklist parity.** The console is measured
   against how quickly a chemist can set parameters, preview a calibration,
   pick an active peak and re-analyse — not against a vendor's menu tree.

## 2. What the prototype implements

```
                 ┌───────────────────────────────────────────────┐
 Browser UI ───▶ │ app.py  (Flask)                               │
 (semantic HTML, │  routes · form parsing · audit writer ·       │
 vanilla JS,     │  model-integrity loop · calibration library   │
 inline SVG)     └───────┬───────────────┬───────────────────────┘
                         │               │
        ┌────────────────┘               └───────────────┐
        ▼                                                 ▼
   uvsim.py                                    bridge.py ──▶ SQLite
   physics · quantitation · peaks ·            ingest · API-key auth · queue
   baselines · model corrections                       ▲
                                                       │
        ai.py  (LLM note-taker / offline expert)   driver_example.py (CLI)
        bots.py (project / researcher / company reviewers)
```

- **Storage:** one SQLite file with tables for labs, runs, instruments,
  UV measurements, calibrations, a bridge queue, an audit trail and a
  model-state row. Schema and lightweight migrations live in `app.py`.
- **Physics:** `uvsim.py` generates Beer–Lambert spectra per compound with
  instrument-specific wavelength accuracy, stray light and noise; four baseline
  methods; four measurement modes; weighted linear/quadratic regression with
  peak-height or peak-area signal and unit conversion.
- **Integrity:** a SHA-256 hash chain per measurement, `hash = SHA256(prev |
  action | detail | ts)`. Trend events (creation, re-analysis, model
  corrections) are appended, never edited; the run page and print report verify
  the chain in the browser.
- **Determinism:** the live quantitation preview is seeded, so the same inputs
  always produce the same standards, unknowns and regression before anything is
  persisted. This makes the UI reviewable and the tests stable.
- **AI:** `ai.py` prefers a configured LLM (xAI or any OpenAI-compatible
  endpoint) and otherwise falls back to a built-in expert engine; every note is
  labelled with which engine produced it, so nothing is silently hallucinated.

## 3. The audit + integrity model

Three independent records are kept, deliberately separated:

| Record | Written by | Mutable? | Purpose |
|---|---|---|---|
| Measurement log (hash chain) | `uvsim` + re-analysis | **append-only** | Provenance and order of every experiment-level event. |
| Audit trail (SQLite) | route handlers | append-only by convention | Who did what to which run and when. |
| Model mistakes | integrity loop | append + revise | Acknowledged misses, their cause, and the correction applied. |

A **re-analysis** (picking a different active peak) rebuilds derived values —
absorbances re-scaled by the ε-ratio, curve refit, chart regenerated — but
**never rewrites the original PASS/FAIL judgment**; the change is appended to
the chain with a `peak.reanalyze` event. That distinction (recompute derived
values vs. alter recorded results) is the core of trustworthy lab UX.

## 4. Path to production

The prototype is single-process and single-workspace on purpose. A credible
production shape would keep the same domain model and change four things:

1. **Multi-tenancy & data store.** Postgres instead of SQLite; lab/company
   tenancy enforced at the query layer and by row-level security; object storage
   for raw spectra.
2. **Identity & access.** OIDC/SAML SSO, role-based permissions (analyst,
   reviewer, admin), and real **electronic signatures** (21 CFR Part 11 /
   Annex 11): signature meaning, re-authentication at signing, and a signed
   audit record bound to the hash chain.
3. **Instrument integration.** Move the bridge to a first-class agent with
   device discovery, per-instrument credentials/rotation, back-pressure and
   reconciliation, plus importers for vendor export formats.
4. **Review & release workflow.** Stateful lifecycles (draft → submitted →
   reviewed → released), electronic sign-off, and immutable released records
   with retention policy.

None of these require re-architecting the physics, the quantitation, the audit
chain or the UI conventions — they are additive layers over the same
`measurement` core.

## 5. Roadmap

- [ ] Multi-tenant Postgres backend behind the existing storage seams.
- [ ] OIDC login + RBAC + e-signatures bound to the hash chain.
- [ ] Vendor-format importers and a hardened instrument agent.
- [ ] Calibration drift/expiry monitoring and control-chart (Levey–Jennings) views.
- [ ] Exportable audit packages (PDF + machine-readable chain) for reviewers.
- [ ] Public API tokens and webhooks for LIMS/ELN integration.

## 6. Non-goals (for now)

- Validating the prototype for regulated use. It is explicitly **not** validated
  software; treat generated data and the audit chain as a design sketch.
- Being a full LIMS. LabLedger is an analytical measurement + knowledge platform,
  not a sample-receiving or inventory system.
