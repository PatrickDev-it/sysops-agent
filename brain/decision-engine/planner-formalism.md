# Planner Formalism — fasi, Decision Graph, diff Expected/Actual

> **Owner** di: fasi del piano (`PlanPhase`), grafo delle decisioni (`DecisionGraph`, `EdgeKind`),
> e del confronto **Expected vs Actual** (`GraphDefect`, `GraphDiff`). Copre la mission §3, §4, §7.
> Consuma `Decision` ([decision-model.md](decision-model.md)); alimenta il Divergence Engine
> ([root-cause-framework.md](root-cause-framework.md)).

---

## 1. Fasi del piano — `PlanPhase`

Ogni Decision appartiene a **esattamente una** fase. Enum chiuso, allineato al `step_type` del runtime
ma più fine (una fase è cognitiva; uno `step_type` è operativo):

| `PlanPhase` | Definizione | `step_type` corrispondente |
|-------------|-------------|-----------------------------|
| `PRECONDITION` | verifica un vincolo che deve valere prima di agire (rischio, permessi, esistenza workspace) | — / safety_gate |
| `DISCOVER` | acquisisce un valore o una capability ignoti | `DISCOVERY` |
| `REASON` | deriva una conclusione da fatti/belief senza toccare il mondo | — (inference/deduction) |
| `EXECUTE` | modifica lo stato del mondo | `MODIFY` |
| `VERIFY` | osserva se l'`expected_outcome` regge | `VERIFY` |
| `RECOVER` | rimedia a una Decision `REFUTED` | `RECOVER` |

Un piano ben formato è una sequenza di fasi che rispetta l'**ordinamento parziale canonico**:

```
PRECONDITION ⟶ DISCOVER ⟶ REASON ⟶ EXECUTE ⟶ VERIFY        (RECOVER innesta dopo un VERIFY fallito)
```

Regola **PLAN-1 (dataflow-before-effect)**: nessuna `EXECUTE` il cui `expected_outcome` contiene un
simbolo libero `X` può precedere la `DISCOVER`/`REASON` che rende `X` un fatto PROVEN. Questa è la
formalizzazione generale del difetto `WRITE_BEFORE_KNOW` (D1) e `NEVER_WRITE` (D2) del
[decision-analysis.md](../../workspace/validation/windows-lab/reports/decision-analysis.md) — non un
caso speciale di `write_file`, ma l'invariante di dataflow di *qualsiasi* effetto che consuma un valore.

---

## 2. Decision Graph — DAG

> Ogni task produce un **DAG**, non una lista. Nodo = `Decision`. Arco = dipendenza logica *tipizzata*.

### `EdgeKind` (enum chiuso)

| `EdgeKind` | `A —kind→ B` significa | Come si deriva (deterministico) |
|------------|------------------------|----------------------------------|
| `DATAFLOW` | B consuma un fatto/valore prodotto da A | `A.facts_produced ∩ B.evidence_required ≠ ∅` |
| `PRECONDITION` | B richiede che A sia `CONFIRMED` | `B.expected_recovery` presuppone `A` (belief/capability) |
| `ORDER` | B deve seguire A per contratto di fase | `phase(A) ≺ phase(B)` sullo stesso target |
| `RECOVERY_OF` | B rimedia ad A `REFUTED` | `B.parent_decision == A.id` |
| `ALTERNATIVE_OF` | B è un tentativo alternativo di A (stesso intent, dopo fallimento) | stessa `signature`-classe, A `REFUTED` |

### Costruzione del grafo (Graph Builder, stage 2)

```
build_graph(decisions):
    nodes = [ node(D) for D in decisions ]
    edges = []
    for A, B in ordered_pairs(decisions):        # A.timestamp < B.timestamp
        if A.facts_produced ∩ B.evidence_required: edges += DATAFLOW(A,B)
        if B.parent_decision == A.id:             edges += RECOVERY_OF(A,B)
        if precondition_holds(A,B):               edges += PRECONDITION(A,B)
        if same_target(A,B) and phase(A) ≺ phase(B): edges += ORDER(A,B)
    g = Graph(nodes, edges)
    g.is_dag = not has_cycle(g)                   # cicli = GraphDefect.CIRCULAR (belief non-sticky)
    g.topo_order = topo_sort(g) if g.is_dag else None
    return canonicalize(g)                        # ordine stabile → DE-1
```

Il grafo è **atteso essere aciclico**. Un ciclo è di per sé un difetto (`CIRCULAR`) e la sua firma
tipica è il `REDISCOVERY_LOOP` (D3): `DISCOVER(X) → … → DISCOVER(X)` perché il belief `X:exists` non è
diventato PROVEN sticky — l'invariante #10 rotto, misurabile come ciclo nel DAG.

---

## 3. Expected Decision Graph

L'Expected DAG è costruito **deterministicamente** dallo stesso schema, a partire dall'
`expected.reasoning` del failure-db case (o, in assenza di case, dalla forma canonica del goal). Il
formato del case è già strutturato per questo — vedi
[WIN-ENV_PATH-00001.json](../../workspace/validation/windows-lab/failure-db/WIN-ENV_PATH-00001.json)
campi `expected.reasoning`, `expected.commands`, `expected.success_criteria`:

