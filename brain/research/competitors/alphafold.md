# AlphaFold

> **Fonte:** il Deep Research interno sui progetti OSS virali (§ AlphaFold) + analisi propria.
> **Affidabilità:** ✅ Reale (DeepMind). **Categoria:** modello scientifico (predizione strutture proteiche) —
> **NON un agente**. Nel corpus solo come **case study**. La rilevanza per noi è *minima*; sezioni agent **N/A**.

---

## Overview

- **Cos'è:** sistema di deep learning per predire la struttura 3D delle proteine.
- **Anno:** CASP14 2020; codice open luglio 2021. **Licenza:** Apache-2.0. **Repo:** google-deepmind/alphafold.
- **Paper:** Nature 2021. **Impatto:** Nobel 2024 ai creatori; AlphaFold DB (200M+ strutture).

## Success Story — *(viralità "scientifica", non social)*

Non virale sui social: virale per **rilevanza scientifica + credibilità istituzionale** (Nature/Science, premi,
CASP). Rilascio del codice **dopo** forte domanda della community. Documentazione + Docker per abbassare la barriera.

## Architettura (non-agent)

Python + JAX + OpenMM; pipeline MSA + transformer strutturale; monolitica; Docker; DB genetici 3TB. **N/A** per agent.

## Debolezze

Installazione pesantissima (3TB, GPU), hardware proibitivo, manutenzione fragile (JAX/OpenMM), non estensibile,
no GUI/API server integrati (ColabFold è nato per semplificare).

## Cosa NON copiare

- **Barriera d'ingresso proibitiva (3TB/GPU)** → il contrario della nostra tesi di accessibilità. Un tool
  inaccessibile viene "wrappato" da altri (ColabFold) che si prendono la UX.

## Cosa vale la pena copiare *(marginale)*

- **Credibilità via rigore/benchmark (CASP)** → per noi: una metrica pubblica osservata (autonomous resolution
  rate) costruisce fiducia più del marketing.
- **Docker per riproducibilità** → utile come *opzione* di distribuzione, **non** come requisito (vedi OpenHands: no Docker obbligatorio).

## Gap Analysis (vs Sistemista)

Non competitor, dominio ortogonale. Unica lezione: **rigore misurabile = credibilità**; e **barriera alta → altri
ti wrappano prendendosi gli utenti** (ColabFold docet). Corollario per noi: restare accessibili e leggeri.

## Lessons Learned

- **Growth/Business:** credibilità scientifica/benchmark può sostituire il marketing.
- **Prodotto:** se sei potente ma inaccessibile, qualcuno costruirà l'interfaccia facile e si prenderà la relazione con l'utente.

## Fonti

- Deep Research interno sui progetti OSS virali (rimosso, consolidato qui) §AlphaFold. Repo: google-deepmind/alphafold · Nature 2021 · AlphaFold DB.
