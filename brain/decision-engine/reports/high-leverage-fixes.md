# High-Leverage Fixes Report

> Template generato. Owner del formato: [root-cause-framework.md §3](../root-cause-framework.md#3-leverage-estimator).
> `provenance`: **RECONSTRUCTED** (corpus full-safe30). Δ stimati = frequenza-corpus dell'archetipo eliminato.
> Ordinamento = `score` deterministico (pesi versionati). Nessun numero è un'opinione.

---

## Ranking (per `score`)

| # | Fix | elimina | Δftfr | Δarr | Δraf | gen. | loc | risk | score |
|---|-----|---------|-------|------|------|------|-----|------|-------|
| 0 | **Cablare `Decision` in `record_run`** (prerequisito osservabilità) | debito TELEMETRY | — | — | — | 1.0 | S | LOW | *gate* |
| 1 | **Belief PROVEN/REFUTED sticky** (invariante #10) | F-BELIEF-01 (8) | 0.36 | 0.18 | −0.8 | 0.70 | S | LOW | **0.42** |
| 2 | **Planner dataflow-aware** (invariante PLAN-1) | F-DATAFLOW-01 (7) + F-DATAFLOW-02 (5) | 0.32 | 0.14 | −0.3 | 0.80 | M | LOW | **0.40** |
| 3 | **Context rule: write-literal / value-before-write** | F-DATAFLOW-01 (7) | 0.20 | 0.09 | −0.1 | 0.60 | S | LOW | 0.28 |
| 4 | **Gate diagnose-before-change** su Intent REPAIR | F-STRATEGY-01 (4) | 0.10 | 0.14 | −0.1 | 0.30 | M | MED | 0.19 |
| 5 | **Verify tier-upgrade** (ARTIFACT_CONTENT min per OBSERVE) | F-VERIFY-01 | 0.08 | 0.05 | 0 | 0.50 | S | LOW | 0.15 |

> `score = 0.35·Δftfr + 0.25·Δarr + 0.15·(−Δraf) + 0.15·gen − 0.06·risk − 0.04·loc` (pesi versionati,
> [root-cause-framework §3.2](../root-cause-framework.md#32-ranking-scalare-deterministico-pesi-fissi)).

---

## <a id="fix-2"></a>Dettaglio Fix 1 — Belief sticky

- **eliminates_archetype:** F-BELIEF-01 (REDISCOVERY_LOOP), 8/22 casi, ≥5 domini.
- **kind:** STATE_FIX (invariante #10) su [reasoning.py::BeliefSystem](../../../workspace/src/reasoning.py).
- **perché in cima:** spegne i loop di rediscovery che gonfiano il RAF (2.11→~1.3) e liberano budget,
  permettendo ai piani di *raggiungere* la fase EXECUTE mancante. Alta generalizzabilità, basso rischio,
  poche righe. Nota: il changelog PATCH-011 segnala 5 test falliti su `refute()/is_proven` — la firma.

## <a id="fix-3"></a>Dettaglio Fix 2 — Planner dataflow-aware (PLAN-1)

- **eliminates_archetype:** F-DATAFLOW-01 **e** F-DATAFLOW-02 (12/22 combinati).
- **kind:** INVARIANT nel planner — un `EXECUTE` con `missing_evidence≠∅` è mal-formato; un Intent con
  artefatto richiede sempre un nodo EXECUTE terminale.
- **generalizza:** su *qualsiasi* effetto che consuma un valore, non solo `write_file`.

## <a id="fix-4"></a>Dettaglio Fix 4 — Diagnose-before-change

- **eliminates_archetype:** F-STRATEGY-01 (FABRICATE_NOT_DIAGNOSE), 4 casi CICD.
- **rischio MEDIO:** alcuni casi CICD sono mal-posti (fixture non materializzate → BENCHMARK debt); il
  Δ reale va misurato dopo aver isolato quei casi.

---

## Vincoli sul ranking

1. **Prerequisito (Fix 0)** precede tutti: senza `Decision` cablato, ogni Δ sopra è `confidence=LOW`
   (provenance RECONSTRUCTED). Il framework lo forza come gate, non come opinione.
2. **Non-regressione:** nessuno dei fix rompe un caso `FIRST_TIME_FIX` della baseline
   ([success-taxonomy.md](../success-taxonomy.md)) — verificato prima dell'inserimento in roadmap.

Roadmap ordinata → [improvement-roadmap.md](improvement-roadmap.md).
