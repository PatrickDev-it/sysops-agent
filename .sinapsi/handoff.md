# Handoff

_Aggiornato: 2026-07-22 — RFC-006 chiusa localmente; integrazione su development in corso._

## Stato

Repository: `https://github.com/Ignoryx/sistemista`; default `development`, con branch
`validation` e `production` protetti. Branch corrente: `rfc/006-typed-runtime`.
Storia pre-pubblicazione preservata solo nel branch locale `archive/pre-publication`.

Sistemista è un alpha sysops agent locale dual-GGUF, Python + `llama-server`, mono-utente e
sequenziale. NAV usa Qwen3-4B; CODER usa Qwen2.5-Coder-3B; oracolo HTTP opzionale.

## RFC chiuse localmente

- RFC-004: baseline OSS, storia pubblica curata, governance e packaging.
- RFC-005: only-SAFE, classifier fail-closed, no env opt-out, dynamic sink/host mutation bloccati.
- RFC-006: Mypy 2.3.0 su tutto il runtime, baseline **30→0**, nessun suppress globale.
- Il boundary resta policy applicativa, non sandbox o isolamento kernel.

## Evidenza locale corrente

- Suite completa: **713 passed, 3 skipped**; mirati RFC-006: **74 passed**.
- Ruff verde; formatter verde su **149 file**; Mypy **zero errori**.
- Wheel/sdist `0.1.0a1` e pip-audit verdi.
- Gitleaks storia pubblica 16,89 MB + diff RFC 24,30 KB: zero finding.
- Wheel con prompt 8/8, KB YAML 8/8, LICENSE e NOTICE.
- Benchmark isolato storico: **32/48 = 66,7% ARR**; cross-OS/8 GB non certificati.

## Governance remota

- Ruleset attivo sui tre branch: PR, CODEOWNER review, thread resolution, linear history,
  sei required check, no delete/force-push; admin bypass solo tramite PR.
- Secret scanning, push protection, Dependabot security updates e private reporting attivi.
- PR #2 RFC-005 integrata su `development` al commit `d1967e2`.
- Blocco esterno: Ignoryx flagged; dispatch CI HTTP 500; Security non indicizzato.
- Ticket reinstatement aperto; nessuna promozione senza run CI e Security verdi.

## Release path

- Integrare RFC-006 su `development` via PR con evidenza locale e bypass tracciato.
- RFC-007: dependency reproducibility, SBOM e provenance.
- RFC-008: backend isolato kernel/VM e escape suite, blocker production.
- RFC-009: benchmark multi-OS, risorse e claim falsificabili.
- RFC-010: release engineering, signing/attestations, docs finali e GO.
- `validation`: vietata finché Actions remoti non sono verdi.
- `production`: vietata fino a tutti i publication-target chiusi e GO formale.

## Rischi P0 aperti

1. `Confinement` è un parser/policy applicativo, non una jail.
2. Manca isolamento kernel/VM/container per input o mutazioni unattended.
3. `orchestrator.py` e `reasoning.py` restano monoliti; FSM implicita.
4. Coverage runtime disomogenea; benchmark cross-OS e target 8 GB non certificati.
5. GitHub Actions non operativo finché persiste il flag organizzativo.

## Comandi canonici

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest -q
python -m build
python -m pip_audit -r requirements.txt
gitleaks git . --log-opts="HEAD" --no-banner --redact
```
