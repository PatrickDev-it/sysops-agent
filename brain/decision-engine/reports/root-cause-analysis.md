# Root Cause Analysis Report

> Template generato. Owner del formato: [root-cause-framework.md](../root-cause-framework.md).
> `provenance`: **RECONSTRUCTED** (corpus full-safe30). Questo report riempie il blocco `study{}`
> dei failure-db JSON.

---

## Sintesi corpus (22 casi)

| `DivergenceCause` (primaria) | Casi | Archetipo | Componente |
|------------------------------|------|-----------|------------|
| `PREMATURE_EXECUTION` | 7 | F-DATAFLOW-01 | Planner+Context |
| `MISSING_DISCOVERY`/`PLANNING_ERROR` | 5 | F-DATAFLOW-02 | Planner |
| `BELIEF_CORRUPTION` | 8 | F-BELIEF-01 | Belief |
| `WRONG_STRATEGY` | 4 | F-STRATEGY-01 | Supervisor/Planner |
| `EXECUTION_ERROR` | 3 | F-EXEC-01 | Execution *(fuori scope)* |
| `MODEL` | 0 | — | — (goal sempre compreso) |

> Nota: molti casi co-occorrono (D2+D3): il primary è il difetto **a monte** in ordine topologico
> (belief prima di planner-write). Vedi [reasoning-taxonomy §2](../reasoning-taxonomy.md#2-divergencecause-enum-chiuso-12).

---

## <a id="win-env_path-00001"></a>Caso: WIN-ENV_PATH-00001 (blocco `study` popolato)

```jsonc
"study": {
  "root_cause": "PREMATURE_EXECUTION",
  "divergence_point": { "decision": "d0", "timestamp": 0, "archetype": "F-DATAFLOW-01" },
  "secondary_causes": ["WRONG_STRATEGY", "MISSING_VERIFICATION"],
  "contributing": ["DECISIVE context missing: dataflow literal-write rule"],
  "components": ["PLANNER", "CONTEXT", "VERIFICATION"],
  "confidence": 0.75,          // limitata da provenance RECONSTRUCTED
  "minimal_fix": { "target_component": "CONTEXT", "kind": "CONTEXT_RULE",
                   "description": "iniettare la regola: contenuto di write è letterale, valore prima come fatto" },
  "architectural_fix": { "target_component": "PLANNER", "kind": "INVARIANT",
                   "description": "PLAN-1: vietare EXECUTE con missing_evidence != {}",
                   "eliminates_archetype": "F-DATAFLOW-01" },
  "estimated_ftfr_gain": 0.32,
  "estimated_arr_gain": 0.14,
  "estimated_complexity": "M",
  "estimated_risk": "LOW",
  "candidate_solutions": ["F-DATAFLOW-01 architectural fix (PLAN-1)", "F-VERIFY-01 tier upgrade"]
}
```

Il **primo** errore è d0 (write-before-know), non il placeholder finale d6. Correggere d6 (il sintomo)
non generalizza; correggere il vuoto strutturale (PLAN-1) elimina i 7 casi della classe.

---

## Template per-caso

```
### Caso: {{case_id}}
- primary_cause: {{DivergenceCause}}   @ decision {{id}} (timestamp {{n}})
- archetype: {{FailureArchetype.id}}   downstream: {{[decision_id]}}
- secondary: {{[DivergenceCause]}}
- components: {{[ArchitecturalComponent]}}
- confidence: {{float}} (provenance {{profile}})
- minimal_fix / architectural_fix: {{FixProposal}}
- Δftfr {{f}} · Δarr {{f}} · complexity {{S|M|L}} · risk {{LOW|MED|HIGH}}
```

Debito per componente → [architectural-debt.md](architectural-debt.md).
Fix ordinati → [high-leverage-fixes.md](high-leverage-fixes.md).
