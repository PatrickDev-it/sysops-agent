# Summary

<!-- Sinapsi keeps the directory tree below current on its own — on every build, and live
     from the watcher whenever a file or folder is created, moved or deleted. There is no
     command to run and nothing to ask an agent to do. Do not edit between its markers;
     your edits are replaced. Everything else in this file is yours. -->

<!-- sinapsi:start v0.2.6 — kept current automatically by Sinapsi — refreshed on every build and by the watcher whenever files or folders are created, moved or deleted. No command to run; edits between these markers are replaced -->
```
brain/
  100_market/
  200_business/
  300_product/
  400_architecture/
  500_engineering/
  700_research/
  800_decisions/
  900_execution/
  architecture-next/
  decision-engine/
  research/
  thinking/
  000_identity.md
  BRAIN.md
workspace/
  _attic/
  _sandbox/
  benchmarks/
  bin/
  models/
  src/
  tests/
  validation/
  var/
  .coverage
.gitignore
.mcp.json
AGENTS.md
README.md
pyproject.toml
requirements.txt
```
<!-- sinapsi:end -->

**Read this first, and usually only this.** It is the cardinal read at the start of every
patch: the project's shape (above), the last sessions at a glance, and a short recap. Open
`session.md` or `handoff.md` only when this file leaves your actual question unanswered.

## Recent sessions

<!-- The last 10 patches, newest first: `- <timestamp> — <one line>`. Appended by the
     agent at the end of every patch, at the same time it appends session.md. Drop the
     11th; the full history is in session.md and, once archived, in archive/. -->

- 2026-07-22 — Migrata storia pubblica al profilo personale; fixate 9 failure CI Ubuntu non ermetiche.
- 2026-07-22 — Chiusa RFC-006: Mypy 30→0, 713 test verdi e runtime netto -26 LOC.
- 2026-07-22 — Implementata RFC-005 fail-closed: 712 test verdi; promozione bloccata da Actions HTTP 500.
- 2026-07-22 — Pubblicato Ignoryx/sistemista: tre branch, security features e ruleset attivi; CI remota da provare.
- 2026-07-22 — Chiuso gate locale RFC-004: 692 test, lint/build/audit/secrets verdi, baseline OSS pronta.
- 2026-07-22 — Approvata RFC-004: alpha pubblica minima su development, promozioni bloccate da security e GO gate.

## Where things stand

<!-- 5–10 lines, no more. What the project is doing right now, what is in flight, what is
     fragile, what the next action is. Rewritten (not appended) from session.md + handoff.md
     at the end of every patch. If it grows past 10 lines it has stopped being a summary. -->

- Repository target: `PatrickDev-it/sistemista`; tre branch migrati con SHA identici.
- RFC-005 integrata; RFC-006 chiusa localmente con Mypy 30→0 senza suppress globali.
- Gate locale: 713 passed/3 skipped; Ruff/format/type, build, audit e Gitleaks verdi.
- Wheel/sdist `0.1.0a1` verdi con 8 prompt, 8 KB YAML, LICENSE e NOTICE.
- Ruleset/security features personali attivi; Security remoto verde.
- Primo CI Ubuntu ha esposto 9 test non ermetici, corretti; PR personale deve confermare.
- Prossimo: PR verde, cancellare copia organizzativa, poi RFC-007 SBOM/provenance.
