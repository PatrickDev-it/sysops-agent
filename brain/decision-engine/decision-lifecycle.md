# Decision Lifecycle & Cognitive Trace

> **Owner** della FSM di una `Decision` e degli stadi della **Cognitive Trace**.
> Definisce `DecisionState`, `TraceStage`, e il modello di `provenance`. Entità →
> [decision-model.md](decision-model.md). Serializzazione → [decision-schema.md](decision-schema.md).

---

## 1. La FSM di una Decision

Una Decision **non** è statica: passa attraverso stati osservabili dal momento in cui è proposta a
quello in cui è confermata, refutata o superata. Enum chiuso `DecisionState` (10 stati):

```
                 ┌───────────┐
                 │ PROPOSED  │  il planner l'ha generata (∈ plan[])
                 └─────┬─────┘
        ExecutionPolicyGuard.check()
          allow=false │ allow=true
        ┌─────────────┴───────────────┐
        ▼                             ▼
  ┌──────────┐                  ┌──────────┐
  │ BLOCKED  │                  │ SELECTED │  scelta per l'esecuzione
  └──────────┘                  └────┬─────┘
   (pre_execute_check)               ▼
                              ┌──────────────┐
                              │  EXECUTED    │  ActionResult ottenuto
                              └──────┬───────┘
                                     ▼
                              ┌──────────────┐
                              │  OBSERVED    │  observe()/stdout catturati
                              └──────┬───────┘
                       observe_judge / supervisor.verify / _artifact_check
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
             ┌───────────┐    ┌───────────┐    ┌────────────┐
             │ CONFIRMED │    │ REFUTED   │    │ SUPERSEDED │
             └───────────┘    └─────┬─────┘    └────────────┘
              expected_outcome       │ recovery genera una nuova Decision
              soddisfatto            └──► child Decision (parent=questa)
                                    ABANDONED = run finisce senza verifica
```

| `DecisionState` | Significato | Sorgente runtime |
|-----------------|-------------|------------------|
| `PROPOSED` | in `plan[]`, non ancora eseguita | `Supervisor.plan` |
| `SELECTED` | superato il gate, in esecuzione | `pre_execute_check` allow=true |
| `BLOCKED` | vietata prima dell'esecuzione | `ExecutionPolicyGuard` allow=false |
| `EXECUTED` | azione eseguita, esito grezzo noto | `ActionResult` |
| `OBSERVED` | osservazione raccolta | `observe()` / `stdout` |
| `CONFIRMED` | `expected_outcome` verificato vero | `_artifact_check`/`verify` ok |
| `REFUTED` | `expected_outcome` verificato falso | verify/artifact ko |
| `SUPERSEDED` | rimpiazzata da una Decision successiva | recovery re-plan |
| `ABANDONED` | run terminato senza verifica di questa Decision | fine loop |
| `SKIPPED` | no-op deliberato (es. DISCOVERY su wizard) | orchestrator |

Invariante **DEC-LIFE-1**: una Decision `CONFIRMED` non torna mai indietro nello *stesso* run; una
`REFUTED` può solo generare **figli** (recovery), mai mutare sé stessa — coerente con la stickiness dei
belief PROVEN/REFUTED in [reasoning.py::BeliefSystem](../../workspace/src/reasoning.py).

---

## 2. Cognitive Trace — gli stadi

La **Cognitive Trace** è la sequenza ordinata e tipizzata di stadi che ogni Decision attraversa. È la
forma richiesta dalla mission §2. Enum chiuso `TraceStage` (13 stadi), nell'ordine canonico:

```
GOAL → INTENT → PLANNER → DECISION → BELIEF_READ → EVIDENCE_COLLECTION
     → HYPOTHESIS → CAPABILITY_SELECTION → EXECUTION → OBSERVATION
     → BELIEF_UPDATE → VERIFICATION → OUTCOME → LESSON_LEARNED
```

Ogni stadio è un record `TraceStage`:

```jsonc
TraceStage = {
  "stage": "HYPOTHESIS",            // membro dell'enum
  "decision_id": str | null,        // a quale Decision appartiene (null per GOAL/INTENT globali)
  "payload": { ... },               // tipizzato per stage (sotto)
  "provenance": Provenance
}
```

