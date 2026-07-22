# Decision Engine — infrastruttura di Decision Engineering

> **Entry point del framework.** Owner della *metodologia* con cui ogni run dell'agente
> diventa una traccia cognitiva osservabile, interrogabile e confrontabile tra release.
> Non contiene fix, capability o euristiche: contiene i **modelli tipizzati** e gli
> **algoritmi deterministici** con cui le iterazioni future decideranno *cosa* cambiare.
> Introdotto come DEC-ENG-v1. Versione schema: `decision-engine/1.0`.

---

## Perché esiste

Il [decision-analysis.md](../../workspace/validation/windows-lab/reports/decision-analysis.md)
(run `full-safe30`) è stato prodotto **a mano**. Ha risposto a due domande:

1. *Perché il supervisor ha preso questa decisione?*
2. *Qual è la minima modifica architetturale che aumenta il First-Time Fix Rate (FTFR)?*

Quel documento è un **artefatto una tantum, non riproducibile**. Il suo stesso §0 identifica
il vincolo bloccante: *la telemetria registra azioni, non decisioni* (`Decision` è tipizzato in
[telemetry_schema.py](../../workspace/benchmarks/telemetry_schema.py) ma **non cablato** in
[telemetry.py::record_run](../../workspace/src/telemetry.py); il campo `decisions` è sempre `[]`).

Questo framework trasforma quell'analisi manuale in **infrastruttura**: una pipeline
deterministica `run → cognitive trace → decision graph → divergence → root cause → leverage → proposals`
che ogni benchmark esegue automaticamente, producendo conoscenza strutturata anziché intuizione.

**L'output non è codice migliore. È la capacità di capire perfettamente il comportamento del sistema.**

---

## Cosa NON è (confini)

- **Non** è un fixer. Non contiene `if <framework>`, casi speciali, euristiche di PowerShell/OS.
- **Non** è un nuovo runtime. Consuma artefatti (`SystemState`, `ReasoningContext`, telemetria)
  già prodotti dall'agente; non li modifica.
- **Non** duplica fatti tecnici del codice. Dove serve un fatto già di proprietà del codice
  (invarianti, lifecycle, ErrorClass), **linka** l'owner. Vedi [documentation contract](../../AGENTS.md#documentation-contract).

---

## Vincoli invarianti del framework (VETO)

Ogni modello o report di questa cartella **deve** essere:

| # | Invariante | Verifica |
|---|-----------|----------|
| DE-1 | **Deterministico** | stessa traccia in input → stesso output, byte-identico. Nessun sampling, nessuna data/ora nel corpo analitico. |
| DE-2 | **Tipizzato** | ogni entità è un record con campi dichiarati; ogni classificazione è un enum **chiuso**. |
| DE-3 | **Misurabile** | ogni giudizio è ancorato a una metrica esistente (ARR/FTFR/RAF/token/latency da [metrics.py](../../workspace/benchmarks/osbench/scoring/metrics.py)) o a un conteggio sul corpus. |
| DE-4 | **Riproducibile** | l'algoritmo è pseudocodice eseguibile, non prosa interpretabile. |
| DE-5 | **Versionabile** | ogni schema porta `schema_version`; i diff tra release sono confrontabili. |
| DE-6 | **Indipendente dal modello** | nessuna assunzione su 4B/3B o su un vendor. Analizza *decisioni*, non *token di un modello specifico*. |
| DE-7 | **Generalizzabile** | classifica per *categoria cognitiva* (dataflow, belief, ordine), mai per tool o OS. |
| DE-8 | **Mai UNKNOWN se inferibile** | un classificatore che può dedurre una categoria dalle evidenze non deve emettere UNKNOWN. |

