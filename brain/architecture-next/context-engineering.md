# context-engineering.md

> Owner: **il compilatore di contesto.** Il documento più importante dopo l'architettura: qui si vince o si perde
> la battaglia dei token, cioè la fattibilità su modelli 3B–8B. *Il prompt è un artefatto compilato, non scritto.*

---

## Principio: il contesto è memoria, e la memoria è cara

Un LLM è una CPU senza RAM persistente: il **context window è l'unica memoria di lavoro**, ed è la risorsa più
costosa (token = latenza + $ + degrado qualità oltre una certa densità). La regola aurea:

> **Non caricare mai tutto. Derivare il contesto minimo sufficiente per *questa* decisione.**

Il **Context Engine** è un **compilatore**: sorgente = (task cognitivo + belief state + world model + esperienza);
target = un prompt tipizzato sotto un **token budget** duro. Come un compilatore fa instruction selection e register
allocation, noi facciamo **fact selection** e **token allocation**.

## I pass del compilatore

```
compile(cognitive_task) -> Prompt:
  1. SCOPE     Determina cosa serve al task (Planner? Reasoner? Recovery?) → schema di slot richiesti.
  2. RETRIEVE  - World Model: query del sottografo rilevante al goal (ranked, depth-limited).
               - Knowledge Graph: comandi/capability validi per l'OS corrente per gli intenti in gioco.
               - Experience: 1–3 esperienze per signature (failure/pattern/recovery).
               - Belief: solo i Fact PROVEN/relevant al sotto-goal (mai tutto lo stato).
  3. RANK      Ordina i candidati per rilevanza = f(distanza-dal-goal, confidence, freschezza, costo-token).
  4. BUDGET    Packing zaino sotto budget: massimizza rilevanza/token. Ciò che non entra → riassunto o citato per-riferimento.
  5. COMPRESS  Fatti tipizzati → forma tabellare/compatta (non prosa). Dedup. Elide il noto-al-modello.
  6. RENDER    Template minimale per il task; registra la provenienza (quali Fact sono entrati → explainability).
```

## Budget e allocazione (esempio)

```
Task: Recovery dopo "systemctl restart nginx" fallito. Budget totale: 2048 token.
  system/role        120   (fisso, minimale)
  goal + sub-goal      60
  env (os/shell/priv)  40   (Fact compatti)
  world subgraph      380   (nginx + port:443 + config + user + dep openssl)  ← query, non dump
  capabilities         90   (systemctl, journalctl disponibili; openssl assente)
  error (typed)        70   (error-class: unit-failed + exit 3 + prima riga journal)
  experience          180   (1 recovery-DB hit: stessa signature risolta con `nginx -t` prima del restart)
  output schema       120
  ------------------------------------------------
  ~1060 token → resta headroom.  Un ReAct loop qui infilerebbe l'intero journalctl (~8k).
```

## Perché batte tutti (il confronto che conta)

| Approccio | Come gestisce il contesto | Costo | Fragilità su 3B/4B |
|---|---|---|---|
| **Sistemista v2** | compilato, minimo, tipizzato, ranked | **basso** | **bassa** |
| Aider | repo-map rankato (codice) | medio | media |
| OpenHands | event stream cresce | alto | alta |
| Cline/Codex/Goose | history + file letti nel prompt | alto | alta |
| v1 | contesto accumulato → parse-error 4B (Issue #8) | alto | **alta (osservata)** |

Nota su v1: l'Issue #8 (il 4B va in parse-error sotto contesto accumulato) **è esattamente il fallimento che questo
componente elimina**: il modello non vede mai contesto accumulato, solo il compilato minimo del passo corrente.

## Anti-allucinazione by construction

Il modello riceve i **fatti** (dal World Model/KG), non deve *ricordarli*. Se un fatto non è nel belief/mappa, il
Context Engine lo segna esplicitamente come *unknown* → il modello è istruito a **chiedere un probe** (gap → System
Mapper), non a inventare. (v1 T060: inventava `wsl --install -d Docker Desktop`; qui: capability:docker = MISSING è
un Fact, la diagnosi è ancorata.)

## Pattern software / AI

Compiler passes · Knapsack/budget packing · Learned/heuristic ranking (à la Aider repo-map, ma sul world graph) ·
Retrieval-augmented generation *strutturato* · Prompt-as-artifact (compilato + versionato + tracciato) · Elision del noto.

## Alternative scartate

- **Prompt statico ricco ("mettiamo tutto quello che potrebbe servire"):** brucia budget, degrada qualità, non scala
  su 3B. **Rifiutato** — è l'anti-pattern.
- **RAG generico su vector store di output:** recupera testo simile, non struttura causale rilevante; niente budget
  discipline. **Rifiutato** come primario (embedding solo per fuzzy fallback).
- **Lasciar decidere al modello cosa caricare (tool "read_context"):** costa round-trip e token, e delega al 4B una
  scelta che una funzione di ranking fa meglio e gratis. **Rifiutato.**

## Trade-off

- Un compilatore di contesto è codice *nostro* sofisticato (ranking, budget). Ma è **deterministico, testabile,
  misurabile** — al contrario del "prompt engineering" a mano. È dove investiamo, perché è il moat token-efficiency.
- Ranking imperfetto può omettere un fatto rilevante → mitigazione: il ciclo cognitivo è iterativo (se manca, emerge
  un gap → si recupera al giro dopo), e il ranking migliora dall'esperienza.

## Benchmark teorico

Obiettivo di progetto: **p50 ≤ 1.5k token/decisione**, **p95 ≤ 3k**, indipendente dalla durata del task (il contesto
non cresce con la history). Questo è il numero che rende un **4B locale competitivo con un agente cloud**.

## Evoluzioni

Ranking appreso dall'experience store · budget adattivo per capacità del modello (3B→budget più stretto) · caching
del contesto compilato per sotto-goal ricorrenti · "context diff" (invia solo il delta rispetto al passo precedente
quando il provider supporta prompt-caching).
