# Planner Analysis Report

> Template generato. Owner del formato: [planner-formalism.md §5](../planner-formalism.md#5-planner-analysis-mission-7).
> `provenance`: **RECONSTRUCTED** (corpus full-safe30, 22 casi).

---

## Estrazione fasi (aggregato corpus)

| PlanPhase | Casi in cui presente | Casi in cui **attesa ma assente** |
|-----------|----------------------|-----------------------------------|
| PRECONDITION | {{n}} | — |
| DISCOVER | 22 | 0 |
| REASON (X∈facts PROVEN) | ~2 | **~17** ← il buco centrale |
| EXECUTE (write-back) | ~10 | **~5** (D2 NEVER_WRITE) |
| VERIFY (content) | ~3 | **~15** (WEAK/absent) |
| RECOVER | frequente | — |

## Difetti di piano (aggregato)

| Difetto | Conteggio | Archetipo | Componente |
|---------|-----------|-----------|------------|
| azioni **premature** (`PREMATURE_DECISION`) | 7 | F-DATAFLOW-01 | Planner+Context |
| azioni **mancanti** (`MISSING_DECISION`, fase EXECUTE) | 5 | F-DATAFLOW-02 | Planner |
| azioni **mancanti** (fase REASON) | ~17 | radice comune | Planner |
| azioni **duplicate** (rediscovery) | 8 | F-BELIEF-01 | Belief |
| azioni **impossibili** (`BLOCKED`/OCKE-filtered) | {{n}} | — | Safety/Knowledge |
| azioni **inutili** (`DEAD_DECISION`) | ~6 | — | Planner |
| azioni **mai raggiunte** (`UNREACHABLE`) | {{n}} (budget bruciato) | co-effetto F-BELIEF-01 | Belief |

## Conclusione strutturale

Il difetto dominante è a livello di **piano**, non di comando: 16/22 casi hanno l'owner-decisione
`Planner` ([decision-analysis.md §3](../../../workspace/validation/windows-lab/reports/decision-analysis.md)).
La fase mancante più frequente è `REASON` (il nodo *"il valore è NOTO/PROVEN"* tra DISCOVER ed EXECUTE):
la sua assenza genera sia `F-DATAFLOW-01` (write-before-know) sia `F-DATAFLOW-02` (never-write).

**Fix strutturale indicato** (non un caso speciale): imporre nel planner l'invariante `PLAN-1`
(dataflow-before-effect) — un `EXECUTE` che consuma `X` è mal-formato senza un `DISCOVER(X)+REASON(X
PROVEN)` a monte. Vedi [high-leverage-fixes.md](high-leverage-fixes.md#fix-3).

Per-caso → [decision-graph.md](decision-graph.md) · causa → [root-cause-analysis.md](root-cause-analysis.md).
