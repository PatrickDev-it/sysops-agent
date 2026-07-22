# state-engine.md

> Owner: **il ciclo di vita e le transizioni valide di Fact ed entità.** Il *dato* è in [belief-system.md](belief-system.md);
> qui le *regole* che ne governano l'evoluzione (le "leggi di conservazione" del belief state).

---

## Perché un engine dedicato

La blackboard è mutabile e condivisa. Senza un guardiano, diventa un pantano (v1: stato sparso in un god-object).
Lo **State Engine** è l'unico punto che *applica* le mutazioni: valida ogni transizione contro invarianti, gestisce
TTL/STALE, versiona (`supersedes`), e rifiuta stati proibiti.

## Macchine a stati

**Fact status:**
```
OBSERVED ──(inference)──► INFERRED ──(confirming observation)──► PROVEN
   │                          │                                     │
   └──(contradicting obs)────►└──────────────► REFUTED ◄────────────┘
PROVEN/INFERRED ──(ttl expira)──► STALE ──(re-observe)──► OBSERVED
```

**Entity (World Model) lifecycle** (successore delle WorldEntity v1):
```
UNKNOWN → DISCOVERED → { RUNNING | STOPPED | INSTALLED | MISSING | DELETED } → (transizioni causate da azioni verificate)
```

## Invarianti applicati qui (forbidden states)

Eredita e generalizza gli invarianti v1:

1. **Nessun placeholder in un Fact `plan.action`** — token `<x>`/`{slot}`/`$VAR` non risolti ⇒ transizione rifiutata.
2. **Nessun overwrite di entità EXECUTABLE** senza safe-check.
3. **Discovery prima di action** — un `plan.step` MODIFY che referenzia un `entity.*` non ancora DISCOVERED è invalido.
4. **Artifact/verify sovrascrive l'exit code** — un'entità passa a INSTALLED/RUNNING solo con un `verify.*` PROVEN.
5. **Solo PROVEN guida azioni distruttive.**
6. **TTL enforce** — un Fact STALE non può soddisfare una precondizione di piano.

Questi non sono "controlli sparsi" (v1) ma **regole centralizzate nello State Engine** → un solo posto da testare.

## Interfaccia

```
apply(mutation) -> Result           # unica via di scrittura; valida invarianti
transition(entity, event) -> Entity # macchina a stati entità
tick()                              # avanza TTL, marca STALE
snapshot() / diff(a,b)              # per telemetry e debugging
```

## Confronto competitor

Nessun competitor ha uno state engine esplicito: gestiscono lo stato *implicitamente* nella history/prompt
(Goose, Cline, OpenHands). Conseguenza loro: stati proibiti raggiungibili (v1 T040: accettava un placeholder come
"risolto"). Noi li rendiamo **irraggiungibili per costruzione**.

## Pattern

State machine · Guarded commands (Dijkstra) · Invariant enforcement · Transactional apply (o tutto o niente).

## Trade-off

Centralizzare le mutazioni introduce un collo di bottiglia logico (tutto passa di qui). Accettato: è *deterministico
e testabile*, e il volume di mutazioni per run è piccolo (ordine 10²–10³). Non è un hot path di performance.

## Benchmark teorico

Copertura test: l'intero set di invarianti è testabile **senza LLM** (input Fact → transizione attesa). Target 100%
di branch coverage sullo State Engine → i "forbidden states" diventano garanzie, non speranze.

## Evoluzioni

Rollback transazionale (snapshot → undo di un'azione fallita) · time-travel debugging (replay del diff sequence) ·
invarianti dichiarativi caricabili per-OS dal Knowledge Graph.
