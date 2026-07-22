# supervisor.md

> Owner: **il ruolo che ragiona e coordina L3 — mai esegue.** Non è un componente monolitico: è il *ruolo* che
> compone Goal Manager + Planning + Reasoning + Learning sotto lo scheduler. Contrasto totale con [executor.md](executor.md).

---

## Contratto: il Supervisor pensa, non tocca

> Il Supervisor **non apre mai una shell**, non scrive mai un file, non esegue mai un comando.
> Fa solo: **capire · pianificare · delegare · validare · imparare · aggiornare il belief state.**

Questa separazione è netta perché in v1 (e in Goose/Codex) reasoning ed esecuzione sono mescolati nel loop → il
god-object. Qui il Supervisor produce **decisioni tipizzate** (piani, ipotesi, verdetti), l'Execution Engine le esegue.

## Cosa fa (le sue 6 verbi)

| Verbo | Engine L3 | Output tipizzato |
|---|---|---|
| **Capire** | Goal Manager | goal decomposto, intento, vincoli |
| **Pianificare** | Planning Engine | DAG di azioni con precondizioni/effetti |
| **Delegare** | (scheduler) | azioni concrete → Execution Engine |
| **Validare** | Validator | verdetto `verify.*` su effetti attesi |
| **Imparare** | Learning Engine | esperienza → Failure/Pattern/Recovery DB |
| **Aggiornare belief** | Reasoning Engine | transizioni belief PROVEN/REFUTED |

## Modello economico: il Supervisor è caro, quindi raro

Ogni verbo del Supervisor costa una chiamata al modello (4B/8B/cloud). Lo scheduler VoI lo invoca **solo quando serve
giudizio**; i passi meccanici (probe, fix sintassi, dispatch, verifica strutturale) sono L1/L2 deterministici. È il
motivo per cui reggiamo un 4B: il "cervello caro" pensa poco e bene, non ad ogni tick.

## Delega, non esecuzione (la differenza con v1)

In v1 l'`Executor` (classe) era istanziato ma *mai usato*: il reasoning e l'esecuzione vivevano entrambi
nell'orchestrator. In v2 la delega è reale: il Supervisor emette un `plan.action` concreto → l'Execution Engine lo
prende. Il Supervisor non ha *riferimenti* al runtime (dependency inversion): non *può* eseguire anche volendo.

## Confronto competitor

- **Codex/Goose/Aider:** "supervisor" ed "executor" sono lo stesso loop del modello → nessuna separazione, il modello
  fa tutto (costoso, non isolabile).
- **OpenHands:** agente unico che emette Action; separa il *runtime* ma non il *ragionamento* dal *decidere-l'azione*.
- **Noi:** il Supervisor è un *ruolo cognitivo puro* con dependency-inversion sull'esecuzione. Testabile senza toccare
  un OS (gli si danno Fact, produce piani).

## Pattern

Mediator / Orchestrator (ma senza logica di esecuzione) · Command (produce comandi, non li esegue) · Dependency
inversion · CQS (query il belief, comanda via azioni tipizzate).

## Alternative scartate

- **Supervisor che esegue "i comandi facili" per velocità:** riapre la porta al god-object e ai side-effect non
  gated. **Rifiutato** — purezza assoluta.
- **Un unico agente-modello (no ruoli):** semplice ma non frugale e non isolabile. **Rifiutato** dal vincolo modello-piccolo.

## Trade-off / Benchmark / Evoluzioni

Trade-off: più indirezione (decisione→azione→esecuzione) vs un loop diretto; ripagata da testabilità e frugalità.
Benchmark: chiamate-modello per task minimizzate (vedi [cognitive-architecture.md](cognitive-architecture.md), target
≤35% dei tick). Evoluzioni: Supervisor multi-modello (8B per pianificare incident complessi, 3B per giudizi semplici),
meta-supervisione (stima della propria confidence → escalation).
