# Root Cause Framework — Divergence · Root Cause · Leverage · Classifier

> **Owner** dei quattro motori analitici della pipeline (mission §5, §9, §10, §11) e dell'enum
> `ArchitecturalComponent`. Consuma una `DecisionTrace` con `GraphDiff`
> ([planner-formalism.md](planner-formalism.md)) ed emette `RootCause`, `LeverageEstimate[]` e i
> conteggi per componente. Tutti gli engine sono deterministici e model-independent.

---

## 1. Divergence Engine (mission §5)

> Identifica il **primo punto** in cui il reasoning diverge — **non** l'errore finale.

```
divergence_point(trace):
    actual   = trace.graph
    expected = build_expected_graph(trace.case)            # planner-formalism §3
    diff     = graph_diff(expected, actual)                # planner-formalism §4
    # scorri l'Actual in ordine topologico; il primo nodo difettoso è il divergence point
    for D in actual.topo_order:
        if is_defective(D, diff):                          # ha ≥1 GraphDefect o Decision-defect
            return DivergencePoint(
                decision_id = D.id,
                timestamp   = D.timestamp,
                cause       = divergence_cause(D, diff),   # reasoning-taxonomy §2 (una sola)
                archetype   = match_archetype(D, diff),    # failure-taxonomy §2
                downstream  = descendants(actual, D))      # cosa questo ha avvelenato a valle
    return None                                            # nessuna divergenza → successo pulito
```

Output tipizzato:

```jsonc
DivergencePoint = {
  "decision_id": str, "timestamp": int,
  "cause": DivergenceCause,             // reasoning-taxonomy
  "archetype": FailureArchetype.id,     // failure-taxonomy
  "downstream_decisions": [decision_id],// tutte le Decision contaminate a valle
  "confidence": "HIGH"|"MEDIUM"|"LOW"   // LOW se basata su campi RECONSTRUCTED/PROXY (decision-lifecycle §4)
}
```

Perché il "primo": nel corpus, il sintomo finale (un placeholder scritto, un `web_search`) è
*downstream*; la divergenza è al passo 1. Il `downstream_decisions` quantifica il danno propagato —
la giustificazione numerica del "correggi il primo, non l'ultimo".

---

## 2. Root Cause Engine (mission §9)

Dal DivergencePoint costruisce la spiegazione causale completa. Ogni fallimento produce **un**
`RootCause`:

```jsonc
RootCause = {
  "primary_cause":   DivergenceCause,      // dal divergence point
  "secondary_causes":[DivergenceCause],    // difetti co-occorrenti non a monte
  "contributing":    [str],                // condizioni abilitanti (es. context DECISIVE mancante)
  "confidence":      float,                // §5 formula
  "affected_components": [ArchitecturalComponent],
  "minimal_fix":     FixProposal,          // il fix più piccolo che spegne il primary
  "architectural_fix": FixProposal,        // il fix che spegne l'intera categoria/archetipo
  "estimated_ftfr_gain": float,            // §3
  "estimated_arr_gain":  float,
  "estimated_complexity":"S"|"M"|"L",
  "estimated_risk":     "LOW"|"MEDIUM"|"HIGH"
}
```

`minimal_fix` vs `architectural_fix` è la distinzione operativa della mission: il primo copre il *caso*,
il secondo la *categoria*. Il framework mostra **entrambi** e lascia al Leverage Estimator ordinarli —
ma marca sempre il `minimal_fix` come "copre un caso" (red flag di AGENTS.md), così non viene scambiato
per una soluzione.

Questo record riempie **esattamente** il blocco `study` già presente e vuoto nei failure-db JSON
(`root_cause`, `secondary_causes`, `components`, `confidence`, `candidate_solutions` — vedi
[WIN-ENV_PATH-00001.json](../../workspace/validation/windows-lab/failure-db/WIN-ENV_PATH-00001.json)).
Il Root Cause Engine è ciò che popola quel blocco automaticamente.

### FixProposal

