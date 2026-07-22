# Context Analysis Report

> Template generato. Owner del formato: [context-selection-model.md](../context-selection-model.md).
> `provenance`: **RECONSTRUCTED** (corpus full-safe30).

---

## Distribuzione `ContextUtilization` (aggregato)

| Classe | Frazione | Interpretazione |
|--------|----------|-----------------|
| AVAILABLE | 100% baseline | — |
| USED | {{%}} | context che ha vincolato la scelta |
| IGNORED | {{%}} | presente ma violato → difetto NON di context |
| **MISSING** | {{%}} | necessario e assente → difetto di context |
| USELESS | {{%}} | budget speso a vuoto |
| REDUNDANT | {{%}} | — |
| **DECISIVE** | vedi sotto | mancante e avrebbe evitato la divergenza |

## Elementi `DECISIVE` ricorrenti (l'output più prezioso)

Ordinati per frequenza sul corpus — candidati a regola permanente di context / invariante di planner:

| # | Elemento DECISIVE mancante | Casi | Cura indicata |
|---|----------------------------|------|---------------|
| 1 | **Regola di dataflow**: *"il contenuto di una scrittura è testo letterale; il valore deve esistere come fatto PROVEN prima della scrittura"* | 7 (tutti i D1) | Context rule + invariante PLAN-1 |
| 2 | **Regola diagnose-before-change** su Intent REPAIR | 4 (D4 CICD) | Context rule + gate |
| 3 | Marcatura PROVEN sticky visibile al planner | 8 (D3) | Belief fix (non context) |

L'elemento #1 è `DECISIVE` in 7 casi su 22: un singolo elemento di context che, iniettato, alza il FTFR
su un'intera categoria (dominio-indipendente: env_path, users, services, processes). È il candidato di
context a più alta leva. Vedi [high-leverage-fixes.md](high-leverage-fixes.md).

## Waste & starvation

| Metrica | Valore |
|---------|--------|
| waste_ratio medio | {{%}} |
| casi in starvation (MISSING in evidence_required) | ~7+ (tutti i premature-execution) |
| budget AttentionManager | 3600 char (~900 tok) |

## Nota di attribuzione

Un elemento `DECISIVE`/`MISSING` instrada il fix verso **Context/Planner** (l'informazione mancava);
un elemento `IGNORED` instrada verso **Planner/Belief** (l'informazione c'era ma è stata violata). Nel
corpus i D1 sono `MISSING` (la regola di dataflow non era nel prompt) → doppia ownership
`Planner+Context`, coerente con [decision-analysis.md §3](../../../workspace/validation/windows-lab/reports/decision-analysis.md).
