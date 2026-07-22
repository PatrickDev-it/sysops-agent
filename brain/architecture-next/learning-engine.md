# learning-engine.md

> Owner: **migliorare con l'esperienza, senza training.** Cattura gli esiti e li ripropone. Usa i tre DB definiti
> in [memory.md](memory.md) (Failure/Pattern/Recovery); qui la *logica* di cattura, generalizzazione e retrieval.

---

## Tesi: un 4B che impara come dati, non come pesi

Non addestriamo il modello. Trasformiamo ogni run in **esperienza strutturata** riutilizzabile. Il modello resta
piccolo e fisso; l'intelligenza *cumulativa* vive nell'experience store, iniettata dal Context Engine. È
**case-based reasoning + experience replay senza gradient**.

## Ciclo di apprendimento

```
Fine di ogni goal / step:
  1. CAPTURE     Estrai la signature (os·shell·tool·error-class·goal-intent) e l'esito.
  2. GENERALIZE  Astrai il caso: da "restart nginx fallito, nginx -t poi restart ha risolto"
                 → Recovery(unit-failed + config-error) = "valida config prima di restart".
  3. STORE       Failure/Pattern/Recovery DB, con confidence iniziale.
  4. PROMOTE     Se un pattern regge su N casi → promuovilo a voce del Knowledge Graph (conoscenza, non aneddoto).
  5. DECAY       Se un pattern smette di funzionare → abbassa confidence → smette di essere suggerito.
```

## Cosa impara (tre livelli)

| Livello | Esempio | Effetto |
|---|---|---|
| **Failure** | "openssl assente su Windows" | non ri-tentare quella strada su quell'OS |
| **Pattern** | "diagnosi porta: `ss -ltnp` poi mappa pid→servizio" | pianifica in 1 colpo, salta il modello |
| **Recovery** | "unit-failed+config-error → `nginx -t` prima" | recupero mirato, niente flailing |

## Retrieval (dove il valore si realizza)

Il Context Engine, compilando un prompt, interroga per **signature esatta** (poi fuzzy) e inietta le 1–3 esperienze
più rilevanti. Un hit nel Pattern DB può **eliminare la chiamata di pianificazione**; un hit nel Recovery DB
sostituisce il flailing con un'azione mirata. Il valore cresce monotòno con l'uso *su quel parco macchine*.

## Confronto competitor

- **Nessun competitor ha un experience store per il sysops.** Aider/Cline hanno history+git (per-task, non
  trasferibile). Goose ha una memory-extension generica. **Questo è un moat cumulativo**: più Sistemista gira, più
  diventa il *migliore su quei sistemi* — un vantaggio che i competitor non possono copiare senza gli stessi dati.
- **v1** aveva `episodic.db` (regressions, failed_assumptions, causal_edges): intuizione giusta ma poco sfruttata in
  retrieval. Qui è il cuore, indicizzato per signature e cablato nel Context Engine.

## Pattern

Case-based reasoning · Experience replay (no gradient) · Signature indexing · Confidence decay · Promotion (aneddoto→
regola) · Feedback loop chiuso (esito → conoscenza → decisione futura).

## Alternative scartate

- **Fine-tuning continuo:** costoso, non locale-friendly, oblio catastrofico, non spiegabile. **Rifiutato.**
- **RAG generico su testo dei run:** recupera "simile", non "strutturalmente identico"; niente promozione a
  conoscenza. **Rifiutato** come primario.
- **Nessun apprendimento (stateless):** ripete gli stessi errori all'infinito (v1 flailing). **Rifiutato.**

## Trade-off / Benchmark / Evoluzioni

Trade-off: rischio di apprendere un pattern sbagliato (overfitting all'aneddoto) → mitigato da soglia di promozione
(N casi) e decay. Privacy: l'esperienza contiene dettagli di sistema → resta **locale** di default (federazione
opt-in, anonimizzata). Benchmark: ARR e token/task devono migliorare monotonicamente su task ricorrenti dopo N run.
Evoluzioni: playbook di community verificati, meta-learning (pattern di pattern), export dell'esperienza come runbook umano.
