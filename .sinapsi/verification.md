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

- 2026-07-22 — Personal-profile migration: `development`, `validation` e `production` hanno
  SHA identici tra origine organizzativa e `PatrickDev-it/sistemista`; default/ruleset/security
  features ricreati. Security remoto verde; il primo CI Ubuntu ha esposto 9 test non ermetici.
  Fix locale: path fixture native, state DB esterno al task workspace, alias basename indipendente
  dall'OS. Gate locale: **713 passed, 3 skipped**, Ruff/format/Mypy/build/audit/Gitleaks verdi;
  chiusura subordinata alla PR personale verde.
- 2026-07-22 — RFC-006 local gate: Mypy **30 → 0 errori** sull'intero runtime; Ruff clean e
  **149 file** conformi; test mirati **74 passed**, suite completa **713 passed, 3 skipped**;
  wheel/sdist `0.1.0a1` verdi; dependency audit senza vulnerabilità note; Gitleaks sulla storia
  pubblica (16,89 MB) e sul diff RFC (24,30 KB) con zero finding. GitHub Actions resta un
  blocker esterno mentre l'organizzazione è flagged.
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
- Static typing è un release gate: Mypy 2.3.0 controlla tutto `workspace/src` con
  `check_untyped_defs` e baseline zero-error, senza soppressioni globali.
