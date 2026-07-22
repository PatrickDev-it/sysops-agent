# Aider

> **Fonte:** il Deep Research interno sugli agenti da terminale (§ Aider) + analisi propria.
> **Affidabilità:** ✅ Progetto reale e ben noto; la descrizione del report è sostanzialmente corretta. Da
> verificare solo aneddoti (es. "lodato da Eric S. Raymond"): **non confermato**, trattare come non-fatto.
> Aider è **il pair-programmer da terminale di riferimento**: molte sue idee sono direttamente rilevanti per noi.

---

## Overview

- **Cos'è:** pair-programmer AI da terminale, Python, con integrazione git profonda.
- **Mission:** "AI pair programming in your terminal" — modifiche di codice guidate da LLM con commit automatici.
- **Vision:** un collaboratore che edita il repo mantenendo la storia git pulita e i test verdi.
- **Problema che risolve:** editing multi-file guidato da LLM con contesto efficiente e rollback via git.
- **Target:** sviluppatori da terminale che vivono in git.
- **Anno:** 2023–2024 (attivo).
- **Autori:** Paul Gauthier + community.
- **Licenza:** Apache-2.0.
- **Repository:** github.com/Aider-AI/aider.
- **Sito:** aider.chat.

## Success Story

Crescita organica via **qualità reale** + una **leaderboard di benchmark** pubblica (aider mantiene un
code-editing benchmark molto citato). Report: ~47k★. Passaparola dev (Reddit, YouTube "raddoppia la produttività").
Leva: setup semplice (`pip install`), git-native, multi-modello. Momenti chiave: edit formats via diff, repo-map.

## Adozione

~47k★ (report, coerente). Community open-source attiva; nessun funding VC noto (progetto indipendente). Molto
citato come baseline nei confronti tra coding agent.

## Filosofia progettuale

- **Git come memoria e sicurezza:** ogni modifica = commit → rollback naturale, storia leggibile.
- **Contesto efficiente:** repo-map invece di caricare tutto il codice.
- **Human-in-the-loop leggero:** l'utente guida via prompt; Aider propone patch.
- **Non vuole risolvere:** autonomia agentica multi-step complessa; task fuori dal repo (sysops).
- **Risolve meglio:** editing preciso multi-file con contesto minimo e commit puliti.

## Architettura

- **Repo-map:** mappa del repository con **ranking di rilevanza** (via tree-sitter → simboli/AST parziale) per
  dare al modello il contesto giusto senza saturare i token. **Idea centrale e brillante.**
- **Edit formats:** diverse strategie di applicazione modifiche (whole-file, unified diff, search/replace) scelte
  in base al modello; validazione prima di applicare.
- **Git integration:** commit automatici con messaggi generati; rollback.
- **Lint/test loop:** esegue lint e test dopo le modifiche e reinietta gli errori per auto-correzione.
- **LLM abstraction:** multi-provider (Claude, GPT, DeepSeek, locali).
- **Voice-to-code:** input vocale opzionale.

## Engineering

