# knowledge-graph.md

> Owner: **l'ontologia astratta OS/comandi/capability** — cosa *può* esistere e *come si fa* su ciascun OS.
> Successore di **OCKE** (v1). È conoscenza *a priori*, condivisa e statica; il [system-map.md](system-map.md) è il
> sistema *concreto* e dinamico. Uno è "la fisica", l'altro "questo pianeta".

---

## Cosa contiene

- **Command ontology:** per ogni *intento* (list-ports, restart-service, check-cert, find-file…), i comandi
  equivalenti per OS/shell/tool, con precondizioni (capability richieste), effetti, reversibilità, forma dell'output.
- **Capability model:** quali tool esistono in quali ecosistemi; equivalenze (`ss`↔`netstat`, `systemctl`↔`sc.exe`↔`launchctl`).
- **OS invariants:** regole per-OS (path, permessi, package manager, service manager) che filtrano i piani
  cross-platform (l'invariante v1 "il piano è valido per l'OS corrente").
- **Error ontology:** classi d'errore normalizzate (not-found, permission-denied, port-in-use, dependency-conflict…)
  con signature per riconoscerle da qualsiasi shell.

## Perché separato dal System Map

Un fatto → un owner. "systemd usa `systemctl`" è conoscenza universale (Knowledge Graph). "*questo* host usa systemd
e nginx è down" è osservazione (System Map). Mischiarli = il drift che vogliamo evitare. Il Planning Engine consulta
il KG per *tradurre intento → comando valido su questo OS*; il System Map per *sapere lo stato*.

## Come si usa (traduzione intento→azione, framework-neutral)

```
Planning: intento "restart service X"
  KG.resolve(intent=restart_service, os=env.os, shell=env.shell)
    → adapter systemd: "systemctl restart X"   (+ precondizione: capability:systemctl, privilege:root)
  Policy Engine valuta reversibilità/rischio dal KG (restart = RECOVERABLE, non DESTRUCTIVE)
```

Questo è il meccanismo che sostituisce le euristiche `_fix_*` di v1 e il divieto di `if <framework>`: **nessun caso
speciale nel codice**; la conoscenza per-OS vive come *dati* nel KG, non come `if` nel control-flow.

## Rappresentazione

Grafo/tabelle versionate, caricabili e **estendibili senza codice** (un nuovo OS/tool = nuovi dati, non nuovi branch).
Confidence per voce, aggiornata dal Learning Engine (se un comando fallisce sistematicamente su un OS, la sua
confidence scende → il Planner ne sceglie un altro). Il KG **impara** dall'esperienza.

## Confronto competitor

- **Nessun competitor ha un knowledge graph OS.** Si affidano al *parametric knowledge* del modello (v1 T060/T070:
  il 4B "sapeva" openssl → sbagliava su Windows). Noi *esternalizziamo* questa conoscenza in dati verificabili e
  correggibili → un modello piccolo diventa affidabile perché non deve *ricordare* i comandi, glieli forniamo.
- È il complemento naturale di [Aider](../research/competitors/aider.md)-style context: Aider dà il contesto del
  *codice*, il KG dà il contesto delle *capability dell'OS*.

## Pattern

Ontology / knowledge base · Rules-as-data (non rules-as-code) · Adapter per-OS · Confidence-weighted retrieval.

## Alternative scartate

- **Conoscenza OS nel prompt di sistema (hard-coded nel template):** gonfia ogni prompt, non aggiornabile senza
  redeploy, non per-sistema. **Rifiutato**: dati interrogabili, iniettati solo se rilevanti.
- **Affidarsi al parametric knowledge del modello:** è esattamente ciò che rompe v1 su edge-case OS. **Rifiutato.**

## Trade-off

Curare un KG multi-OS è lavoro continuo. Mitigazione: si popola *incrementalmente dall'esperienza* (Learning Engine
promuove pattern osservati a voci del KG) → il costo si ammortizza con l'uso, non tutto upfront.

## Benchmark teorico

Un comando corretto-per-OS iniettato dal KG (≤30 token) elimina i cicli di retry cross-platform di v1 (T002/T070:
5–12 iterazioni sprecate). Riduzione stimata dei retry da mismatch-OS: **>80%**.

## Evoluzioni

KG condiviso/federato tra installazioni (con privacy) · apprendimento automatico di nuove equivalenze di comando ·
verifica formale delle precondizioni · import da man-page/documentazione come bootstrap.
