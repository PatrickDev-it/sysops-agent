# Failure Taxonomy — archetipi di fallimento & clustering

> **Owner** di `FailureArchetype` (l'insieme chiuso dei pattern di fallimento riconoscibili) e del
> metodo di **clustering** dei fallimenti (mission §5, §12). Un archetipo è una firma stabile e
> generalizzabile — mai un tool o un OS. Consuma [reasoning-taxonomy.md](reasoning-taxonomy.md)
> (`DivergenceCause`) e [root-cause-framework.md](root-cause-framework.md) (`ArchitecturalComponent`).

---

## 1. Cos'è un archetipo

> Un **FailureArchetype** è una firma `(DivergenceCause × ArchitecturalComponent × invariante violato)`
> che ricorre nel corpus, con un ID stabile e una descrizione framework-neutral.

Gli archetipi **non** si inventano: emergono dal clustering (§4) e vengono promossi a membri dell'enum
quando ricorrono. L'ID è stabile tra release (DE-5) così una regressione è confrontabile ("F-DATAFLOW-01
è passato da 7 a 2 casi").

Schema di ID: `F-<AREA>-<NN>` dove AREA ∈ {DATAFLOW, BELIEF, STRATEGY, VERIFY, CONTEXT, EXEC, OBS}.

---

## 2. Archetipi seed (dal corpus full-safe30)

Derivati **deterministicamente** dalle 5 classi di divergenza del
[decision-analysis.md](../../workspace/validation/windows-lab/reports/decision-analysis.md), promossi
ad archetipi tipizzati:

| ID | Nome | DivergenceCause | Componente | Invariante violato | Firma rilevabile | Casi corpus |
|----|------|-----------------|------------|---------------------|------------------|-------------|
| `F-DATAFLOW-01` | WRITE_BEFORE_KNOW | `PREMATURE_EXECUTION` | Planner+Context | PLAN-1 dataflow-before-effect | `EXECUTE(write X)` con `missing_evidence={X}` | 7 (D1) |
| `F-DATAFLOW-02` | NEVER_WRITE | `MISSING_DISCOVERY`/`PLANNING_ERROR` | Planner | target-state non nel piano | Intent con artefatto, **nessun** `EXECUTE` che lo produce | 5 (D2) |
| `F-BELIEF-01` | REDISCOVERY_LOOP | `BELIEF_CORRUPTION` | Belief | #10 (PROVEN sticky) | ciclo DAG / `NON_STICKY_PROVEN` ≥1 | 8 (D3) |
| `F-STRATEGY-01` | FABRICATE_NOT_DIAGNOSE | `WRONG_STRATEGY` | Supervisor/Planner | VER-1 + diagnose-before-change | `AUTHOR_ARTIFACT` su Intent `REPAIR` | 4 (D4) |
| `F-EXEC-01` | EXECUTION_LOSS | `EXECUTION_ERROR` | Execution | — (decisione sana) | Decision non-difettosa, effetto perso | 3 (D5) |
| `F-VERIFY-01` | WEAK_COMPLETION | `MISSING_VERIFICATION` | Verification | #9 + wrong-completion | tier-1 pass, tier-3/content assente | co-occorrente |

> **`F-EXEC-01` è marcato fuori-scope** per l'analisi "decisione sbagliata": la decisione era corretta,
> il difetto è a valle (cattura output/permessi). Il framework lo isola esplicitamente così la roadmap
> non gli attribuisce leva cognitiva — coerente col corpus §5.

---

## 3. Record di un archetipo

```jsonc
FailureArchetype = {
  "id": "F-DATAFLOW-01",
  "name": "WRITE_BEFORE_KNOW",
  "divergence_cause": "PREMATURE_EXECUTION",
  "component": "PLANNER",                      // primario; secondari in `also`
  "also": ["CONTEXT"],
  "invariant": "PLAN-1",
  "detector": "exists EXECUTE D with produces_artifact(D) and missing_evidence(D) != {}",
  "generalizes_over": "qualsiasi effetto che consuma un valore non ancora fatto",  // non solo write_file
  "corpus_frequency": 7,
  "exemplars": ["WIN-ENV_PATH-00001", "WIN-USERS-00001", "WIN-SERVICES-00003"]
}
```

`detector` è un predicato eseguibile su `DecisionTrace`, non prosa: due analisti (o due release)
producono la stessa classificazione (DE-4). `generalizes_over` è il campo che impedisce la
degenerazione in caso speciale: obbliga a descrivere la *categoria*, non l'istanza.

---

## 4. Clustering (mission §12) — deterministico

Il clustering **scopre** archetipi nuovi e raggruppa fallimenti simili senza etichette a priori. La
distanza tra due Decision difettose è definita su feature tipizzate, non su testo:

```
feature(D) = ( divergence_cause(D),
               component(D),
               phase(D),
               intent(D),
               sorted(missing_evidence_kinds(D)),
               sorted(belief_defects(D)) )

cluster(defective_decisions):
    # raggruppamento esatto per feature-tuple (deterministico, no k-means, no seed casuale)
    groups = groupby(defective_decisions, key=feature)
    for g in groups:
        if g matches an existing FailureArchetype.detector: assign(g, archetype)
        else: propose_new_archetype(g)      # candidato, va ratificato per entrare nell'enum
    return groups
```

Il clustering per **feature-tuple esatta** è deterministico e riproducibile — nessun algoritmo
stocastico (DE-1). Cluster che non matchano un archetipo esistente diventano **proposte** di nuovo
archetipo (con frequenza e exemplar), portate in [improvement-loop.md](improvement-loop.md). Lo stesso
metodo clusterizza, oltre ai fallimenti: decisioni, recovery e strategie (mission §12) — cambia solo la
`feature()`.

---

## 5. Pattern di secondo livello (mission §12)

Sul corpus clusterizzato, il framework etichetta pattern *tra* archetipi. Enum `PatternClass`
(owner: [improvement-loop.md](improvement-loop.md#pattern-discovery)) applicato qui alle failure:

| PatternClass | Nella failure taxonomy |
|--------------|------------------------|
| `ROOT_PATTERN` | l'archetipo che, se eliminato, ne spegne altri (es. `F-BELIEF-01` alimenta i loop che causano `F-DATAFLOW-02`) |
| `ANTI_PATTERN` | una strategia ricorrente e sistematicamente sbagliata (`F-STRATEGY-01`) |
| `HIDDEN_PATTERN` | co-occorrenza non ovvia (D2+D3 nello stesso caso: never-write *perché* budget bruciato in rediscovery) |
| `REPEATED_PATTERN` | stesso archetipo su domini diversi (F-DATAFLOW-01 su env_path, users, services → è di dominio-indipendente) |
| `EMERGING_PATTERN` | cluster nuovo con frequenza in crescita tra release |

La "causa profonda in una frase" del corpus (*il supervisor non rappresenta il task come dataflow con
stato*) è, in questo linguaggio, il `ROOT_PATTERN`: `F-DATAFLOW-01`, `F-DATAFLOW-02` e `F-BELIEF-01`
sono tre sintomi dello stesso vuoto — e il framework lo mostra come un archetipo-radice con tre
archetipi-figli, non come tre bug indipendenti.

---

## 6. Invarianti

- **FAIL-1**: ogni `FailureArchetype` ha un `detector` eseguibile e un `generalizes_over` esplicito.
- **FAIL-2**: nessun archetipo nomina un tool/OS. La firma è su feature cognitive.
- **FAIL-3**: `F-EXEC-01` è escluso dai conteggi di "decisione sbagliata" ma tracciato a parte (onestà:
  non si nasconde, non si conta due volte).