Python (+ un po' di JS). Pattern: repo-map builder (tree-sitter), edit-format strategy, git wrapper, lint/test
runner. Testing: benchmark di edit come test empirico continuo. Modularità pragmatica. Debito: gestione dei molti
edit format e del parsing dei diff (fragile per modelli deboli).

## Reverse Engineering

Perché repo-map con ranking: il collo di bottiglia degli LLM è il **contesto** → dare *solo* il rilevante è la
leva di qualità/costo n.1. Perché edit-format multipli: modelli diversi producono diff con affidabilità diversa
→ scegliere il formato più robusto per modello. Perché git-native: rollback e trust gratis. Tradeoff: focus
stretto sul codice (niente orchestrazione complessa) in cambio di **affidabilità e semplicità**. Ragionavano:
"fai una cosa benissimo — editing di repo affidabile — e usa git per la sicurezza".

## Analisi del codice

Python idiomatico, pragmatico, ben mantenuto. Punti forti: repo-map, edit-format, benchmark rigoroso. Punti
deboli: parsing diff fragile su LLM deboli; scalabilità limitata a task di editing (non pianifica flussi complessi).
Qualità complessiva alta per un progetto guidato da una persona + community.

## UX

CLI conversazionale semplice; commit automatici trasparenti; test post-edit; voice. Error UX: errori di lint/test
reiniettati. Human-in-the-loop leggero (prompt manuali).

## AI Design

**Repo-map = context engineering** (il pezzo forte). Edit-format adattivo per modello. Self-correction via
lint/test. Nessuna memoria persistente oltre git. Planning minimale (non è un agente multi-step autonomo).

## Sicurezza

Git come rete di sicurezza (rollback). Esegue comandi/test → superficie standard. API key. Nessuna sandbox forte;
si affida a git e alla revisione umana dei commit.

## Performance

Leggero (Python, pip). Repo-map riduce i token → **efficienza di costo notevole**. Latenza LLM dominante.

## Punti di forza

1. **Repo-map con ranking (context engineering).** 2. **Edit-format adattivo + validazione.** 3. Git-native
(rollback/trust). 4. Lint/test loop (self-correction). 5. Multi-provider. 6. Benchmark rigoroso pubblico.

## Debolezze

- **Poca autonomia:** richiede prompt manuali; non pianifica task complessi multi-step.
- **Parsing diff fragile:** con modelli deboli gli edit format falliscono → loop di ri-richiesta.
- **Solo repo di codice:** niente sysops (deps/servizi/OS) fuori dal repository.
- **Nessuna memoria persistente** oltre la storia git.

## Cosa NON copiare

- **Human-in-the-loop / prompt manuali come modello operativo** → Sistemista è autonomo.
- **Assumere sempre un repo git** → noi operiamo anche su sistemi senza repo (fix di PATH/env/servizi).

## Cosa vale la pena copiare

- **Repo-map con ranking di rilevanza** → **idea da rubare**: l'analogo per noi è un *system-map* rankato
  (capabilities/entità rilevanti al goal) prima di agire → potenzia il nostro step DISCOVERY (inv. 5) e riduce il
  contesto del supervisor (mitiga Issue #8, parse error sotto contesto accumulato).
- **Edit-format adattivo per modello + validazione pre-apply** → cruciale per noi con modelli 3B/4B: scegliere il
  formato di output più robusto e **validare prima di eseguire** (allineato al blocco placeholder, inv. 2).
- **Lint/test loop con errore reiniettato** → recovery vincolata dall'errore osservato (inv. 4).
- **Benchmark pubblico come disciplina** → avere una metrica *osservata* (la nostra north star da strumentare).

## Opportunità

Chi lo supera: un agente che prende il **repo-map + edit-format affidabile** di Aider ma è **autonomo** e opera
anche **fuori dal repo** (sistema intero). Aider è deliberatamente stretto: lo spazio sysops autonomo è aperto.

## Gap Analysis (vs Sistemista)

- **Avanti loro:** context engineering (repo-map), affidabilità edit, git integration, benchmark, semplicità.
- **Avanti noi:** autonomia, scope di sistema (non solo repo), reasoning causale, verifica per artifact,
  framework/OS-neutrality, recovery vincolata.
- **Ci differenziamo:** Aider edita *codice*; noi ripariamo *sistemi*. Ma **la loro disciplina di context
  engineering e edit-validation è il singolo apporto tecnico più prezioso** da importare.

## Lessons Learned

- **AI/Engineering:** il context engineering (dare *solo* il rilevante, rankato) è la leva n.1 di qualità/costo
  con qualsiasi modello — priorità alta per noi.
- **AI:** validare l'output del modello *prima* di applicarlo evita danni (edit-format → nostro placeholder-block).
- **Business:** un benchmark pubblico costruisce credibilità e disciplina il team.
- **Design:** fare una cosa benissimo (editing affidabile) batte fare tutto mediocremente.

## Fonti

- Deep Research interno sugli agenti da terminale §Aider.
- Repository reale: github.com/Aider-AI/aider · aider.chat · leaderboard benchmark su aider.chat.
- **Da verificare/scartare:** aneddoto "Eric S. Raymond" (non confermato).
