# roadmap-v2.md

> Owner: **la sequenza temporale e i milestone verso v2.** Il *cosa* per-modulo è in [migration-plan.md](migration-plan.md);
> qui il *quando* e i gate di avanzamento. Ogni milestone è validabile (validation cycle del progetto).

---

## Filosofia: ogni milestone deve alzare l'ARR o abbassare i token/task

Non "milestone = feature". Milestone = **miglioramento misurabile** su una metrica di [telemetry.md](telemetry.md).
Se una fase non muove ARR o token/task, non è pronta.

## Milestone

| M | Nome | Deliverable | Gate (misurabile) |
|---|---|---|---|
| **M0** | Cleanup & baseline | F0 (dead code out); aggregatore ARR sui telemetry esistenti | ARR baseline di v1 *misurata* (oggi ignota) |
| **M1** | Belief spine | Fact tipizzati + State Engine + invarianti centralizzati | 100% branch-coverage invarianti (no LLM) |
| **M2** | Observe & Map | Observation Engine + System Mapper + World Model (grafo) | diagnosi tipica usa un sottografo, non dump |
| **M3** | Context compiler | Context Engine sotto budget | token/task p50 ≤1.5k; Issue #8 (parse-error) sparita |
| **M4** | The brain | Scheduler cognitivo + Planning DAG; orchestrator smontato | model-call ratio ≤35%; ARR ≥ baseline |
| **M5** | Knowledge & Learning | Knowledge Graph interrogabile + experience store | retry cross-OS −80%; hit-rate experience >0 e crescente |
| **M6** | Zero-Trust & Fleet | Security risk-vector + runtime SSH | 0 azioni irreversibili non gated; 1 incident cross-host risolto |
| **M7** | Reference release | hardening, docs, benchmark pubblico multi-OS | ARR ≥ 80% su suite pubblica con modello ≤8B locale |

## Dipendenze

```
M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7
             └────► (M3 è il salto di valore: sblocca modelli piccoli affidabili)
```

## Principio di rilascio

v2 cresce **dietro le interfacce di v1** (strangler): a ogni milestone il sistema resta usabile; i moduli v1 si
spengono quando il sostituto passa il validation cycle. Ogni milestone → un RFC (a partire da RFC-0004 per l'intera
architettura, poi RFC per le fasi non banali).

## Anti-goal (cosa NON facciamo lungo la strada)

Non aggiungiamo coding/IDE/GUI. Non introduciamo dipendenze pesanti obbligatorie (Docker/Postgres). Non
ottimizziamo micro-Python prima di aver misurato l'ARR. Non inseguiamo i leader sul loro terreno (coding) — presidiamo
il white space sysops (vedi [../research/competitors/index.md](../research/competitors/index.md) §7).

## Rischi che possono spostare le date → [risk-analysis.md](risk-analysis.md).
