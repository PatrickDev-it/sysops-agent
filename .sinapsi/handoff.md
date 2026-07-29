# Handoff

_Aggiornato: 2026-07-22 — identità pubblica inglese applicata._

## Stato

Repository canonico: `https://github.com/PatrickDev-it/sysops-agent`; default `development`, con
`validation` e `production` protetti. Branch corrente: `docs/sysops-agent-brand`. `origin` punta
esclusivamente al nuovo URL personale. Il repository resta pinnato dopo la rinomina.

La storia pre-pubblicazione resta solo nel branch locale `archive/pre-publication`, mai pubblicato.
La precedente copia `Ignoryx/sistemista` rimane eliminata e verificata inesistente.

## Rebrand verificato

- Nome pubblico: **SysOps Agent**.
- Package Python e comando primario: `sysops-agent` / `sysops_agent` negli artifact.
- Alias CLI `sistemista` mantenuto temporaneamente durante il ciclo alpha.
- README, URL package, CONTRIBUTING, SECURITY e NOTICE allineati.
- Branch, storia, ruleset e pin preservati dalla rinomina GitHub.

## Gate corrente

- Suite locale: **713 passed, 3 skipped**.
- Ruff: clean; format: **149 file** conformi; Mypy: zero errori.
- Wheel/sdist `sysops_agent-0.1.0a1` costruiti in isolamento.
- CI multi-OS, package, audit e Gitleaks restano required check del ruleset.
- Ruleset personale `19557677` attivo su `development`, `validation` e `production`.

## RFC chiuse

- RFC-004: baseline OSS, storia pubblica curata, governance e packaging.
- RFC-005: execution policy fail-closed; non è isolamento kernel.
- RFC-006: Mypy 2.3.0 su tutto il runtime, baseline **30→0**.

## Release path

1. Integrare il rebrand tramite PR verde su `development`.
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
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
.\.venv\Scripts\python -m mypy
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m build
.\.venv\Scripts\python -m pip_audit -r requirements.txt
gitleaks git . --log-opts="HEAD" --no-banner --redact
```
