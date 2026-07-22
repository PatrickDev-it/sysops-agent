# Decision Schema — serializzazione on-disk

> **Owner** del formato persistente di `Decision`, `CognitiveTrace` e `DecisionGraph`.
> Definisce il contratto di storage: versionato (DE-5), append-only, diffabile tra release,
> leggibile da un aggregatore senza reinvocare il modello. Estende (non rimpiazza)
> [telemetry_schema.py::RunRecord](../../workspace/benchmarks/telemetry_schema.py).
> Entità → [decision-model.md](decision-model.md).

---

## 1. Principi

1. **Un file per run**, JSON, in `validation/decision-traces/<run_id>.json`.
   Affianca (non sostituisce) `var/telemetry/<run_id>.json`.
2. **Append-only**: una trace scritta non si riscrive mai; una re-analisi produce un nuovo file
   `…/<run_id>.<engine_version>.json`. Così i diff tra versioni del *motore di analisi* sono tracciabili
   separatamente dai diff tra *run*.
3. **Auto-descrittivo**: ogni record porta `schema_version` e `engine_version`.
4. **Provenance obbligatoria**: ogni campo non osservato direttamente porta `provenance`
   (vedi [decision-lifecycle.md §Provenance](decision-lifecycle.md#provenance)).

---

## 2. `schema_version`

```
schema_version = "decision-engine/1.0"
engine_version = "<git-describe del corpus di analisi>"   // NON entra negli hash (DE-1)
```

Regola di compatibilità (SemVer ristretto):
- **patch** (`1.0.x`): nuovi campi opzionali, default retro-compatibili.
- **minor** (`1.x`): nuovi enum member (i vecchi restano validi).
- **major** (`x`): rimozione/rinomina di campi o rottura di un enum → richiede migrazione + RFC.

Un lettore che incontra `schema_version` con **major** superiore al proprio **rifiuta** il file
(non indovina). Un membro di enum sconosciuto è mappato a `UNKNOWN` **solo** quando la classificazione
non è ricostruibile dagli altri campi (DE-8).

---

## 3. Record radice — `DecisionTrace`

```jsonc
DecisionTrace = {
  "schema_version": "decision-engine/1.0",
  "engine_version": str,
  "run_id": str,                       // = telemetry run_id → join sui due file
  "case_id": str | null,               // failure-db case, se benchmark
  "goal": str,
  "verdict": "COMPLETE" | "INCOMPLETE" | "REFUSED",
  "environment": { ... },              // copia di SystemState.environment (per join, non per logica)

  "decisions": Decision[],             // §4 — l'array centrale
  "trace": TraceStage[],               // decision-lifecycle §Cognitive Trace
  "graph": DecisionGraph,              // §5

  "analysis": Analysis | null,         // §6 — riempito dagli engine, null se non ancora analizzato
  "metrics": RunMetrics                // §7 — ancorate a metrics.py
}
```

`environment` è duplicato **solo come chiave di join/filtro** (per-OS aggregation in
[metrics.py::score_suite](../../workspace/benchmarks/osbench/scoring/metrics.py)), mai come input di
una classificazione — nessun engine ramifica su `os_name` (DE-6/DE-7).

---

## 4. `Decision` serializzato

Serializzazione 1:1 dei 28 campi di [decision-model.md](decision-model.md). Esempio (con provenance):

```jsonc
{
  "decision_id": "a91f0c33e21b7d40",
  "timestamp": 3,                       // indice di step, non wall-clock
  "goal": "write the effective PATH, one entry per line, to path.txt",
  "intent": "OBSERVE_AND_REPORT",
  "expected_outcome": ["exists(path.txt)", "contains_string(path.txt, <PATH_VALUE>)"],

  "strategy": "OBSERVE_AND_REPORT",
  "chosen_alternative": { "signature": "write_file|path.txt|$(...)", "strategy": "OBSERVE_AND_REPORT",
                          "predicted_outcome": ["exists(path.txt)"], "rejected_reason": null },
  "alternatives_considered": [ /* AlternativeRef[] */ ],   // provenance=UNAVAILABLE se non cablato
  "rejected_alternatives": [],
  "confidence": 0.0,                    // proxy: parse_ok=false → 0.0

  "evidence_required":  [{ "kind": "fact", "key": "PATH_VALUE", "state_at_decision": "absent", "satisfied": false }],
  "evidence_available": [],
  "missing_evidence":   [{ "kind": "fact", "key": "PATH_VALUE", "state_at_decision": "absent", "satisfied": false }],

  "beliefs_read": [], "beliefs_created": [], "beliefs_updated": [], "beliefs_invalidated": [],

  "facts_required": ["PATH_VALUE"], "facts_produced": [], "capabilities_used": [],

  "expected_verification": "ARTIFACT_CONTENT",             // verification-model
  "expected_recovery": ["correct_flags", "use_alternative_command"],  // error_classifier

  "risk": "SAFE",
  "cost": { "tokens": 0, "latency_ms": 0.0, "retries": 1, "actions_emitted": 1, "wasted": true },
  "estimated_token_cost": null, "estimated_latency_ms": null,

  "parent_decision": null, "child_decisions": ["77c2..."],

  "_provenance": {                      // per-campo, solo per i campi non OBSERVED
    "intent": "INFERRED", "strategy": "INFERRED",
    "alternatives_considered": "UNAVAILABLE",
    "estimated_token_cost": "UNAVAILABLE", "confidence": "PROXY"
  }
}
```

Il blocco `_provenance` elenca **solo** i campi la cui provenienza non è `OBSERVED`. Un lettore assume
`OBSERVED` in assenza di voce. Questo è ciò che rende onesta la modalità ricostruzione (nessuna
inferenza spacciata per osservazione).

---

## 5. `DecisionGraph` serializzato

```jsonc
DecisionGraph = {
  "nodes": [ { "id": decision_id, "phase": PlanPhase, "label": str } ],
  "edges": [ { "from": decision_id, "to": decision_id, "kind": EdgeKind } ],
  "is_dag": bool,                       // false → contiene cicli (GraphDefect.CIRCULAR)
  "topo_order": decision_id[] | null    // null se !is_dag
}
```

`PlanPhase` e `EdgeKind` sono di proprietà di [planner-formalism.md](planner-formalism.md). Il grafo è
sempre serializzato in **ordine topologico canonico** (tie-break per `timestamp`, poi `decision_id`)
così che due grafi isomorfi abbiano la stessa serializzazione (DE-1).

---

## 6. `Analysis` — output degli engine

```jsonc
Analysis = {
  "expected_graph": DecisionGraph,      // dall'expected_reasoning del case
  "diff": GraphDiff,                    // planner-formalism §diff
  "divergence": DivergencePoint | null, // root-cause-framework §Divergence Engine
  "root_cause": RootCause | null,       // root-cause-framework §Root Cause Engine
  "belief_analysis": BeliefAnalysis,    // belief-transition-model
  "context_analysis": ContextAnalysis,  // context-selection-model
  "leverage": LeverageEstimate[],       // root-cause-framework §Leverage — ordinato
  "components": { ArchitecturalComponent: int },  // conteggi difetti per componente
  "patterns": PatternRef[]              // improvement-loop §Pattern Discovery
}
```

`Analysis = null` è uno stato lecito e distinto da `Analysis = {…vuoto…}`: il primo significa
"non ancora analizzato", il secondo "analizzato, nessun difetto". Non confonderli (red flag:
"risultato parziale silenzioso").

---

## 7. `RunMetrics` — ancoraggio alle metriche esistenti

```jsonc
RunMetrics = {
  "first_time_fix": bool,      // = failure-db metrics.first_time_fix
  "needed_recovery": bool,
  "resolved": bool,
  "raf": float,                // Recovery Amplification Factor: n_actions / n_min_actions_ideal
  "n_decisions": int,
  "n_wasted_decisions": int,   // Σ cost.wasted — nuovo, misura lo spreco cognitivo
  "arr_contribution": 0 | 1,   // = metrics.py _arr_ok
  "tokens_total": int | null,  // da telemetry_schema se cablato
  "context_tokens_peak": int | null
}
```

**RAF** riusa la definizione operativa del corpus (il "RAF 2.11" di
[decision-analysis.md §4](../../workspace/validation/windows-lab/reports/decision-analysis.md)):
azioni realmente eseguite ÷ azioni minime del reference path. `n_wasted_decisions` è la sua controparte
a livello di *decisione* (non di comando), ed è ciò che il framework punta a portare a zero.

---

## 8. Contratto del Trace Builder (stage 1 della pipeline)

Input: `telemetry/<run_id>.json` (+ opzionale `failure-db/<case>.json`).
Output: `decision-traces/<run_id>.json` con `analysis=null`.

```
build_trace(telemetry, case?):
    decisions = []
    for i, action in enumerate(telemetry.history):
        D = Decision(timestamp=i, chosen_alternative=sig(action), ...)
        D.facts_produced   = keys(action.produced_facts)
        D.beliefs_* = diff(belief_snapshot[i-1], belief_snapshot[i])   # se debug_dump presente
        D.strategy         = classify_strategy(D)     # strategy-model, deterministico
        D.intent           = classify_intent(D)       # strategy-model
        D.expected_outcome = predicates_from(case.success_criteria or plan.success)
        D.evidence_required= require_evidence(D)      # decision-model §5
        mark_provenance(D)                            # OBSERVED | INFERRED | PROXY | UNAVAILABLE | RECONSTRUCTED
        decisions.append(D)
    return DecisionTrace(decisions=decisions, graph=build_graph(decisions), analysis=None)
```

Il Trace Builder **non chiama mai il modello** ed è totalmente deterministico: data la stessa
telemetria produce la stessa trace. È l'unico stage che tocca dati grezzi; tutti gli altri engine
operano solo su `DecisionTrace`.
