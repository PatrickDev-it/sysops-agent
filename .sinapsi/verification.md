# Verification checklist

No patch is complete until its affected checks are green and the evidence is recorded here.

## Canonical commands

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m build
python -m pip_audit -r requirements.txt
gitleaks git . --no-banner --redact
```

Package validation must confirm that the wheel contains all eight prompt templates, all eight
knowledge-base YAML files, `LICENSE`, and `NOTICE`. A public-history scan must run from the root
of the public branch; scanning the private pre-publication archive is diagnostic, not a release
gate.

## Latest verification

- 2026-07-22 — RFC-004 local gate: Ruff check clean; all 148 Python files formatted;
  **692 passed, 3 skipped**; targeted security/redaction tests **78 passed**; wheel and sdist
  `0.1.0a1` built in isolation with prompts 8/8, KB 8/8, LICENSE and NOTICE; dependency audit
  reports no known vulnerabilities after removal of unused `diskcache`; curated-tree Gitleaks
  scan reports no leaks. Remote Actions and rulesets remain to be verified after first push.
- Static typing is not yet a release gate: the baseline has 30 Mypy errors and RFC-005/RFC-006
  must introduce a ratchet rather than suppressing them globally.
