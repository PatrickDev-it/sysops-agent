# RFC 005 — Fail-Closed Execution Boundary

> Stato: **IMPLEMENTATA / PROMOZIONE REMOTA BLOCCATA**, 2026-07-22. Priorità P0.

## Context

Il runtime esegue stringhe generate da un modello nello stesso account dell'operatore. Il filtro
di confinement riduce il blast radius ma non è una sandbox: il parser può avere falsi negativi,
`SISTEMISTA_UNCONFINED=1` disabilita lo scope dei path, `RECOVERABLE` procede senza consenso e
PowerShell viene lanciato con `ExecutionPolicy Bypass`.

Il target immediato non può promettere isolamento kernel: Docker non è disponibile e WSL monta
il filesystem host, quindi non è un boundary. Il contratto di validation deve essere più stretto
e falsificabile: nessuna mutazione host, nessun opt-out ambientale, solo goal classificati SAFE.

## Decision

1. **Only SAFE proceeds.** `RECOVERABLE`, output malformato e classifier non disponibile
   terminano con `REFUSED` prima del planner.
2. **No unconfined mode.** `SISTEMISTA_UNCONFINED` non modifica più la policy. Ogni run CLI ha
   un workspace esplicito; write esterni e mutazioni pathless di sistema restano vietati.
3. **Dynamic write targets fail closed.** Variabili/espansioni usate come destinazione di un
   mutatore o di una redirection sono rifiutate; valori dinamici restano ammessi.
4. **No policy bypass.** PowerShell usa `-NoProfile -NonInteractive -Command`, senza forzare
   l'ExecutionPolicy.
5. **Every execution owner shares the same boundary.** Session, PTY, file operations e smoke
   verification continuano a chiamare l'owner unico `Confinement`.

## Non-goals

- Non chiamare questa policy una sandbox.
- Non abilitare installazioni globali, service/registry/ACL/power mutations o write fuori root.
- Non certificare input ostile, network isolation o modelli non fidati.
- Non promuovere a production senza un backend isolato a livello kernel/VM e test di escape.

## Validation gate

- Test di composizione: un goal `RECOVERABLE` non consulta il planner e non esegue comandi.
- Errori/malformed del classifier non aprono il gate.
- `SISTEMISTA_UNCONFINED=1` non disabilita lo scope.
- Dynamic path sink rifiutati; dynamic value non regressivi.
- Nessun `ExecutionPolicy Bypass` nel launcher.
- Tutta la suite, Ruff, build, audit e Gitleaks verdi.

## Consequences

L'alpha diventa deliberatamente read-anywhere/write-workspace. Alcuni task sysops reali saranno
rifiutati: è un limite corretto finché manca isolamento verificabile. L'eventuale capability
`system-mutation` richiederà una RFC separata, grant esplicito e backend isolato; non sarà un env
flag che riapre il processo host.

## Implementation evidence — 2026-07-22

- Boundary mirato: **83 test passati**; suite completa: **712 passed, 3 skipped**.
- Ruff check verde e **149 file** conformi al formatter.
- Wheel/sdist `0.1.0a1`, audit dipendenze e Gitleaks sulla superficie pubblica verdi.
- I test di composizione provano che `RECOVERABLE`/malformed fermano il run prima del planner
  e che nessun comando viene eseguito.
- La promozione a `validation` resta bloccata: GitHub registra CI ma il dispatch restituisce
  HTTP 500 e Security non viene indicizzato mentre l'organizzazione è flagged.
