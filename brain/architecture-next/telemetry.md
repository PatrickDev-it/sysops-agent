# telemetry.md

> Owner: **il log append-only degli eventi e le metriche di prodotto (north-star).** Observability by design.
> Distinto dall'experience store ([learning-engine.md](learning-engine.md)): la telemetry *misura*, l'experience *insegna*.

---

## Principio: se non è misurato, non esiste

v1 ha ~90 file `telemetry/run_*.json` ma la north-star (Autonomous Resolution Rate) **non è mai aggregata** → si
ottimizza alla cieca. v2: la telemetry è **first-class**, con uno schema stabile e un aggregatore che produce le
metriche di [vision.md](vision.md).

## Event sourcing

Ogni evento significativo è un record immutabile append-only: `{ts, run_id, type, payload, cost_tokens, latency_ms,
provenance}`. Tipi: decision, model_call, action, observation, belief_transition, gate_decision, verify, recovery,
outcome. Da questo log si **ricostruisce** qualsiasi run (replay/time-travel debugging) e si derivano tutte le metriche.

## Le metriche che contano

| Metrica | Definizione | Perché |
|---|---|---|
| **ARR** | % goal chiusi PROVEN senza intervento umano | la north-star |
| **Tokens/task** (p50/p95) | costo cognitivo | fattibilità 3B–8B |
| **Model-call ratio** | chiamate-modello / tick | frugalità (target ≤35%) |
| **Time-to-diagnosis** | dall'obiettivo al belief causale PROVEN | qualità sysops |
| **Recovery success rate** | recovery riuscite / fallimenti | robustezza |
| **Gate precision** | CONFIRM/REFUSE appropriati | sicurezza |
| **Experience hit rate** | % decisioni servite dall'experience store | apprendimento |

## Explainability trace

Ogni run produce un **trace ispezionabile**: goal → belief chain → decisioni (con i Fact che le hanno alimentate) →
azioni → esiti. È l'output di debug primario e, ripulito, la spiegazione mostrata all'utente ("ecco cosa ho fatto e perché").

## Confronto competitor

- **OpenHands** logga l'event stream (buono) ma testuale, senza metriche di prodotto aggregate.
- **LangSmith** (ecosistema LangChain) mostra che l'observability degli agenti è un prodotto a sé → confermiamo che
  va progettata, non aggiunta dopo.
- **v1:** telemetry scritta ma non aggregata → l'anti-pattern che correggiamo.

## Pattern

Event sourcing · Structured logging · Metrics pipeline (raccolta→aggregazione→dashboard) · Distributed tracing
(per la fleet) · Provenance trace.

## Alternative scartate

- **Log testuali non strutturati:** non aggregabili, non replayabili. **Rifiutato.**
- **Telemetry come dettaglio implementativo aggiunto a fine progetto:** è come è nato il problema v1. **Rifiutato** —
  è first-class dal giorno 1.

## Trade-off / Benchmark / Evoluzioni

Trade-off: event sourcing genera volume → retention/rotazione (i `run_*.json` vanno gestiti/ignorati dal VCS, non
versionati come in v1). Benchmark: da ogni run derivano tutte le metriche senza strumentazione ad-hoc. Evoluzioni:
dashboard locale, export OpenTelemetry, aggregazione di fleet, A/B test di prompt/policy misurati su ARR.
