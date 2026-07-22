# RFC 002 — Architettura V2

> Stato: **proposta di design**, 2026-07-14. Nessun codice. Nessuna modifica alla V1. Segue il processo
> §5 (AGENT_INSTRUCTIONS): problema → evidenza misurata → alternative → decisione → test che la falsifica.
> Owner della strategia: `brain/BRAIN.md`; questa RFC è un cambiamento di confine e va approvata prima di
> qualsiasi implementazione.

---

## 0. Framing — cosa QUESTO sistema è, e cosa NON è

Ogni decisione sotto discende da qui. Sbagliare il framing è il modo più costoso di sbagliare l'architettura.

**È:** un agente **mono-processo, mono-utente, sequenziale**, su **un solo box** (RTX 4060 8 GB, 8 GB RAM,
Windows), con backend **llama.cpp**. Due modelli **residenti insieme in VRAM** che la **saturano al ~95 %**
(misurato: 4B + 3B = **7756 / 8192 MiB**, ~436 MiB liberi). I costi dominanti sono **latenza di inferenza**
(prefill+decode) e **latenza dei tool** (shell/npm/PTY, I/O-bound, da secondi a minuti). I guasti dominanti
sono: output LLM invalido, **OOM di VRAM**, tool timeout/fallito, **PTY appeso**, incoerenza di stato,
crash di `llama-server`.

**NON è:** un sistema distribuito, multi-tenant, ad alto throughput, con asimmetria read/write. Non ha
fan-out multi-consumer, non ha nodi, non ha scaling orizzontale.

**Conseguenza dura (guida tutto):** la concorrenza reale qui è **overlap di I/O** (inferenza ‖ tool ‖ PTY),
**non** calcolo parallelo. Con 2 slot-modello fissi e ~436 MiB liberi, un "worker pool di LLM" è una
finzione: non c'è VRAM per un terzo contesto. Chi propone worker-pool/actor-mesh/message-bus qui sta
rispondendo a problemi che questo sistema non ha, e paga latenza+RAM+complessità per zero throughput in più.
Questo è precisamente ciò che il mandato runtime-first del progetto vieta.

---

## 1. Review della V1 — la distruggo dove serve (con evidenza)

