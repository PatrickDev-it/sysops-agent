# Decision Graph Report

> Template generato. Owner del formato: [planner-formalism.md](../planner-formalism.md).
> `provenance`: **RECONSTRUCTED** (worked example: WIN-ENV_PATH-00001).

---

## Expected DAG (derivato da `case.expected.success_criteria`)

```
[E0 DISCOVER]  read $env:PATH -split ';'
      │ DATAFLOW (PATH_VALUE)
      ▼
[E1 REASON]    PATH_VALUE ∈ facts, state=PROVEN
      │ PRECONDITION
      ▼
[E2 EXECUTE]   write_file(path.txt, <PATH_VALUE verbatim>)
      │ ORDER
      ▼
[E3 VERIFY]    ARTIFACT_CONTENT: path.txt contains PATH_VALUE
```

## Actual DAG (da telemetry.history)

```
[d0 EXECUTE] write $(Get-Command…)  missing={PATH_VALUE}   REFUTED ↯
[d1 EXECUTE] write … | Out-File      missing={PATH_VALUE}   REFUTED
[d2 DISCOVER] $env:PATH              CONFIRMED          ─┐ (mai consumato da un EXECUTE valido)
[d3 EXECUTE] Write-Content $(…)      missing={PATH_VALUE}   REFUTED
[d4 EXECUTE] write $( $env:PATH… )   missing={PATH_VALUE}   REFUTED
[d5 DISCOVER] web_search             SUPERSEDED
[d6 EXECUTE] write path.txt PATH_CONTENT  missing={PATH_VALUE}  REFUTED → INCOMPLETE
   (no edge DATAFLOW d2→d*: il fatto scoperto non è mai diventato il contenuto scritto)
is_dag = true (nessun ciclo qui; i cicli compaiono negli archetipi F-BELIEF-01)
```

## GraphDiff (Expected vs Actual)

| `GraphDefect` | Nodi | Note |
|---------------|------|------|
| `MISSING_DECISION` | E1 (REASON PATH_VALUE∈facts) | il valore non è mai stato promosso a fatto usato |
| `PREMATURE_DECISION` | d0, d1, d3, d4, d6 | EXECUTE con `missing_evidence={PATH_VALUE}` |
| `WRONG_ORDER` | (E0,E2) invertito: EXECUTE prima di DISCOVER effettivo | dataflow rotto |
| `DEAD_DECISION` | d2, d5 | discovery riuscita ma output mai consumato; web_search inutile |
| `WRONG_ORDER` residuo | — | — |
| `CIRCULAR_DECISION` | — (nessuno in questo caso) | — |

**First topological defect:** `PREMATURE_DECISION @ d0` → input del Divergence Engine.

---

## Legenda archetipi grafici (corpus)

| Archetipo | Firma nel DAG |
|-----------|---------------|
| `F-DATAFLOW-01` WRITE_BEFORE_KNOW | EXECUTE con `missing_evidence≠∅` prima del DISCOVER che lo alimenta |
| `F-DATAFLOW-02` NEVER_WRITE | nessun nodo EXECUTE che produce l'artefatto richiesto |
| `F-BELIEF-01` REDISCOVERY_LOOP | ciclo `DISCOVER(X)…DISCOVER(X)` (belief non-sticky) → `is_dag=false` |

Aggregato per il corpus → [planner-analysis.md](planner-analysis.md). Cause → [root-cause-analysis.md](root-cause-analysis.md).
