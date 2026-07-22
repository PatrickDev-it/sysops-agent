# Reasoning Taxonomy — step di ragionamento & cause di divergenza

> **Owner** di `ReasoningStepKind` (i tipi di passo cognitivo) e di `DivergenceCause` (le 12 classi di
> primo errore cognitivo, mission §5). È il vocabolario che il [Divergence Engine](root-cause-framework.md)
> emette. Non descrive *cosa* è fallito (→ [failure-taxonomy.md](failure-taxonomy.md)) ma *quale tipo di
> ragionamento* ha deviato.

---

## 1. `ReasoningStepKind` (enum chiuso)

Ogni stadio `HYPOTHESIS` / `REASON` di una trace è uno di questi tipi. Mappano sui layer di
[reasoning.py](../../workspace/src/reasoning.py) (Inference/Deduction) e sul ciclo
`OBSERVE→HYPOTHESIZE→VERIFY→CHANGE→TEST` di [AGENTS.md](../../AGENTS.md).

| `ReasoningStepKind` | Forma | Layer runtime |
|---------------------|-------|---------------|
| `OBSERVATION` | "ho visto X" | `observe` / stdout |
| `ABDUCTION` | "X spiega il sintomo" (ipotesi di causa) | supervisor plan |
| `DEDUCTION` | "da A,B segue C" | `DeductionEngine` |
| `INDUCTION` | "N osservazioni ⇒ regola" | `InferenceEngine._extract_facts` |
| `ELIMINATION` | "C è impossibile perché ¬P" | `InferenceEngine._infer_from_failure` (IMPOSSIBLE) |
| `PLANNING` | "per il goal servono i passi …" | `Supervisor.plan` |
| `PRIORITIZATION` | "faccio prima A di B" | ordine del plan |
| `COMMITMENT` | "scelgo l'alternativa a" | `chosen_alternative` |

Un ragionamento sano su un task OBSERVE è:
`OBSERVATION(valore) → INDUCTION(valore è fatto) → PLANNING(scrivi valore) → COMMITMENT(write verbatim)`.
Le divergenze del corpus sono deviazioni *tipizzabili* da questa catena.

---

## 2. `DivergenceCause` (enum chiuso, 12) — il primo errore cognitivo

