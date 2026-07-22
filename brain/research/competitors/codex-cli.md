# Codex CLI (OpenAI)

> **Fonte:** il Deep Research interno sugli agenti da terminale (§ OpenAI Codex CLI) + analisi propria.
> **Affidabilità:** ⚠️ Correzioni importanti. Il report dice "no planning loop, è un chatbot" → **falso**: Codex
> CLI è agentico con approval modes e sandbox. Sul linguaggio: nato in **TypeScript/Node (apr 2025)**, poi
> **riscritto in Rust** (metà 2025) → il "96% Rust" del report riflette la versione post-rewrite. Le versioni
> tardo-2026 del report non sono verificate.

---

## Overview

- **Cos'è:** agente di coding open-source da terminale di OpenAI.
- **Mission:** rendere i modelli OpenAI (o-series / GPT-5-codex) eseguibili localmente nel terminale con azioni reali.
- **Vision:** un pair-agent locale che legge, edita ed esegue nel repo con controllo dei permessi.
- **Problema che risolve:** coding agentico end-to-end (leggi→modifica→esegui→correggi) senza IDE.
- **Target:** sviluppatori OpenAI/ChatGPT che vogliono azione locale, non solo chat.
- **Anno:** aprile 2025 (TS), rewrite Rust metà 2025.
- **Autori:** OpenAI.
- **Licenza:** Apache-2.0.
- **Repository:** github.com/openai/codex.
- **Sito:** developers.openai.com / pagina Codex.

## Success Story

Traino del **brand OpenAI** e dell'onda "coding agent". Adozione forte in community (il report cita ~95k★,
plausibile per un repo OpenAI di punta ma **da verificare**). Il rewrite in Rust ha segnato un momento chiave:
da prototipo Node a tool performante e distribuibile come binario. Canali: GitHub, Hacker News, dev Twitter.

## Adozione

Report: ~95k★. **Da verificare.** Ecosistema OpenAI = adozione enterprise indiretta. Contributor/PR non dichiarati.

## Filosofia progettuale

- **Modello-first:** l'intelligenza è nel modello OpenAI; la CLI è un guscio agentico sicuro.
- **Controllo esplicito:** approval modes (suggest / auto-edit / full-auto) → l'utente decide l'autonomia.
- **Sandbox by default:** esecuzione confinata (seatbelt su macOS, landlock/seccomp su Linux).
- **Non vuole risolvere:** offline / provider-neutralità (legato a OpenAI).
- **Risolve meglio:** coding agentico con guardrail di sicurezza sull'esecuzione.

## Architettura

- **Loop agentico:** il modello propone azioni (patch, comandi); Codex le applica secondo l'approval mode.
- **Executor:** applica diff ed esegue comandi in **sandbox**; reinietta output/errori.
- **Approval policy:** livello di autonomia configurabile (chiave di design).
- **Context:** `AGENTS.md` come istruzioni persistenti; config in `config.toml`.
- **MCP:** supporto server MCP.
- **LLM abstraction:** legata a OpenAI (o3/o4-mini/GPT-5-codex).
- **Sandbox/Security:** seatbelt (macOS), landlock+seccomp (Linux) → isolamento OS-level nativo.

## Engineering

Post-rewrite: **Rust** (~96%), distribuito via `cargo`/binari. Pattern: state machine dell'approval, executor
sandboxed, tokenizer/network/TUI moduli. Rust → performance, binario singolo, memory safety. CI Rust.

## Reverse Engineering

Perché Rust: distribuzione come binario, performance, sicurezza di memoria per un tool che esegue comandi.
Perché sandbox OS-native invece di Docker: latenza minima e zero dipendenza da Docker per l'utente. Tradeoff:
sandbox OS-specifica (seatbelt/landlock) = più codice per-OS, ma UX migliore (niente container obbligatorio).
Ragionavano: "un coding agent che esegue deve essere sicuro *per default* e installabile ovunque".

## Analisi del codice

