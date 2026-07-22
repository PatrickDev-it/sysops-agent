# Cline

> **Fonte:** il Deep Research interno sugli agenti da terminale (§ Cline) + analisi propria.
> **Affidabilità:** ⚠️ Il report contiene errori: attribuisce Cline a **"Rafael Winterhalter"** → **falso**
> (Cline è di **Saoud Rizwan**; Winterhalter è l'autore di Byte Buddy, non c'entra). La "Kanban web app
> multi-agente" è dubbia/confusa. Cline è primariamente una **estensione VS Code** (open-source, TS), non un CLI
> standalone → collocarlo tra i "terminal agent" è parzialmente improprio, ma esegue comandi shell nel terminale IDE.

---

## Overview

- **Cos'è:** agente AI di coding come estensione VS Code (e JetBrains), open-source.
- **Mission:** un assistente autonomo che pianifica e agisce nel progetto, con l'umano che approva.
- **Vision:** coding agentico trasparente e sotto controllo, model-agnostic.
- **Problema che risolve:** editing/refactoring/esecuzione guidati da LLM dentro l'IDE, con approvazione umana.
- **Target:** sviluppatori che vivono in VS Code e vogliono un agente con guardrail.
- **Anno:** 2024–2025.
- **Autori:** Saoud Rizwan + community (il report sbaglia l'attribuzione).
- **Licenza:** Apache-2.0.
- **Repository:** github.com/cline/cline.
- **Sito:** cline.bot · docs.cline.bot.

## Success Story

Crescita rapida 2025 (report: ~64k★, plausibile — Cline è genuinamente popolare). Leva: **modalità Plan/Act**
esplicita + human-in-the-loop + MCP + trasparenza (mostra ogni diff/comando prima di eseguirlo). Community
Reddit/Twitter attiva. Deriva/fork: Roo Code (Roo Cline) è un fork noto — **non citato nei report** ma rilevante.

## Adozione

~64k★ (report). Ecosistema marketplace VS Code = distribuzione enorme. MCP marketplace integrato. Community forte.

## Filosofia progettuale

- **Human-in-the-loop by default:** ogni azione richiede approvazione (auto-approve opzionale).
- **Trasparenza:** l'utente vede diff e comandi prima dell'esecuzione.
- **Plan poi Act:** separa esplicitamente la fase di pianificazione da quella di azione.
- **Model-agnostic:** molti provider (Anthropic, OpenAI, Gemini, locali via OpenRouter/Ollama).
- **Non vuole risolvere:** autonomia totale senza supervisione; sysops fuori dal repo.
- **Risolve meglio:** coding assistito trasparente e controllabile dentro l'IDE.

## Architettura

- **Core agent (estensione, Node/TS):** loop plan/act; esegue LLM configurabile; monitora build/test in background.
- **Plan mode:** il modello chiede chiarimenti e propone un piano prima di agire.
- **Act mode:** esegue azioni (edit file, comandi shell nel terminale integrato) con approvazione.
- **MCP:** client MCP + marketplace per tool esterni (DB, API, browser).
- **Rules/skills:** `.clinerules` per iniettare knowledge di dominio.
- **Context:** legge il workspace (Git), gestisce context window, checkpoints.

## Engineering

TypeScript (~97%), pacchetto estensione VS Code. Pattern: state machine plan/act, provider abstraction, MCP client,
checkpoint/undo. CI Node (vitest). Debito: molte dipendenze Node, heavy su risorse JS, molte opzioni di config.

## Reverse Engineering

Perché VS Code extension: distribuzione via marketplace = crescita gratis + UX ricca (diff nativi, terminale
integrato). Perché plan/act esplicito: dare all'utente **controllo e comprensione** (fiducia) invece di autonomia
opaca. Tradeoff: legato all'IDE (non un CLI puro), heavy JS. Ragionavano: "gli sviluppatori vogliono controllo e
trasparenza più che magia; l'IDE è dove già vivono".

## Analisi del codice

TS moderno. Punti forti: plan/act pulito, checkpoint, MCP marketplace, UX diff. Punti deboli: consumo risorse,
molte configurazioni (curva d'apprendimento), dipendenza dal contesto di progetto Git. **Da confermare sul repo.**

## UX

**Tra le migliori del gruppo.** Diff review nativi, terminale integrato, approvazione per-azione, checkpoint/undo,
progress visibile, plan mode conversazionale. Human-in-the-loop di prima classe.

## AI Design

Plan/act come planning esplicito a due fasi; approvazione umana come guardrail; monitoraggio build/test →
feedback loop; tool selection via MCP; checkpoint per rollback. Memoria = contesto progetto + `.clinerules`.

## Sicurezza

Human-in-the-loop = difesa primaria (nulla si esegue senza approvazione, se auto-approve off). Superficie: API
key, comandi shell approvati, tool MCP di terzi. Nessuna sandbox forte: si affida all'approvazione umana.

## Performance

Heavy su Node/JS → possibile latenza e consumo RAM nell'IDE. Latenza LLM dominante. Nessuna esecuzione batch pesante.

## Punti di forza

1. **Plan/Act esplicito.** 2. UX diff/approvazione eccellente. 3. Trasparenza (fiducia). 4. MCP marketplace.
5. Model-agnostic. 6. Distribuzione marketplace VS Code.

## Debolezze

- **Legato all'IDE:** non un agente da terminale puro; dipende da VS Code/JetBrains.
- **Human-in-the-loop obbligatorio (di fatto):** meno autonomo → per sysops autonomo è un limite.
- **Heavy JS:** consumo risorse, molte config.
- **Sysops fuori scope:** focalizzato sul repo di codice, non su deps/servizi/OS.
- **Nessuna sandbox:** la sicurezza è l'approvazione umana, non l'isolamento.

## Cosa NON copiare

- **Human-in-the-loop come requisito** → Sistemista è **autonomo** per identità; l'approvazione per-azione
  annullerebbe il valore (l'utente non deve sapere/decidere il "come").
- **Accoppiamento all'IDE** → noi siamo terminal-only, dobbiamo girare anche via SSH su macchine nude.

## Cosa vale la pena copiare

- **Plan/Act come fasi esplicite** → mappa bene sul nostro DISCOVERY→plan prima dei MODIFY (inv. 5). Rende il
  piano ispezionabile.
- **Diff-review + checkpoint/undo** → reversibilità + `assert_safe_overwrite`.
- **Trasparenza del "cosa sto per fare"** → UX di fiducia = la nostra promessa "ti mostro cosa faccio e perché".
- **`.clinerules` (knowledge di dominio iniettabile)** → analogo utile per regole OS-specifiche via OCKE.

## Opportunità

Chi lo supera per sysops: un agente con la **trasparenza plan/act di Cline** ma **autonomo e da terminale puro**,
capace di girare dove non c'è un IDE. È lo spazio che occupiamo.

## Gap Analysis (vs Sistemista)

- **Avanti loro:** UX (diff/approvazione/checkpoint), plan/act maturo, marketplace, MCP.
- **Avanti noi:** autonomia reale, terminal-only (SSH/VPS), reasoning causale, verifica per artifact,
  framework/OS-neutrality, sysops.
- **Ci differenziamo:** Cline mette *l'umano* nel loop di controllo; noi mettiamo il *reasoning engine* nel loop,
  dando all'utente la trasparenza (mostrare il piano) senza chiedergli di approvare ogni passo.

## Lessons Learned

- **UX:** la trasparenza (mostrare diff/comandi) genera fiducia più dell'autonomia opaca — adottare il principio
  di *mostrare il piano*, senza però delegare la decisione all'utente.
- **Engineering:** plan/act a due fasi è un pattern pulito e ispezionabile.
- **Business:** distribuire dove l'utente già vive (marketplace VS Code) è una leva di crescita enorme.
- **Community:** i fork (Roo Code) nascono quando il progetto è buono ma la governance/velocità non basta.

## Fonti

- Deep Research interno sugli agenti da terminale §Cline.
- Repository reale: github.com/cline/cline · docs.cline.bot (autore: Saoud Rizwan).
- **Correzioni da propagare:** autore (non Winterhalter); natura (estensione IDE, non CLI); verificare "Kanban".
