# IronClaw (NEAR AI)

> **Fonte:** il Deep Research interno sugli agenti da terminale (§ IronClaw).
> **Affidabilità:** 🔴 **NON VERIFICATO / PROBABILE ALLUCINAZIONE.** "IronClaw", "Agent OS" NEAR AI, eseguibile
> "Reborn", sandbox WASM, pgvector, lancio marzo 2026: **nessuna conferma indipendente**. Scheda mantenuta per
> completezza del corpus; ogni affermazione è *claim-da-report*. **Il valore reale qui è concettuale** (i pattern
> di sicurezza descritti sono sensati *a prescindere* dall'esistenza del prodotto).

---

## Overview *(claim-da-report, non verificato)*

- **Cos'è:** "Agent OS" open-source focalizzato sulla sicurezza, in orbita NEAR/Web3.
- **Mission:** eseguire agenti in modo sicuro e isolato, con memoria persistente e multicanale.
- **Vision:** un sistema operativo per agenti sicuro by design.
- **Problema che risolve:** eseguire tool di agenti senza compromettere il sistema (sandbox forte).
- **Target:** enterprise/Web3 attenti a sicurezza e privacy.
- **Anno:** *report:* marzo 2026.
- **Autori:** NEAR AI.
- **Licenza:** *report:* Apache-2.0.
- **Repository:** *report:* github.com/nearai/ironclaw (**da verificare**).

## Architettura *(claim-da-report — i pattern sono comunque interessanti)*

- **Sandbox WASM:** ogni tool gira in WebAssembly con permessi limitati (capability-based).
- **Segreti nel backend:** operazioni pericolose e credenziali confinate, mai esposte all'agente.
- **Allowlist endpoint:** protezione da prompt-injection verso servizi esterni.
- **Multicanale:** REPL + Web (SSE/WebSocket) + Slack/Telegram + gateway WebUI.
- **Automazione:** cron, webhook, contesti paralleli isolati, heartbeat monitoring.
- **Tool-building dinamico:** genera tool a runtime; connettività MCP.
- **Memoria persistente:** indice full-text + vettoriale (pgvector), ricerca ibrida, "identity files".

## Engineering *(claim-da-report)*

Rust + WebUI (Node), PostgreSQL/pgvector. Installazione pesante. Nessun dettaglio verificabile su qualità/test.

## Reverse Engineering *(concettuale, indipendente dall'esistenza)*

Il *ragionamento di design* attribuito è valido: se un agente esegue tool arbitrari, l'isolamento
**capability-based (WASM)** + i **segreti fuori dalla portata dell'agente** + **allowlist** sono le difese
corrette contro prompt-injection ed esfiltrazione. Tradeoff: peso d'installazione (Postgres, WASM runtime) in
cambio di sicurezza forte. È l'estremo "security-first" dello spettro.

## Analisi del codice

🔴 Impossibile: repo non verificato.

## Sicurezza *(il cuore concettuale della scheda)*

Modello **capability-based con sandbox WASM**: potenzialmente il più rigoroso del gruppo, *se reale*. Segreti nel
backend + allowlist = difesa contro injection/esfiltrazione. Questo è l'aspetto da studiare a prescindere.

## Punti di forza *(se reale)*

Sandbox WASM capability-based, protezione credenziali, multicanale, memoria ibrida (full-text+vettoriale).

## Debolezze *(se reale)*

Installazione pesantissima (Rust+Postgres+Node), setup complesso (OAuth/Slack/dominio), meno "terminal-centric"
(UI-driven), ecosistema Rust giovane, avvio lento — **e incertezza sull'esistenza**.

## Cosa NON copiare

- **Peso d'installazione enorme (Postgres+pgvector+Node)** → contro il nostro requisito "gira *sul* sistema da
  riparare, spesso una VPS nuda".
- **UI-driven / multicanale (Slack/Telegram)** → fuori dal nostro scope terminal-only.
- (Meta) **Non promuovere claim non verificati a fatti.**

## Cosa vale la pena copiare *(concettuale, alto valore)*

- **Sandbox capability-based per l'esecuzione dei tool** → il modello giusto per confinare comandi rischiosi;
  più elegante di una sandbox per-OS hard-coded (cfr. Codex). Da studiare per un futuro isolamento generalizzato.
- **Segreti fuori dalla portata del ragionatore** → principio applicabile: l'LLM non deve mai vedere le credenziali.
- **Allowlist per endpoint esterni** → difesa da injection.
- **Memoria ibrida full-text + vettoriale** → riferimento per un'eventuale evoluzione del nostro `episodic.db`.

## Opportunità

Lo spazio "agente sicuro" è reale, ma IronClaw (se esiste) lo occupa in modo *pesante e UI-centrico*. Uno spazio
aperto: **sicurezza forte + leggerezza terminale** — vicino a dove potremmo evolvere.

## Gap Analysis (vs Sistemista)

- **Avanti loro (concettualmente):** modello di sicurezza dell'esecuzione (WASM capability, secret isolation).
- **Avanti noi:** leggerezza, terminal-only, gira sul sistema reale, reasoning causale, verifica per artifact.
- **Ci differenziamo:** la loro sicurezza è *isolamento dell'esecuzione*; la nostra è *sicurezza del ragionamento*
  (safety gate, no placeholder, no overwrite). I due modelli sono **complementari**: potremmo adottare il loro
  isolamento capability-based mantenendo la nostra leggerezza.

## Lessons Learned

- **Security (concettuale):** capability-based sandbox + secret isolation + allowlist è il tridente difensivo
  corretto per agenti che eseguono — vale la pena studiarlo *anche se il prodotto non fosse reale*.
- **Metodo:** separare "idea di design valida" da "prodotto esistente" — qui la prima ha valore, il secondo è ignoto.

## Fonti

- Deep Research interno sugli agenti da terminale §IronClaw (**unica fonte, non verificata**).
- **Azione richiesta:** verificare github.com/nearai/ironclaw e la copertura stampa (il report cita Forbes) prima
  di trattare qualunque dettaglio come fatto.
