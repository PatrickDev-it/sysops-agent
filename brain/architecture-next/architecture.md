# architecture.md

> Owner: **la mappa dei componenti e il flusso dati di v2.** Il modello di *controllo* (come pensa) è in
> [cognitive-architecture.md](cognitive-architecture.md); qui i *pezzi* e come si collegano.

---

## Modello architetturale: blackboard + three-tier

Adottiamo una **blackboard architecture** (fatti condivisi + knowledge source specializzate) con **tre livelli**
mutuati dalle architetture robotiche 3T (reactive / executive / deliberative). Motivazione: separare *cosa
pensare* (scheduler) da *come pensarlo* (engine), e invocare il modello **solo** dove serve giudizio.

```
                          ┌───────────────────────────────────────────────┐
   L3  DELIBERATIVE       │ Goal Manager · Planning Engine · Reasoning     │  ← modello (4B/8B), lento, raro
   (model, sparse)        │ Engine · Learning Engine                       │
                          └───────────────▲───────────────┬───────────────┘
                                          │ query/compile  │ decisions
                          ┌───────────────┴───────────────▼───────────────┐
   L2  EXECUTIVE          │      SCHEDULER / CONTROL LOOP  (deterministic) │
   (deterministic         │  Context Engine · Policy/Safety · Model Router │  ← nessun modello: pura logica
    control)              │  Recovery Engine · Validator                   │
                          └───────────────▲───────────────┬───────────────┘
                                          │ facts          │ actions
                          ┌───────────────┴───────────────▼───────────────┐
   L1  REACTIVE           │ Execution Engine · Observation Engine ·        │  ← veloce, deterministico
   (effectors)            │ System Mapper · Terminal/PTY Runtime           │
                          └───────────────▲───────────────┬───────────────┘
                                          │ bytes          │ commands
                                    ╔═════╧════════════════▼═════╗
                                    ║   OS / shell / host / net  ║
                                    ╚════════════════════════════╝

   ┌─────────────────────── SHARED STORES (single-owner data) ───────────────────────┐
   │  Belief State (blackboard)  ·  World Model / System Map (graph)                  │
   │  Knowledge Graph (OS/cmd ontology)  ·  Memory hierarchy + Experience DBs         │
   │  Telemetry (append-only)                                                         │
   └──────────────────────────────────────────────────────────────────────────────────┘
```

## Componenti e responsabilità (nessun overlap)

| # | Componente | Responsabilità unica | Owner-doc |
|---|---|---|---|
| 1 | **Belief State** | fatti tipizzati correnti del run (blackboard) | [belief-system.md](belief-system.md) |
| 2 | **State Engine** | transizioni di fatti/entità, invarianti, TTL | [state-engine.md](state-engine.md) |
| 3 | **World Model / System Map** | grafo interrogabile del sistema reale | [system-map.md](system-map.md) |
| 4 | **Knowledge Graph** | ontologia OS/comandi/capability | [knowledge-graph.md](knowledge-graph.md) |
| 5 | **Memory** | working/task/session/semantic/LT + experience | [memory.md](memory.md) |
| 6 | **Context Engine** | compila il prompt minimo sotto budget | [context-engineering.md](context-engineering.md) |
| 7 | **Goal Manager** | decomposizione e ciclo di vita dei goal | [planning-engine.md](planning-engine.md) |
| 8 | **Planning Engine** | piano come DAG di azioni con precondizioni | [planning-engine.md](planning-engine.md) |
| 9 | **Reasoning Engine** | inferenza causale, ipotesi, belief update | [reasoning-engine.md](reasoning-engine.md) |
| 10 | **Supervisor** | orchestra L3: capisce/pianifica/valida/impara | [supervisor.md](supervisor.md) |
| 11 | **Policy/Safety Engine** | risk vector + gate (allow/confirm/sandbox/refuse) | [security.md](security.md) |
| 12 | **Model Router / Cost Optimizer** | modello più economico capace del task | [performance.md](performance.md) |
| 13 | **Recovery Engine** | selezione recovery vincolata dall'errore | [reasoning-engine.md](reasoning-engine.md) |
| 14 | **Validator** | post-condizioni/artifact → fatti di verifica | [observation-engine.md](observation-engine.md) |
| 15 | **Execution Engine** | dispatch atomico/idempotente delle azioni | [execution-engine.md](execution-engine.md) |
| 16 | **Observation Engine** | bytes → Fact tipizzati | [observation-engine.md](observation-engine.md) |
| 17 | **System Mapper** | probe deterministici → World Model | [system-map.md](system-map.md) |
| 18 | **Terminal/PTY Runtime** | sessioni, prompt detection, pyte | [terminal-runtime.md](terminal-runtime.md) |
| 19 | **Learning Engine** | cattura/recupero esperienza | [learning-engine.md](learning-engine.md) |
| 20 | **Telemetry** | eventi append-only + metriche | [telemetry.md](telemetry.md) |

