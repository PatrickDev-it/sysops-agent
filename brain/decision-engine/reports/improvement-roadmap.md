# Improvement Roadmap

> Template generato. Owner del formato: [improvement-loop.md §5](../improvement-loop.md#5-improvement-roadmap-la-chiusura).
> `provenance`: **RECONSTRUCTED** (corpus full-safe30). Ordine = Leverage ranking + vincoli hard
> (prerequisiti prima, non-regressione). Ogni voce è una **decisione supportata da evidenza**, non un'intuizione.

---

## Ordine di esecuzione

### Passo 0 — Osservabilità (prerequisito, gate)
**Cablare `Decision` in [telemetry.py::record_run](../../../workspace/src/telemetry.py)**
(plan + rationale + belief-delta per step, come da
[telemetry_schema.py §INTEGRATION](../../../workspace/benchmarks/telemetry_schema.py)).
- Perché primo: finché `decisions=[]`, ogni causa è `RECONSTRUCTED` e ogni Δ ha `confidence=LOW`. È il
  passo che trasforma l'intero framework da inferenza a misura.
- Δ: nessuno diretto sul FTFR; **sblocca** la fiducia su tutti i passi seguenti.
- rischio LOW · loc S · componente TELEMETRY.

### Passo 1 — Belief sticky (invariante #10)
`is_proven`/`refute` sticky in [reasoning.py::BeliefSystem](../../../workspace/src/reasoning.py).
- elimina **F-BELIEF-01** (8 casi) · Δftfr ≈ 0.36 · ΔRAF 2.11→~1.3 · rischio LOW.
- effetto collaterale positivo: libera budget → i piani raggiungono la fase EXECUTE mancante.

### Passo 2 — Planner dataflow-aware (invariante PLAN-1)
Il piano di *"metti X in file"* deve contenere, in quest'ordine,
`DISCOVER(X) → X∈facts PROVEN → EXECUTE(write X) → VERIFY(content)`.
- elimina **F-DATAFLOW-01 + F-DATAFLOW-02** (12 casi) · Δftfr ≈ 0.32 · generalizzabile (qualsiasi
  effetto che consuma un valore) · rischio LOW.

### Passo 3 — Gate diagnose-before-change
Su Intent `REPAIR`: isolare il fattore divergente prima di correggere.
- elimina **F-STRATEGY-01** (4 casi) · rischio MED (isolare prima i casi BENCHMARK mal-posti).

### Fuori scope di questa iterazione
- **F-EXEC-01 (EXECUTION_LOSS, 3 casi):** la decisione era corretta; è territorio executor
  (cattura/redirect/permessi), non cognitivo. Tracciato in [architectural-debt.md](architectural-debt.md),
  escluso dai fix cognitivi.

---

## Contratto di non-regressione

La baseline di casi `FIRST_TIME_FIX`/`MINIMAL_PATH`/`CORRECT_REFUSAL`
([success-taxonomy.md](../success-taxonomy.md)) è il contratto: ogni passo va ri-misurato contro di essa.
Un fix che rompe un caso della baseline è respinto anche se alza l'ARR altrove.

## Loop di calibrazione

Dopo ogni passo: ri-benchmark → `generate_reports` → confronto Δ **previsto vs reale** → i pesi del
Leverage Estimator ([root-cause-framework §3.2](../root-cause-framework.md#32-ranking-scalare-deterministico-pesi-fissi))
si ricalibrano sulla differenza. Il framework impara a stimare la leva sempre meglio.

---

## Validazione del framework

Questa roadmap **coincide** con quella derivata a mano in
[decision-analysis.md §6](../../../workspace/validation/windows-lab/reports/decision-analysis.md)
(osservabilità → belief sticky → planner dataflow → diagnose-before-change). La coincidenza è il **test
di accettazione**: il Decision Engine riproduce l'analisi umana esistente prima di essere autorizzato a
guidare quelle future. Da qui in avanti, ogni benchmark la ri-genera automaticamente e la aggiorna con i
numeri reali.
