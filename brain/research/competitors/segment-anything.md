# Segment Anything Model (SAM)

> **Fonte:** il Deep Research interno sui progetti OSS virali (§ SAM) + analisi propria.
> **Affidabilità:** ✅ Reale (Meta AI, 2023). **Categoria:** modello di computer vision — **NON un agente**.
> Zero rilevanza architetturale per un agente sysops. Presente nel corpus solo come **case study di crescita
> open-source**. Le sezioni agent (Planner/Executor/PTY/AI orchestration) sono **N/A per costruzione**.

---

## Overview

- **Cos'è:** modello foundation di segmentazione immagini "promptable" (Meta AI).
- **Anno:** 5 aprile 2023. **Licenza:** Apache-2.0. **Repo:** facebookresearch/segment-anything.
- **Paper:** arXiv 2304.02643. **Dataset:** SA-1B (1B+ maschere).

## Success Story — *(l'unica sezione con valore trasferibile: viralità)*

Lancio Meta con **ecosistema completo** simultaneo: modello + dataset gigante + **demo web interattiva** + paper
+ blog. La demo "provalo senza installare nulla" è stata il moltiplicatore virale principale. Copertura stampa
tech immediata (SiliconANGLE, MIT Tech Review). Community di ricerca come amplificatore. ~54k★.

## Architettura (non-agent)

PyTorch, encoder ViT + mask decoder, design promptable (click/box → maschera). Repo ~notebook (dimostrativo, non
production). **N/A** rispetto a planner/executor/terminal/agent-loop.

## Debolezze (come software)

Nessun test automatizzato; repo notebook-heavy (research code, non industriale); dipendenza GPU/PyTorch; pesi esterni.

## Cosa NON copiare

- **Research code notebook-heavy senza test** → contro il nostro operating contract (verifica, osservabilità).

## Cosa vale la pena copiare *(go-to-market)*

- **Ecosistema completo al lancio** (modello+dati+demo+docs) → per noi: rilasciare l'agente con **demo che si
  prova subito** e documentazione che abbassa la barriera (lezione per [../../200_business](../../200_business/roadmap.md)).
- **"Prova senza installare"** → una demo/asciinema di Sistemista che risolve un problema reale = viralità.

## Gap Analysis (vs Sistemista)

Non competitor. Solo lezione: **la demo interattiva è il moltiplicatore virale n.1** per un progetto tecnico.

## Lessons Learned

- **Growth:** un ecosistema completo (non solo il core) + una demo provabile al secondo zero guida l'adozione.
- **Nota:** modello di dominio diverso → nessuna lezione architetturale per noi.

## Fonti

- Deep Research interno sui progetti OSS virali (rimosso, consolidato qui) §SAM. Repo: facebookresearch/segment-anything · paper arXiv 2304.02643.
