# Contributing

Sistemista accepts focused, evidence-backed contributions. The project is security-sensitive:
behavioral claims must be reproducible, and safety controls must fail closed.

## Before opening a change

1. Use an issue for architectural or behavior-changing proposals; use an RFC under
   `.sinapsi/rfc` for changes to trust boundaries, execution policy, public APIs, or releases.
2. Branch from `development`. Never target `production` directly.
3. Keep runtime state, model weights, binaries, credentials, and personal infrastructure data
   outside version control.
4. Add a regression test that fails before the fix and passes after it.

## Local validation

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\ruff check .
.\.venv\Scripts\ruff format --check .
.\.venv\Scripts\pytest -q
.\.venv\Scripts\python -m build
```

Run Gitleaks against the complete branch history before pushing. Synthetic credentials in tests
must carry a precise inline `gitleaks:allow`; path-wide allowlists are not accepted.

## Pull requests

Describe the problem, the invariant being changed, the evidence, risk, rollback, and exact test
commands. Keep unrelated formatting and refactors out of the same change. All required checks and
review requirements must pass before promotion.

Contributions are licensed under Apache-2.0. By submitting a contribution, you represent that
you have the right to license it on those terms. Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