```jsonc
FixProposal = {
  "target_component": ArchitecturalComponent,
  "description": str,                  // cosa cambiare, framework-neutral
  "eliminates_archetype": FailureArchetype.id | null,
  "kind": "INVARIANT" | "CONTEXT_RULE" | "STATE_FIX" | "SCHEMA" | "PROMPT_STRUCTURE"
}
```

`kind` è deliberatamente *strutturale* (invarianti, regole di context, fix di stato) — mai
"aggiungi euristica per il tool X". Un FixProposal con `kind` euristico-specifico è invalido per costruzione.

---

## 3. Leverage Estimator (mission §10)

Per ogni `FixProposal` calcola un **vettore di leva** e ordina tutti i fix in modo deterministico.

```jsonc
LeverageEstimate = {
  "fix": FixProposal,
  "delta_ftfr":  float,   // Δ First-Time-Fix-Rate previsto
  "delta_arr":   float,   // Δ Autonomous-Resolution-Rate
  "delta_raf":   float,   // riduzione RAF (azioni per successo) — negativo = miglioramento
  "delta_retry": float,   // riduzione retry medi
  "delta_tokens":float,   // riduzione token medi
  "delta_latency":float,  // riduzione latenza media
  "loc_touched": "S"|"M"|"L",   // quanto codice cambia
  "risk":        "LOW"|"MEDIUM"|"HIGH",
  "generalizability": float,     // frazione di domini distinti coperti (0..1)
  "score": float          // §3.2 ranking scalare
}
```

### 3.1 Stima dei Δ — corpus-frequency, non intuizione

Il punto che rende la leva **misurabile e riproducibile**: il guadagno di un fix è la frazione di casi
che esibiscono l'archetipo che il fix elimina.

```
delta_ftfr(fix) = |{ case ∈ corpus : archetype(case) == fix.eliminates_archetype
                                     ∧ not other_blocking_archetype(case) }| / |corpus|
delta_arr(fix)  = |{ case : resolved(case)==False ∧ archetype(case)==fix.eliminates_archetype }| / |corpus|
delta_raf(fix)  = mean_over(affected_cases, raf_before - raf_ideal_after)
generalizability(fix) = |distinct_domains(affected_cases)| / |distinct_domains(corpus)|
```

Tutti i termini sono **conteggi sul corpus** già classificato — nessuna previsione soggettiva. Esempio
dal corpus: `fix = "belief PROVEN sticky (invariante #10)"` elimina `F-BELIEF-01` (8 casi su 22),
presente su ≥5 domini distinti → `delta_ftfr≈0.36`, `generalizability≈0.7`, `delta_raf` forte
(spegne i rediscovery loop che gonfiano il RAF 2.11). Questo è esattamente il ranking che il corpus ha
prodotto a mano; qui è calcolato.

### 3.2 Ranking scalare (deterministico, pesi fissi)

```
score(L) =  w_ftfr·L.delta_ftfr + w_arr·L.delta_arr
          + w_raf·(−L.delta_raf) + w_gen·L.generalizability
          − w_risk·risk_penalty(L.risk) − w_loc·loc_penalty(L.loc_touched)

WEIGHTS = { ftfr:0.35, arr:0.25, raf:0.15, gen:0.15, risk:0.06, loc:0.04 }   // versionati, DE-5
```

I pesi sono **espliciti e versionati** (come `DEFAULT_WEIGHTS` in
[metrics.py](../../workspace/benchmarks/osbench/scoring/metrics.py)). Cambiare priorità = cambiare i
pesi in un punto, non riscrivere l'analisi. Il ranking finale è
`sort(estimates, key=score, desc)` — totalmente ordinato, riproducibile.

Tie-break: a parità di score, vince `generalizability` più alta, poi `loc_touched` minore, poi ID
archetipo (stabile). Output → [reports/high-leverage-fixes.md](reports/high-leverage-fixes.md).

---

## 4. Architectural Classifier (mission §11)

