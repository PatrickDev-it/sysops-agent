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

- 2026-07-22 — RFC-005 local gate: boundary mirato **83 passed**; suite completa
  **712 passed, 3 skipped**; Ruff check clean e **149 file** conformi; wheel/sdist `0.1.0a1`,
  dependency audit e curated-tree Gitleaks verdi. Test di composizione provano il rifiuto
  pre-planner di `RECOVERABLE`/malformed, dynamic write target fail-closed, nessun opt-out
  ambientale e nessun `ExecutionPolicy Bypass`. GitHub Actions è un blocker esterno: dispatch
  CI HTTP 500 e workflow Security non indicizzato mentre l'organizzazione è flagged.
- 2026-07-22 — RFC-004 local gate: Ruff check clean; all 148 Python files formatted;
  **692 passed, 3 skipped**; targeted security/redaction tests **78 passed**; wheel and sdist
  `0.1.0a1` built in isolation with prompts 8/8, KB 8/8, LICENSE and NOTICE; dependency audit
  reports no known vulnerabilities after removal of unused `diskcache`; curated-tree Gitleaks
  scan reports no leaks. Remote Actions and rulesets remain to be verified after first push.
- Static typing is not yet a release gate: la baseline ha 30 errori Mypy; RFC-006 deve
  introdurre un ratchet senza soppressioni globali.
