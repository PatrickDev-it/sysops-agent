# memory.md

> Owner: **la gerarchia di memoria e l'experience store.** Il belief *corrente* è in [belief-system.md](belief-system.md);
> qui c'è la memoria *nel tempo* (dentro il run e tra i run). Alimenta il [context-engineering.md](context-engineering.md)
> e il [learning-engine.md](learning-engine.md).

---

## Perché gerarchica

Come una gerarchia di cache (registri→L1→L2→RAM→disco), la memoria di un agente ha livelli con costo/latenza/scope
diversi. Confondere i livelli (v1: memoria "episodica" + facts + cache mescolati) causa duplicazione e prompt gonfi.
Un livello → un owner → un uso.

```
                       scope        durata        supporto        chi la usa
 Working Memory        1 decisione  effimera      RAM (belief)    Context Engine (input immediato)
 Task Memory           1 goal       run           RAM             Planner, Reasoning
 Session Memory        1 sessione   sessione      RAM+disco       continuità multi-goal
 Execution History     1 run        persistente   append log      Telemetry, replay
 Semantic Memory       cross-run    persistente   Knowledge Graph  Planning (conoscenza OS)
 Long-Term / Experience cross-run   persistente   3 DB (sotto)     Learning → Context
```

## L'Experience Store (il cuore del "learning senza training")

Tre database indicizzati per **signature strutturale** (OS · shell · tool · error-class · goal-intent), *non* per
testo:

| DB | Chiave | Valore | Uso |
|---|---|---|---|
| **Failure DB** | signature dell'errore + contesto | cosa è stato tentato e ha fallito | evita di ripetere errori |
| **Pattern DB** | signature della situazione/goal | template di piano che ha funzionato | pianifica più veloce/meglio |
| **Recovery DB** | error-class + contesto | la recovery che ha risolto | recupero mirato, non a caso |

Retrieval: dato il goal+belief corrente, il Context Engine interroga per **signature** e inietta *solo* le 1–3
esperienze più rilevanti. È **case-based reasoning**, non fine-tuning: il modello resta piccolo, l'esperienza è dati.

## Perché signature, non embedding

Un vector store recupera "testo simile"; noi vogliamo "*strutturalmente* lo stesso problema" (stesso OS+error-class+
tool). Una signature (`linux:systemd:port-in-use:8080`) è **esatta, spiegabile, deduplicabile** e costa zero
inferenza. Embedding come *fallback* per il fuzzy match, non come primario. (Differenza netta vs RAG generico.)

## Confronto competitor

- **Aider/Cline/Codex:** memoria = history di chat + git/checkpoint. Nessuna esperienza *trasferibile* tra task.
- **Goose:** estensione "memory" opzionale, ma non un experience store strutturato per sysops.
- **Nessuno** ha Failure/Pattern/Recovery DB per il dominio sistemi. È un **moat**: più Sistemista opera, più diventa
  bravo *su quel parco macchine*, senza training.
- **v1:** aveva `episodic.db` (events, regressions, failed_assumptions, causal_edges) — intuizione giusta, ma
  indicizzata debolmente e non chiaramente separata dal belief corrente. La rendiamo un livello *distinto* con signature.

## Pattern

Memory hierarchy · Case-based reasoning · Experience replay (senza gradient) · Signature indexing · Write-behind
(l'esito del run confluisce nell'experience store a fine goal).

## Alternative scartate

- **Un unico store "memoria" piatto (v1-ish):** mescola scope → duplicazione e recupero rumoroso. **Rifiutato.**
- **Fine-tuning continuo sul parco macchine:** costoso, non locale-friendly, rischio di dimenticanza catastrofica,
  non spiegabile. **Rifiutato**: l'esperienza deve essere *dati ispezionabili*, non pesi.
- **Solo vector store:** perde esattezza strutturale. **Rifiutato** come primario.

## Trade-off

- Signature richiedono uno schema di normalizzazione (error-class ontology dal KG). Investimento ripagato da recupero
  esatto e a costo zero.
- L'experience cresce → serve pruning/decay (confidence che scende se un pattern smette di funzionare).

## Benchmark teorico

Su task ricorrenti, un hit nel Pattern DB **salta la pianificazione col modello** (–1 chiamata 4B/8B) e nel Recovery
DB **evita il flailing** di v1 (T070: da 6+ tentativi random a 1 mirato). Target: dopo N run su un host, ARR ↑ e
token/task ↓ monotonicamente.

## Evoluzioni

Experience federata tra installazioni (playbook di community verificati) · decay temporale · meta-pattern (pattern di
pattern) · export dell'esperienza come *runbook* leggibile dall'umano.