Owner della tassonomia richiesta dalla mission §5. Il Divergence Engine emette **una** causa: quella
del **primo** nodo in cui l'Actual DAG rompe l'Expected (non l'errore finale). Ogni causa è definita
formalmente su campi `Decision`/`GraphDefect`, così la classificazione è deterministica (DE-4).

| `DivergenceCause` | Definizione formale | Segnale primario | Componente tipico |
|-------------------|---------------------|------------------|-------------------|
| `WRONG_HYPOTHESIS` | `HYPOTHESIS.proposition` contraddetta dai fatti disponibili a quel timestamp | ipotesi ∌ facts | Planner/Model |
| `WRONG_STRATEGY` | `strategy ∉ CORRECT[intent]` ([strategy-model.md](strategy-model.md)) | strategy mismatch | Planner/Supervisor |
| `WRONG_CAPABILITY` | capability scelta ≠ quella disponibile/idonea; belief `x:exists` REFUTED ma usata | capability mismatch | Capability/Knowledge |
| `WRONG_ORDER` | `GraphDefect.WRONG_ORDER` sul primo arco DATAFLOW | topo inversion | Planner |
| `MISSING_DISCOVERY` | un `EXECUTE` consuma `X` senza una `DISCOVER(X)` precedente | `GraphDefect.MISSING_DECISION` (fase DISCOVER) | Planner |
| `PREMATURE_EXECUTION` | `EXECUTE` con `missing_evidence≠∅` | `GraphDefect.PREMATURE_DECISION` | Planner/Context |
| `MISSING_VERIFICATION` | `expected_verification` < minimo Intent, o stadio VERIFY assente | [verification-model.md](verification-model.md) VER-1 | Verification/Planner |
| `BELIEF_CORRUPTION` | `BeliefDefect ∈ {NON_STICKY_PROVEN, PREMATURE_REFUTE, SILENT_DROP}` | [belief-transition-model.md](belief-transition-model.md) | Belief |
| `CONTEXT_CORRUPTION` | context `DECISIVE` mancante o `IGNORED` che ha guidato male la scelta | [context-selection-model.md](context-selection-model.md) | Context |
| `PLANNING_ERROR` | il piano è mal-formato a monte dell'esecuzione (fase mancante non riconducibile alle sopra) | GraphDiff residuo | Planner |
| `EXECUTION_ERROR` | Decision **corretta**, effetto perso in esecuzione (output non catturato, encoding, permessi) | esito ko con Decision sana | Execution |
| `OBSERVATION_ERROR` | l'osservazione ha mal-riportato lo stato → belief/verify sbagliati su dato giusto | observe ≠ realtà | Observation |

### Regola di attribuzione (una sola causa, deterministica)

```
divergence_cause(first_defective_decision D, diff):
    # ordine di precedenza: la causa più "a monte" vince (cognitive earliness)
    if belief_corruption_at(D):        return BELIEF_CORRUPTION
    if D in diff.missing and phase==DISCOVER: return MISSING_DISCOVERY
    if strategy_mismatch(D):           return WRONG_STRATEGY
    if hypothesis_contradicted(D):     return WRONG_HYPOTHESIS
    if D in diff.premature:            return PREMATURE_EXECUTION
    if D in diff.wrong_order:          return WRONG_ORDER
    if capability_mismatch(D):         return WRONG_CAPABILITY
    if missing_verification(D):        return MISSING_VERIFICATION
    if decisive_context_missing(D):    return CONTEXT_CORRUPTION
    if observation_wrong(D):           return OBSERVATION_ERROR
    if decision_sound_but_effect_lost(D): return EXECUTION_ERROR   # D5: escludere da "decisione sbagliata"
    return PLANNING_ERROR              # default esplicito, MAI UNKNOWN (DE-8)
```

L'ordine di precedenza **non** è arbitrario: riflette l'*earliness cognitiva*. Un belief corrotto
avvelena tutto ciò che segue, quindi domina; un `EXECUTION_ERROR` è l'ultima risorsa perché lì la
decisione era sana (il D5 del corpus, esplicitamente *fuori scope* per "decisione sbagliata").

---

## 3. Perché "il primo errore, non l'ultimo"

Il corpus lo dimostra: in WIN-ENV_PATH-00001 l'errore *finale* visibile è `web_search` +
`write_file|path.txt|PATH_CONTENT` (un placeholder), ma il **primo** errore cognitivo è al passo 1 —
`PREMATURE_EXECUTION` / `WRONG_STRATEGY`: scrivere prima di sapere. Correggere l'ultimo errore
(il placeholder) non generalizza; correggere il primo (imporre `X∈facts` prima di `write(X)`) elimina
l'intera classe. Il Divergence Engine esiste per **non** farsi ingannare dal sintomo terminale.

---

## 4. Relazioni con le altre tassonomie

- `DivergenceCause` risponde: *che tipo di ragionamento ha deviato per primo?*
- [`FailureArchetype`](failure-taxonomy.md) risponde: *quale pattern di fallimento riconoscibile è?*
  (un archetipo = spesso una coppia `DivergenceCause × ArchitecturalComponent` ricorrente).
- [`ArchitecturalComponent`](root-cause-framework.md#4-architectural-classifier) risponde: *quale layer
  possiede il fix?*

I tre sono ortogonali e componibili: `(WRONG_STRATEGY, Planner) → FailureArchetype F-STRAT-FABRICATE`.

Invariante **REAS-1**: `divergence_cause` è totale e deterministica; emette esattamente una causa per
Decision divergente; mai UNKNOWN.
