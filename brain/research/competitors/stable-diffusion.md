# Stable Diffusion

> **Fonte:** il Deep Research interno sui progetti OSS virali (§ Stable Diffusion) + analisi propria.
> **Affidabilità:** ✅ Reale (Stability AI + CompVis + LAION, 2022). **Categoria:** modello generativo di
> immagini — **NON un agente**. Nel corpus solo come **case study di crescita open-source**. Sezioni agent **N/A**.

---

## Overview

- **Cos'è:** modello text→image (latent diffusion), open-source.
- **Anno:** 22 agosto 2022. **Licenza:** CreativeML OpenRAIL-M. **Repo:** CompVis/stable-diffusion.
- **Paper:** "High-Resolution Image Synthesis with Latent Diffusion Models" (CVPR 2022).

## Success Story — *(il valore: viralità di massa)*

Viralità esplosiva perché ha **liberato alla massa** una capacità prima chiusa (qualità ~DALL·E, ma open). Leve:
open-source vs DALL·E chiuso; modello piccolo (860M, GPU 10GB) → **girava sull'hardware della gente**; community
(Reddit/Discord/Twitter) ha prodotto UI, plugin, ottimizzazioni in settimane; collaborazione HuggingFace. ~73k★.

## Architettura (non-agent)

Autoencoder + UNet + CLIP encoder. Repo notebook-heavy (89% Jupyter), research code. **N/A** per agent/terminal.

## Debolezze (come software / rischi)

Codice frammentato in notebook, no test/CI, no release versionate; lo sviluppo reale è migrato a `diffusers`
(HuggingFace). Rischi etici/copyright (training su dati web).

## Cosa NON copiare

- **Repo research-code non manutenibile** → gli utenti sono migrati altrove (diffusers). Lezione: un core non
  mantenuto perde la community anche se è virale. Per noi: la manutenibilità è parte del prodotto.

## Cosa vale la pena copiare *(go-to-market)*

- **"Gira sull'hardware della gente"** → esattamente la nostra tesi local-first: l'accessibilità (nessun cloud
  obbligatorio) è un moltiplicatore di adozione ([../../100_market/moat.md](../../100_market/moat.md) #3).
- **Abilitare la community a costruirci sopra** → estendibilità (per noi: MCP/plugin) come volano.

## Gap Analysis (vs Sistemista)

Non competitor. Lezione forte: **accessibilità locale (no barriere cloud/hardware) → adozione di massa**. È il
nostro moat #3 validato da un fenomeno storico.

## Lessons Learned

- **Growth:** liberare una capacità potente su hardware accessibile + community estendibile = viralità.
- **Manutenzione:** un core non mantenuto viene abbandonato (fork diffusers) → la manutenibilità trattiene la community.

## Fonti

- Deep Research interno sui progetti OSS virali (rimosso, consolidato qui) §Stable Diffusion. Repo: CompVis/stable-diffusion · HuggingFace diffusers.
