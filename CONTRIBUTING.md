# Contributing to LabLedger

Thanks for wanting to help. LabLedger is a small, dependency-light prototype —
the whole app is plain Python + Flask + SQLite with no build step, so getting
started takes seconds.

## Set up

```bash
git clone https://github.com/enoshiylas23-star/labledger.git
cd labledger
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python seed.py          # optional demo data
python app.py           # http://127.0.0.1:5000
```

## Run the tests

```bash
python -m unittest discover -s tests -v
```

The suite uses Flask's test client against a throwaway SQLite file
(`LABLEDGER_DB` is pointed at a temp path), so it never touches your real data.

## What we care about

- **Auditability.** Anything that changes a stored result leaves a
  hash-chained log entry. Never mutate a stored check or PASS/FAIL judgment in
  place; append a new event instead.
- **Honesty about the model.** The "model integrity" loop exists to admit and
  correct its own errors. Keep the promised-vs-observed accounting truthful.
- **No hidden services.** The prototype must keep running with `pip install
  flask` alone; optional integrations (live LLM, real instruments) stay behind
  environment variables and degrade gracefully.
- **Plain, readable code.** Single-file Flask, SQLite, semantic HTML, no
  frameworks where the platform already gives us the behaviour.

## Pull requests

1. Fork, branch (`git checkout -b feature/your-thing`).
2. Keep changes focused; add or update tests where behaviour changes.
3. Make sure `python -m unittest discover -s tests` is green.
4. Describe what and why, and note anything you could not verify.

## Ideas that would help most

- More reference compounds / spectra for the `/world` library.
- HPLC and GC simulators alongside `uvsim.py`.
- Real vendor driver adapters behind the bridge protocol.
- Accessibility and print-report polish.

By contributing you agree your work is licensed under the repository's MIT
license.