```
build_expected_graph(case):
    steps = parse_reasoning_steps(case.expected.reasoning)   # una Decision-attesa per step
    for s in steps: s.expected_outcome = predicates_from(case.expected.success_criteria)
    return build_graph(steps)                                # stesso builder → confrontabile
```

Per i task OBSERVE (19/22 del corpus) l'Expected DAG è la catena canonica:
`DISCOVER(X) → REASON(X∈facts, PROVEN) → EXECUTE(write X) → VERIFY(content==X)`. Il framework non la
hardcoda: la *deriva* dai `success_criteria` del case, quindi vale per qualsiasi dominio.

---

## 4. `GraphDiff` — Expected vs Actual

Per ogni task il framework genera Structural Diff + Semantic Diff. Enum chiuso `GraphDefect` (9 classi,
= mission §4):

| `GraphDefect` | Definizione formale | Rilevazione |
|---------------|---------------------|-------------|
| `MISSING_DECISION` | nodo presente in Expected, assente in Actual | node-set diff |
| `EXTRA_DECISION` | nodo in Actual senza corrispondente Expected | node-set diff |
| `WRONG_ORDER` | coppia (A,B) con `topo(A)<topo(B)` in Expected ma invertita in Actual | topo-order diff |
| `PREMATURE_DECISION` | `EXECUTE` con `missing_evidence≠∅` al suo `timestamp` | evidence check |
| `LATE_DECISION` | `DISCOVER` che segue l'`EXECUTE` che ne consuma l'output | edge DATAFLOW invertito |
| `CIRCULAR_DECISION` | ciclo nel grafo Actual | `!is_dag` |
| `DEAD_DECISION` | nodo senza archi uscenti né effetto su GoalDistance (`cost.wasted`) | grado uscente 0 + wasted |
| `IMPOSSIBLE_DECISION` | Decision `BLOCKED` da `ExecutionPolicyGuard` o filtrata da `OCKE.filter_plan` | policy/ocke log |
| `UNREACHABLE_DECISION` | nodo in Actual mai raggiunto (budget esaurito prima) | esecuzione troncata |

### Algoritmo di diff (deterministico)

```
graph_diff(expected, actual):
    node_map = align_nodes(expected, actual)      # match per (phase, expected_outcome-signature)
    d = GraphDiff()
    d.missing   = expected.nodes \ matched
    d.extra     = actual.nodes \ matched
    d.wrong_order = [ (A,B) for (A,B) in expected.order_pairs
                       if inverted_in(actual, node_map[A], node_map[B]) ]
    d.premature = [ N for N in actual.EXECUTE if N.missing_evidence ]
    d.late      = [ N for N in actual.DISCOVER if feeds_earlier_execute(N) ]
    d.circular  = cycles(actual)
    d.dead      = [ N for N in actual if out_degree(N)==0 and N.cost.wasted ]
    d.impossible= [ N for N in actual if N.state==BLOCKED ]
    return d
```

`align_nodes` matcha per **firma semantica** (fase + predicato di outcome normalizzato), **non** per
testo del comando — così un `write_file` e un `Out-File` che producono lo stesso artefatto sono lo
stesso nodo logico (DE-6/DE-7: indipendenza da tool/shell).

---

## 5. Planner Analysis (mission §7)

Dalla scomposizione del piano in fasi, il framework estrae **automaticamente**, per ogni piano:

| Estratto | Definizione | Da |
|----------|-------------|-----|
| Preconditions | Decision in fase `PRECONDITION` | phase partition |
| Discover phase | Decision `DISCOVER` | phase partition |
| Reasoning phase | Decision `REASON` | phase partition |
| Execution phase | Decision `EXECUTE` | phase partition |
| Verification phase | Decision `VERIFY` | phase partition |
| Recovery phase | Decision `RECOVER` | phase partition |
| **azioni mancanti** | `GraphDefect.MISSING_DECISION` | diff |
| **azioni premature** | `GraphDefect.PREMATURE_DECISION` | diff |
| **azioni duplicate** | nodi Actual con stessa firma semantica | node dedup |
| **azioni impossibili** | `GraphDefect.IMPOSSIBLE_DECISION` | policy/ocke |
| **azioni inutili** | `GraphDefect.DEAD_DECISION` | wasted |
| **azioni mai raggiunte** | `GraphDefect.UNREACHABLE_DECISION` | troncamento |

Output → [reports/planner-analysis.md](reports/planner-analysis.md) e
[reports/decision-graph.md](reports/decision-graph.md). Il **primo** difetto in ordine topologico è
l'input privilegiato del [Divergence Engine](root-cause-framework.md#1-divergence-engine): non tutti i
difetti pesano uguale, il primo cognitivo domina.

---

## 6. Invarianti del formalismo

- **PLAN-2**: `align_nodes` è simmetrico e stabile → `graph_diff(E,A)` è deterministico (DE-1).
- **PLAN-3**: ogni `GraphDefect` è ancorato a un `EdgeKind`/campo Decision, mai a prosa → riproducibile (DE-4).
- **PLAN-4**: nessuna soglia dipende da OS/tool. Le uniche costanti (`phase order`) sono cognitive.
