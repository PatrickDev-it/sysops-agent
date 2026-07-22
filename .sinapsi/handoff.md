# Handoff

_Aggiornato: 2026-07-22 — gate locale RFC-004 verde, pubblicazione remota immediata._

## Stato

Repository canonico: `( 2026 ) Sistemista`; il duplicato parziale è stato eliminato.
Branch corrente pre-pubblicazione: `hardening/production-readiness`, HEAD storico `faaf00d`
più un worktree di hardening intenzionale. Nessun remote configurato.

Sistemista è un agente sysops locale dual-GGUF:

- NAV `Qwen3-4B-Q5_K_M`: planning, verifica, recupero e fallback PTY;
- CODER `Qwen2.5-Coder-3B-Q6_K`: authoring/riparazione di comandi;
- oracolo opzionale via HTTP; `SISTEMISTA_ORACLE=0` mantiene l'esecuzione locale;
- runtime Python + processi `llama-server`, mono-utente e sequenziale.

## Gate RFC-004

- Ruff check verde; 148 file conformi al formatter.
- Test finali: **692 passed, 3 skipped**.
- Gitleaks sulla superficie pubblicabile: **zero finding**.
- `pip-audit -r requirements.txt`: **zero vulnerabilità note**.
- Wheel + sdist `0.1.0a1` verdi; wheel con prompt 8/8, KB 8/8, LICENSE e NOTICE.
- Apache-2.0, NOTICE, SECURITY, CONTRIBUTING, Code of Conduct e ownership presenti.
- CI least-privilege e Security scan definiti; action pinned a SHA.
- `.gitattributes` normalizza il testo LF e separa launcher CRLF/asset binari.
- `git diff --check` deve restare verde sullo snapshot pubblico.
- README coerente col runtime, con alpha/trust boundary dichiarati prima dei claim.

## Correzioni rilevanti

- Il guard anti-fabrication gestisce path con spazi/parentesi, sibling-prefix e riferimenti
  reali + inventati nella stessa stringa.
- `diskcache` inutilizzato è stato rimosso per `PYSEC-2026-2447` senza fix disponibile.
- Fixture secret sintetiche allowlisted puntualmente; validation data e path utente neutralizzati.
- Config Sinapsi portabile tramite PATH; nessun path macchina nel contratto pubblico.

## Strategia Git

1. Committare il worktree completo sul ramo storico.
2. Creare `archive/pre-publication` locale per conservare tutta la storia tecnica.
3. Creare `development` come root commit curata con lo snapshot corrente.
4. Creare `Ignoryx/sistemista`, pushare `development`, `validation`, `production`.
5. Impostare `development` come default e applicare ruleset senza force-push/deletion.
6. Verificare Actions e private vulnerability reporting sul remoto.

La root commit pubblica è necessaria perché la storia privata contiene fixture sintetiche che
Gitleaks segnala correttamente; non è una perdita di dati perché l'archive resta locale.

## Release path

- RFC-004: gate locale completato; remoto da verificare.
- `development`: alpha pubblica `0.1.0a1`, default iniziale.
- RFC-005: prossimo P0, Secure Execution Boundary.
- `validation`: vietata finché RFC-005 non è implementata e testata.
- `production`: vietata finché tutti gli RFC publication-target, benchmark, review security,
  SBOM/provenance e GO formale non sono chiusi.

## Rischi P0 aperti

1. `Confinement` è un filtro applicativo, non una jail.
2. `RECOVERABLE` può procedere senza approvazione umana.
3. Manca isolamento kernel/VM/container per mutazioni unattended.
4. `orchestrator.py` e `reasoning.py` restano monoliti; FSM implicita.
5. Mypy baseline: 30 errori, da chiudere con ratchet e non con soppressione globale.
6. Benchmark cross-OS e target 8 GB RAM non certificati.

## Evidenza da preservare

- Benchmark isolato onesto: **32/48 = 66,7% ARR**.
- Planner riproducibile: 132/132 prompt; residuo sullo stdout/stderr reale.
- Coverage baseline: 66,1%; orchestrator 48,6%, session 35,3%, terminal 20%.
- GBNF, predicati tipizzati, trace redatto e verdict distinti sono invarianti.

## Comandi canonici

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m build
python -m pip_audit -r requirements.txt
gitleaks git . --no-banner --redact
```
