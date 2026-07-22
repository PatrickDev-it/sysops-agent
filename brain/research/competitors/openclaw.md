# OpenClaw

> **Fonte:** il Deep Research interno sui progetti OSS virali (§ OpenClaw).
> **Affidabilità:** 🔴 **NON VERIFICATO / PROBABILE ALLUCINAZIONE.** "OpenClaw" (ex "Warelay"→"Moltbot"), 381k★,
> Microsoft "Scout": nessuna conferma indipendente. Peter Steinberger è una figura reale nella scena AI-dev, ma
> i dettagli/metriche sono da trattare come *claim*. **Categoria:** agente AI autonomo consumer — **non** un
> agente sysops da terminale → competitor solo indiretto. Valore reale: *case study di crescita virale*.

---

## Overview *(claim-da-report)*

- **Cos'è:** agente AI autonomo multi-piattaforma (consumer/full-stack).
- **Target:** utenti generali / early adopter di agenti autonomi.
- **Anno:** *report:* nov 2025 (come "Warelay"), picco Q1 2026.
- **Autori:** *report:* Peter Steinberger.
- **Licenza:** MIT. **Repository:** *report:* openclaw/openclaw (**da verificare**).

## Success Story — *(il cuore utile della scheda: viralità)*

*Claim-da-report:* crescita esplosiva (247k→381k★ in mesi) cavalcando il tema "AI agent" post-ChatGPT/AutoGPT;
demo espressive su X/Reddit; amplificazione da Microsoft (progetto "Scout" a Build 2026); crescendo **organico**
senza marketing formale. Rinominazioni multiple (Warelay→Moltbot→OpenClaw). **Lezione (se vera):** un progetto
può esplodere cavalcando un tema caldo con demo virali, ma paga in debito tecnico.

## Architettura *(claim-da-report)*

TypeScript (~91%) + Swift/Kotlin (mobile). Moduli chatbot, gestione contesti, plugin (`.agents/skills`), NLP.
63k+ commit, 219 release in pochi mesi → sviluppo febbrile. **Sezioni agent-specifiche (Planner/Executor/PTY):
non documentate in modo affidabile → N/A.**

## Debolezze *(claim-da-report — coerenti col pattern "viral OSS")*

Debito tecnico da crescita febbrile; test scarsi; 600+ security issue citati; API instabili (219 release);
dipendenze opache; perimetro di sicurezza fragile (agente che esegue + plugin esterni).

## Cosa NON copiare

- **Crescita febbrile a scapito della qualità** → 219 release/scarso testing = il contrario del nostro operating
  contract (verifica prima di dichiarare fatto). Noi non barattiamo qualità per hype.
- **Multi-linguaggio (TS+Swift+Kotlin) per un tool che dovrebbe essere focalizzato** → superficie e competenze disperse.

## Cosa vale la pena copiare *(go-to-market, non tecnica)*

- **Demo virali espressive** → il valore di far *vedere* l'agente risolvere qualcosa di impressionante (per noi:
  mostrare un fix di sistema "impossibile" risolto autonomamente).
- **Cavalcare un tema caldo con timing** → lezione di distribuzione per [../../200_business/roadmap.md](../../200_business/roadmap.md).

## Gap Analysis (vs Sistemista)

Competitor indiretto (consumer agent, non sysops). Se reale, il suo punto debole (debito/sicurezza) è esattamente
il nostro punto forte (rigore causale, safety gate). **Non inseguire la sua velocità; batterlo sull'affidabilità.**

## Lessons Learned

- **Business/Growth:** viralità organica + tema caldo + demo = crescita rapida; ma senza consolidamento (test,
  sicurezza) il debito esplode. Per noi: la difendibilità è nel *reasoning*, non nella velocità di feature.
- **Metodo:** metriche spettacolari non verificate → quarantena.

## Fonti

- Deep Research interno sui progetti OSS virali (rimosso, consolidato qui) §OpenClaw (**unica fonte, non verificata**).
- **Azione:** verificare repo/metriche/"Microsoft Scout" prima di trattarli come fatti.
