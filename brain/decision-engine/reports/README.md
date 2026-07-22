# Reports — output generati del Decision Engine

> Questi 9 file sono **template deterministici**, non prosa. Il generatore descritto in
> [improvement-loop.md §Report generation](../improvement-loop.md#4-report-generation) legge le
> `DecisionTrace` analizzate e riempie le sezioni tipizzate (placeholder `{{…}}`).
> Owner del contenuto di ciascuno → tabella in [../README.md](../README.md#report-gli-output).

## Stato attuale (onestà, non fabbricazione)

Ogni report è pre-popolato con il corpus **`full-safe30`** (22 casi) come **worked example**, marcato
`provenance = RECONSTRUCTED` a livello di documento: i valori derivano dalla ricostruzione parziale del
[decision-analysis.md](../../../workspace/validation/windows-lab/reports/decision-analysis.md) e dal
[failure-db/](../../../workspace/validation/windows-lab/failure-db/), **non** da una telemetria di
decisioni (che non è ancora cablata — vedi il Prerequisito nella roadmap). Servono a due scopi:

1. **validare il framework**: deve riprodurre l'analisi umana esistente;
2. **essere il formato di riferimento** che il generatore emetterà una volta cablato `Decision`.

I campi non derivabili dalla ricostruzione riportano `— (pending Decision instrumentation)`, mai un
valore inventato.

## Indice

| Report | Scopo |
|--------|-------|
| [decision-report.md](decision-report.md) | Cognitive Trace navigabile per run |
| [decision-graph.md](decision-graph.md) | Actual vs Expected DAG + GraphDiff |
| [planner-analysis.md](planner-analysis.md) | fasi + azioni mancanti/premature/inutili |
| [belief-analysis.md](belief-analysis.md) | transizioni belief + invarianti violati |
| [context-analysis.md](context-analysis.md) | utilizzo context + elementi DECISIVE |
| [root-cause-analysis.md](root-cause-analysis.md) | divergence + root cause per caso |
| [architectural-debt.md](architectural-debt.md) | istogramma difetti per componente |
| [high-leverage-fixes.md](high-leverage-fixes.md) | fix ordinati per leva |
| [improvement-roadmap.md](improvement-roadmap.md) | roadmap ordinata + non-regressione |
