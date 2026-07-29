# Handoff

_Aggiornato: 2026-07-30 — sweep Dependabot integrato, ratchet ruff 0.16._

## Stato

Repository canonico: `https://github.com/PatrickDev-it/sysops-agent`; default `development`, con
`validation` e `production` protetti. Branch corrente: `ops/record-dependency-sweep`. `origin` punta
esclusivamente al nuovo URL personale. Il repository resta pinnato dopo la rinomina.

La storia pre-pubblicazione resta solo nel branch locale `archive/pre-publication`, mai pubblicato.
La precedente copia `Ignoryx/sistemista` rimane eliminata e verificata inesistente.

Nessuna PR aperta: le sette PR Dependabot sono integrate, `development` è a `2cd9893` con i sei
required check verdi.

## Dependency baseline corrente

- Runtime: `numpy==2.5.1`, `typing_extensions==4.16.0`, `Jinja2==3.1.6`, `MarkupSafe==3.0.3`.
- Tooling: `ruff==0.16.0`, `mypy 2.3.0`, `pytest 9.1.1`, `types-PyYAML 6.0.12.20260724`.
- Actions pinnate per SHA: `actions/checkout` v7.0.1, `actions/setup-python` v7.0.0,
  `gitleaks/gitleaks-action` v3.0.0.
- `gitleaks-action` v3 gira su `node24` e non richiede input nuovi: nessuna `GITLEAKS_LICENSE`
  serve su questo repository pubblico a profilo personale. Verificato dal check `Gitleaks` verde.

## Ratchet ruff 0.16 (leggere prima di toccare un `.md`)

ruff 0.16 formatta anche i **fence Python dentro Markdown**. Il perimetro di `ruff format` passa da
149 a **275 file**: un blocco ```python in un README ora è codice per il formatter. Vedi
[known-issues.md](known-issues.md) per il sintomo esatto.

## Rebrand verificato

- Nome pubblico: **SysOps Agent**.
- Package Python e comando primario: `sysops-agent` / `sysops_agent` negli artifact.
- Alias CLI `sistemista` mantenuto temporaneamente durante il ciclo alpha.
- README, URL package, CONTRIBUTING, SECURITY e NOTICE allineati.
- Branch, storia, ruleset e pin preservati dalla rinomina GitHub.

## Gate corrente

- Suite locale: **713 passed, 3 skipped**.
- Ruff 0.16.0: check clean; format: **275 file** conformi; Mypy 2.3.0: exit 0, zero output.
- `pip-audit -r requirements.txt`: nessuna vulnerabilità nota.
- Wheel/sdist `sysops_agent-0.1.0a1`: verificati dal job `Package` su `development`.
- CI multi-OS, package, audit e Gitleaks restano required check del ruleset.
- Ruleset personale `19557677` attivo su `development`, `validation` e `production`.

## Come si integra una PR Dependabot qui

`strict_required_status_checks_policy` è attivo: ogni merge rende `BEHIND` tutte le altre PR, e i
bump pip toccano tutti `pyproject.toml` + `requirements.txt`. La sequenza è quindi **seriale**, una
PR per volta. Il ruolo admin ha `bypass_mode: pull_request` sul ruleset, quindi può saltare il
requisito di review ma **non** il fatto che i check debbano esistere. Regola operativa: bypassare
solo la review, mai la verifica — se la base è cambiata, riesegui la CI sulla base aggiornata prima
di mergiare. Sui conflitti Dependabot rebasa da sé: attendi che il branch sia discendente di
`development` prima di aggiungere commit propri, altrimenti il force-push del bot li cancella.

## RFC chiuse

- RFC-004: baseline OSS, storia pubblica curata, governance e packaging.
- RFC-005: execution policy fail-closed; non è isolamento kernel.
- RFC-006: Mypy 2.3.0 su tutto il runtime, baseline **30→0**.

## Release path

1. RFC-007: dependency reproducibility, SBOM e provenance.
2. RFC-008: backend isolato kernel/VM ed escape suite; blocker production.
3. RFC-009: benchmark multi-OS, risorse e claim falsificabili.
4. RFC-010: release engineering, signing/attestations, documentazione finale e GO.

`validation` resta vietata finché RFC-007 non è chiusa. `production` resta vietata fino alla
chiusura di tutti i publication target e al GO formale.

## Rischi P0 aperti

1. `Confinement` è policy applicativa, non una jail.
2. Manca isolamento kernel/VM/container per input o mutazioni unattended.
3. `orchestrator.py` e `reasoning.py` restano monoliti; FSM implicita.
4. Benchmark cross-OS e target 8 GB non certificati.

## Comandi canonici

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev]"   # allinea il tooling alle pin del pyproject
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
.\.venv\Scripts\python -m mypy
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m build
.\.venv\Scripts\python -m pip_audit -r requirements.txt
gitleaks git . --log-opts="HEAD" --no-banner --redact
```

> `pip install -e .` da solo **non** aggiorna il tooling: le pin di `ruff`/`mypy`/`pytest` stanno
> nell'extra `[dev]`. Una venv che riporta `ruff 0.15.x` mentre il pyproject pinna `0.16.0` conta
> 149 file invece di 275 e non riproduce il gate della CI.
