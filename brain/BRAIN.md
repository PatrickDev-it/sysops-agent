# BRAIN.md — kernel cognitivo di Sistemista

> **Piano strategico. Leggi questo _prima_ di [AGENTS.md](../AGENTS.md).** AGENTS.md ti dice _come_ costruire (operating contract). BRAIN.md ti dice
> _se_ e _cosa_ costruire. Kernel = orchestratore: non contiene conoscenza di dominio, contiene **quando** consultarla e **con quale potere di veto**.
> Introdotto da [RFC-0003](../.sinapsi/rfc/) · DEC-018.

---

## Cos'è (e cosa NON è)

Questo **non** è documentazione. È una **gerarchia decisionale persistente**. Prima di _ogni_ patch non banale, esegui la pipeline sotto: pensa come
un founder, poi come un principal engineer.

Il brain possiede il livello **strategico**. La verità **tecnica** resta del **codice** (un fatto → un
owner): i nodi `400/500/700/800/900` sono **pointer**, non copie. Se un file brain contraddice il codice,
vince il codice. Gli invarianti e il glossario hanno un owner testuale — [AGENTS.md](../AGENTS.md) — perché
sono le uniche cose che il codice non sa dire di sé.

---

## La pipeline di deliberazione (obbligatoria)

Ogni richiesta attraversa 6 gate, in quest'ordine. Un gate **VETO** può fermare tutto; un gate **ADVISORY** può solo condizionare il come. Se non hai
una risposta a un gate, **quello è il lavoro** — non saltarlo.

```
Richiesta
   │
   ▼
1. BUSINESS      ── VETO ──►  Vale la pena? Serve la north star? ───────────┐  no → STOP (motiva)
   │  [200_business]                                                        │
   ▼                                                                        │
2. PRODUCT       ── VETO ──►  Migliora il prodotto per la persona reale? ───┤  no → STOP (motiva)
   │  [300_product]                                                         │
   ▼                                                                        │
3. MARKET        ── ADVISORY  È un vantaggio (moat / DX)? Cosa fanno i ─────┤  debole → ridimensiona
   │  [100_market]            competitor? Cosa NON copiare?                 │
   ▼                                                                        │
4. ARCHITECTURE  ── VETO ──►  Come cambia l'architettura? Viola un ─────────┤  sì → STOP o RFC
   │  → AGENTS.md invarianti  invariante? (→ pointer 400)                   │
   ▼                                                                        │
5. ENGINEERING   ── ADVISORY  Qual è l'implementazione framework-neutral ───┤  copre un caso → astrai
   │  → AGENTS.md + codice    e minima? (→ pointer 500)                     │
   ▼                                                                        │
6. QUALITY       ── VETO ──►  Osservabile, debuggabile, testabile, ─────────┘  no → non è finito
      → AGENTS.md red flags   reversibile? Nessuna red flag?
   │
   ▼
Patch (poi: OBSERVE→HYPOTHESIZE→VERIFY→CHANGE→TEST di AGENTS.md)
```

**Regola di composizione:** il gate strategico (1-3) è a monte l'analogo cognitivo di `safety_gate.classify()` — come i goal DESTRUCTIVE sono
rifiutati prima della pianificazione (invariante 7), le richieste fuori-visione sono rifiutate prima dell'implementazione.

---

## Potere dei gate (i "pesi" come veto, non come float)

Un numero su un `.md` non attiva nulla in un LLM. Il "peso" di un nodo è il suo **potere di veto**:

| Gate         | Nodo                                                                   | Potere   | Regola di veto                                                                                              |
| ------------ | ---------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------- |
| Business     | [200_business/north-star.md](200_business/north-star.md)               | **VETO** | Se non serve la north star → non implementare.                                                              |
| Product      | [300_product/product-philosophy.md](300_product/product-philosophy.md) | **VETO** | Se non serve la persona reale, o rompe la promessa "terminal-only, autonomo" → no.                          |
| Market       | [100_market/moat.md](100_market/moat.md)                               | ADVISORY | Se non aumenta moat né DX → ammesso ma deprioritizzato. Se **copia** un competitor senza motivo → red flag. |
| Architecture | [400_architecture/README.md](400_architecture/README.md) → codice      | **VETO** | Se viola un [invariante](../AGENTS.md#invarianti-core) → STOP o RFC.                                        |
| Engineering  | [500_engineering/README.md](500_engineering/README.md) → AGENTS.md     | ADVISORY | Se introduce `if <framework>` o copre un caso → astrai (framework-neutrality).                              |
| Quality      | AGENTS.md → red flags                                                  | **VETO** | Silent failure / risultato parziale / non testabile → non è finito.                                         |

---

## Sequenza di attivazione (reading order del piano strategico)

All'inizio di un task strategico, attiva i nodi in quest'ordine — è il "priming" cognitivo:

```
000_identity  →  200_business/north-star  →  300_product/product-philosophy
      →  100_market/moat  →  research/competitors/index  →  thinking/first-principles
      →  [passa a AGENTS.md per il piano tecnico]
```

Per il piano _tecnico_ prosegui col reading order di [AGENTS.md](../AGENTS.md#reading-order) (session → handoff → reference → architecture → …). Il
brain non lo duplica.

---

## Mappa dell'albero

| Nodo                                   | Owner di…                                     | Tipo                                                          |
| -------------------------------------- | --------------------------------------------- | ------------------------------------------------------------- |
| [000_identity.md](000_identity.md)     | chi è (e chi NON è) Sistemista                | **owner**                                                     |
| [100_market/](100_market/)             | moat, competitor KB, go-to-market             | **owner**                                                     |
| [200_business/](200_business/)         | north star, roadmap strategica                | **owner**                                                     |
| [300_product/](300_product/)           | filosofia di prodotto, personas               | **owner**                                                     |
| [thinking/](thinking/)                 | first-principles, trade-off, failure patterns | **owner**                                                     |
| [400_architecture/](400_architecture/) | —                                             | **pointer** → [orchestrator.py](../workspace/src/orchestrator.py) + [invarianti](../AGENTS.md#invarianti-core) |
| [500_engineering/](500_engineering/)   | —                                             | **pointer** → [AGENTS.md](../AGENTS.md) + [config.py](../workspace/src/config.py) |
| [100_market/competitors/](100_market/competitors/) | — | **pointer** → [research/competitors/](research/competitors/index.md) |
| [research/competitors/](research/competitors/index.md) | competitive intelligence: schede tecniche + matrici + ranking | **owner** |
| [700_research/](700_research/)         | indice paper rilevanti al design              | **owner (index)**                                             |
| [architecture-next/](architecture-next/README.md) | design v2 (blackboard cognitiva + world model); da ratificare come RFC-0004 | **owner (design)** |
| [decision-engine/](decision-engine/README.md) | **Decision Engineering**: modelli tipizzati + engine deterministici che rendono ogni run una traccia cognitiva osservabile/confrontabile (DEC-ENG-v1) | **owner (metodologia)** |
| [800_decisions/](800_decisions/)       | —                                             | **pointer** → [.sinapsi/decisions.md](../.sinapsi/decisions.md) |
| [900_execution/](900_execution/)       | —                                             | **pointer** → [.sinapsi/session.md](../.sinapsi/session.md) + handoff |

Regola: se stai per scrivere in un nodo **pointer** un fatto tecnico, fermati — scrivilo dove sta l'owner
(il codice, o `AGENTS.md` per invarianti e termini) e linkalo. I nodi pointer contengono solo _rotte_, mai contenuto.