| `TraceStage` | payload | Sorgente | Doc owner del contenuto |
|--------------|---------|----------|-------------------------|
| `GOAL` | `{goal}` | run | — |
| `INTENT` | `{intent: IntentClass}` | classificato | [strategy-model.md](strategy-model.md) |
| `PLANNER` | `{plan_phases: PlanPhase[]}` | plan | [planner-formalism.md](planner-formalism.md) |
| `DECISION` | `{decision_id}` | trace | [decision-model.md](decision-model.md) |
| `BELIEF_READ` | `{beliefs: BeliefRef[]}` | AttentionManager | [belief-transition-model.md](belief-transition-model.md) |
| `EVIDENCE_COLLECTION` | `{available, missing: EvidenceRef[]}` | facts | [context-selection-model.md](context-selection-model.md) |
| `HYPOTHESIS` | `{proposition, kind: ReasoningStepKind}` | inferito | [reasoning-taxonomy.md](reasoning-taxonomy.md) |
| `CAPABILITY_SELECTION` | `{capability, alternatives}` | capabilities | [strategy-model.md](strategy-model.md) |
| `EXECUTION` | `{command_sig, exit_code}` | ActionResult | — |
| `OBSERVATION` | `{observed: Predicate[]}` | observe | [verification-model.md](verification-model.md) |
| `BELIEF_UPDATE` | `{transitions: BeliefTransition[]}` | reasoning delta | [belief-transition-model.md](belief-transition-model.md) |
| `VERIFICATION` | `{kind: VerificationKind, passed: bool}` | verify | [verification-model.md](verification-model.md) |
| `OUTCOME` | `{state: DecisionState}` | FSM | questo doc |
| `LESSON_LEARNED` | `{learning_ref}` | post-run | [improvement-loop.md](improvement-loop.md) |

Invariante **DEC-LIFE-2**: la trace è **totale** — ogni Decision ha *esattamente* uno stadio per ogni
`TraceStage` applicabile al suo `step_type`. Uno stadio mancante non si omette: si emette con
`payload=null` e `provenance=UNAVAILABLE`. Uno stadio *saltato dal runtime* (es. `VERIFICATION` assente
perché il piano non l'ha pianificata) è esso stesso un **segnale diagnostico** — è la firma di
`MISSING_VERIFICATION` ([reasoning-taxonomy.md](reasoning-taxonomy.md)), non un buco da nascondere.

---

## 3. Mapping step_type → stadi attesi

Il `step_type` del runtime (DISCOVERY/MODIFY/VERIFY/RECOVER) determina quali stadi sono *obbligatori*:

| `step_type` | Stadi obbligatori | Note |
|-------------|-------------------|------|
| `DISCOVERY` | GOAL…EXECUTION, OBSERVATION, BELIEF_UPDATE | non produce artefatti (nessun ARTIFACT check) |
| `MODIFY` | tutti | il caso pieno; `VERIFICATION` obbligatoria |
| `VERIFY` | EXECUTION, OBSERVATION, VERIFICATION, OUTCOME | il comando *è* la verifica |
| `RECOVER` | HYPOTHESIS, DECISION, …, VERIFICATION | deve avere una `parent_decision` REFUTED |

Se un MODIFY non ha lo stadio `EVIDENCE_COLLECTION` con `missing=∅` prima di `EXECUTION`, è una
**PREMATURE_EXECUTION** rilevabile deterministicamente (nessun modello coinvolto).

---

## 4. Provenance

Enum chiuso `Provenance` — la fonte di ogni campo/stadio. È il meccanismo che tiene onesta la
modalità ricostruzione (il framework opera *anche* prima che `Decision` sia cablato in telemetry).

| `Provenance` | Significato | Ammesso in analisi? |
|--------------|-------------|---------------------|
| `OBSERVED` | letto direttamente da un artefatto del runtime | ✅ pieno peso |
| `INFERRED` | derivato deterministicamente da campi OBSERVED (es. `strategy`) | ✅ pieno peso |
| `PROXY` | approssimato da un segnale correlato (es. `confidence`←`parse_ok`) | ⚠️ segnalato nei report |
| `RECONSTRUCTED` | ricostruito da `facts`/`history` in assenza di telemetria decisioni | ⚠️ segnalato, mai in ranking hard |
| `UNAVAILABLE` | non derivabile → `null` | escluso dai conteggi |

Regola **DEC-LIFE-3**: un engine di ranking (Leverage) **non** può basare una conclusione *hard* solo
su campi `RECONSTRUCTED`/`PROXY`; deve marcare la conclusione come `confidence=LOW` e richiedere il
cablaggio di `Decision` come precondizione (esattamente il "Prerequisito iterazione #1" del corpus).
Questo impedisce di costruire una roadmap su inferenze spacciate per misure.

---

## 5. Da lifecycle a knowledge

Lo stadio finale `LESSON_LEARNED` è il ponte verso [improvement-loop.md](improvement-loop.md): ogni
Decision `REFUTED` la cui divergenza è stata classificata genera un `Learning Entry`. Una Decision
`CONFIRMED` con `cost.wasted=false` e trace completa alimenta la [success-taxonomy.md](success-taxonomy.md)
(cosa ha funzionato, non solo cosa ha fallito).
