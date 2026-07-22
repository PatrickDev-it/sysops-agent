# architecture-next/ — Sistemista v2

> **Deliverable di design (CTO / Principal Architect).** Progetta la prossima generazione dell'agente da
> **first principles**, ignorando l'implementazione attuale; il codice v1 è *esperienza*, non vincolo.
> Da ratificare come **RFC-0004** prima di implementare. Non è ancora codice.
> Contesto: [../BRAIN.md](../BRAIN.md) (identità/moat), [../research/competitors/index.md](../research/competitors/index.md) (KB), analisi codice v1.

---

## Tesi (il perno di tutto il design)

> Per un **agente sysops su modelli locali 3B–8B / 16GB RAM**, le due risorse scarse sono
> **(1) i token di contesto** e **(2) la qualità di ragionamento del modello piccolo**.
> Quindi: **tutto ciò che non richiede un modello è deterministico**, e **il contesto è *compilato* al minimo
> per ogni decisione** interrogando un **world model** persistente. Non una pipeline: un **cervello a blackboard**
> con uno **scheduler** che sceglie *quale* pensiero fare, e un **world model interrogabile** che sostituisce il
> "caricare tutto nel prompt".

Tre spostamenti rispetto a v1 e a tutti i competitor:

1. **Da prompt a *compilazione del contesto*.** Il prompt è un *artefatto compilato* sotto budget di token, non
   un blob scritto a mano. (Va oltre il repo-map di [Aider](../research/competitors/aider.md).)
2. **Da testo a *fatti tipizzati*.** Nessun componente ragiona su testo di terminale grezzo; l'unità è il **Fact**
   con owner e provenienza. (Generalizza l'event-stream di [OpenHands](../research/competitors/openhands.md).)
3. **Da pipeline a *blackboard + scheduler a due livelli* (deliberativo lento / reattivo deterministico).** Il
   modello è invocato solo ai veri punti di decisione. (Nessun competitor lo fa: tutti sono ReAct-loop monolitici.)

## Perché "cervello, non pipeline"

Una pipeline `Supervisor→Executor` (v1, Goose, Codex) impone un *ordine fisso di pensiero*. Un sistemista reale
non pensa in ordine fisso: a volte manca un fatto (→ osserva), a volte il piano è pronto (→ agisci), a volte
qualcosa è fallito (→ recupera). Il **control model** è quindi **event-driven su una blackboard**: lo scheduler
sceglie la prossima azione cognitiva in base ai *gap del belief state*, non a un contatore di step.

## Mappa di proprietà (un fatto → un owner — anche tra questi doc)

I nomi dei file si sovrappongono per progetto: qui li disambiguo con confini netti (stessa disciplina del
[Documentation contract](../../AGENTS.md#documentation-contract)).

| Layer | Doc / componente | Owner di… |
|---|---|---|
| **Thesis** | [vision.md](vision.md) · [architecture.md](architecture.md) · [cognitive-architecture.md](cognitive-architecture.md) | scopo, mappa dei componenti, modello di controllo |
| **Data spine** | [belief-system.md](belief-system.md) | il Fact e il belief state (blackboard) |
| | [state-engine.md](state-engine.md) | ciclo di vita/transizioni dei Fact e delle entità |
| | [knowledge-graph.md](knowledge-graph.md) | ontologia OS/comandi (successore di OCKE) |
| | [system-map.md](system-map.md) | world model del sistema *reale* (grafo interrogabile) |
| | [memory.md](memory.md) | gerarchia di memoria + experience store |
| **Cognizione** | [context-engineering.md](context-engineering.md) | il *compilatore di contesto* (cuore) |
| | [reasoning-engine.md](reasoning-engine.md) | inferenza sui belief, ipotesi causali |
| | [planning-engine.md](planning-engine.md) | il piano come **task-graph (DAG)**, non lista |
| | [observation-engine.md](observation-engine.md) | bytes → Fact tipizzati |
| **Esecuzione** | [supervisor.md](supervisor.md) | ragiona/pianifica/valida (mai esegue) |
| | [executor.md](executor.md) | effettore puro (mai ragiona) |
| | [execution-engine.md](execution-engine.md) | dispatch atomico, idempotenza, scheduling azioni |
| | [runtime.md](runtime.md) | substrato d'esecuzione (batch + interactive, umbrella) |
| | [terminal-runtime.md](terminal-runtime.md) | sessione, prompt-detection, wizard driving |
| | [pty-runtime.md](pty-runtime.md) | il layer bytes/pyte/VT100 (il più basso) |
| **Trasversale** | [learning-engine.md](learning-engine.md) | esperienza: failure/pattern/recovery DB |
| | [security.md](security.md) | zero-trust: risk scoring + gate + sandbox degradabile |
| | [telemetry.md](telemetry.md) | log append-only + metriche (north-star) |
| | [performance.md](performance.md) | budget token/latency/RAM, model routing |
| | [scalability.md](scalability.md) | multi-host, fleet, concorrenza |
| **Delivery** | [roadmap-v2.md](roadmap-v2.md) · [migration-plan.md](migration-plan.md) · [risk-analysis.md](risk-analysis.md) · [future-research.md](future-research.md) | come ci arriviamo, rischi, ricerca |

Regola: se due doc descrivono lo stesso fatto, uno è owner e l'altro linka. `runtime`/`terminal-runtime`/
`pty-runtime` sono **tre layer di uno stack**, non tre viste dello stesso fatto — vedi [runtime.md](runtime.md).

## Reading order

`vision → architecture → cognitive-architecture → belief-system → context-engineering → system-map → il resto`.

## Confronto sintetico coi competitor (dettaglio nei singoli doc)

| Scelta v2 | Chi fa altrimenti | Perché noi vinciamo |
|---|---|---|
| World model interrogabile | Aider (solo repo di codice) | mappiamo il *sistema vivo*, non un repo |
| Contesto compilato sotto budget | tutti (prompt statico/RAG) | token-optimal per modelli piccoli |
| Blackboard + scheduler | tutti (ReAct loop) | il modello pensa solo ai punti di decisione |
| Fatti tipizzati | OpenHands (event stream testuale) | zero testo grezzo nel reasoning |
| Experience store sysops | nessuno | migliora senza training |
| Zero-trust degradabile | Codex (sandbox OS), IronClaw (WASM pesante) | sicurezza forte *anche su VPS nuda* |
