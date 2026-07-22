# Goose (Block)

> **Fonte:** il Deep Research interno sugli agenti da terminale (§ Goose) + analisi propria.
> **Affidabilità:** ⚠️ Il report attribuisce Goose a "AAIF / Linux Foundation" e al repo `AAIF-Goose/goose`:
> **dubbio**. Goose è un progetto open-source di **Block** (repo reale: `block/goose`). L'architettura
> ACP/MCP e il loop descritti sono coerenti con la realtà. È **il competitor filosoficamente più vicino a noi**
> (local-first, model-agnostic, terminal-first).

---

## Overview

- **Cos'è:** agente AI on-machine, open-source, estendibile via extension (MCP), con CLI + desktop.
- **Mission:** un "ingegnere junior automatizzato" che esegue comandi, legge file, corregge errori.
- **Vision:** agente locale, model-agnostic, estendibile a qualsiasi tool via protocollo aperto.
- **Problema che risolve:** automazione di task di engineering end-to-end dal terminale, con self-correction.
- **Target:** sviluppatori/DevOps che vogliono un agente locale e componibile.
- **Anno:** open-sourced da Block (2024–2025).
- **Autori:** Block (ex-Square).
- **Licenza:** Apache-2.0.
- **Repository:** github.com/block/goose (il report cita erroneamente `AAIF-Goose/goose`).
- **Sito:** block.github.io/goose.

## Success Story

Crescita via posizionamento **terminal-first + local-first** e blog/Medium ("junior engineer automatizzato").
Report: ~50k★ (**da verificare**). Traino: brand Block, ecosistema MCP ampio (70+ estensioni citate),
supporto multi-provider LLM (15+). Canali: GitHub, Medium, dev community.

## Adozione

~50k★ (report, da verificare). >100 contributor (report). Ecosistema di 70+ estensioni MCP → segnale di
community attiva. Backing Block (fintech) = risorse stabili.

## Filosofia progettuale

- **Local-first:** gira sulla macchina dell'utente; model-agnostic.
- **Componibilità via MCP:** l'agente è un core sottile + estensioni intercambiabili.
- **Self-correction:** cattura errori dei tool come feedback per il modello.
- **Non vuole risolvere:** essere specializzato sysops (è generalista); il reasoning resta delegato all'LLM.
- **Risolve meglio:** orchestrare tool eterogenei via un unico loop agentico, con qualsiasi modello.

## Architettura

- **Interfaccia:** CLI + Desktop (Rust backend, UI multipiattaforma).
- **Nucleo agent (loop):** invia richiesta+lista-tool all'LLM → il modello restituisce tool-call JSON → Goose
  esegue → reinietta risultato → ripete fino a completamento.
- **Estensioni (MCP servers):** shell, file, web, memoria, DB, ecc.; built-in + esterne.
- **Context management:** sommarizzazione dei dati vecchi per risparmiare token.
- **LLM abstraction:** 15+ provider (OpenAI, Anthropic, Gemini, locali…).
- **ACP/MCP:** protocolli aperti per tool e interoperabilità.
- **Memory:** estensione dedicata opzionale (non belief-system formale).

## Engineering

Rust backend. Pattern: tool-registry via MCP, agent loop, provider abstraction, context compressor. Multi-OS CI.
Modularità alta (core + estensioni). Debito: qualità variabile delle estensioni esterne; ampiezza dell'ecosistema.

## Reverse Engineering

Perché MCP/ACP: disaccoppiare il core dai tool → estendibilità senza toccare il nucleo (Open/Closed). Perché
model-agnostic: non scommettere su un solo provider. Tradeoff accettato: la **recovery dipende dalla qualità
dell'LLM** (nessun error-classifier strutturato) → con LLM piccoli degrada a "prova finché passa". Ragionavano:
"il valore è nell'ecosistema di tool + neutralità, non in un reasoning engine proprietario".

## Analisi del codice