Se un documento viola DE-1…DE-8, non è finito (red flag, vedi [AGENTS.md](../../AGENTS.md#operating-contract)).

---

## Mappa di ownership (un fatto → un owner)

### Modelli (il formalismo — owner)

| File | Owner di… | Enum chiusi che definisce |
|------|-----------|---------------------------|
| [decision-model.md](decision-model.md) | l'entità **Decision** tipizzata (28 campi) e le sue relazioni | — |
| [decision-schema.md](decision-schema.md) | serializzazione on-disk di Decision / CognitiveTrace / DecisionGraph | `schema_version` |
| [decision-lifecycle.md](decision-lifecycle.md) | la **FSM** di una Decision + gli stadi della **Cognitive Trace** | `DecisionState`, `TraceStage` |
| [planner-formalism.md](planner-formalism.md) | fasi del piano, **Decision Graph (DAG)**, diff expected/actual | `PlanPhase`, `EdgeKind`, `GraphDefect` |
| [strategy-model.md](strategy-model.md) | tassonomia di **Strategy / Intent / Expected Outcome** | `StrategyClass`, `IntentClass` |
| [belief-transition-model.md](belief-transition-model.md) | transizioni e invarianti dei **belief** ai fini di analisi | `BeliefTransition`, `BeliefDefect` |
| [context-selection-model.md](context-selection-model.md) | analisi di **utilizzo del context** per Decision | `ContextUtilization` |
| [verification-model.md](verification-model.md) | formalismo di **Expected Verification / Expected Recovery** | `VerificationKind`, `RecoveryClass` |
| [reasoning-taxonomy.md](reasoning-taxonomy.md) | tassonomia degli **step di ragionamento** e delle **cause di divergenza** | `ReasoningStepKind`, `DivergenceCause` |
| [failure-taxonomy.md](failure-taxonomy.md) | **archetipi di fallimento** chiusi + clustering | `FailureArchetype` |
| [success-taxonomy.md](success-taxonomy.md) | **classi di successo** | `SuccessClass` |
| [root-cause-framework.md](root-cause-framework.md) | **Divergence Engine**, **Root Cause Engine**, **Leverage Estimator**, **Architectural Classifier** | `ArchitecturalComponent` |
| [improvement-loop.md](improvement-loop.md) | **Learning Database**, **Pattern Discovery**, **Automatic Improvement Proposals**, chiusura del loop | `PatternClass` |

### Report (gli output — generati, non scritti a mano)

Sono **template deterministici**: il generatore riempie le sezioni tipizzate da una o più
`CognitiveTrace`. Vivono in [reports/](reports/) e sono descritti in
[improvement-loop.md §Report generation](improvement-loop.md#report-generation).

| Report | Prodotto da | Sorgente |
|--------|-------------|----------|
| [reports/decision-report.md](reports/decision-report.md) | aggregatore per-run | CognitiveTrace |
| [reports/decision-graph.md](reports/decision-graph.md) | planner-formalism | DecisionGraph |
| [reports/planner-analysis.md](reports/planner-analysis.md) | planner-formalism | Expected/Actual diff |
| [reports/belief-analysis.md](reports/belief-analysis.md) | belief-transition-model | belief delta per Decision |
| [reports/context-analysis.md](reports/context-analysis.md) | context-selection-model | context utilization |
| [reports/root-cause-analysis.md](reports/root-cause-analysis.md) | root-cause-framework | Divergence + Root Cause |
| [reports/architectural-debt.md](reports/architectural-debt.md) | Architectural Classifier | conteggi per componente |
| [reports/high-leverage-fixes.md](reports/high-leverage-fixes.md) | Leverage Estimator | ranking dei fix |
| [reports/improvement-roadmap.md](reports/improvement-roadmap.md) | improvement-loop | roadmap ordinata |

---

## La pipeline (deterministica, end-to-end)

```
                                     ┌─────────────────────────────────────────┐
   RUNTIME (già esistente)           │        DECISION ENGINE (questo)         │
   ───────────────────────           │        ─────────────────────────        │
   SystemState  ┐                    │                                         │
   ReasoningCtx ├──► telemetry ──────►  1. TRACE BUILDER                        │
   plan/verify/ ┘   (Decision[]      │     costruisce la CognitiveTrace         │
   recover          da cablare)      │           │                             │
                                     │           ▼                             │
   benchmark case ─── expected ──────►  2. GRAPH BUILDER                        │
   (failure-db json)  reasoning      │     Actual DAG + Expected DAG            │
                                     │           │                             │
                                     │           ▼                             │
                                     │  3. DIVERGENCE ENGINE                    │
                                     │     primo punto di divergenza cognitiva  │
                                     │           │                             │
                                     │           ▼                             │
                                     │  4. ROOT CAUSE + CLASSIFIER              │
                                     │     Primary/Secondary + ArchComponent    │
                                     │           │                             │
                                     │           ▼                             │
                                     │  5. LEVERAGE ESTIMATOR                    │
                                     │     ΔFTFR/ΔARR/ΔRAF per ogni fix, ordina  │
                                     │           │                             │
                                     │           ▼                             │
                                     │  6. LEARNING DB  ──►  REPORTS + ROADMAP  │
                                     └─────────────────────────────────────────┘
```

**Prerequisito di attivazione: ✅ CHIUSO (PATCH-013, 2026-07-03).** Il runtime ora reifica ogni
decisione in [decisions.py](../../workspace/src/decisions.py) (FSM `PROPOSED→BLOCKED|EXECUTED→
CONFIRMED/DIVERGED`, Prediction vs Observation, archi `RETRY_OF`/`REPLACES`/`RECOVERS`) e
[telemetry.py::record_run](../../workspace/src/telemetry.py) emette il DecisionGraph completo
(`record["decisions"]` = nodi + stats) più il WorldGraph. La pipeline opera su **provenance=OBSERVED**;
la modalità ricostruzione ([decision-lifecycle.md §Provenance](decision-lifecycle.md#provenance)) resta
solo per i run legacy pre-PATCH-013. Nota: i campi di costo (token/parse per model call) restano da
cablare in `model_router` ([telemetry_schema.py §INTEGRATION](../../workspace/benchmarks/telemetry_schema.py)).

---

## Come si legge questo framework

1. **[decision-model.md](decision-model.md)** — cos'è una Decision (il mattone).
2. **[decision-lifecycle.md](decision-lifecycle.md)** — come una Decision evolve; cos'è una Cognitive Trace.
3. **[planner-formalism.md](planner-formalism.md)** — come le Decision formano un DAG e come lo si confronta con l'ideale.
4. **[root-cause-framework.md](root-cause-framework.md)** — come si trova il primo errore cognitivo e la leva massima.
5. **[improvement-loop.md](improvement-loop.md)** — come tutto ciò diventa la roadmap della prossima iterazione.

Le tassonomie ([reasoning](reasoning-taxonomy.md) · [failure](failure-taxonomy.md) ·
[success](success-taxonomy.md)) e i modelli di analisi ([belief](belief-transition-model.md) ·
[context](context-selection-model.md) · [strategy](strategy-model.md) ·
[verification](verification-model.md)) sono i **vocabolari chiusi** consumati dalla pipeline.

---

## Glossario del framework

| Termine | Significato | Owner |
|---------|-------------|-------|
| **Decision** | scelta tipizzata (non un comando): intent + strategia + alternative + evidenze + belief-delta | [decision-model.md](decision-model.md) |
| **Cognitive Trace** | rappresentazione completa e ordinata del ragionamento di un run | [decision-lifecycle.md](decision-lifecycle.md) |
| **Decision Graph** | DAG delle Decision di un task; archi = dipendenze logiche | [planner-formalism.md](planner-formalism.md) |
| **Divergence Point** | primo nodo in cui l'Actual DAG rompe l'Expected DAG | [root-cause-framework.md](root-cause-framework.md) |
| **Leverage** | vettore tipizzato ΔFTFR/ΔARR/ΔRAF/… di un fix, con ranking deterministico | [root-cause-framework.md](root-cause-framework.md) |
| **Architectural Component** | il layer responsabile (Planner/Belief/Context/…), enum chiuso di 15 | [root-cause-framework.md](root-cause-framework.md) |
| **Learning Entry** | record persistente `decisione→context→outcome→causa→fix→impatto` | [improvement-loop.md](improvement-loop.md) |
