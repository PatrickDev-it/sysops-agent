# Architectural Debt Report

> Template generato. Owner del formato: [root-cause-framework.md §4](../root-cause-framework.md#4-architectural-classifier).
> `provenance`: **RECONSTRUCTED** (corpus full-safe30). Un difetto → un componente (owner della decisione sbagliata).

---

## Istogramma difetti per `ArchitecturalComponent`

Conteggio dell'owner della **decisione** sbagliata (co-occorrenze contate sull'owner primario a monte):

```
PLANNER        ████████████████  16   ← dominante (order/decomp/write-back)
BELIEF          ████████           8   ← rediscovery / non-sticky (spesso con Planner)
CONTEXT         ███████            7   ← regola write-literal assente (concausa dei D1)
SUPERVISOR      ████               4   ← classificazione task (D4 fabricate)
EXECUTION       ███                3   ← fuori scope (decisione sana, effetto perso)
VERIFICATION    (co-occ.)          —   ← WEAK_COMPLETION, co-occorrente ai D1
TELEMETRY       ■                  1*  ← Prerequisito: Decision non cablato (blocca tutto il resto)
KNOWLEDGE       ·                  0
CAPABILITY      ·                  0
OBSERVATION     ·                  0
SAFETY          ·                  0
PROMPT          ·                  0
MODEL           ·                  0   ← goal sempre compreso
INFRASTRUCTURE  ·                  0
BENCHMARK       ▪                  ~3  ← fixture CICD non materializzate (non colpa dell'agente)
EXTERNAL        ·                  0
```
`*` TELEMETRY conta 1 come **debito meta**: l'assenza di tracciamento decisioni degrada la confidence di
ogni altra riga a `RECONSTRUCTED`. È il debito da ripagare per primo (roadmap passo 0).

---

## Lettura

- **Il debito è concentrato nel piano e nei belief**, non nel modello né nell'esecuzione. Confermato:
  `MODEL=0` (nessun fallimento attribuibile alla capacità del modello — 21/22 goal compresi).
- **`BENCHMARK ~3`** isola i casi mal-posti (fixture non materializzate): non inquinano il debito
  dell'agente. Onestà: non si contano come difetti cognitivi.
- **`EXECUTION=3` è tracciato ma fuori scope** per "decisione sbagliata" (F-EXEC-01): la decisione era
  corretta; è debito di cattura-output, non cognitivo.

## Debito → leva

| Componente | Debito | Fix a più alta leva | Ref |
|------------|--------|---------------------|-----|
| TELEMETRY | meta | cablare `Decision` in `record_run` | [roadmap #0](improvement-roadmap.md) |
| BELIEF | 8 | `is_proven`/`refute` sticky (#10) | [fix-2](high-leverage-fixes.md#fix-2) |
| PLANNER | 16 | invariante PLAN-1 dataflow-before-effect | [fix-3](high-leverage-fixes.md#fix-3) |
| SUPERVISOR | 4 | gate diagnose-before-change | [fix-4](high-leverage-fixes.md#fix-4) |

Trend tra release (DE-5): questo istogramma va confrontato benchmark-su-benchmark; una riga che cala è
debito ripagato, una che cresce è una regressione architetturale.
