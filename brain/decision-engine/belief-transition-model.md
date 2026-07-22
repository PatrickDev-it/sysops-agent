# Belief Transition Model — analisi dei belief per Decision

> **Owner** di `BeliefTransition` e `BeliefDefect`, e del contratto di analisi belief per Decision
> (mission §6). Mappa 1:1 sul runtime [reasoning.py::BeliefSystem](../../workspace/src/reasoning.py):
> non ridefinisce i belief, ne modella le **transizioni** ai fini diagnostici. Stati di belief
> (`UNKNOWN/POSSIBLE/LIKELY/PROVEN/REFUTED`) sono di proprietà di `reasoning.py`.

---

## 1. Cosa registra per ogni Decision

Per ogni `Decision` il framework registra il **belief-delta** (campi 13–16 di
[decision-model.md](decision-model.md)): letti, creati, aggiornati, invalidati. Da questi deriva la
lista tipizzata di transizioni e ne verifica gli invarianti.

```jsonc
BeliefAnalysis = {                 // per Decision, aggregato per run
  "read":        BeliefRef[],
  "transitions": BeliefTransition[],
  "invariants_violated": BeliefDefect[],
  "provenance_gaps": BeliefRef[]   // belief usati ma senza evidenza tracciata
}
```

---

## 2. `BeliefTransition` (enum chiuso)

Ogni cambiamento di un belief tra lo snapshot pre- e post-Decision è una di queste transizioni.
Le colonne "score" riflettono le soglie di `BeliefState.from_score` in `reasoning.py`.

| `BeliefTransition` | Da → A | Trigger runtime | Legittima? |
|--------------------|--------|-----------------|------------|
| `ASSERT` | UNKNOWN → POSSIBLE/LIKELY | `assert_belief(score<0.8)` | ✅ |
| `PROVE` | * → PROVEN | `assert_belief(score≥0.8)` / locate / version | ✅ |
| `STRENGTHEN` | POSSIBLE → LIKELY → (PROVEN) | evidenza concorde | ✅ |
| `WEAKEN` | PROVEN/LIKELY → LIKELY/POSSIBLE | evidenza discorde (0.20≤s<0.80) | ⚠️ bloccata se PROVEN sticky |
| `REFUTE` | * → REFUTED | `refute()` non-PROVEN | ✅ |
| `STICKY_BLOCK` | PROVEN ↛ (refute rifiutato) | `refute()` su PROVEN | ✅ (invariante #10) |
| `REFUTE_OVERRIDE` | REFUTED → PROVEN | `assert_belief(score=1.0)` post-install | ✅ |
| `INVALIDATE` | belief → azione bloccata | DeductionEngine `invalidates[]` | ✅ |
| `REDISCOVER` | PROVEN/LIKELY → (ri-DISCOVER dello stesso) | discovery ripetuta di X già noto | ❌ anti-pattern |
| `SILENT_DROP` | belief presente → assente senza refute | perdita di stato | ❌ corruzione |

`REDISCOVER` e `SILENT_DROP` sono le uniche transizioni **illegittime**: sono la firma della
`BELIEF_CORRUPTION` ([reasoning-taxonomy.md](reasoning-taxonomy.md)) e del `REDISCOVERY_LOOP` (D3).

---

## 3. `BeliefDefect` (enum chiuso) — invarianti violati

Owner della lista degli invarianti belief *osservabili in analisi*. Ognuno cita l'invariante di sistema
canonico (set completo in [AGENTS.md § Invarianti core](../../AGENTS.md#invarianti-core)).

| `BeliefDefect` | Invariante violato | Rilevazione deterministica |
|----------------|--------------------|----------------------------|
| `NON_STICKY_PROVEN` | #10 (solo PROVEN guidano; devono restare) | esiste `REDISCOVER` di un belief che era PROVEN |
| `PREMATURE_REFUTE` | #10 (REFUTED blocca i retry) | `REFUTE` su un belief che diventa poi PROVEN nello stesso run |
| `ORPHAN_BELIEF` | provenienza | belief con `evidence=[]` che guida una Decision |
| `PHANTOM_DRIVE` | "solo PROVEN guidano l'esecuzione" | Decision `EXECUTE` guidata da belief non-PROVEN |
| `STALE_BELIEF` | freschezza | belief `read` non aggiornato dopo un'osservazione che lo contraddice |
| `CONTRADICTION` | coerenza | due belief PROVEN mutuamente esclusivi coesistono |

### Rilevazione di `NON_STICKY_PROVEN` (la firma di D3/RAF)

```
detect_non_sticky(trace):
    proven_at = {}                       # proposition → primo timestamp in cui è PROVEN
    defects = []
    for D in trace.decisions:
        for t in D.beliefs_updated + D.beliefs_created:
            if t.state == PROVEN: proven_at.setdefault(t.proposition, D.timestamp)
        for r in rediscovers(D):         # DISCOVER di prop già in proven_at
            if r.proposition in proven_at and r.timestamp > proven_at[r.proposition]:
                defects.append(BeliefDefect.NON_STICKY_PROVEN @ D)
    return defects
```

Questo produce **la misura decisionale del RAF**: ogni `NON_STICKY_PROVEN` è una discovery bruciata che
il piano ripete. Il conteggio per run alimenta [reports/belief-analysis.md](reports/belief-analysis.md)
e la stima di `ΔRAF` nel [Leverage Estimator](root-cause-framework.md#3-leverage-estimator).

---

## 4. Spiegazione obbligatoria di ogni violazione

Invariante **BELIEF-1** (mission §6: *"Ogni violazione deve essere spiegata"*): ogni `BeliefDefect`
emesso porta un record di spiegazione, non solo un'etichetta:

```jsonc
BeliefDefectExplanation = {
  "defect": BeliefDefect,
  "belief": "get-nettcpconnection:exists",
  "at_decision": decision_id,
  "expected_transition": "STICKY_BLOCK",     // cosa sarebbe dovuto succedere
  "actual_transition":   "REDISCOVER",       // cosa è successo
  "owner_component": "BELIEF",               // ArchitecturalComponent (root-cause-framework)
  "evidence": ["3× DISCOVER 'Get-NetTCPConnection is available' @ steps 1,3,5"]
}
```

`expected_transition` vs `actual_transition` rende la spiegazione **falsificabile**: chi legge può
verificare la transizione attesa contro `reasoning.py` senza fidarsi di una narrazione.

---

## 5. Confidence, provenance, owner

Per ogni belief `read`/mutato la BeliefAnalysis riporta i tre campi richiesti dalla mission §6:

- **confidence**: lo `score` del belief (0–1), da `Belief.score`.
- **provenance**: la lista `Belief.evidence` (ultimi 8 elementi, come in `reasoning.py`).
- **owner**: quale layer del `ReasoningContext` ha prodotto il belief
  (`InferenceEngine` da successo/fallimento, `DeductionEngine` da regola, o assert esplicito) —
  desumibile dalla forma dell'evidenza (`"located at…"`, `"pip install…"`, `"⟹ …"`).

Nessuno di questi richiede il modello: sono già in `debug_dump()`. Finché `debug_dump` non è persistito
per-step in telemetry, la BeliefAnalysis opera con `provenance=RECONSTRUCTED` (le transizioni sono
inferite dai `facts`/`history`, coerentemente con [decision-lifecycle.md §Provenance](decision-lifecycle.md#4-provenance)).
