# Improvement Loop — Learning DB · Pattern Discovery · Proposals · Report

> **Owner** del **Learning Database** (mission §13), della **Pattern Discovery** (§12), delle
> **Automatic Improvement Proposals** (§14), della **generazione dei report** (§15) e della chiusura del
> loop. È lo stage terminale della pipeline: trasforma le `DecisionTrace` analizzate in conoscenza
> persistente e in una roadmap ordinata.

---

## 1. Learning Database (mission §13)

> Mai salvare solo `errore → fix`. Salvare il **processo decisionale completo**.

Storage: `validation/decision-traces/learning.db` (SQLite, accanto all'`episodic.db` di
[memory.py](../../workspace/src/memory.py) — stesso pattern, non un nuovo runtime). Formato di ogni
entry, tipizzato:

```jsonc
LearningEntry = {
  "id": str,                          // hash stabile di (case_id, divergence.decision_id)
  "schema_version": "decision-engine/1.0",

  "decision": Decision,               // la Decision divergente, per intero (decision-model)
  "context": ContextAnalysis,         // cosa aveva/mancava (context-selection-model)
  "trace_excerpt": TraceStage[],      // gli stadi dal GOAL al divergence point
  "outcome": { "verdict": str, "success_class": SuccessClass | null },

  "failure": FailureArchetype.id | null,
  "reason": RootCause,                // primary/secondary/contributing (root-cause-framework)
  "fix": { "minimal": FixProposal, "architectural": FixProposal },
  "impact": LeverageEstimate,         // Δ metriche, ordinabile
  "confidence": float,
  "generalizability": float,

  "provenance_profile": { Provenance: int }   // quanti campi OBSERVED vs RECONSTRUCTED — onestà
}
```

Invariante **LEARN-1**: una `LearningEntry` senza `reason` (RootCause) è invalida. Non si registra un
fallimento senza la sua spiegazione causale completa; non si registra un fix senza il processo che lo
motiva. Questo è ciò che distingue il DB da un log di errori.

Le `LearningEntry` di successo (`FIRST_TIME_FIX`) sono registrate con `failure=null`: il DB apprende
anche cosa proteggere ([success-taxonomy.md](success-taxonomy.md)).

### Consumo a runtime (chiusura del loop, opzionale e non-vincolante)

Le entry ad alta `confidence`+`generalizability` possono alimentare il context del supervisor via
l'`AttentionManager` esistente (come già fanno le regressioni di `memory.get_regressions`). Il loop si
chiude *senza* aggiungere capability: le lezioni entrano come **regole di context/invarianti**, non come
casi speciali. Questa integrazione è una *proposta* del framework, non parte di questa iterazione (che
resta pura infrastruttura di comprensione).

---

## 2. Pattern Discovery (mission §12)

