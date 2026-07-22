# Decision Model — l'entità Decision tipizzata

> **Owner** dell'entità `Decision`. Una Decision **non è un comando**: è la scelta cognitiva che
> *precede* (o giustifica) un'azione. Ogni altro documento del framework consuma questo tipo.
> Substrato di costo/latenza: [telemetry_schema.py::Decision](../../workspace/benchmarks/telemetry_schema.py)
> (che questo modello **estende**, non rimpiazza). Enum referenziati dai rispettivi owner.

---

## 1. Definizione

> Una **Decision** è un record immutabile che cattura *una singola scelta deliberata* del sistema:
> quale intento perseguire, quale strategia adottare, quali alternative esistevano, quali evidenze
> erano richieste e disponibili, quali belief ha letto e mutato, e cosa si aspettava come esito.

Corollario (invariante **DEC-MODEL-1**): *un comando eseguito senza una Decision associata è un
difetto di osservabilità*, non un'assenza di decisione. Il runtime **ha** deciso; se la Decision
non è tracciata, la trace la marca `provenance=RECONSTRUCTED` (vedi
[decision-lifecycle.md](decision-lifecycle.md#provenance)), mai la omette.

Una Decision è distinta da:
- un **Action** ([state.py::ActionResult](../../workspace/src/state.py)) — l'*effetto* eseguito;
- un **Belief** ([reasoning.py::Belief](../../workspace/src/reasoning.py)) — una *proposizione* sul mondo;
- un **Fact** ([state.py::Fact](../../workspace/src/state.py)) — un *valore osservato*.

Relazione: `Decision --produces--> {Action*, Belief-delta, Fact*}`; `Action --observed_as--> Observation --updates--> Belief`.

---

## 2. I 28 campi (tipizzati)

Ogni campo dichiara: **tipo**, **cardinalità**, **sorgente runtime** (da dove il Trace Builder lo
deriva), e se è **osservabile oggi** o richiede il cablaggio di `Decision` in telemetry.

### Identità e scopo

| # | Campo | Tipo | Sorgente | Oggi |
|---|-------|------|----------|------|
| 1 | `decision_id` | `str` (stable hash, §4) | derivato | ✅ |
| 2 | `goal` | `str` | `SystemState` / case goal | ✅ |
| 3 | `intent` | `IntentClass` (enum) | classificato da goal+step | ⚠️ inferito |
| 4 | `expected_outcome` | `Predicate[]` | plan `success[]` + `DesiredState` | ✅ |

### Strategia e spazio delle alternative

| # | Campo | Tipo | Sorgente | Oggi |
|---|-------|------|----------|------|
| 5 | `strategy` | `StrategyClass` (enum) | classificato ([strategy-model.md](strategy-model.md)) | ⚠️ inferito |
| 6 | `alternatives_considered` | `AlternativeRef[]` | model output (da cablare) | ❌ |
| 7 | `chosen_alternative` | `AlternativeRef` | = l'azione emessa | ✅ |
| 8 | `rejected_alternatives` | `AlternativeRef[]` | model output (da cablare) | ❌ |
| 9 | `confidence` | `float ∈ [0,1]` | model logprob/self-report o `parse_ok` proxy | ⚠️ proxy |

### Evidenze

| # | Campo | Tipo | Sorgente | Oggi |
|---|-------|------|----------|------|
| 10 | `evidence_required` | `EvidenceRef[]` | derivato da `strategy` (vedi §5) | ⚠️ inferito |
| 11 | `evidence_available` | `EvidenceRef[]` | `facts` ∩ `evidence_required` a decision-time | ✅ |
| 12 | `missing_evidence` | `EvidenceRef[]` | `evidence_required \ evidence_available` | ✅ |

### Belief-delta (mappa 1:1 su [reasoning.py](../../workspace/src/reasoning.py))

| # | Campo | Tipo | Sorgente | Oggi |
|---|-------|------|----------|------|
| 13 | `beliefs_read` | `BeliefRef[]` | `AttentionManager` proiezione al prompt | ⚠️ inferito |
| 14 | `beliefs_created` | `BeliefRef[]` | belief nuovi post-step | ✅ (via debug_dump diff) |
| 15 | `beliefs_updated` | `BeliefRef[]` | belief con score cambiato | ✅ |
| 16 | `beliefs_invalidated` | `BeliefRef[]` | belief → REFUTED post-step | ✅ |

### Fatti e capability

| # | Campo | Tipo | Sorgente | Oggi |
|---|-------|------|----------|------|
| 17 | `facts_required` | `str[]` (fact keys) | derivato da `expected_outcome` | ⚠️ inferito |
| 18 | `facts_produced` | `str[]` (fact keys) | `ActionResult.produced_facts` | ✅ |
| 19 | `capabilities_used` | `str[]` | `SystemState.capabilities` toccate | ✅ |

### Verifica e recovery attesi

| # | Campo | Tipo | Sorgente | Oggi |
|---|-------|------|----------|------|
| 20 | `expected_verification` | `VerificationKind` (enum) | `step_type`+`success[]` ([verification-model.md](verification-model.md)) | ✅ |
| 21 | `expected_recovery` | `RecoveryClass[]` | `error_classifier.allowed_recoveries` | ✅ |

### Costo e rischio

| # | Campo | Tipo | Sorgente | Oggi |
|---|-------|------|----------|------|
| 22 | `risk` | `RiskClass` (enum: SAFE/RECOVERABLE/DESTRUCTIVE) | [safety_gate.classify](../../workspace/src/tools/safety_gate.py) | ✅ |
| 23 | `cost` | `CostVector` (§3) | telemetry | ⚠️ parziale |
| 24 | `estimated_token_cost` | `int` | `telemetry_schema.Decision.total_tokens` | ❌ (da cablare) |
| 25 | `estimated_latency_ms` | `float` | `telemetry_schema.Decision.latency_ms` | ❌ (da cablare) |

### Struttura del grafo

| # | Campo | Tipo | Sorgente | Oggi |
|---|-------|------|----------|------|
| 26 | `parent_decision` | `decision_id \| null` | Graph Builder | ✅ |
| 27 | `child_decisions` | `decision_id[]` | Graph Builder | ✅ |
| 28 | `timestamp` | `float` (monotonic index, non wall-clock) | history order | ✅ |

> **Nota DE-1 (determinismo):** `timestamp` nel corpo analitico è l'**indice monotòno di step**,
> non l'orario di parete — così due run identici producono trace byte-identiche. Il wall-clock vive
> solo nei metadati del record, mai nelle chiavi o negli hash.

**Copertura oggi:** 17/28 campi derivabili dal runtime attuale (✅ o ⚠️), 4 richiedono il cablaggio di
`Decision` (alternatives + costi-modello), il resto è inferito con provenienza esplicita. Nessun campo
è mai *inventato*: se non derivabile, vale `null` con `provenance=UNAVAILABLE`.

---

## 3. Tipi composti

```jsonc
// AlternativeRef — una scelta possibile nello spazio delle azioni
AlternativeRef = {
  "signature": str,          // hash stabile dell'azione candidata (§4)
  "strategy": StrategyClass, // la strategia che rappresenta
  "predicted_outcome": Predicate[],
  "rejected_reason": str | null   // perché scartata (null se è la scelta presa)
}

// EvidenceRef — un pezzo di conoscenza richiesto/disponibile a decision-time
EvidenceRef = {
  "kind": "fact" | "belief" | "capability" | "observation",
  "key": str,                // es. "tool_path:git", "git:exists"
  "state_at_decision": str,  // es. PROVEN, "value=..."  (snapshot, non riferimento vivo)
  "satisfied": bool
}

// BeliefRef — snapshot di un belief nel momento della Decision
BeliefRef = {
  "proposition": str,        // "git:exists"
  "state": BeliefState,      // UNKNOWN|POSSIBLE|LIKELY|PROVEN|REFUTED  (reasoning.py)
  "score": float,
  "transition": BeliefTransition | null  // se questa Decision lo ha mutato
}

// CostVector — tutte le grandezze scalari misurabili di una Decision
CostVector = {
  "tokens": int,             // 0 se deterministica (System-1)
  "latency_ms": float,
  "retries": int,            // ExecutionPolicyGuard / MAX_RETRIES_PER_STEP
  "actions_emitted": int,
  "wasted": bool             // true se la Decision non ha ridotto GoalDistance
}

// Predicate — un esito verificabile (stesso linguaggio di _artifact_check)
Predicate = "exists(path)" | "dir_not_empty(path)"
          | "contains_string(path, text)" | "is_executable(name)"
          | "belief(proposition, state)" | "fact(key)"
```

`Predicate` **riusa deliberatamente** la grammatica di
[orchestrator.py::_artifact_check](../../workspace/src/orchestrator.py) e di `DesiredState`: così
l'`expected_outcome` di una Decision è verificabile con lo stesso motore già in produzione — nessun
secondo linguaggio di asserzione da mantenere.

---

## 4. `decision_id` e `signature` — hashing deterministico

```
signature(action)  = sha1(normalize(action.command))[:12]
decision_id(D)     = sha1( D.goal_norm + "|" + D.strategy + "|" +
                           D.chosen_alternative.signature + "|" +
                           str(D.timestamp) )[:16]

normalize(cmd): lowercase; collassa whitespace; rimuove path assoluti volatili
                (workspace temp dir → "<WS>"); ordina i flag; NON tocca la semantica.
```

Invariante **DEC-MODEL-2**: `decision_id` è funzione *pura* dei campi semantici + indice di step.
Due run che prendono la stessa decisione al medesimo passo producono lo stesso `decision_id`
→ le trace sono **diffabili tra release** (DE-5). `normalize` è l'unico punto in cui si neutralizza
la volatilità di ambiente, ed è framework-neutral (nessun nome di tool o OS).

---

## 5. Derivazione di `evidence_required` (deterministica)

`evidence_required` **non** è un campo che il modello dichiara: è **derivato dalla strategia** via una
tabella chiusa (owner: [strategy-model.md](strategy-model.md#evidence-contract)). Esempio di forma
(non un caso speciale — è la regola generale del dataflow):

```
require_evidence(D):
    req = []
    for pred in D.expected_outcome:
        for symbol in free_symbols(pred):        # es. il valore X in write(X)
            req.append(EvidenceRef(kind=classify(symbol), key=symbol,
                                   satisfied = symbol in facts_at(D.timestamp)))
    req += STRATEGY_EVIDENCE[D.strategy]          # tabella chiusa
    return dedup(req)
```

Questo rende misurabile il difetto centrale del corpus (`WRITE_BEFORE_KNOW`, D1 in
[decision-analysis.md](../../workspace/validation/windows-lab/reports/decision-analysis.md)): una
`write(X)` la cui `X` non è ancora un fatto ha `missing_evidence ≠ ∅` **al momento della Decision**,
indipendentemente dall'esito. Il difetto è visibile *nella decisione*, non solo nell'errore finale.

---

## 6. Cosa questo modello rende possibile

| Domanda della mission | Campi che la rispondono |
|-----------------------|-------------------------|
| *Perché ha scelto questo?* | `intent`, `strategy`, `alternatives_considered`, `rejected_alternatives`, `beliefs_read`, `evidence_available` |
| *La scelta era informata?* | `missing_evidence`, `confidence`, `beliefs_read` |
| *Ha corrotto lo stato?* | `beliefs_invalidated`, `beliefs_updated` + [belief-transition-model.md](belief-transition-model.md) |
| *Era prematura?* | `missing_evidence ≠ ∅` + posizione nel DAG ([planner-formalism.md](planner-formalism.md)) |
| *Quanto è costata?* | `cost`, `estimated_token_cost`, `estimated_latency_ms` |
| *È stata inutile?* | `cost.wasted` (GoalDistance non ridotta) |

Serializzazione → [decision-schema.md](decision-schema.md). Evoluzione nel tempo →
[decision-lifecycle.md](decision-lifecycle.md).
