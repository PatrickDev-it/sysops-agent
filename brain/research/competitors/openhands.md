# OpenHands (ex-OpenDevin)

> **Fonte:** il Deep Research interno sugli agenti da terminale (§ OpenHands) + analisi propria.
> **Affidabilità:** ⚠️ Il report dice "backend Django/Flask" → **impreciso** (OpenHands usa FastAPI + Python).
> La descrizione "orchestratore multi-agente / Agent Canvas" mescola il progetto OSS con feature cloud
> commerciali di All Hands AI: distinguere. Il cuore reale è **event stream (Action/Observation) + runtime in
> sandbox Docker + agente CodeAct**. OpenDevin = nome precedente (stesso progetto → vedi [opendevin.md](opendevin.md)).

---

## Overview

- **Cos'è:** piattaforma open-source per agenti di sviluppo software autonomi.
- **Mission:** un agente che scrive codice, esegue comandi, naviga il web — "less coding, more creating".
- **Vision:** democratizzare gli agenti dev; leadership su benchmark (SWE-bench).
- **Problema che risolve:** risoluzione autonoma di issue/task di sviluppo end-to-end.
- **Target:** ricercatori, dev, aziende che vogliono automazione di engineering.
- **Anno:** marzo 2024 (come OpenDevin).
- **Autori:** All Hands AI + community accademica (ricercatori LLM).
- **Licenza:** MIT.
- **Repository:** github.com/All-Hands-AI/OpenHands.
- **Sito:** all-hands.dev · docs.all-hands.dev.

## Success Story

Nato come **OpenDevin** (risposta open a Devin di Cognition) marzo 2024; viralità immediata cavalcando l'hype
Devin. Rebranding in **OpenHands**. Milestone 1 anno (mar 2025): ~50k★, ~250 contributor (report). AMA su HN,
guida accademica, leadership **SWE-bench** come motore di crescita credibile. Canali: HN, GitHub trending, paper.

## Adozione

~50k★, ~250 contributor (report; plausibile, OpenHands è tra i più grandi). Backing All Hands AI (funding).
Adozione enterprise via cloud offering. Community accademica forte (paper CodeAct, benchmark).

## Filosofia progettuale

- **Agent-as-event-stream:** ogni passo è Action → Observation, log completo e riproducibile.
- **Code-as-action (CodeAct):** unificare lo spazio d'azione in codice eseguibile invece di N tool discreti.
- **Sandbox obbligatoria:** esecuzione in container per isolamento.
- **Non vuole risolvere:** essere leggero/minimale (è una piattaforma pesante).
- **Risolve meglio:** task di sviluppo complessi multi-step con esecuzione reale e riproducibilità.

## Architettura

- **Event stream:** spina dorsale Action/Observation; l'agente emette Action, il runtime risponde con Observation.
- **Runtime/sandbox:** container Docker isolato per eseguire codice/comandi.
- **Agent (CodeAct):** azione = snippet di codice (bash/python) → spazio d'azione unificato e potente.
- **Front-end:** UI web (React+TS) per conversazione, file, terminale.
- **Server:** Python (FastAPI), gestione sessioni, runtime, integrazioni (GitHub resolver, ecc.).
- **Microagents:** istruzioni/knowledge attivate per contesto.
- **Multi-provider LLM:** via LiteLLM (Anthropic, OpenAI, locali…).

## Engineering

Python (server/agent) + TypeScript (UI). Pattern: event-driven, plugin agent, runtime pluggable (Docker/remote/local).
Testing: forte pressione da SWE-bench (valutazione empirica continua). Modularità: agent ↔ runtime ↔ event stream
disaccoppiati. Debito: complessità (Docker, molte dipendenze, UI+server+runtime).

## Reverse Engineering

Perché event stream: rende il loop **osservabile e riproducibile** (log completo → debug + benchmark). Perché
CodeAct: un LLM che scrive codice è più espressivo di N tool discreti (meno gabbie, più potenza). Perché Docker
sandbox: sicurezza + riproducibilità dell'ambiente. Tradeoff: **peso e complessità** in cambio di potenza e
rigore scientifico. Ragionavano da **ricercatori**: ottimizzano SWE-bench e riproducibilità, non minimalismo.

## Analisi del codice

Codebase ampia e attiva. Punti forti: astrazione event-stream pulita, runtime pluggable, pressione empirica.
Punti deboli: superficie enorme (UI+server+runtime+integrazioni), setup pesante (Docker obbligatorio), curva
ripida. Debito legato alla velocità di ricerca. Qualità generalmente alta per gli standard OSS-accademici.

