# execution-engine.md

> Owner: **dispatch delle azioni: atomicità, idempotenza, scheduling, timeout, concorrenza.** L'Executor
> ([executor.md](executor.md)) *esegue* la singola azione; l'Execution Engine decide *quali/quando/come* e ne
> garantisce le proprietà transazionali.

---

## Responsabilità

- **Ready-set:** prende dal DAG di piano ([planning-engine.md](planning-engine.md)) i nodi con precondizioni
  soddisfatte → li schedula.
- **Idempotenza:** se gli `expected_effects` di un'azione sono già Fact PROVEN, **skip** (non ri-eseguire). Es. "avvia
  nginx" quando `service:nginx = RUNNING` → no-op.
- **Atomicità e rollback:** azioni con side-effect reversibili possono essere annullate se la verifica fallisce
  (snapshot dello State Engine + azione inversa dal Knowledge Graph, dove esiste).
- **Timeout/long-running:** classifica i comandi (one-shot vs server/dev vs streaming) e applica cap deterministici
  (generalizza il fix v1 sui dev-server che non ritornano mai).
- **Concorrenza:** azioni indipendenti (probe diagnostici) in parallelo; azioni con dipendenza serializzate.

## Perché separato dall'Executor

L'Executor è un adapter stupido (un'azione → bytes). L'Execution Engine è la **logica di controllo dell'esecuzione**
(quali azioni, in che ordine, con quali garanzie). Separarli = un solo posto per idempotenza/rollback/scheduling
(testabile), e un Executor sostituibile (locale, SSH, sandbox) senza toccare la logica.

## Interazione col resto

```
Planning Engine ──DAG──► Execution Engine ──Action──► Executor ──bytes──► Observation ──Fact──► State Engine
      ▲                        │ gate                                                              │
      └────re-plan locale──────┴──► Policy/Safety Engine (risk gate prima di ogni Action) ◄────────┘
```

## Confronto competitor

- **OpenHands:** runtime pluggable (Docker/local/remote) è un ottimo riferimento per l'Executor; ma non hanno
  idempotenza/rollback dichiarativi basati su effetti tipizzati.
- **Ansible/Terraform (fuori dal gruppo AI, ma rilevante):** idempotenza dichiarativa è il loro cuore → la portiamo
  *dentro* un agente AI: gli effetti dichiarati rendono le azioni ri-eseguibili in sicurezza. Nessun agente AI lo fa.
- **v1:** esecuzione (`_run_batch`/`_run_interactive`/`_run_fileops`) mescolata nell'orchestrator, senza idempotenza
  né rollback. **Anti-esempio** che questo componente risolve.

## Pattern

Scheduler / work queue · Idempotent operations (dichiarative) · Saga/compensation (rollback) · Bulkhead
(isolamento azioni concorrenti) · Circuit breaker (stop su loop/anomalie, come lo stuck-detector PTY di v1).

## Alternative scartate

- **Esecuzione sequenziale semplice (v1):** niente parallelismo dei probe, niente idempotenza → lento e non sicuro
  alla riesecuzione. **Rifiutato.**
- **Idempotenza "sperata" dal modello:** il modello non garantisce nulla. **Rifiutato** — idempotenza *strutturale*
  dagli effetti dichiarati.

## Trade-off / Benchmark / Evoluzioni

Trade-off: rollback richiede azioni inverse (non sempre esistono) → dove mancano, si degrada a "confirm prima di
agire" (Safety Engine). Benchmark: probe diagnostici paralleli → latenza di diagnosi ~/N. Evoluzioni: transazioni
distribuite su fleet, dry-run/simulazione delle azioni ad alto rischio, esecuzione speculativa con commit ritardato.
