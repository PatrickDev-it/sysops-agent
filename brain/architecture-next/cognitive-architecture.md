# cognitive-architecture.md

> Owner: **il modello di controllo — *come* il sistema pensa.** I *pezzi* sono in [architecture.md](architecture.md).
> Questo è il documento che rende Sistemista "un cervello, non una pipeline".

---

## Principio: separare il *controllo* dalla *conoscenza*

In una pipeline, l'ordine di pensiero è cablato nel codice. In un cervello, l'ordine **emerge** dallo stato.
Adottiamo il pattern **blackboard**: un insieme di *knowledge source* (i nostri engine) che non si chiamano tra
loro, ma leggono/scrivono uno **stato condiviso tipizzato** (il Belief State). Uno **scheduler** decide, ad ogni
ciclo, *quale* knowledge source attivare, in base ai **gap** dello stato.

> Analogia: non un thread che esegue funzioni in sequenza, ma un **sistema operativo** che schedula processi
> pronti. Il "ready set" è determinato dai fatti mancanti/instabili nel belief state.

## Il ciclo cognitivo (Sense → Score → Route → Think → Commit)

```
loop:
  gaps      = Scheduler.assess(BeliefState)      # cosa manca/è instabile per avanzare sul goal?
  if goal.PROVEN or budget.exhausted or risk.block: break
  action    = Scheduler.select(gaps)             # gap a valore atteso massimo
  if action.needs_model:
      prompt = ContextEngine.compile(action)     # contesto MINIMO per QUEL task
      model  = ModelRouter.pick(action)          # deterministico < 3B < 4B < 8B < cloud
      result = model.decide(prompt)              # output TIPIZZATO, validato allo schema
  else:
      result = DeterministicPolicy.run(action)   # nessun modello
  BeliefState.apply(result)                      # con provenienza; State Engine valida le transizioni
```

**Value-of-information scheduling:** ogni gap ha un *valore atteso* = quanto avvicina il goal / costo (token,
latenza, rischio). Lo scheduler massimizza VoI. Esempio: se un solo probe deterministico (`ss -ltnp`) disambigua
il goal, vale più di una chiamata al 4B → si fa il probe prima.

## I due sistemi (fast/slow), esplicitamente

Ispirazione: Kahneman System-1/2 + subsumption di Brooks.

| | System-1 (reattivo, L1/L2) | System-2 (deliberativo, L3) |
|---|---|---|
| Chi | policy deterministiche, probe, parser, gate | Goal/Planning/Reasoning/Learning (modello) |
| Quando | sempre che una regola copre il caso | solo su *giudizio* genuino (intento, piano, causa) |
| Costo | ~0 token, µs–ms | token + latenza del modello |
| Esempi | fix sintassi shell, artifact-check, risk-scoring, retrieval | "cosa vuole l'utente", "perché fallisce", "quale piano" |

**Regola di frugalità del modello (invariante):** *nessuna chiamata al modello se una policy deterministica o una
query al World Model risponde.* Questo, e non "un modello più grande", è come reggiamo 3B/4B. È anche la cura al
male di v1: le euristiche `_fix_*` nell'orchestrator erano System-1 *annegato* nel codice del control-flow — qui
sono un layer esplicito e testabile.

## Ownership dei fatti (no duplicazione cognitiva)

Ogni *tipo* di fatto ha **un solo engine produttore** (owner) e molti consumatori:

| Fact type | Owner (produttore) | Consumatori |
|---|---|---|
| `env.*` (os, shell, arch) | System Mapper | tutti |
| `capability.*` (tool disponibile/versione) | System Mapper / Observation | Planning, Policy, Context |
| `entity.*` (service, port, container, file) | System Mapper / Observation | Reasoning, Planning |
| `belief.*` (PROVEN/REFUTED/…) | Reasoning Engine | Scheduler, Planning, Recovery |
| `plan.*` (DAG, step state) | Planning Engine | Execution, Validator |
| `risk.*` | Policy/Safety Engine | Scheduler, Execution |
| `experience.*` | Learning Engine | Context Engine |
| `verify.*` | Validator | Scheduler, Goal Manager |

Un consumatore che vuole scrivere un fatto altrui → errore di design (come scrivere in un doc di cui non sei owner).

## Explainability by construction

Ogni Fact porta **provenienza** (engine, comando, timestamp, confidence). Ogni decisione del modello cita i Fact
che l'hanno alimentata (il Context Engine registra *cosa* ha messo nel prompt). Quindi ogni azione è **tracciabile**
a una catena di fatti osservati → il belief state *è* l'audit trail. Nessun competitor ha questo: OpenHands logga
l'event stream (testo), noi logghiamo il *ragionamento tipizzato*.

## Alternative scartate

- **ReAct puro come control model:** il modello *è* lo scheduler. Elegante ma: (a) brucia token perché il modello
  decide anche i passi banali; (b) non deterministico → non debuggabile; (c) degrada su 3B/4B. **Rifiutato.**
- **BDI classico (Belief-Desire-Intention) formale:** troppo rigido/accademico; le "intention" formali mal si
  sposano con l'incertezza degli output LLM. Ne prendiamo l'idea di *belief*, non il formalismo.
- **Behavior Trees:** ottimi per comportamento reattivo scriptato, ma il nostro spazio d'azione è aperto
  (sysops arbitrario) → un BT diventa ingestibile. Usati eventualmente *dentro* Recovery, non come control model.

## Trade-off

- Lo scheduler VoI richiede una funzione di stima del valore → all'inizio euristica, poi appresa (Learning Engine).
  Trade-off: complessità iniziale vs frugalità di token enorme a regime.
- Blackboard = stato condiviso mutabile → richiede disciplina (single-owner + State Engine che valida). Lo
  accettiamo perché rende il sistema *ispezionabile*.

## Pattern

Blackboard · Subsumption/3T · System-1/2 · Value-of-Information scheduling · Provenance graph (explainability).

## Benchmark teorico

Frazione di iterazioni che invocano il modello: target **≤35%** (le altre risolte da policy/query). È la leva
diretta su token e latenza, e il moat sui competitor ReAct che invocano il modello ~100% delle iterazioni.

## Evoluzioni

Scheduler con stima VoI *appresa* dall'experience store · meta-cognizione (il sistema stima la propria confidence
e decide quando escalare a un modello più grande) · pianificazione gerarchica (HTN) per incident complessi.
