# executor.md

> Owner: **l'effettore puro — riceve un'azione atomica, la esegue, restituisce evidenza. Mai ragiona.**
> È il complemento di [supervisor.md](supervisor.md). Lo *scheduling/atomicità* delle azioni è in
> [execution-engine.md](execution-engine.md); qui il *contratto di stupidità*.

---

## Contratto: l'Executor è deliberatamente stupido

> Riceve un'**azione atomica completamente concreta** (nessun placeholder, nessuna scelta da fare), la esegue nel
> runtime, cattura i bytes, e li passa all'Observation Engine. **Zero reasoning. Zero decisioni. Zero conoscenza del goal.**

Perché stupido *by design*: tutta l'intelligenza è nel Supervisor/engine; l'Executor deve essere **deterministico,
testabile, sostituibile** (un adapter). Se l'Executor "decidesse" qualcosa, avremmo reasoning duplicato in due posti
→ drift. Un solo owner del giudizio (Supervisor), un solo owner dell'effetto (Executor).

## Contratto d'ingresso/uscita

```
Action  { id, kind: BATCH|INTERACTIVE|FILEOP|PROBE, command|payload (concreto), cwd, timeout, expected_effects }
  ── esegue via runtime ──►
Result  { raw_bytes, exit_code, duration, side_effects_observed }  → Observation Engine → Fact[]
```

Invarianti applicati *prima* di ricevere l'azione (dallo State/Safety Engine, non dall'Executor):
nessun placeholder · azione gated dal rischio · precondizioni soddisfatte. L'Executor **non li verifica**: si fida
del contratto (fail-fast se violato = bug a monte).

## Idempotenza e atomicità

Un'azione dichiara i suoi `expected_effects` → l'Execution Engine può renderla idempotente (skip se l'effetto è già
un Fact) e atomica (o completa o rollback). L'Executor esegue; la *semantica* è dell'Execution Engine.

## Confronto competitor

- **v1:** l'`Executor` (classe) esisteva ma era bypassato → l'esecuzione era annegata nell'orchestrator con
  reasoning intrecciato. **Anti-esempio.** In v2 l'Executor è reale, minimale e l'unico che tocca il runtime.
- **OpenHands:** il runtime (Docker) è ben separato → buona ispirazione; ma la loro azione è "codice arbitrario"
  (CodeAct) potente e pericoloso. La nostra azione è **tipizzata e gated**, più sicura e osservabile.
- **Aider:** l'"esecuzione" è applicare diff + git → dominio codice. Noi: azioni di sistema tipizzate.

## Pattern

Adapter / Port (hexagonal) · Command executor · Dumb pipe · Fail-fast su contratto violato · Anti-corruption a valle
(Observation) e a monte (State/Safety).

## Alternative scartate

- **Executor "smart" che ottimizza/corregge i comandi:** riporta reasoning nell'effettore → drift e side-effect non
  gated. **Rifiutato.** La correzione è un layer L2 esplicito a monte, non nell'Executor.
- **Executor che legge il goal per adattarsi:** accoppiamento e duplicazione del giudizio. **Rifiutato.**

## Trade-off / Benchmark / Evoluzioni

Trade-off: un Executor stupido richiede che tutto arrivi concreto e gated → più lavoro a monte, ma quel lavoro è
*testabile senza OS*. Benchmark: l'Executor è copribile al 100% con test deterministici (azione→effetto simulato).
Evoluzioni: Executor remoti (esecuzione su host via SSH con lo stesso contratto), executor sandboxed (vedi
[security.md](security.md)), pool di executor concorrenti per azioni indipendenti (vedi [scalability.md](scalability.md)).
