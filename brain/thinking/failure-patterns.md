# thinking · Failure patterns

> Owner: **gli errori ricorrenti da riconoscere prima di commetterli.** Attivato dal gate QUALITY (VETO).

---

## Le red flag (da AGENTS.md — qui espanse)

Ogni voce sotto significa **lavoro non finito**, non "quasi fatto":

- **Silent failure** — un passo fallisce senza log/errore. → Rendi il fallimento osservabile.
- **Risultato parziale** — metà del goal raggiunto, dichiarato "fatto". → Artifact check obbligatorio.
- **Log mancante** — non sai *perché* ha funzionato. → Se non è osservabile, non è finito.
- **Exit code anomalo ignorato** — 0 assunto senza verifica. → L'artifact check sovrascrive l'exit code (inv. 9).
- **Placeholder eseguito** — `<token>`, `{SLOT}`, `$VAR` non risolti arrivano all'executor. → BLOCCA (inv. 2).

## Failure patterns cognitivi (a monte del codice)

- **Coprire il caso** — patch locale per far passare *questo* input. → Cerca l'astrazione (first-principles).
- **Fixare il sintomo** — silenziare l'errore invece dello stato che lo genera.
- **Fiducia senza osservazione** — "dovrebbe funzionare". → Definisci l'esito atteso, poi guardalo.
- **Recovery inventata** — retry non vincolato dall'errore osservato. → La recovery deriva dall'`error_classifier` (inv. 4).
- **Belief non provato che guida** — agire su un'ipotesi REFUTED. → Solo belief PROVEN guidano (inv. 10).

## Il rituale prima di dire "fatto"

1. Qual era l'esito atteso, scritto *prima*?
2. L'ho **osservato** (non dedotto)?
3. C'è una red flag di questa lista aperta?
4. Se dovesse fallire in produzione, il log basterebbe a capirlo?

Se una risposta è no → non è finito.

Collegati: [first-principles](first-principles.md) · [../BRAIN.md](../BRAIN.md) (gate QUALITY)