## Flusso di un run (una iterazione dello scheduler)

```
1. SENSE     Scheduler ispeziona Belief State → trova il gap di valore massimo.
2. ROUTE     Gap = "goal ambiguo" → Goal Manager · "manca un fatto" → System Mapper ·
             "piano pronto" → Execution Engine · "step fallito" → Recovery Engine ·
             "obiettivo forse raggiunto" → Validator.
3. COMPILE   Se serve il modello: Context Engine compila il prompt MINIMO per quel task
             (query al World Model + capability + esperienza rilevante) sotto budget.
4. DECIDE    Model Router sceglie il modello; l'engine deliberativo produce una decisione tipizzata.
5. GATE      Se la decisione è un'azione → Policy/Safety Engine assegna risk vector e decide.
6. ACT       Execution Engine esegue l'azione atomica; Observation Engine ne ricava Fact.
7. UPDATE    Reasoning Engine aggiorna il belief state; Learning Engine registra l'esito. Torna a 1.
```

Nessun contatore di step fisso: si itera finché il goal è PROVEN o il budget/rischio impone stop.

## Pattern software impiegati

Blackboard · Three-tier control (robotica) · Ports & Adapters (hexagonal) attorno a OS/PTY/modelli ·
Strategy (Model Router, Recovery) · Rule/Policy engine · Event sourcing (Telemetry) · CQRS soft (World Model:
scrittura via Mapper, lettura via query) · Compiler passes (Context Engine).

## Pattern AI impiegati

ReAct *confinato* a L3 · Reflexion (belief update post-step) · Retrieval-augmented context (dal World Model, non
da un vector store generico) · Program-of-thought deterministico (piano = DAG) · Speculative/cascade model calls.

## Alternative architetturali scartate

- **Pipeline lineare Supervisor→Executor (v1, Goose, Codex):** ordine di pensiero rigido; recovery/discovery non
  interlacciabili; l'orchestrator diventa un god-object (successo osservato in v1: 1905 LOC). **Rifiutata.**
- **ReAct monolitico (OpenHands CodeAct):** potente ma il modello fa *tutto* → costoso in token e fragile su 3B/4B;
  nessuna separazione deterministico/deliberativo. **Rifiutata** per il vincolo modello-piccolo.
- **Multi-agent conversazionale (agenti che chattano):** overhead di token enorme, non deterministico, difficile da
  debuggare. **Rifiutata**: preferiamo engine tipizzati con contratti, non "agenti che si parlano".

## Trade-off

- Più componenti = più confini da mantenere. Mitigazione: confini = contratti tipizzati + single-owner (questo doc).
- Lo scheduler deterministico è più codice *nostro* (non delegato all'LLM) → ma è **testabile** e **debuggabile**,
  al contrario dell'"emergenza" di un ReAct loop. È un trade-off deliberato a favore di explainability.

## Benchmark teorico

Rispetto a un ReAct loop equivalente: **–40/–70% token per task** (il modello vede solo contesto compilato e
viene invocato ~1/3 delle iterazioni), a parità o superiore ARR grazie al world model e all'experience store.
