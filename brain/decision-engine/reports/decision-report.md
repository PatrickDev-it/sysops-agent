# Decision Report — {{run_id}}

> Template generato. Owner del formato: [decision-lifecycle.md](../decision-lifecycle.md).
> `provenance` documento: **RECONSTRUCTED** (worked example: WIN-ENV_PATH-00001, run_1783040996).

---

## Meta

| Campo | Valore |
|-------|--------|
| run_id | `{{run_id}}` — es. `run_1783040996` |
| case_id | `{{case_id}}` — es. `WIN-ENV_PATH-00001` |
| goal | `{{goal}}` — es. *"Scrivi il PATH effettivo, una voce per riga, in path.txt"* |
| intent | `{{IntentClass}}` — es. `OBSERVE_AND_REPORT` |
| verdict | `{{verdict}}` — es. `INCOMPLETE` |
| success_class | `{{SuccessClass}}` — es. `—` (fallito) |
| n_decisions | `{{n}}` — es. 7 azioni → 7 Decision |
| provenance_profile | OBSERVED {{n}} · INFERRED {{n}} · RECONSTRUCTED {{n}} |

---

## Cognitive Trace (worked example)

Sequenza `TraceStage` fino al divergence point. **↯** marca il primo errore cognitivo.

```
GOAL           "write effective PATH, one entry per line, to path.txt"
 ↓
INTENT         OBSERVE_AND_REPORT           [readonly=true, artifact=path.txt]
 ↓
PLANNER        phases = [EXECUTE]           ← manca DISCOVER, manca REASON  ✗
 ↓
DECISION  d0   strategy=AUTHOR_ARTIFACT     ← atteso OBSERVE_AND_REPORT     ↯ WRONG_STRATEGY
 ↓
BELIEF_READ    (none)
 ↓
EVIDENCE       required={PATH_VALUE}  available={}  missing={PATH_VALUE}     ✗ starvation
 ↓
HYPOTHESIS     "write_file valuta il contenuto come espressione"  (ABDUCTION errata)
 ↓
CAPABILITY     write_file
 ↓
EXECUTION      write_file|path.txt|$(Get-Command | Where-Object …)          exit=1
 ↓
OBSERVATION    "template placeholders not filled in: $_.Source, $_.Name"
 ↓
BELIEF_UPDATE  (none — nessun fatto PATH_VALUE prodotto)
 ↓
VERIFICATION   kind=ARTIFACT_EXISTS  passed=true   ← atteso ARTIFACT_CONTENT ✗ WEAK
 ↓
OUTCOME        REFUTED → recovery … → d6 write_file|path.txt|PATH_CONTENT (placeholder) → INCOMPLETE
 ↓
LESSON_LEARNED F-DATAFLOW-01 (WRITE_BEFORE_KNOW) → learning entry
```

## Decision list

| # | phase | strategy | missing_evidence | state | cost.wasted |
|---|-------|----------|------------------|-------|-------------|
| d0 | EXECUTE | AUTHOR_ARTIFACT | {PATH_VALUE} | REFUTED | true |
| d1 | EXECUTE | AUTHOR_ARTIFACT | {PATH_VALUE} | REFUTED | true |
| d2 | DISCOVER | DISCOVER_CAPABILITY | {} | CONFIRMED | false |
| d3 | EXECUTE | AUTHOR_ARTIFACT | {PATH_VALUE} | REFUTED | true |
| d4 | EXECUTE | AUTHOR_ARTIFACT | {PATH_VALUE} | REFUTED | true |
| d5 | DISCOVER | (web_search) | — | SUPERSEDED | true |
| d6 | EXECUTE | AUTHOR_ARTIFACT (placeholder) | {PATH_VALUE} | REFUTED | true |

**Divergence point:** d0 · cause `WRONG_STRATEGY`/`PREMATURE_EXECUTION` · archetype `F-DATAFLOW-01` ·
downstream = {d1,d3,d4,d6}. Vedi [root-cause-analysis.md](root-cause-analysis.md#win-env_path-00001).

---

## Navigazione

- Grafo → [decision-graph.md](decision-graph.md)
- Belief → [belief-analysis.md](belief-analysis.md)
- Context → [context-analysis.md](context-analysis.md)
- Causa e fix → [root-cause-analysis.md](root-cause-analysis.md)

> Un `decision-report.md` per run è emesso in `validation/decision-traces/reports/<run_id>.md`.
> Questo file è il template + il caso di riferimento.