| # | Problema | Categoria | Evidenza (dal grafo / misurata) |
|---|---|---|---|
| V1-1 | **God-loop.** `Orchestrator._run_loop` (~450 righe) chiama **38+ funzioni** su planning, OCKE, state, observe, verify, classify, execute, logging, JSON-repair. `_execute_step` ~480 righe. `orchestrator` è god-node **degree 90**. | manutenzione, testabilità, affidabilità | `get_neighbors(_run_loop)` = 38 archi `calls`; `graph_stats` god-nodes: orchestrator(90), `_run_loop`(40) |
| V1-2 | **Loop imperativo, non state machine.** Recovery/replan/verify intrecciati in un'unica funzione con stato implicito. Il deadlock mkdir (debito #7) è un sintomo: "prerequisite MODIFY fallito → halt fatale → replan → stessa mkdir" è logica sepolta nel loop, non uno stato osservabile. | affidabilità, concorrenza, osservabilità | `known-issues.md` (deadlock, 2026-07-14) |
| V1-3 | **Stato solo in RAM (invariante #1).** `SystemState` muore col processo. Un crash / OOM / restart di `llama-server` a metà task **perde tutto il task**. Incompatibile con "gira per settimane, recupera da crash". | affidabilità, recovery | invariante #1; obiettivo esplicito dell'utente |
| V1-4 | **Verify indulgente (falso COMPLETE).** Misurato oggi: run e2e `node_backend` col 4B → il verify LLM ha dichiarato COMPLETE con `server.js` mancante, benché il `_artifact_check` deterministico l'avesse già beccato. La verità deterministica non ha potere di veto sul verdetto finale. | affidabilità | `session.md` 2026-07-14 |
| V1-5 | **Nessuna gestione di VRAM/KV.** Modelli lanciati con arg fissi; nessun budget del KV; l'overflow *alza* (bene) ma il recovery da quell'alzata non è graceful. Su ~436 MiB liberi, un transcript PTY lungo o un piano grande può OOM-are. | affidabilità, VRAM | misurato 7756/8192; `config` disabilita context-shift |
| V1-6 | **Concorrenza zero.** Tutto sequenziale. Mentre `npm install` gira (minuti), l'intero agente blocca; probe di discovery indipendenti girano in serie. Latenza lasciata sul tavolo. | latenza, throughput | architettura del loop |
| V1-7 | **Accoppiamento totale.** L'orchestratore importa e coordina terminal, session, supervisor, model_router, memory, observer, confinement, reasoning, state — senza interfacce né DI. Cambiarne uno propaga. | manutenzione, modularità | import di `orchestrator` |
| V1-8 | **Routing modello statico, degrado grezzo.** `_oracle/_nav/_coder` senza circuit breaker: un modello che fallisce di continuo viene richiamato all'infinito. | affidabilità | `model_router` |
| V1-9 | **Osservabilità parziale.** C'è `trace.jsonl` + telemetry (stato finale), ma **niente metriche** (istogrammi di latenza, gauge VRAM, cache-hit, retry, tempo-per-stato, stato del circuit). "Osservabile tramite metriche" è un obiettivo non soddisfatto. | osservabilità | `trace.py`, telemetry |
| V1-10 | **Testabilità dei god-object.** 366 test, ma `_run_loop`/`_execute_step` non sono testabili in isolamento → si testano i pezzi, non le transizioni. Il deadlock non aveva test perché è un comportamento emergente del loop. | testing | assenza di test sul loop |

**Cosa la V1 fa GIÀ bene e va PRESERVATO** (non buttare il bambino):
- **Decoding grammaticale (GBNF)** → l'output JSON invalido è *irrappresentabile*. Ha cancellato ~130 righe
  di regex-repair. È l'idea migliore del sistema. La V2 la tiene al centro.
- **Predicati tipizzati (`predicates.py`)** → verifica come tabella pura, valutata senza eseguire nulla.
- **Prefix cache** → misurato 37× sul prefill; system-block byte-identico (invariante #13). Vincolo di design, non ottimizzazione opzionale.
- **Confinement filter, safety_gate, OCKE, error_classifier** → owner deterministici che tolgono
  ragionamento al modello. Il principio "deterministic > LLM" è giusto e va esteso, non ridotto.

---

## 2. Principi di design V2 (derivati da §0 + mandato runtime-first)

1. **Un processo, single-thread async.** La concorrenza è overlap di I/O, non parallelismo di calcolo.
2. **Event sourcing.** Lo stato è la piega (fold) di un log append-only immutabile → recovery, replay, osservabilità *gratis*.
3. **La macchina a stati è il sistema.** Il loop diventa una FSM esplicita: ogni transizione è un evento, testabile e ripartibile.
4. **La verità deterministica ha potere di veto.** Un predicato/`_artifact_check` batte sempre un verdetto LLM.
5. **Ogni processo esterno è supervisionato.** `llama-server`, shell, PTY: health, watchdog, restart con backoff, circuit breaker.
6. **Budget espliciti su VRAM/KV e RAM.** Admission control prima di allocare, non OOM dopo.
7. **Componenti a responsabilità unica dietro interfacce strette,** cablati con DI leggera (constructor injection) → sostituibili e testabili in isolamento.
8. **Ogni pattern paga il suo posto** con un beneficio misurabile su una delle 7 assi. Altrimenti fuori.

---

## 3. Diagramma architetturale

```
                          ┌───────────────────────────────────────────────┐
                          │           EVENT LOG (append-only, durable)      │  ← fonte di verità
                          │   plan.created · step.scheduled · tool.done ·   │    (recovery/replay)
                          │   belief.proven · vram.pressure · fsm.moved …   │
                          └───────▲───────────────────────────────▲─────────┘
                                  │ append                         │ fold → stato
   User Request                   │                                │
        │                 ┌───────┴────────────────────────────────┴─────────┐
        ▼                 │            AGENT FSM  (supervisor)                 │
   ┌─────────┐   goal     │  INTAKE→PLAN→SCHEDULE→EXECUTE→OBSERVE→VERIFY→      │
   │ Intake  │──────────► │  CRITIC→(RECOVER|COMPOSE)→DONE|FAILED             │
   └─────────┘            └───┬───────┬─────────┬────────┬───────┬────────────┘
                              │        │         │        │       │
                    ┌─────────▼──┐ ┌───▼────┐ ┌──▼─────┐ ┌▼─────┐ ┌▼────────┐
                    │  Planner   │ │Scheduler│ │ Tool   │ │Valid.│ │ Critic  │
                    │ (4B, GBNF) │ │(DAG,    │ │Executor│ │(pred.│ │ (4B,    │
                    │            │ │ dep-aw) │ │(coder  │ │ det.)│ │ optional│
                    └─────┬──────┘ └───┬─────┘ │ 3B +   │ └──────┘ └─────────┘
                          │            │       │ PTY)   │
                          │            │       └───┬────┘
                    ┌─────▼────────────▼───────────▼──────────────────────┐
                    │   INFERENCE LAYER (supervised)                       │
                    │   ProcessSupervisor · Watchdog · CircuitBreaker ·    │
                    │   VRAM/KV BudgetManager · prefix-cache guard         │
                    │        ├── nav-4b  (2 slots)   ── llama-server        │
                    │        └── coder-3b (1 slot)   ── llama-server        │
                    └──────────────────────────────────────────────────────┘
                    ┌──────────────────────────────────────────────────────┐
                    │  CROSS-CUTTING: Capability Registry (OCKE) · Memory    │
                    │  (working RAM + durable SQLite) · Confinement · Metrics│
                    └──────────────────────────────────────────────────────┘
```

**Nota di design:** l'Event Log al centro NON è un message-bus fra i componenti (niente pub/sub, niente
attori). È un **journal**: la FSM appende, e lo stato è il fold del journal. I componenti si chiamano per
funzione dietro interfaccia. Il journal dà recovery+replay+osservabilità senza il costo di un bus.

---

## 4. Componenti (responsabilità unica)

| Componente | Responsabilità unica | Modello | Sostituisce in V1 |
|---|---|---|---|
| **Intake** | normalizza la richiesta; safety-gate; enhance (specialist brief) | 4B + deterministico | pezzi sparsi in `_run_loop` |
| **Planner** | goal → Task DAG (nodi tipizzati DISCOVERY/MODIFY/VERIFY con dipendenze + success-predicates GBNF) | 4B, grammar-constrained | `supervisor.plan` + JSON-repair inline |
| **Scheduler** | ordina il DAG; parallelizza SOLO DISCOVERY indipendenti; serializza MODIFY | deterministico | assente (era seq. implicito) |
| **Tool Executor** | esegue un nodo: coder authoring, shell, PTY-wizard; confinement | 3B + deterministico | `_execute_step` (480 righe) |
| **Validator** | verifica deterministica per-step via `predicates.py` (esiste-e-ha-contenuto) | **deterministico, veto** | `_artifact_check` (ma ora con veto) |
| **Critic** | verify a livello-goal, SOLO se il Validator è verde; può bocciare, mai promuovere oltre il Validator | 4B, opzionale | `supervisor.verify` (ma subordinato al Validator) |
| **Memory** | working-state (RAM) + episodica/regressioni (SQLite durable) + retrieval | deterministico | `memory.py` + `SystemState` |
| **Response Composer** | fold finale → risposta/telemetria | deterministico | coda di `run()` |
| **Inference Layer** | lifecycle+salute dei `llama-server`, budget VRAM/KV, circuit breaker | — | `llm_backend.ManagedServer` (esteso) |
| **Capability Registry** | ciò che l'OS/shell sa fare, probed una volta | deterministico | OCKE (formalizzato) |

Ogni componente: **interfaccia stretta + constructor DI** → riavviabile e testabile da solo (obiettivo utente).

---

## 5. Flusso dati

```
Request ─▶ Intake ─(SpecialistBrief, SafetyVerdict)▶ Planner ─(TaskDAG)▶ Scheduler
   ▶ (ready set) ─▶ Tool Executor ─(ToolResult)▶ Validator ─(predicate verdicts, DETERMINISTIC)
   ├─ tutti i predicati del nodo verdi ─▶ marca nodo DONE, sblocca dipendenti ─▶ Scheduler
   ├─ predicato rosso ─▶ Recover (error_classifier vincola le recovery ammesse)
   └─ DAG completo ─▶ Critic (goal-level) ─▶ [se boccia] Recover  [se ok] Composer ─▶ Response
Ogni freccia = un evento immutabile appeso al log. Lo stato vive nel fold, non nelle variabili locali.
```

Regola d'oro (fix diretto a V1-4): **il Critic non può dichiarare COMPLETE ciò che il Validator non ha
già certificato per ogni requisito del goal.** La verità deterministica ha il veto.

---

## 6. State machine (l'agente È una FSM)

```
INTAKE ──▶ PLAN ──▶ SCHEDULE ──▶ EXECUTE ──▶ OBSERVE ──▶ VERIFY ──┬─▶ CRITIC ─┬─▶ COMPOSE ─▶ DONE
   │         │          ▲            │                             │           │
   │         │          └──── next ready node ◀────────────────────┘           │
   │         ▼                                                                  ▼
   └──▶ REJECTED (safety)                                        RECOVER ◀── (predicate red /
             PLAN ◀── REPLAN ◀── RECOVER ── tool fail/timeout ──┘              critic reject)
                                    │
                                    └─(budget esaurito: max_replans / circuit open)─▶ FAILED
```

- Ogni stato ha: **invariante d'ingresso**, **timeout (watchdog)**, **evento di uscita**.
- Ogni transizione è un evento nel log → **la FSM è ripartibile**: al restart si rifà il fold e si riprende
  dall'ultimo stato coerente. Fix diretto a V1-2 e V1-3.
- Il deadlock mkdir (debito #7) diventa impossibile: un `exit 126 "DIRECTORY NOT NEEDED"` è un **evento di
  guard tipizzato**, non un fallimento fatale; la transizione lo mappa a **skip del nodo** (prerequisite già
  soddisfatto), e il messaggio del guard entra nel contesto di RECOVER.

**Costo:** medio (riscrittura del loop). **Latenza:** neutra. **RAM/VRAM:** trascurabile (la FSM è un enum +
un fold). **Complessità:** **la riduce** (elimina 2 god-function). **Beneficio misurabile:** testabilità
(una transizione = un test), resumability (recovery da crash), osservabilità (tempo-per-stato).

---

## 7. Pipeline

`Intake → Planner → TaskDAG → Scheduler → Worker(s) → Tool Executor → Validator → Critic → Memory → Composer`
è la pipeline richiesta. Mapping onesto sui vincoli:
- **Worker(s)**: NON un pool di LLM (VRAM). È un **executor concorrente bounded** (default 1, max ~3) per i
  soli nodi I/O-bound indipendenti (probe di discovery: `node -v`, `npm -v`, `where git`). Il 4B/3B restano
  a slot fissi; il parallelismo è sui *processi shell*, non sui modelli.
- **Critic** subordinato al **Validator** (§5). Il Critic è opzionale e a costo controllato: gira solo a
  fine-DAG, non per-step (per-step basta il Validator deterministico → risparmia chiamate 4B).

---

## 8. Scheduler

**Decisione:** DAG dependency-aware che **parallelizza solo i DISCOVERY indipendenti**; **serializza tutti i
MODIFY** (mutano lo stato condiviso del filesystem → race). VERIFY segue il suo nodo.

| asse | valutazione |
|---|---|
| Vantaggi | latenza sui task discovery-heavy (N probe in overlap invece che in serie); dipendenze esplicite eliminano il "discovery prima di action" implicito (invariante #5 diventa struttura, non convenzione) |
| Svantaggi | complessità del DAG; la maggior parte dei piani è corta (≈5 nodi) → guadagno modesto sui task semplici |
| Costo impl | medio | 
| Latenza | **↓** su discovery paralleli; neutra sui piani lineari |
| RAM/VRAM | trascurabile (il DAG è metadati; i processi shell paralleli costano RAM, non VRAM — bounded a ~3) |
| Complessità | **+** (giustificata solo perché rende l'invariante #5 strutturale e abilita l'overlap I/O) |

**Falsificabile:** se, misurato, <15 % dei nodi in un benchmark rappresentativo è DISCOVERY-parallelizzabile,
lo scheduler DAG non ripaga la complessità → degradare a scheduler lineare con overlap inferenza‖tool.

---

## 9. Inference Layer (il cuore del rischio: VRAM 95 % pieno)

Estende `ManagedServer`. Owner unico di "come parliamo ai modelli e come restano vivi".

- **ProcessSupervisor (Supervisor Tree, 1 livello):** un supervisore per `llama-server`. Health-gate,
  restart con backoff esponenziale + jitter, shutdown pulito. *Beneficio:* riavvio indipendente per modello
  (obiettivo utente). *Costo:* basso (già quasi presente).
- **Watchdog:** timeout per-richiesta e per-PTY-screen. Un decode che sfora `n_predict` (V1: T43 loop) o un
  PTY appeso vengono uccisi e mappati a evento `timeout`, non a hang. *Latenza:* protegge la coda; *costo:* basso.
- **CircuitBreaker per ruolo:** N fallimenti consecutivi di un modello → circuito **open** → si smette di
  chiamarlo, si degrada o si fallisce *fast and loud*. Uccide i loop tipo deadlock/retry-infinito (V1-8).
  *Costo:* basso; *beneficio:* niente spin.
- **VRAM/KV BudgetManager (admission control):** contabilizza pesi + KV per slot + compute buffer **prima**
  di allocare. Su 8 GB: 4B+3B = 7756 MiB, headroom ~436. Regole:
  - ctx e slot sono **budget dichiarati**, non speranze; il manager rifiuta una config che sfora *al lancio*,
    non a runtime.
  - il KV cresce col transcript → **prima dell'overflow** si **compatta il contesto** (riassunto
    deterministico del tail vecchio, mai del system-block: invariante #13/prefix-cache intatta), non si droppa
    il blocco d'istruzioni. Fix a V1-5.
  - se serve un terzo contesto (non c'è VRAM), è un **errore di ammissione esplicito**, non un OOM.
- **Prefix-cache guard:** il system-block resta byte-identico (invariante #13); il manager rifiuta qualsiasi
  prompt che rompa il prefisso condiviso. La cache 37× è un vincolo, non un optional.

| asse | Inference Layer |
|---|---|
| Vantaggi | affidabilità (restart/watchdog/breaker), niente OOM (admission), cache preservata |
| Svantaggi | il BudgetManager è lavoro non banale; la compaction del contesto è un algoritmo da misurare |
| Costo impl | **alto** (è la parte dura, come RFC-001 preannuncia con QLora/offload) |
| Latenza | neutra/positiva (evita restart-storm e OOM-recovery costosi) |
| VRAM | **è il punto**: rende gli 8 GB una risorsa gestita, non una roulette |
| Complessità | + ma concentrata in un owner unico (non sparsa nel loop) |

---

## 10. Gestione memoria (RAM + VRAM + durabilità)

Tre memorie, tre owner, tre cicli di vita — oggi confuse:
1. **Working state (RAM):** il fold corrente della FSM. Effimero, ricostruibile dal log. (Era `SystemState`.)
2. **KV (VRAM):** gestito dal BudgetManager (§9). Non è "memoria dell'agente", è cache d'inferenza.
3. **Durable (SQLite + Event Log su disco):** episodi, regressioni (`known-issues` machine-readable),
   e **il journal**. Questo dà la resumability che V1 non ha (V1-3). 8 GB RAM: il journal sta su disco, non
   in RAM; il working-state è piccolo (KB), il grosso della RAM la prende il processo Python + pyte + il
   client HTTP — bounded.

| asse | valutazione |
|---|---|
| Vantaggi | separazione netta effimero/durabile; recovery; nessun "filesystem come memoria" (invariante #1 rispettato *e* reso durevole dove serve) |
| Costo impl | medio (event log + fold) |
| RAM | **↓** rischio (journal su disco, working-state minimo) |
| VRAM | gestita esplicitamente |
| Complessità | neutra (sostituisce stato implicito con stato esplicito) |

---

## 11. Gestione errori

**Tassonomia** (estende `error_classifier`, che già vincola le recovery — invariante #4):
`TRANSIENT` (server restart, timeout, connection-refused) · `INVALID_OUTPUT` (raro, GBNF lo previene; resta
il caso `truncated`) · `TOOL_FAILED` (exit≠0 classificato) · `GUARD_REFUSED` (confinement/placeholder/mkdir —
**non fatale**, mappa a skip/redirect) · `PTY_STUCK` · `VRAM_PRESSURE` · `STATE_INCOHERENT`.

Ogni classe → **policy dichiarata**:
- `TRANSIENT` → **retry con backoff** (cap N), poi circuit-break.
- `TOOL_FAILED` → **RECOVER**: il coder ri-authora dal vero stderr (self-correction, RFC role-inversion),
  bounded; oltre il cap → REPLAN.
- `GUARD_REFUSED` → transizione deterministica (skip/redirect), **mai halt fatale** (fix deadlock).
- `INVALID_OUTPUT/truncated` → raddoppia il budget una volta, poi fallisce.
- `VRAM_PRESSURE` → compaction del contesto (§9), poi admission-fail.

Principio: **niente retry non bounded, niente loop implicito.** Ogni fallimento consuma un budget esplicito;
esaurito il budget si transita a FAILED *fast and loud*. Fix diretto a V1-2/V1-8.

---

## 12. Recovery (girare per settimane senza supervisione)

- **Crash di processo:** il journal su disco è la verità. Al restart, `fold(events) → last coherent FSM
  state → resume`. Un task non si perde per un crash Python o un OOM di `llama-server`. Fix a V1-3.
- **Restart di modello:** il Supervisor riavvia `llama-server`; il BudgetManager riammette; la FSM ritenta il
  nodo in corso (idempotenza: i nodi MODIFY dichiarano `rollback`, i DISCOVERY sono naturalmente ripetibili).
- **Incoerenza di stato:** un check periodico confronta il fold col filesystem reale; una divergenza è un
  evento `STATE_INCOHERENT` → re-observe → aggiorna belief (i REFUTED bloccano i retry — invariante #10).
- **Watchdog globale:** se la FSM non progredisce entro un budget (nessun evento in T), è un **livelock** →
  circuit-break del task, snapshot diagnostico, FAILED pulito.

**Test che lo prova sbagliato:** iniettare (fault injection) kill di `llama-server`, `kill -9` del processo
a metà DAG, e OOM simulato; il task deve **riprendere e completare** (o fallire pulito) senza intervento.
Se non riprende, il recovery è teatro.

---

## 13. Logging

Due canali distinti, come già in V1 (`trace` ≠ telemetry), formalizzati:
- **Event Log (structured, immutable, JSONL):** *la* fonte di verità. Ogni evento: `ts, fsm_state, kind,
  node_id, payload, causal_id`. È al tempo stesso audit, recovery, e input del replay dei test.
- **Human log (rich):** derivato, per l'operatore. Mai fonte di verità.

Regola: se un fatto guida una decisione, è un **evento**, non una riga di log umano (lezione da V1: la
recovery leggeva il messaggio sbagliato — vedi deadlock).

---

## 14. Telemetria (obbligatoria per l'autonomia)

Metriche minime per operare senza supervisione (V1-9):
- **Gauge:** `vram_used_mib`, `kv_used_per_slot`, `circuit_state{role}`, `ram_rss_mib`.
- **Counter:** `retries{class}`, `guard_refusals{kind}`, `replans`, `tool_failures{tool}`, `llama_restarts{role}`.
- **Histogram:** `latency_ms{stage}` (prefill/decode/tool/pty/fsm_state), `cache_hit_ratio{role}`, `tokens{role}`.
- **Derivate/allarmi:** VRAM > soglia → pre-compaction; circuit open → alert; livelock watchdog → snapshot.

Esposte via un endpoint locale (o file) scrapabile. Costo basso; senza queste, "gira per settimane" è cieco.

---

## 15. Testing

- **Transizioni FSM:** ogni transizione = un test unitario puro (input evento → nuovo stato). I god-object
  di V1 rendevano questo impossibile (V1-10).
- **Replay deterministico:** un test = un event-log registrato → rifai il fold → asserisci lo stato finale.
  Rende riproducibili anche i bug emergenti (il deadlock avrebbe avuto un replay-test).
- **Fault injection:** kill modello / OOM / tool-timeout / PTY-hang → asserisci recovery (§12).
- **Property-based sui predicati** e **golden-tests GBNF** (una griglia di grammatiche → mai output fuori-schema).
- **Contract tests** per ogni interfaccia di componente (sostituibilità: un fake Planner soddisfa il contratto).
- Mantieni la suite verde attuale (366) come rete; la V2 aggiunge i livelli sopra.

---

## 16. Benchmark

- Riusa `SISTEMISTA_DETERMINISTIC=1` (seed pinned, greedy) — un benchmark non riproducibile non misura nulla.
- **A/B pareggiato** (`benchmarks/ab_paired.py`) con potenza statistica: è il prerequisito, già segnato come
  debito #3, per decidere V2-vs-V1 e per il test #3 di RFC-001 (qualità 4B). **Rinforzare la misura viene
  prima di dichiarare qualunque vittoria.**
- KPI: scaffold-rate, tempo/caso, tok/s, cache-hit, **task-completati-senza-intervento su una corsa lunga**
  (il vero KPI dell'autonomia), OOM/1000-step, replan/task.

---

## 17. Scalabilità futura

- **Verticale (GPU più grande):** il BudgetManager rende trivialmente sfruttabile la VRAM extra (più ctx,
  più slot, un terzo modello) — è già una risorsa contabilizzata, non hardcoded.
- **Modelli intercambiabili:** l'Inference Layer dietro interfaccia rende il 4B/3B (o un futuro QLora/offload
  di RFC-001, o un modello più grande) uno swap di config, non una riscrittura.
- **Multi-box:** *non-obiettivo*. Ma i confini (event log, componenti dietro interfaccia) non lo precludono:
  il giorno che servisse, il journal diventa il punto di distribuzione. Non progettarlo ora (YAGNI), non
  murarlo fuori.

---

## 18. Verdetto pattern-per-pattern (il cuore: niente pattern per moda)

| Pattern | Verdetto | Perché (beneficio misurabile o costo netto) |
|---|---|---|
| **State Machine** | ✅ **ADOTTA** | elimina 2 god-function; abilita test-per-transizione e resume. Latenza 0, VRAM 0, complessità **↓**. |
| **Event Sourcing / Immutable Messages** | ✅ **ADOTTA** | recovery+replay+audit "gratis"; è l'unica via al "gira per settimane, recupera da crash". Disco, non RAM. |
| **Supervisor Tree (1 livello)** | ✅ **ADOTTA** | riavvio indipendente dei `llama-server` (obiettivo utente). Costo basso (quasi presente). |
| **Watchdog** | ✅ **ADOTTA** | uccide PTY-hang e decode runaway. Protegge la latenza di coda. |
| **Circuit Breaker** | ✅ **ADOTTA** | uccide i loop (deadlock/retry-infinito). Costo minimo. |
| **Retry Policy (bounded)** | ✅ **ADOTTA** | guasti TRANSIENT; sempre con cap → mai spin. |
| **Capability Registry** | ✅ **ADOTTA** (formalizza OCKE) | evita re-probe, grounda il modello (deterministic > LLM). |
| **Scheduler / Task Graph** | 🟡 **PARZIALE** | solo per DISCOVERY paralleli; falsificabile (§8). Serializza MODIFY. |
| **Async event loop (single-thread)** | ✅ **ADOTTA** | overlap inferenza‖tool‖PTY. NIENTE multithread (GIL/VRAM inutili). |
| **Dependency Injection (leggera)** | ✅ **ADOTTA** (constructor) | testabilità/sostituibilità. NON un framework DI. |
| **Worker Pool** | 🟡 **SOLO I/O** | un pool di *shell* bounded (~3) per probe indipendenti. Un pool di **LLM** è impossibile (VRAM) → **RIFIUTA**. |
| **Actor Model** | ❌ **RIFIUTA** | concorrenza bounded + mono-processo: le mailbox aggiungono latenza e complessità per zero throughput. La FSM+journal dà l'isolamento senza il costo. |
| **Message Bus** | ❌ **RIFIUTA** | nessun fan-out multi-consumer, nessuna distribuzione. Aggiunge indirection+latenza; il journal + chiamate dietro interfaccia bastano. |
| **CQRS** | ❌ **RIFIUTA** | nessuna asimmetria read/write da scalare. Separare i modelli è puro overhead qui. |
| **Plugin System (framework)** | ❌ **RIFIUTA** | tool-set piccolo e OS-specifico; il Capability Registry + interfaccia tool tipizzata bastano. Un framework a plugin è complessità senza domanda. |

Questo è il rispetto del vincolo utente ("ogni pattern deve avere un beneficio misurabile") e del mandato
runtime-first ("ogni astrazione deve cancellare complessità di runtime"). **4 pattern su 15 rifiutati** non
perché brutti, ma perché rispondono a problemi che questo box non ha.

---

## 19. Refactoring roadmap (strangler-fig, incrementale, ogni fase spedibile)

La V2 **non** è un rewrite big-bang (rischio massimo, valore differito). È uno strangolamento per fasi;
ognuna spedibile, misurata contro V1 con l'A/B pareggiato.

- **F0 — Misura prima.** Rinforza il benchmark (debito #3): potenza statistica, corsa-lunga-senza-intervento
  come KPI. Senza questo, ogni fase è indistinguibile dal rumore. *(Prerequisito di tutto.)*
- **F1 — Event Log + Telemetria (additivo, zero rischio).** Introduci il journal accanto a `trace` e le
  metriche §14. Non cambia comportamento; inizia a *vedere*. Sblocca il replay-test.
- **F2 — Inference Layer.** Estrai `ManagedServer` in ProcessSupervisor + Watchdog + CircuitBreaker +
  BudgetManager. Il pezzo più a rischio (VRAM) e più a valore. Testabile in isolamento.
- **F3 — FSM.** Estrai la macchina a stati da `_run_loop`; ogni stato è una funzione pura sul fold. Il
  deadlock mkdir muore qui (guard→skip). `_run_loop` si svuota progressivamente.
- **F4 — Componenti dietro interfaccia + DI.** Planner/Scheduler/ToolExecutor/Validator/Critic/Memory/Composer
  estratti da `_execute_step`. Il Validator ottiene il **veto** sul Critic (fix V1-4).
- **F5 — Scheduler DAG.** Solo se F0 mostra abbastanza DISCOVERY-parallelismo da ripagarlo. Altrimenti resta
  lineare con overlap I/O.
- **F6 — Recovery/resume dal journal + fault injection.** L'ultimo miglio dell'autonomia.

Ogni fase: append a `session.md`, riscrivi `handoff.md`, e **non procede** se l'A/B mostra regressione.

---

## 20. Il test che prova sbagliata questa RFC (§5, obbligatorio)

1. **Se, misurato, la V1 già regge una corsa-lunga-senza-intervento** (recovery da crash/OOM/PTY-hang) senza
   il journal → l'event-sourcing non ripaga il suo costo. (Previsione: falso — V1-3 lo impedisce per costruzione.)
2. **Se <15 % dei nodi è DISCOVERY-parallelizzabile** su un benchmark rappresentativo → lo Scheduler DAG (§8)
   è overengineering; degrada a lineare.
3. **Se la FSM non riduce le LOC** dei god-object o non aggiunge test di transizione verdi → non ha
   cancellato complessità → va rifiutata (mandato runtime-first).
4. **Se il BudgetManager non elimina gli OOM** su una corsa lunga (metrica `OOM/1000-step → 0`) → l'astrazione
   VRAM non ha mantenuto la promessa → ridiscutere §9.

Se uno di questi è vero dopo la misura, la parte corrispondente della V2 si ferma o si ridisegna. La misura
(F0) viene **prima** della vittoria, sempre.