Rust idiomatico presumibile. Punti forti: modularità MCP, multi-provider, context compression. Punti deboli:
recovery non deterministica, sicurezza dell'esecuzione shell, dipendenza da estensioni di terzi. **Da confermare.**

## UX

CLI + Desktop; loop trasparente (mostra tool-call ed esiti); gestione errori come feedback; recipes/subagents.
Human-in-the-loop configurabile.

## AI Design

Loop tool-use guidato dall'LLM; context compression per long context; tool selection dal modello; self-correction
via errori reiniettati. Planning non separato dal reasoner. Memory come estensione.

## Sicurezza

**Punto debole dichiarato:** l'agente esegue comandi reali sul sistema → prompt malizioso o errore può
danneggiare l'ambiente. Raccomandato l'uso in sandbox/container. Nessun sandbox obbligatorio built-in forte.

## Performance

Rust efficiente; latenza dell'LLM scelto; context compression mitiga il costo token su progetti grandi;
possibili colli di bottiglia su repo enormi.

## Punti di forza

1. **Local-first + model-agnostic** (moat condiviso con noi). 2. Ecosistema MCP ricchissimo. 3. Context
compression. 4. Self-correction loop. 5. CLI+Desktop. 6. Backing Block.

## Debolezze

- **Recovery debole:** delegata all'LLM, nessun error-classifier → fragile con modelli piccoli.
- **Sicurezza esecuzione:** nessuna sandbox forte di default; rischio sul sistema reale.
- **Nessun modello del sistema ispezionabile:** stato = conversazione, non belief verificabili.
- **Generalista:** non specializzato sysops; qualità estensioni di terzi variabile.
- **Complessità:** molte dipendenze, superficie ampia.

## Cosa NON copiare

- **Delegare la recovery interamente all'LLM** → è esattamente il nostro moat #1 (reasoning esplicito,
  recovery vincolata dall'`error_classifier`, inv. 4). Copiare questo ci renderebbe come loro su modelli 3B/4B: fragili.
- **Esecuzione senza sandbox forte di default** → contro le nostre promesse di sicurezza.

## Cosa vale la pena copiare

- **MCP per l'estendibilità** → standard interoperabile; ottimo per tool esterni futuri.
- **Context compression / sommarizzazione** → utile per il nostro supervisor sotto contesto accumulato (Issue #8).
- **Local-first + model-agnostic come valore di prodotto** → validazione esterna del nostro moat #3.
- **Loop tool-call trasparente** → l'utente vede cosa fa (UX di fiducia).

## Opportunità

Chi lo supera: un agente local-first che **aggiunge il reasoning esplicito** che a Goose manca — belief system,
recovery vincolata, verifica per artifact. È precisamente la nostra posizione.

## Gap Analysis (vs Sistemista)

- **Avanti loro:** ecosistema MCP, maturità, multi-provider, desktop UX, context compression.
- **Avanti noi:** reasoning causale ispezionabile, recovery vincolata dall'errore, verifica per artifact,
  safety gate, framework/OS-neutrality via OCKE, specializzazione sysops.
- **Ci differenziamo:** Goose è "loop tool-use + LLM"; noi siamo "modello del sistema + belief PROVEN che guidano".
  Sullo **stesso terreno local-first**, vinciamo sulla *qualità del ragionamento sotto modelli piccoli*.

## Lessons Learned

- **Engineering:** MCP come confine di estensione è una scelta eccellente (Open/Closed) — adottabile.
- **AI:** senza un reasoning engine, con LLM piccoli si degrada a trial-and-error → conferma la nostra tesi.
- **Business:** local-first + neutralità è un posizionamento reale e apprezzato (non siamo soli, ma siamo migliori sul reasoning).
- **UX:** trasparenza del loop = fiducia.

## Fonti

- Deep Research interno sugli agenti da terminale §Goose (+ diagrammi mermaid architettura e agent-loop).
- Repository reale: github.com/block/goose · block.github.io/goose.
- **Da integrare:** doc estensioni/MCP, blog Block, verifica ownership (Block, non "AAIF").
