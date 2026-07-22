# Handoff

_Aggiornato: 2026-07-22 — migrazione personale chiusa e copia organizzativa rimossa._

## Stato

Repository canonico: `https://github.com/PatrickDev-it/sistemista`; default `development`, con
`validation` e `production` protetti. `origin` punta esclusivamente al profilo personale.
`Ignoryx/sistemista` è stata eliminata e verificata inesistente. La storia pre-pubblicazione resta
solo nel branch locale `archive/pre-publication`, intenzionalmente mai pubblicato.

## Migrazione verificata

- I tre branch pubblici sono stati replicati inizialmente con SHA identici.
- PR personale #7 integrata in `development` al commit `04a36b7`.
- Sei required check verdi: Lint, Ubuntu, Windows, Package, Dependency audit e Gitleaks.
- Ruleset personale `19557677` attivo su `development`, `validation` e `production`.
- Discussions, topics, secret scanning, push protection, Dependabot e private reporting attivi.
- README, package metadata e NOTICE riferiscono il repository personale.
- La copia organizzativa e il relativo remote locale sono stati rimossi.

## Gate corrente

- Suite locale: **713 passed, 3 skipped**.
- Ruff, format check e Mypy verdi.
- Wheel/sdist, pip-audit e Gitleaks verdi.
- CI multi-OS personale confermata su Ubuntu e Windows.
- Pin del profilo ancora manuale: GitHub non espone una API pubblica per questa operazione.

## RFC chiuse

- RFC-004: baseline OSS, storia pubblica curata, governance e packaging.
- RFC-005: execution policy fail-closed; non è isolamento kernel.
- RFC-006: Mypy 2.3.0 su tutto il runtime, baseline **30→0**.

## Release path

1. Pin manuale di `PatrickDev-it/sistemista` tramite **Customize your pins**.
2. RFC-007: dependency reproducibility, SBOM e provenance.
3. RFC-008: backend isolato kernel/VM ed escape suite; blocker production.
4. RFC-009: benchmark multi-OS, risorse e claim falsificabili.
5. RFC-010: release engineering, signing/attestations, documentazione finale e GO.

`validation` resta vietata finché RFC-007 non è chiusa. `production` resta vietata fino alla
chiusura di tutti i publication target e al GO formale.

## Rischi P0 aperti

1. `Confinement` è policy applicativa, non una jail.
2. Manca isolamento kernel/VM/container per input o mutazioni unattended.
3. `orchestrator.py` e `reasoning.py` restano monoliti; FSM implicita.
4. Benchmark cross-OS e target 8 GB non certificati.

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