Rust idiomatico presumibile (team OpenAI). Punti forti: sandbox nativa, approval model, performance. Punti
deboli: legame stretto con l'API OpenAI; il rewrite TS→Rust ha lasciato probabilmente aree in transizione.
Debito: mantenere due paradigmi di sandbox OS-specifici. **Da confermare sul repo.**

## UX

TUI da terminale, streaming, diff review prima dell'applicazione, approval modes. Error UX: output comando
reiniettato. Human-in-the-loop calibrabile (da conferma-ogni-passo a full-auto).

## AI Design

Planning implicito nel modello o-series (reasoning models); self-correction via output sandbox; retry guidato
dall'errore. Tool selection dal modello. Nessuna memoria persistente cross-task oltre `AGENTS.md`.

## Sicurezza

**Punto di forza distintivo.** Sandbox OS-native (seatbelt/landlock/seccomp), approval modes, diff-review.
Superficie: API key OpenAI, comandi eseguiti (mitigati da sandbox). Modello di sicurezza tra i migliori del gruppo.

## Performance

Rust → avvio rapido, basso overhead locale. Latenza dominata dall'API OpenAI. Consumo token del modello.

## Punti di forza

1. Sandbox OS-native (sicurezza reale). 2. Approval modes (autonomia calibrabile). 3. Rust performante/binario.
4. Brand + modelli OpenAI forti. 5. MCP + AGENTS.md. 6. Diff-review UX.

## Debolezze

- **Lock-in OpenAI:** nessuna provider-neutralità; costo/limiti token.
- **No offline:** reasoning nel cloud.
- **Non sysops:** orientato al codice, non a deps/servizi/config di sistema.
- **Sandbox OS-specifica:** manutenzione duplicata per macOS/Linux; Windows meno coperto.
- **Nessuno stato del sistema ispezionabile:** reasoning non verificabile fuori dal prompt.

## Cosa NON copiare

- **Lock-in su un singolo provider cloud** → contro il nostro moat locale.
- **Sandbox OS-specifica hard-coded per OS** → attenzione: rischia casi speciali per-OS. Noi generalizziamo via
  capability (OCKE), non via branch per sistema operativo.

## Cosa vale la pena copiare

- **Approval modes (autonomia calibrabile)** → ottimo pattern: mappa sul nostro safety gate + human-in-the-loop.
- **Sandbox by default per l'esecuzione** → principio di isolamento per operazioni rischiose.
- **Diff-review prima di applicare** → allineato a `assert_safe_overwrite` + verifica pre-azione.
- **AGENTS.md come standard** → lo condividiamo già.

## Opportunità

Chi lo supera: un agente con **sandbox generalizzata via capability** (non per-OS hard-coded), provider-neutral
e con reasoning ispezionabile. Manca: verifica per artifact, modello del sistema, offline.

## Gap Analysis (vs Sistemista)

- **Avanti loro:** sandbox OS-native matura, modelli o-series potenti, approval UX.
- **Avanti noi:** offline/locale, provider-neutral (GGUF locali), reasoning causale ispezionabile, verifica per
  artifact, framework/OS-neutrality via OCKE, focus sysops.
- **Ci differenziamo:** la loro sicurezza è *sandbox dell'esecuzione*; la nostra è *sicurezza del ragionamento*
  (safety gate, no placeholder, no overwrite executable) — complementari, noi possiamo prendere entrambe.

## Lessons Learned

- **Engineering:** riscrivere in Rust per distribuzione/perf è un segnale di maturazione — ma valuta il costo.
- **AI/UX:** l'**approval mode** è la miglior idea trasferibile: dà all'utente il dial dell'autonomia.
- **Security:** sandbox *by default* è table-stakes per un agente che esegue.
- **Business:** un brand modello forte traina l'adozione della CLI, ma è un moat del *modello*, non della CLI.

## Fonti

- Deep Research interno sugli agenti da terminale §Codex CLI.
- Repository: github.com/openai/codex.
- **Da integrare:** doc approval modes & sandbox (seatbelt/landlock), changelog rewrite TS→Rust, config.toml ref.