Ogni difetto è assegnato a **esattamente uno** `ArchitecturalComponent` (enum chiuso, 15). Mai
`UNKNOWN` se una categoria è inferibile (DE-8).

| `ArchitecturalComponent` | Possiede… | File runtime |
|--------------------------|-----------|--------------|
| `PLANNER` | scomposizione del goal, ordine, fasi, target-state | `supervisor.py` (plan) |
| `BELIEF` | world-model, stickiness, transizioni | `reasoning.py` (BeliefSystem) |
| `CONTEXT` | selezione/priorità del context al prompt | `reasoning.py` (AttentionManager) |
| `KNOWLEDGE` | conoscenza OS/capability, filtro piano | `knowledge/ocke.py` |
| `CAPABILITY` | modello delle capability, probing | `state.py` (Capability) |
| `EXECUTION` | esecuzione, cattura output, redirect, PTY | `orchestrator`/`terminal_runtime` |
| `OBSERVATION` | osservazione dello stato, judge | `tools/observer.py` |
| `VERIFICATION` | verifica esiti, artifact/behavioral | `_artifact_check`/`behavior_verifier` |
| `TELEMETRY` | osservabilità, tracciamento decisioni | `telemetry.py` |
| `SAFETY` | classificazione rischio, gate | `tools/safety_gate.py` |
| `PROMPT` | struttura del prompt, template | `prompts/` |
| `MODEL` | capacità intrinseca del modello | model_router |
| `INFRASTRUCTURE` | venv, PATH runtime, filesystem host | ambiente |
| `BENCHMARK` | difetto della fixture/case, non dell'agente | `validation/`, `benchmarks/` |
| `EXTERNAL` | rete, registry, servizi terzi | fuori sistema |

### Assegnazione (deterministica)

```
component(defect):
    return CAUSE_TO_COMPONENT[divergence_cause(defect)] with refinement:
        # la mappa base viene da reasoning-taxonomy col 5; raffinamenti tipizzati:
        if cause==MISSING_VERIFICATION and stage_absent:   return VERIFICATION
        if cause==BELIEF_CORRUPTION:                        return BELIEF
        if cause==EXECUTION_ERROR and output_lost:          return EXECUTION
        if defect is telemetry_gap:                         return TELEMETRY
        if case_fixture_malformed:                          return BENCHMARK    # es. WIN-CICD fixture non materializzata
        ...                                                 # tabella completa, totale
```

Regola **RC-1**: la classificazione `MODEL` richiede prova che il goal **non** sia stato compreso.
Nel corpus, `MODEL` = 0 casi (goal sempre compreso) — il classificatore non deve usare `MODEL` come
scorciatoia per "non so". `BENCHMARK` cattura i casi mal-posti (fixture CICD non materializzate),
tenendoli fuori dai difetti dell'agente (onestà, non gonfiare i numeri).

Output → [reports/architectural-debt.md](reports/architectural-debt.md): l'istogramma dei difetti per
componente. Nel corpus: Planner 16, Belief 8, Supervisor(Planner) 4, Context 7 (concausa),
Execution 3 (fuori scope), Model 0.

---

## 5. Confidence degli engine

```
confidence(root_cause) = base(divergence.cause)                 // quanto è netto il segnale
                       × provenance_factor(decisions_involved)  // 1.0 OBSERVED … 0.5 RECONSTRUCTED
                       × corpus_support(archetype)              // più exemplar → più confidenza
```

Un RootCause con `confidence` bassa (perché costruito su trace `RECONSTRUCTED`) **non** blocca l'analisi
ma appare come tale nei report e **richiede** il cablaggio di `Decision` in telemetry come prerequisito
del fix — la stessa conclusione del corpus §0/§6, qui prodotta automaticamente e per-caso.

Invariante **RC-2**: ogni engine è totale (emette sempre un output tipizzato), deterministico (DE-1),
e ancora ogni numero a un conteggio sul corpus o a una metrica di `metrics.py` (DE-3). Nessun numero è
un'opinione.
