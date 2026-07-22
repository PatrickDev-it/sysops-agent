# Continue

> **Fonte:** il Deep Research interno sugli agenti da terminale (§ Continue) + analisi propria.
> **Affidabilità:** ⚠️ Il report afferma che Continue è **"obsoleto / archiviato / non più attivo"** → **quasi
> certamente falso**. Continue è un progetto attivo e finanziato (assistant IDE open-source, autocomplete+chat,
> poi anche un CLI `cn`). Trattare il giudizio "morto" del report come **errore**. Metriche (~34k★) plausibili
> ma non verificate.

---

## Overview

- **Cos'è:** assistente AI open-source per IDE (VS Code / JetBrains) — autocomplete, chat, edit; con CLI più recente.
- **Mission:** un assistente di coding personalizzabile e model-agnostic, "build your own AI code assistant".
- **Vision:** infrastruttura aperta per assistenti di coding, non un prodotto chiuso single-model.
- **Problema che risolve:** completamento/chat/edit assistiti configurabili, con qualsiasi modello/provider.
- **Target:** dev/team che vogliono controllo su modelli, prompt e contesto del proprio assistente.
- **Anno:** 2023 (tra i primi coding assistant OSS).
- **Autori:** Continue Dev, Inc. + community.
- **Licenza:** Apache-2.0.
- **Repository:** github.com/continuedev/continue.
- **Sito:** continue.dev.

## Success Story

Tra i **pionieri** dei coding assistant OSS (2023), quando l'autocomplete AI era nuovo. Report: ~34k★. Leva:
model-agnostic + configurabilità (`config`) + estensioni IDE. Ha poi mosso verso "agenti" e un CLI. La crescita
è legata all'essere arrivato presto e all'apertura. (Il report lo dà per morto: **da correggere**.)

## Adozione

~34k★ (report). Distribuzione via marketplace IDE. Funding VC (Continue Dev è una startup). Community discreta.

## Filosofia progettuale

- **Model-agnostic e configurabile:** l'utente sceglie modelli, prompt, contesto.
- **Open infrastructure:** mattoni per costruire il proprio assistente, non una black box.
- **IDE-first (poi CLI):** vive dove il dev scrive codice.
- **Non vuole risolvere:** sysops/OS fuori dall'IDE.
- **Risolve meglio:** autocomplete/chat/edit personalizzabili e portabili tra provider.

## Architettura

- **Core (TS):** motore di autocomplete + chat + edit; context providers pluggable (repo, docs, terminale, ecc.).
- **IDE extensions:** VS Code / JetBrains come front-end.
- **Config:** file di configurazione per modelli, context providers, regole.
- **CLI (`cn`):** interfaccia da terminale più recente (agentica).
- **MCP / tool:** integrazioni verso tool e provider.

## Engineering

Node/TypeScript. Pattern: context-provider plugin, provider abstraction, config-driven. CI Node. Modularità
orientata alla configurabilità. Debito: essere arrivato presto = codice con più anni/legacy di alcune scelte.

## Reverse Engineering

Perché config-driven/model-agnostic: nel 2023 il vincitore non era chiaro → non scommettere su un provider,
dare all'utente il controllo. Perché IDE-first: l'autocomplete vive nell'editor. Tradeoff: generalità/
configurabilità in cambio di una UX "opinionata" meno guidata. Ragionavano: "sii l'infrastruttura aperta, non
il prodotto chiuso".

## Analisi del codice

TS maturo. Punti forti: context providers, configurabilità, multi-provider. Punti deboli: essere generico può
rendere la UX meno affilata; codice con storia. **Da confermare sul repo** (e da smentire l'idea "archiviato").

## UX

Autocomplete inline + chat + edit nell'IDE; config potente ma con curva; CLI agentico recente. Human-in-the-loop
nell'editor.

## AI Design

Context providers = context engineering configurabile; autocomplete a bassa latenza; multi-provider; edit/chat.
Planning agentico introdotto più tardi (CLI). Memoria = contesto configurato.

## Sicurezza

Superficie: API key, context providers che leggono il repo, esecuzione (nel CLI agentico). Rischio standard IDE.

## Performance

Autocomplete richiede bassa latenza → ottimizzazioni su modelli piccoli/locali per il completamento. Chat/edit
latenza LLM.

## Punti di forza

1. Pioniere (early mover). 2. Model-agnostic + configurabile. 3. Context providers pluggable. 4. Multi-IDE.
5. Open infrastructure.

## Debolezze

- **Focus IDE:** non terminal/sysops nativo (il CLI è recente).
- **Genericità:** configurabilità → UX meno guidata, curva di setup.
- **Legacy:** codice con storia; scelte iniziali da mantenere.
- **Posizionamento sfumato:** tra autocomplete, chat e agente — identità meno netta dei rivali focalizzati.

## Cosa NON copiare

- **Accoppiamento all'IDE come centro di gravità** → noi siamo terminal-only.
- **Configurabilità estrema come default** → rischia di scaricare sull'utente decisioni che dovremmo prendere noi
  (contro la nostra promessa "l'utente non deve sapere il come").

## Cosa vale la pena copiare

- **Context providers pluggable** → astrazione pulita per iniettare contesto (repo/OS/docs) in modo componibile.
- **Model-agnostic dal giorno 1** → validazione del non-lock-in (noi: GGUF locali, ma il principio regge).
- **Autocomplete ottimizzato per modelli piccoli** → tecniche di low-latency utili per i nostri 3B/4B.

## Opportunità

Chi lo supera: prodotti più **focalizzati** (Cursor sul lato IDE, agenti dedicati sul lato terminale). La
genericità di Continue è insieme forza e debolezza: lo spazio "assistente affilato e opinionato" gli erode quota.

## Gap Analysis (vs Sistemista)

- **Avanti loro:** maturità, context providers, configurabilità, multi-IDE, autocomplete a bassa latenza.
- **Avanti noi:** terminal-only, autonomia, sysops, reasoning causale, verifica per artifact, opinionatezza (decidiamo noi il come).
- **Ci differenziamo:** Continue è *infrastruttura configurabile per l'IDE*; noi un *agente autonomo opinionato per il sistema*.

## Lessons Learned

- **Business:** l'early-mover advantage svanisce senza un focus netto: la genericità diluisce l'identità.
- **Engineering:** context providers pluggable è un pattern di context-engineering adottabile.
- **Design:** troppa configurabilità = decisioni scaricate sull'utente → anti-pattern per noi.
- **Nota di metodo:** il report ha sbagliato dichiarandolo "morto" → **verifica sempre le fonti prima di citarle**
  (proprio il motivo di questi box di affidabilità).

## Fonti

- Deep Research interno sugli agenti da terminale §Continue (⚠️ giudizio "archiviato" errato).
- Repository reale: github.com/continuedev/continue · continue.dev.
- **Da integrare:** stato reale del progetto (attivo), CLI `cn`, funding.
