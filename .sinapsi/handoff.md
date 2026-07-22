# Handoff

_Aggiornato: 2026-07-22 — RFC-005 implementata localmente; integrazione su development in corso._

## Stato

Repository: `https://github.com/Ignoryx/sistemista`; default `development`, con branch
`validation` e `production` protetti. Branch di lavoro: `rfc/005-secure-execution-boundary`.
Storia pre-pubblicazione preservata solo nel branch locale `archive/pre-publication`.

Sistemista è un agente sysops locale dual-GGUF, Python + processi `llama-server`, mono-utente
e sequenziale. NAV usa Qwen3-4B; CODER usa Qwen2.5-Coder-3B; oracolo HTTP opzionale.

## RFC-005 implementata

- Solo goal `SAFE` raggiungono il planner.
- `RECOVERABLE`, classifier offline e malformed terminano `REFUSED` prima dell'esecuzione.
- `SISTEMISTA_UNCONFINED` non disabilita più il confinement.
- Dynamic write target e mutazioni host note sono rifiutati fail-closed.
- PowerShell non usa più `ExecutionPolicy Bypass`.
- Tutti gli owner di esecuzione continuano a condividere `Confinement`.
- Contratto dichiarato: policy applicativa, non sandbox o isolamento kernel.

## Evidenza locale

- Boundary mirato: **83 passed**.
- Suite completa: **712 passed, 3 skipped**.
- Ruff verde; formatter verde su **149 file**.
- Wheel/sdist `0.1.0a1`, pip-audit e curated-tree Gitleaks verdi.
- Wheel con prompt 8/8, KB YAML 8/8, LICENSE e NOTICE.
- Benchmark isolato storico: **32/48 = 66,7% ARR**; cross-OS/8 GB non certificati.

## Governance remota

- Ruleset attivo su tre branch: PR, review CODEOWNER, conversazioni risolte, history lineare,
  sei status check, no delete/force-push; admin bypass solo tramite PR.
- Secret scanning, push protection, Dependabot security updates e private reporting attivi.
- PR bootstrap integrata; CI registrato.
- Blocco esterno: Ignoryx è flagged, dispatch CI restituisce HTTP 500, Security non indicizzato.
- Ticket di reinstatement già aperto; nessuna promozione senza run CI e Security verdi.

## Release path

- RFC-004: gate locale/governance completati; chiusura attende Actions verdi.
- RFC-005: implementata localmente; PR verso `development` da integrare.
- RFC-006: typed orchestration/state-machine ratchet; baseline Mypy 30 errori.
- RFC successivi: dependencies/SBOM/provenance, execution backend isolato + escape suite,
  benchmark multi-OS e release engineering finale.
- `validation`: vietata finché RFC-005 non è integrata e i check remoti non sono verdi.
- `production`: vietata fino a tutti i publication-target chiusi e GO formale.

## Rischi P0 aperti

1. `Confinement` è un parser/policy applicativo, non una jail.
2. Manca isolamento kernel/VM/container per input o mutazioni unattended.
3. `orchestrator.py` e `reasoning.py` restano monoliti; FSM implicita.
4. Mypy baseline 30 errori e coverage runtime disomogenea.
5. Benchmark cross-OS e target 8 GB RAM non certificati.
6. GitHub Actions non operativo finché persiste il flag organizzativo.

## Comandi canonici

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m build
python -m pip_audit -r requirements.txt
gitleaks git . --log-opts="HEAD" --no-banner --redact
```
