# belief-system.md

> Owner: **il Fact e il Belief State (la blackboard).** L'unità atomica di tutto il sistema.
> Il *ciclo di vita* dei fatti → [state-engine.md](state-engine.md). L'*inferenza* → [reasoning-engine.md](reasoning-engine.md).

---

## Il Fact (unità atomica)

Niente nel sistema ragiona su testo. L'unità è il **Fact tipizzato**:

```
Fact {
  id:         FactId              # stabile, deduplicabile
  type:       env.os | capability.tool | entity.service | belief | plan.step | risk | verify | experience ...
  key:        str                 # es. "capability:docker", "entity:port:8080"
  value:      typed               # bool | path | version | struct — MAI blob di testo grezzo
  status:     OBSERVED | INFERRED | PROVEN | REFUTED | STALE
  confidence: 0.0–1.0
  provenance: { source_engine, command?, timestamp, cost_tokens? }
  ttl:        duration?           # dopo cui torna STALE (il mondo cambia sotto di noi)
  supersedes: FactId?             # versioning esplicito
}
```

**Perché tipizzato + provenienza:** (a) explainability (ogni decisione cita i Fact); (b) deduplicazione (un fatto
→ un id); (c) TTL — un sistema *vivo* cambia, un fatto vecchio non è verità (differenza chiave vs un repo di codice statico).

## Belief State (blackboard)

Insieme dei Fact del run corrente, indicizzato per `key` e `type`. È la **single source of truth in RAM** (eredita
l'invariante v1 "filesystem non è memoria"). Interfaccia:

```
assert(fact)            # via owner-engine; State Engine valida la transizione
query(type|key|pred)    # lettura per chiunque
resolve(key) -> value   # valore corrente vincente (max confidence, non STALE, non REFUTED)
provenance(FactId)      # catena causale
```

## Solo i belief PROVEN guidano l'esecuzione (invariante ereditato)

Un `belief` REFUTED **blocca** i retry che lo assumono (cura al loop infinito di v1). Un `belief` INFERRED può
guidare la *pianificazione* ma non un'azione distruttiva finché non è PROVEN da osservazione. Il Reasoning Engine
è l'unico owner delle transizioni di `belief`.

## Provenienza = grafo causale

`provenance` collega ogni Fact al comando/engine che l'ha prodotto → un **grafo causale** ispezionabile: "perché
hai riavviato nginx?" → belief `service:nginx = down` (PROVEN da `systemctl status`, exit 3) ← observation ← action.
Questo è l'audit trail che rende Sistemista *debuggabile* dove i competitor hanno solo log testuali.

## Confronto competitor

- **OpenHands** ha un event stream Action/Observation — ma **testuale**: il reasoning re-interpreta testo ad ogni
  passo. Noi promuoviamo l'osservazione a **Fact tipizzato una volta**, poi tutti leggono la struttura.
- **Aider** ha un repo-map ma **nessun belief state** dinamico del *runtime*. Il codice non muta sotto di te; un
  sistema sì → serve TTL/STALE, che loro non hanno.
- **v1** aveva `SystemState`+`ReasoningContext` (belief PROVEN/REFUTED): **giusta intuizione**, la manteniamo e la
  generalizziamo (tipizzazione forte, provenienza, TTL, single-owner per type).

## Pattern

Blackboard · Fact/Tuple space · Event sourcing (provenienza) · Versioned truth (supersedes) · Truth maintenance system (TMS) leggero.

## Trade-off

- Tipizzare tutto costa schema-design e parser (Observation Engine). Trade-off accettato: è la base di explainability
  e token-efficiency (il modello riceve struttura compatta, non testo prolisso).
- TTL introduce invalidazione → complessità. Ma senza, agiremmo su una mappa del sistema obsoleta: rischio reale in prod.

## Benchmark teorico

Un Fact tipizzato costa in media **5–15 token** in prompt vs **50–300 token** per l'equivalente testo grezzo di
terminale → il Context Engine impacca 1 ordine di grandezza più *segnale* nello stesso budget.

## Evoluzioni

Belief probabilistici con propagazione bayesiana della confidence · TMS completo con ritrattazione automatica ·
condivisione di Fact `capability.*`/`experience.*` tra host (fleet).
