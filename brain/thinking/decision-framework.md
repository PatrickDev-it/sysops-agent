# thinking · Decision framework

> Owner: **il protocollo end-to-end da richiesta a patch.** È la forma lunga della pipeline in [../BRAIN.md](../BRAIN.md).

---

## Protocollo

```
1. INQUADRA     Qual è il problema reale? (sintomo vs causa — first-principles)
2. GATE STRAT.  Business → Product → Market: la richiesta va fatta? (VETO)
3. INVARIANTE   Quale invariante è in gioco? (→ AGENTS.md § Invarianti core)
4. GENERALIZZA  La soluzione vale su una categoria? (no `if <framework>`)
5. TRADE-OFF    Se >1 approccio valido → assi + regole di rottura (thinking/tradeoffs)
6. RFC?         Cambio non banale? → .sinapsi/rfc/ (invariante/flusso/sottosistema/trade-off)
7. ATTESO       Definisci l'esito osservabile PRIMA di scrivere
8. IMPLEMENTA   Minimo, framework-neutral, osservabile
9. OSSERVA      Esegui il flusso reale; guarda l'esito (non dedurlo)
10. DOC         Aggiorna gli owner toccati (update triggers, AGENTS.md)
```

## Quando fermarsi e chiedere (non decidere da solo)

- La richiesta viola una promessa di [000_identity](../000_identity.md) → riporta, non implementare in silenzio.
- Servono >1 approccio con trade-off strategici (non tecnici) → l'utente sceglie la direzione.
- Il gate business/product richiede un fatto di prodotto che non esiste ancora → è un buco da colmare, non da assumere.

## Quando NON chiedere (decidi e procedi)

- C'è un default convenzionale o un invariante che detta la scelta → applicalo e menzionalo.
- La risposta è verificabile nel codice/doc → verificala, non chiedere.

Collegati: [first-principles](first-principles.md) · [tradeoffs](tradeoffs.md) · [../BRAIN.md](../BRAIN.md)
