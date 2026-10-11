# Analysis: Shimadzu & competitor analytical software (UV-Vis, HPLC, GC)

## 1. Shimadzu LabSolutions family

| Product | Scope | Deployment |
|---|---|---|
| **LabSolutions LC/GC** | Control + analysis of up to 4 HPLC/GC instruments from one PC | Standalone, file-based |
| **LabSolutions DB / CS** | Database-backed data management, projects, users, audit trail, e-signature, 21 CFR Part 11 / GLP / CSV compliance | Client-server, server can run on AWS/Azure/GCP IaaS |
| **LabSolutions CS powered by i-QLinks** | Above + test plans, test orders, auto report generation (lightweight LIMS) | Client-server + browser clients |
| **LabSolutions UV-Vis** | UV-Vis spectrophotometer control: spectrum, quantitative, photometric, time-course modes; QC judgment, JIS/ISO color calc, Excel live transfer | Standalone (DB/CS variants for compliance) |
| **LabSolutions Insight** | LC-MS/MS & GC-MS/MS multi-analyte review, side-by-side display, threshold flagging | Client |
| **Peakintelligence** | AI peak integration trained on expert integrations; ~75 % less analysis time | Option add-on |
| **i-PDeA II** | MCR-ALS deconvolution of unseparated/hidden peaks with PDA | Option add-on |
| **LabSolutions MD** | AQbD method development (DoE, design space) | Option |
| **LabSolutions Sync** | Workflow automation with 3rd-party pretreatment/synthesis hardware | Option |
| **LabSolutions Direct** | Phone/tablet browser remote monitoring & control of LC/GC | Web (pre-installed) |
| **Open Solution / Data Browser** | Open-access data viewing for research teams | Web |

**Strengths**
- One consistent UI from acquisition → analysis → report across LC, GC, LC-MS, GC-MS, UV-Vis, IR, ICP, TOC.
- Genuine compliance machinery: single unified audit trail, revision numbers on re-integration (raw data never overwritten), report sets bundling results + full operation log, e-signatures, project-scoped permissions.
- Instrument status monitor with lab-room icon layout; scheduled auto startup/shutdown.
- Cloud-viable server (IaaS) for LabSolutions CS, terminal-server clients, LIMS/ELN linkage.

**Weaknesses / gaps**
1. **Vendor lock-in** — mixed-vendor instrument drivers need extra validation; non-Shimadzu data mostly imported, not controlled.
2. **Not cloud-native** — CS is a Windows client/server lifted onto IaaS; no real multi-tenant SaaS, no web-first UX for the analysis itself (Data Browser is the exception, view-only).
3. **Per-instrument/per-option licensing** — Peakintelligence, i-PDeA II, MD, Sync are paid add-ons, so capability varies lab by lab.
4. **Failures are invisible** — LabSolutions records *an* audit trail for *your* run, but a failed method, a bad column, an out-of-spec result stays inside that lab's database forever. No cross-lab learning, no registry of negative results.
5. **Manual integration still a regulatory sore point** — AI helps (Peakintelligence) but the platform offers no community-level validation of integration choices.
6. **Research vs QC split** — research teams get Data Browser/Open Solution; QC gets compliance. The "publish what I learned" workflow for researchers is not served.

## 2. Competitive landscape

| CDS | Strengths | Weaknesses |
|---|---|---|
| **Waters Empower** | Pharma compliance gold standard, huge installed base | Old UX, Waters-centric, weak AI |
| **Thermo Chromeleon** | Modern UI, best multi-vendor control, Ardia cloud add-on | Method tuning effort, MS ecosystem pull |
| **Agilent OpenLab** | Method-led workflow, strong GC/LC | Slow rollout, Agilent-centric |
| **Shimadzu LabSolutions** | Broadest instrument span (LC→UV-Vis→ICP), AI integration option | Least cloud-ready of the big four, lock-in |
| **DataApex Clarity / OpenChrom** | Cheap / open source | No enterprise compliance depth |

Market-wide gaps (from 2026 buyer guides): cloud deployment is still a checkbox, AI is bolted on per-vendor, LIMS integration is the biggest ROI driver yet still painful, and **no product anywhere** offers a shared, citable registry of analytical outcomes.

## 3. The gap this project targets

Everything above is *record-keeping for one lab*. The scientific failure modes that actually destroy accuracy are:

- a method that fails on a specific matrix, discovered again six months later by another lab
- an integration parameter set that quietly inflates results near a specification limit
- a column lot / mobile phase / column-age effect nobody published
- duplicated method-development effort across labs (LabSolutions MD solves this only inside one company)

**LabLedger's thesis:** every run — success *or* failure — should be publishable as a structured, citable, machine-readable record, so accuracy compounds across labs instead of staying trapped in per-vendor databases.

## 4. What we build instead

Cloud-native, browser-first, multi-tenant analytical platform:

1. **Runs of any technique** (UV-Vis, HPLC, GC — extensible) with structured results and embedded traces.
2. **Mandatory outcome capture**: success / failure / invalid, with failure mode and "what we learned".
3. **One-click publish** of any run to a shared, anonymizable ledger — the negative-results registry.
4. **Immutable, hash-chained audit trail** per run (data-integrity answer to 21 CFR Part 11, without the Windows client/server).
5. **Ledger discovery**: filter/search published outcomes by technique, matrix, instrument, outcome — the thing LabSolutions/Empower/Chromeleon/OpenLab all lack.

Full architecture in `DESIGN.md`; working prototype in `app.py`.
