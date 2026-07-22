# vision.md

> Owner: **cosa vogliamo essere tra 5 anni.** Deriva da [../000_identity.md](../000_identity.md) e la porta al livello v2.

---

## Vision

**Il riferimento mondiale open-source per l'amministrazione di sistemi via terminale**, guidato da AI locale.
Un sistemista che non dorme: dai un obiettivo in linguaggio naturale, lui *osserva → ragiona → agisce → verifica*
sul sistema reale — Linux, Windows, macOS, container, cluster, host remoti — e ti restituisce il *perché*.

## Cosa è (e cosa NON è)

- **È** un *AI Systems Engineer*: Linux/Windows/macOS admin, DevOps, Docker/K8s, SSH, networking, monitoring,
  troubleshooting, incident response, infra automation, server management. **Solo terminale.**
- **NON è** un coding agent, un editor, un IDE, un assistente generalista. Il terminale è l'unica interfaccia.

## Perché ora (first principles)

1. **Il sysops è il dominio *meno* servito dagli agenti.** Tutti i leader ([Claude Code](../research/competitors/index.md),
   Codex, Aider, Cline, OpenHands) sono *coding agent*. Nessuno mappa e ripara un *sistema vivo*. È il white space §7 dell'index.
2. **I sistemi hanno struttura interrogabile** (processi, servizi, pacchetti, socket, config) — perfetta per un
   *world model* che rende il ragionamento economico. Il codice non ha il monopolio della "mappa".
3. **La sovranità conta nel sysops.** Un agente che tocca produzione deve poter girare **locale/offline**, senza
   mandare lo stato dei tuoi server a un cloud. Moat strutturale vs Gemini/Codex.

## North star (v2)

> Massimizzare la frazione di problemi di sistema risolti **autonomamente e correttamente** dando *un solo
> obiettivo*, su qualsiasi OS, con un modello **locale piccolo** — misurata come **Autonomous Resolution Rate
> (ARR)** a parità di costo-token. Vedi [telemetry.md](telemetry.md).

## Principi di prodotto irrinunciabili

- **Terminal-only**, autonomo, causale, sicuro-per-default, verificabile (eredita [../300_product/product-philosophy.md](../300_product/product-philosophy.md)).
- **Explainable**: ogni azione traccia ai *fatti* che l'hanno motivata (il belief state è audit trail).
- **Degradabile**: funziona su una VPS nuda (no Docker/GUI/IDE) e scala fino a una fleet.

## Alternative di visione scartate

- **"Diventare un coding agent con feature sysops"** → ci butterebbe nel mare rosso dei leader. Rifiutato: il
  focus *è* il moat.
- **"SaaS cloud-first"** → distrugge la sovranità (moat #3) e il target "opera su macchina altrui via SSH".
- **"Framework/librerie per costruire agenti"** (à la LangChain) → saremmo colla, non un prodotto. Rifiutato.

## Trade-off accettati

- Rinunciamo all'ampiezza (non facciamo coding/IDE) per la **profondità** nel sysops.
- Rinunciamo alla potenza di un modello cloud garantito per la **sovranità** locale (con fallback cloud opzionale).

## Benchmark teorico di successo (5 anni)

- ARR ≥ 80% su una suite sysops multi-OS pubblica, con un modello **≤8B locale**.
- p50 latency per "diagnosi→azione" competitiva con un umano esperto su task comuni.
- "The tool you SSH into a broken box with." Riconoscibilità = categoria.

## Evoluzioni possibili

Fleet-level (un cervello, N host) · knowledge-graph condivisi tra installazioni (federati, privacy-preserving) ·
marketplace di *playbook* verificati · integrazione con osservabilità esistente (Prometheus/journald) come *fonti di fatti*.