## UX

UI web + terminale integrato; conversazione con log delle azioni; GitHub issue resolver. Setup non banale
(Docker). Human-in-the-loop presente ma orientato all'autonomia.

## AI Design

CodeAct (code-as-action); planning emergente dal loop ReAct-like; self-correction via Observation (traceback →
fix); microagents come knowledge iniettata; multi-provider. Stuck-detection euristica. Memoria = event stream + condensazione.

## Sicurezza

**Sandbox Docker obbligatoria** = buon isolamento dell'esecuzione. Superficie ampia (web UI, API, integrazioni
di terze parti, runtime remoto). Gestione chiavi/segreti da curare. L'agente scrive ed esegue codice arbitrario:
l'isolamento del container è la difesa primaria.

## Performance

Overhead del container e della UI; latenza LLM; riproducibilità > velocità. Non ottimizzato per leggerezza.

## Punti di forza

1. **Event stream Action/Observation** (osservabilità/riproducibilità). 2. CodeAct (spazio d'azione potente).
3. Sandbox Docker. 4. Leadership SWE-bench (credibilità). 5. Multi-provider. 6. Community accademica.

## Debolezze

- **Superficie enorme:** UI+server+runtime+integrazioni → complessità e debito.
- **Peso operativo:** Docker obbligatorio, setup non banale → attrito per un uso "da terminale".
- **Espansione di scope:** web/GUI/integrazioni → si allontana dal terminale puro.
- **Overhead:** container + UI = non adatto a interventi leggeri e rapidi.
- **CodeAct = potere pericoloso:** codice arbitrario eseguito; senza sandbox sarebbe insostenibile.

## Cosa NON copiare

- **L'espansione verso web/GUI/multi-integrazione** → noi siamo terminal-only e focalizzati (identità).
- **Docker obbligatorio per funzionare** → attrito inaccettabile per un tool sysops che deve girare *sul* sistema
  che ripara (spesso una VPS senza Docker). Noi ragioniamo per capability dell'OS reale, non in un container astratto.
- **Ottimizzare un benchmark come stella polare** → rischio di over-fitting travestito da generalità.

## Cosa vale la pena copiare

- **Event stream Action → Observation come contratto esplicito** → rende il loop osservabile; ottimo modello
  mentale per il nostro observer/verify (allineato inv. 9 artifact check).
- **CodeAct (azione = codice)** → idea potente; noi ne abbiamo una versione vincolata (step tipizzati) — studiare
  il tradeoff espressività vs sicurezza.
- **Sandbox per operazioni rischiose** → principio di isolamento (adottabile per comandi distruttivi).
- **Pressione empirica continua (benchmark)** → avere una metrica osservata, non dedotta.

## Opportunità

Chi lo supera in *sysops*: un agente **leggero, senza Docker obbligatorio, che gira sul sistema target** e
ragiona sulle sue capability reali. OpenHands è potente ma pesante: lo spazio "leggero + locale + causale" è aperto.

## Gap Analysis (vs Sistemista)

- **Avanti loro:** potenza (CodeAct), riproducibilità (event stream), community, benchmark, runtime pluggable.
- **Avanti noi:** leggerezza (no Docker obbligatorio), esecuzione *sul* sistema reale, reasoning causale
  ispezionabile, verifica per artifact nativa, framework/OS-neutrality, focus sysops, safety gate a monte.
- **Ci differenziamo:** OpenHands è una *piattaforma di ricerca per dev agent*; noi un *agente sysops chirurgico*.
  Prendiamo la loro idea di event-stream/observability senza la loro superficie.

## Lessons Learned

- **Engineering:** disaccoppiare agent ↔ runtime ↔ event-stream è un design pulito e osservabile → adottare il principio.
- **AI:** code-as-action è espressivo ma va confinato (sandbox) — conferma che potere ⇒ isolamento.
- **Business:** cavalcare un hype (Devin) come alternativa *open* è una leva di crescita potente.
- **Community:** benchmark pubblici + rigore accademico = credibilità difendibile.

## Fonti

- Deep Research interno sugli agenti da terminale §OpenHands (+ timeline mermaid: lancio OpenDevin 2024-03, AMA HN,
  milestone 1 anno).
- Repository reale: github.com/All-Hands-AI/OpenHands · docs.all-hands.dev.
- Paper: CodeAct ("Executable Code Actions Elicit Better LLM Agents").
- **Da integrare:** verifica stack (FastAPI, non Django/Flask); separare OSS da cloud offering.
