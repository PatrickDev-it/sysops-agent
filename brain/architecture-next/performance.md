# performance.md

> Owner: **budget di token/latenza/RAM e il Model Router / Cost Optimizer.** Il vincolo di progetto: girare bene su
> **16GB RAM, CPU/GPU consumer, modelli locali 3B–8B**, con fallback cloud opzionale.

---

## I tre budget

| Risorsa | Budget di progetto | Leva principale |
|---|---|---|
| **Token/decisione** | p50 ≤1.5k, p95 ≤3k | Context Engine (compilazione minima) |
| **Latenza** | diagnosi comune competitiva con umano esperto | frugalità model-call + probe paralleli |
| **RAM** | ≤ ~12GB per il modello + resto per grafo/DB in 16GB | modelli quantizzati, grafo su disco+cache |

## Model Router / Cost Optimizer

Instrada ogni chiamata cognitiva al **modello più economico capace del task**, con escalation su fallimento/incertezza:

```
DETERMINISTIC  (0 token)   →  3B (giudizi semplici, prompt-detection ambigua)
     →  4B (pianificazione/diagnosi standard)  →  8B (incident complessi)  →  CLOUD (opt-in, ultimo miglio)
Escalation trigger: bassa confidence · schema-violation ripetuta · goal ad alto rischio.
```

Cascata/speculazione: tenta prima il modello piccolo; se l'output non valida allo schema o la confidence è bassa,
escala. Il costo medio resta basso perché la maggioranza dei task è servita da deterministico/3B/4B.

## Quantizzazione e memoria

Modelli **GGUF quantizzati** (Q4–Q5) per stare in 16GB; il World Model/experience su **SQLite** (disco) con cache in
RAM del sottografo caldo. Nessun servizio esterno pesante (no Postgres/vector-server obbligatori — differenza da
IronClaw). KV-cache riuso tra decisioni con contesto stabile (prompt-caching dove il runtime del modello lo supporta).

## Dove nasce la performance (non è micro-ottimizzazione)

La performance v2 viene dall'**architettura**, non da trucchi:
1. **Context Engine** → –40/–70% token vs ReAct (meno token = meno latenza + meno RAM di KV-cache).
2. **Cognitive scheduler** → il modello gira in ≤35% dei tick (il resto è deterministico, µs).
3. **Experience store** → salta pianificazione/recovery su casi noti (–1 model-call per hit).
4. **Probe paralleli** → latenza di diagnosi ~/N.

## Confronto competitor

- **Cloud agent (Claude Code, Codex, Gemini):** potenti ma dipendono da un datacenter; costo per-token reale e
  latenza di rete. Noi: **zero costo per-token, zero rete, dati sovrani** su hardware consumer.
- **Goose local:** local-first come noi, ma senza context-compilation né frugalità model-call → più token, più lento
  su modelli piccoli.
- **v1:** l'Issue #8 (parse-error 4B sotto contesto accumulato) è un *fallimento di performance/qualità* che il
  Context Engine elimina alla radice.

## Pattern

Cost-based routing · Model cascade / speculative execution · Budget enforcement · Quantization · KV-cache reuse ·
Parallelism (probe indipendenti) · Backpressure.

## Alternative scartate

- **"Usa sempre il modello più grande locale":** spreca RAM/latenza sui task banali; spesso non entra in 16GB. **Rifiutato.**
- **"Sempre cloud":** viola sovranità/offline (moat #3). **Rifiutato** come default (resta fallback opt-in).
- **Micro-ottimizzare il codice Python:** irrilevante — il costo è nei token del modello, non nel control-flow. **Rifiutato** come focus.

## Trade-off / Benchmark / Evoluzioni

Trade-off: la cascata aggiunge latenza quando *deve* escalare (tentativo piccolo + tentativo grande). Mitigato: il
router impara (dall'experience) quando partire direttamente dal modello grande per una classe di task. Benchmark:
token/task e model-call-ratio (telemetry). Evoluzioni: routing appreso, distillazione di un modello sysops-specifico,
batching di probe, prompt-caching aggressivo.
