# RFC 006 — Typed Runtime Ratchet

> Stato: **IMPLEMENTATA / PROMOZIONE REMOTA BLOCCATA**, 2026-07-22. Priorità P0.

## Context

Il runtime aveva una baseline di 30 errori Mypy e nessun type gate riproducibile. I finding
includevano contratti realmente divergenti: predicate object dichiarati come stringhe, belief key
tipizzate chiamate con testo libero, metriche `score` rimosse ma ancora lette, chiavi telemetry non
serializzabili e variabili riusate con tipi incompatibili.

## Decision

1. Mypy 2.3.0 e gli stub PyYAML sono dipendenze development pinned.
2. L'intero `workspace/src` passa come unità; niente baseline parziale o suppress globale.
3. I body non annotati sono controllati; ignore inutili e cast ridondanti sono errori.
4. Il check vive nel job required `Lint`, quindi non richiede un nuovo nome nel ruleset.
5. I finding vengono corretti al confine proprietario, senza trasformare tutto in `Any`.

## Scope

- Contratti typed predicate tra supervisor, orchestrator e `DesiredState`.
- Identità `BeliefKey`, debug telemetry serializzabile e provenance evidence-based.
- Dispatch fileops tipizzato, lifecycle signal handler esplicito, PTY con stato definito.
- Verifier senza riuso cross-type delle variabili.
- Rimozione del fallback `duckduckgo_search` non dichiarato; `ddgs` resta backend unico.

## Non-goals

- Non implementa la FSM/event sourcing proposta da RFC-002.
- Non abilita strict mode globale senza misura; il ratchet corrente è zero-error con
  `check_untyped_defs`, non una dichiarazione di type completeness.
- Non sostituisce test runtime, security gate o isolamento di esecuzione.

## Validation gate

- `mypy` zero errori sull'intero runtime.
- Ruff e formatter verdi.
- Test regressivo: `debug_dump()` è JSON serializzabile con key canoniche.
- Suite completa, build, audit e Gitleaks verdi.
- Promozione remota vietata finché CI/Security GitHub non producono run verdi.

## Implementation evidence — 2026-07-22

- Baseline ridotta da **30 a 0 errori Mypy** sull'intero `workspace/src`.
- Ruff verde; **149 file** conformi al formatter.
- Test mirati reasoning/owner/orchestrator: **74 passed**; suite completa:
  **713 passed, 3 skipped**.
- Wheel/sdist `0.1.0a1` costruiti in isolamento; audit dipendenze senza vulnerabilità note.
- Gitleaks: storia pubblica 16,89 MB e diff RFC 24,30 KB, zero finding.
- Runtime netto **-26 LOC**; fallback non dichiarato e metriche confidence obsolete rimossi.
- CI/Security remoti restano non osservabili per il flag organizzativo: nessuna promozione.
