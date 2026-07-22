# planning-engine.md

> Owner: **il Goal Manager e il piano come DAG di azioni con precondizioni.** L'*inferenza* è del
> [reasoning-engine.md](reasoning-engine.md); qui la *struttura* del piano e il ciclo di vita dei goal.

---

## Il piano è un grafo, non una lista

v1 (e Goose/Codex) trattano il piano come **lista di step** eseguiti in ordine. Un sistemista reale lavora su un
**DAG**: passi con **precondizioni** e **dipendenze**, alcuni paralleli, alcuni condizionali all'esito di un probe.

```
                 ┌─ probe: capability:certutil ─┐
 goal ──► plan ──┤                              ├─► action: check cert ──► verify ──► done
                 └─ probe: env.clock ok ────────┘
   Ogni nodo: { intent, preconditions[Fact], effects[Fact], step_type, reversibility, verify_predicate }
```

- **Precondizioni = Fact richiesti** (es. `capability:systemctl PROVEN`). Se non soddisfatte → il Planner inserisce
  un nodo DISCOVERY *prima* (l'invariante "discovery prima di action" diventa una proprietà del grafo, non una regola sparsa).
- **Effetti attesi = Fact prodotti** → il Validator sa cosa verificare (post-condizione), non indovina.
- **step_type** (DISCOVERY/MODIFY/VERIFY/RECOVER) instrada la verifica (fix del Pattern B di v1, ma nativo nel modello del piano).

## Goal Manager

Possiede il ciclo di vita del goal: decomposizione in sotto-goal, tracking (OPEN/BLOCKED/PROVEN/ABANDONED),
riconoscimento di *goal già soddisfatto* (early-stop: non agire se il mondo è già nello stato voluto — SRE mindset,
generalizza l'adaptive early-stop di v1). Un goal DESTRUCTIVE è rifiutato *prima* dal Safety Engine, mai decomposto.

## Pianificazione gerarchica (HTN-like) per incident

Per obiettivi complessi ("il sito è down"), il Planner opera come **Hierarchical Task Network**: metodo astratto
("ripristina servizio web") → sotto-task ("diagnostica", "correggi", "verifica") → azioni concrete (dal KG per l'OS).
Il modello sceglie il *metodo*; l'espansione in azioni valide-per-OS è vincolata dal Knowledge Graph → **niente
comandi cross-platform** (invariante v1).

## Precondizioni = niente placeholder all'executor

Un nodo azione è *eseguibile* solo se tutte le precondizioni-Fact sono risolte a valori concreti. Un `<git_dir>` non
risolto = precondizione non soddisfatta = nodo non pronto → o lo risolve un DISCOVERY, o il Context Engine lo riempie
da un Fact. L'executor riceve **solo azioni completamente concrete** (invariante ereditato, ora strutturale).

## Confronto competitor

- **Cline** ha un "Plan mode" esplicito — buono, ma è testo per l'umano, non un DAG con precondizioni verificabili.
- **Aider/Codex/Goose:** planning implicito nel modello, lista lineare.
- **OpenHands:** loop CodeAct, nessun piano-oggetto ispezionabile.
- **Nostro DAG con precondizioni/effetti tipizzati** è ispezionabile, parallelizzabile, e rende *strutturali* invarianti
  che gli altri sperano dal modello. Nessuno ha questo per il sysops.

## Pattern

DAG / task-graph · HTN planning · Precondition/effect (STRIPS-like, ma con Fact) · Topological + conditional
execution · Idempotency by design (effetti dichiarati → riesecuzione sicura).

## Alternative scartate

- **Piano lineare (v1):** non esprime dipendenze/parallelismo/condizionali; ogni deviazione richiede re-planning
  completo. **Rifiutato.**
- **Planning puramente simbolico (PDDL/solver):** rigoroso ma richiede un modello del dominio completo e chiuso;
  il sysops è aperto e incerto. **Rifiutato** come unico meccanismo — prendiamo precondizioni/effetti, non il solver.
- **Nessun piano (ReAct step-by-step):** ottimo per esplorare, pessimo per operazioni multi-step con dipendenze e
  rischio (un incident). **Rifiutato** come primario; ReAct resta possibile *dentro* un nodo diagnostico.

## Trade-off

- Un DAG con precondizioni è più da costruire di una lista. Ripagato: parallelismo, verifica mirata, re-planning
  *locale* (ri-espandi solo il sottoalbero fallito, non tutto).
- Richiede che il modello emetta struttura → mitigato da schema rigido + il modello sceglie *metodi/intenti*, non sintassi.

## Benchmark teorico

Re-planning locale dopo un fallimento: costo O(sottoalbero) vs O(piano intero) di v1. Parallelizzazione dei probe
indipendenti: latenza di diagnosi ridotta ~lineare col numero di probe indipendenti.

## Evoluzioni

Planner con costo/rischio come funzione obiettivo (sceglie il piano meno rischioso a parità di esito) · riuso di
sotto-DAG dall'experience store (Pattern DB) · pianificazione anytime (piano parziale eseguibile subito, raffinato in corsa).
