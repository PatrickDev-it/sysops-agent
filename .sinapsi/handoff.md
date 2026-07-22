# Handoff

_Aggiornato: 2026-07-22 — migrazione profilo personale in verifica PR._

## Stato

Repository target: `https://github.com/PatrickDev-it/sistemista`; default `development`, con
`validation` e `production` protetti. Branch corrente: `ops/personal-profile-migration`.
`origin` punta al profilo; `ignoryx` è temporaneo e va rimosso dopo la cancellazione remota.
Storia pre-pubblicazione preservata solo in `archive/pre-publication`, mai pubblicata.

## Migrazione verificata

- SHA dei tre branch identici tra repo organizzativa e personale.
- Default `development`; ruleset personale ID `19557677` attivo sui tre branch.
- Discussions, topics, secret scanning, push protection, Dependabot e private reporting attivi.
- Security workflow personale verde: run `29926272395`.
- CI personale operativo ma prima run rossa: 9 failure Ubuntu non ermetiche ora corrette localmente.
- README, package metadata e NOTICE aggiornati al profilo personale.

## Fix CI multi-OS

- Fixture workspace-path usa una root nativa su POSIX e Windows.
- SQLite di test vive fuori dal task workspace, come in produzione.
- `world.norm_alias` riconosce `/` e `\` indipendentemente dall'host.
- Gate locale: **713 passed, 3 skipped**; 28 mirati verdi.
- Ruff/format/Mypy, wheel/sdist, pip-audit e Gitleaks verdi.

## Sequenza obbligatoria

1. Commit/push del branch e PR verso `development` personale.
2. Attendere CI + Security remoti verdi e integrare tramite ruleset.
3. Verificare SHA/default/security/ruleset post-merge.
4. Eliminare definitivamente `Ignoryx/sistemista`, come autorizzato dall'utente.
5. Rimuovere il remote locale `ignoryx` e verificare assenza repo dall'organizzazione.
6. Pin profilo: GitHub non espone API pubblica; resta un singolo passaggio UI manuale.

## RFC chiuse localmente

- RFC-004: baseline OSS, storia pubblica curata, governance e packaging.
- RFC-005: execution policy fail-closed; non è isolamento kernel.
- RFC-006: Mypy 2.3.0 su tutto il runtime, baseline **30→0**.

## Release path

- RFC-007: dependency reproducibility, SBOM e provenance.
- RFC-008: backend isolato kernel/VM e escape suite, blocker production.
- RFC-009: benchmark multi-OS, risorse e claim falsificabili.
- RFC-010: release engineering, signing/attestations, docs finali e GO.
- `validation`: vietata finché CI personale non è verde e RFC-007 non è chiusa.
- `production`: vietata fino a tutti i publication-target chiusi e GO formale.

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
