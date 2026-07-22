# Context Selection Model — analisi dell'utilizzo del context

> **Owner** di `ContextUtilization` e dell'analisi di context per Decision (mission §8). Mappa sul
> layer [reasoning.py::AttentionManager](../../workspace/src/reasoning.py) (budget 3600 char / ~900
> tok) e sulla proiezione del prompt del supervisor
> ([supervisor.py::plan](../../workspace/src/supervisor.py)). Non ridefinisce l'attention: ne misura
> l'efficacia.

---

## 1. La domanda

Per ogni Decision: *quale context era disponibile, quale è stato realmente usato, quale ignorato,
quale mancava, e quale — se presente — avrebbe evitato il fallimento?* La risposta è misurabile perché
il context proiettato è deterministico (`AttentionManager.build_context`) e le Decision dichiarano cosa
hanno letto (`beliefs_read`, `evidence_available`).

---

## 2. `ContextUtilization` (enum chiuso)

Ogni **elemento di context** (un belief, un fatto, un vincolo, una failure episodica) rispetto a una
Decision è esattamente una di queste classi:

| `ContextUtilization` | Definizione | Rilevazione |
|----------------------|-------------|-------------|
| `AVAILABLE` | presente nel context proiettato al prompt | ∈ `build_context()` output |
| `USED` | presente **e** ha vincolato la scelta | ∈ available ∧ coerente con `chosen_alternative`/`rejected` |
| `IGNORED` | presente ma contraddetto dalla scelta | ∈ available ∧ la scelta lo viola |
| `MISSING` | necessario ma assente dal context | ∈ `evidence_required` ∧ ∉ available |
| `USELESS` | presente e irrilevante alla Decision | ∈ available ∧ ∉ `evidence_required` |
| `REDUNDANT` | presente più volte / già implicato da un altro elemento | duplicato nel budget |
| `DECISIVE` | `MISSING` **e** la sua presenza avrebbe evitato la divergenza | vedi §4 |

`USED` vs `IGNORED` è la distinzione centrale: un context `IGNORED` significa che l'informazione c'era
ma la Decision l'ha violata → il difetto **non** è di context (è di planner/belief). Un context `MISSING`
o `DECISIVE` significa che l'informazione mancava → il difetto **è** di context. Questa disambiguazione
instrada correttamente l'[Architectural Classifier](root-cause-framework.md#4-architectural-classifier).

---

## 3. Misure per Decision

```jsonc
ContextAnalysis = {                    // per Decision
  "budget_chars": 3600,                // AttentionManager.TOTAL_CHAR_BUDGET
  "available_count": int,
  "utilization": { ContextUtilization: [ContextItemRef] },
  "waste_ratio": float,                // (USELESS+REDUNDANT) / available_count
  "starvation": bool,                  // ∃ MISSING in evidence_required
  "decisive_missing": ContextItemRef[] // §4 — l'output più prezioso
}
```

- **waste_ratio** alto → il budget è speso in context inutile: la cura è context *engineering*
  (priorità in `AttentionManager`), non planner.
- **starvation=true** → la Decision ha deciso senza un'evidenza necessaria: candidata a
  `PREMATURE_EXECUTION`.

---

## 4. Context `DECISIVE` — quello che avrebbe evitato il fallimento

Il pezzo più importante della mission §8. Un elemento è `DECISIVE` se è `MISSING` **e**, iniettato,
avrebbe cambiato la classificazione della Decision da difettosa a corretta. Test deterministico
(controfattuale strutturale, non una nuova run del modello):

```
is_decisive(item, D, divergence):
    # 1. l'item è nell'evidenza richiesta ma mancante?
    if item ∉ D.missing_evidence: return False
    # 2. la sua presenza avrebbe reso strategy_ok o evidence-complete?
    D' = D.with_evidence(item)                       # copia con l'item soddisfatto
    return  not is_defective(D')                     # decision-model/strategy predicates
        and divergence.cause in CONTEXT_CURABLE      # {WRONG_STRATEGY, PREMATURE_EXECUTION, MISSING_DISCOVERY}
```

Esempio dal corpus (D1, `WRITE_BEFORE_KNOW`): l'elemento decisivo mancante è la **regola di dataflow**
*"il contenuto di una scrittura è testo letterale, mai un'espressione da valutare; il valore deve
esistere come fatto prima della scrittura"*. Non era nel context del supervisor
([decision-analysis.md §2 D1](../../workspace/validation/windows-lab/reports/decision-analysis.md)).
Il framework lo classifica come `DECISIVE`, il che indirizza il fix verso **Context**
(iniettare l'invariante) e/o **Planner** (imporlo strutturalmente) — la doppia ownership che il corpus
attribuisce a "Planner+Context".

---

## 5. Aggregazione e output

Su tutto il corpus, il framework produce la distribuzione di `ContextUtilization` e la lista dei
`DECISIVE` ricorrenti (candidati a diventare regole permanenti di context o invarianti di planner):

```
context_report(traces):
    decisive = Counter()
    for t in traces:
      for D in t.decisions:
        for item in D.context_analysis.decisive_missing:
            decisive[canonical(item)] += 1     # canonical = firma semantica, non testo
    return decisive.most_common()              # → high-leverage context rules
```

Output → [reports/context-analysis.md](reports/context-analysis.md). Un `DECISIVE` che ricorre in molti
casi è un candidato ad altissima leva (un solo elemento di context che alza il FTFR su un'intera
categoria) — vedi [Leverage Estimator](root-cause-framework.md#3-leverage-estimator). Coerente con la
tesi del corpus: le divergenze dominanti sono *decisioni*, non comandi; correggere il context che le
governa generalizza, correggere un tool no.

Invariante **CTX-1**: nessuna classe di `ContextUtilization` dipende da OS/tool. `canonical(item)`
normalizza a firma semantica (DE-6/DE-7).