Owner dell'enum `PatternClass`, applicato all'intero corpus di `LearningEntry`. Riusa il clustering
deterministico di [failure-taxonomy.md §4](failure-taxonomy.md#4-clustering-mission-12) con `feature()`
diverse per dimensione:

| Dimensione | `feature()` | Cosa scopre |
|------------|-------------|-------------|
| Fallimenti | (cause, component, archetype) | archetipi + `ROOT/ANTI/HIDDEN_PATTERN` |
| Decisioni | (intent, strategy, phase) | strategie ricorrenti (giuste e sbagliate) |
| Recovery | (error_class, recovery_class, esito) | recovery efficaci vs sprecate |
| Strategie | (intent, strategy, success_class) | quali strategie *vincono* per Intent |

`PatternClass` (enum chiuso): `ROOT_PATTERN`, `ANTI_PATTERN`, `HIDDEN_PATTERN`, `REPEATED_PATTERN`,
`EMERGING_PATTERN` (definizioni in [failure-taxonomy.md §5](failure-taxonomy.md#5-pattern-di-secondo-livello-mission-12)).
La scoperta è deterministica: raggruppamento esatto per feature-tuple + soglia di frequenza esplicita
(nessun clustering stocastico).

---

## 3. Automatic Improvement Proposals (mission §14)

Alla fine di ogni benchmark il framework genera **automaticamente** le Top-10 richieste. Ogni lista è un
`sort` deterministico sulle `LearningEntry`/`LeverageEstimate` aggregate:

| Top-10 | Chiave di ordinamento | Fonte |
|--------|-----------------------|-------|
| Problemi architetturali | conteggio difetti per `ArchitecturalComponent` | classifier |
| Problemi di reasoning | frequenza per `DivergenceCause` | reasoning-taxonomy |
| Problemi planner | frequenza `GraphDefect` di fase Planner | planner-formalism |
| Problemi belief | frequenza `BeliefDefect` | belief-transition-model |
| Problemi context | frequenza `DECISIVE`/`MISSING` | context-selection-model |
| Capability mancanti | `WRONG_CAPABILITY` con belief REFUTED persistente | reasoning-taxonomy |
| Fix miglior impatto/rischio | `score` ÷ `risk_penalty` | leverage estimator |
| Fix che alzano di più il FTFR | `delta_ftfr` desc | leverage estimator |

Ogni voce è un `LeverageEstimate` con il suo `FixProposal`, `delta_*`, `generalizability`, `risk` — mai
una frase vaga. "Top 10" significa i primi 10 per la chiave, con i numeri accanto.

---

## 4. Report generation (mission §15)

Owner del contratto di generazione dei 9 report in [reports/](reports/). Ogni report è **generato**
(non scritto a mano) da un aggregatore che legge le `DecisionTrace` con `analysis≠null`. I file in
`reports/` sono **template versionati** con sezioni tipizzate e placeholder `{{…}}`; il generatore li
riempie. Contratto:

```
generate_reports(traces, out_dir):
    corpus = [analyze(t) for t in traces]          # pipeline stage 3-6, deterministica
    render("decision-report.md",    per_run(corpus))
    render("decision-graph.md",     graphs(corpus))
    render("planner-analysis.md",   planner(corpus))
    render("belief-analysis.md",    beliefs(corpus))
    render("context-analysis.md",   context(corpus))
    render("root-cause-analysis.md",root_causes(corpus))
    render("architectural-debt.md", component_hist(corpus))
    render("high-leverage-fixes.md",ranked_leverage(corpus))
    render("improvement-roadmap.md",roadmap(corpus))
```

| Report | Contenuto | Owner del contenuto |
|--------|-----------|---------------------|
| [decision-report.md](reports/decision-report.md) | una CognitiveTrace navigabile per run | decision-lifecycle |
| [decision-graph.md](reports/decision-graph.md) | Actual vs Expected DAG + GraphDiff | planner-formalism |
| [planner-analysis.md](reports/planner-analysis.md) | fasi, azioni mancanti/premature/inutili | planner-formalism |
| [belief-analysis.md](reports/belief-analysis.md) | transizioni, invarianti violati, RAF-decisionale | belief-transition-model |
| [context-analysis.md](reports/context-analysis.md) | utilizzo context, `DECISIVE` ricorrenti | context-selection-model |
| [root-cause-analysis.md](reports/root-cause-analysis.md) | divergence + root cause per caso | root-cause-framework |
| [architectural-debt.md](reports/architectural-debt.md) | istogramma difetti per componente | root-cause-framework |
| [high-leverage-fixes.md](reports/high-leverage-fixes.md) | fix ordinati per leva | root-cause-framework |
| [improvement-roadmap.md](reports/improvement-roadmap.md) | roadmap ordinata + non-regressione | improvement-loop |

Invariante **REPORT-1**: ogni report è completamente **navigabile e referenziato** (mission §15): ogni
caso linka al suo `decision-report`, ogni difetto al suo owner-doc, ogni fix al suo `LeverageEstimate`.
Nessun numero senza la sua derivazione linkata.

---

## 5. Improvement Roadmap — la chiusura

La `improvement-roadmap` è l'output finale della mission: una lista **ordinata** di interventi, ognuno
con Δ-metriche previste, rischio, e archetipo eliminato. Ordinamento = ranking del Leverage Estimator,
con due vincoli hard sovrapposti:

1. **Prerequisiti prima**: un fix la cui evidenza è `RECONSTRUCTED`/`PROXY` è preceduto dal suo
   prerequisito di osservabilità. Nel corpus questo mette **"cablare `Decision` in telemetry"** come
   passo 0 della roadmap — automaticamente, perché tutti i RootCause partono con `confidence` limitata
   dalla provenance ([decision-lifecycle §4](decision-lifecycle.md#4-provenance)).
2. **Non-regressione**: nessun fix che rompe un caso `FIRST_TIME_FIX` della baseline
   ([success-taxonomy.md](success-taxonomy.md)) è ammesso sopra la linea, indipendentemente dallo score.

La roadmap che ne risulta per il corpus attuale coincide con quella derivata a mano nel
[decision-analysis.md §6](../../workspace/validation/windows-lab/reports/decision-analysis.md)
(1. osservabilità → 2. belief sticky → 3. planner dataflow-aware → 4. diagnose-before-change), ma qui è
**prodotta dal framework**, quantificata, e ri-generabile a ogni benchmark. Questa coincidenza è il test
di validazione del framework stesso: deve riprodurre l'analisi umana esistente prima di poter guidare
quelle future.

---

## 6. Come la prossima iterazione usa tutto questo

1. Esegue il benchmark → telemetria (con `Decision` cablato).
2. `build_trace` → `analyze` → `generate_reports` (deterministico, nessun modello).
3. Legge `high-leverage-fixes.md` e `improvement-roadmap.md`.
4. Sceglie il fix in cima (max ΔFTFR, min rischio, generalizzabile, non-regressivo).
5. Lo implementa come **invariante / regola di context / schema** — mai come caso speciale.
6. Ri-esegue il benchmark → confronta i report tra release (DE-5) → misura il ΔFTFR reale vs previsto.
7. La differenza previsto/reale calibra i pesi del Leverage Estimator (§3.2) per l'iterazione dopo.

Ogni modifica futura diventa così una **decisione supportata da evidenza quantitativa**, non da
intuizione — l'obiettivo dichiarato della mission.
