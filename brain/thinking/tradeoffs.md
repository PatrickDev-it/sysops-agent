# thinking · Trade-off

> Owner: **come scegliere tra due soluzioni valide.** Attivato quando più approcci superano i gate.

---

## Assi di valutazione

Per ogni alternativa, valuta esplicitamente (non "a sensazione"):

| Asse | Domanda |
|---|---|
| Generalità | Copre una categoria o un caso? |
| Costo di manutenzione | Chi lo terrà vivo tra 6 mesi? Quanti file toccano lo stesso fatto? |
| Osservabilità | Quando fallirà, capiremo perché senza debugger? |
| Reversibilità | Rollback in un passo o migrazione dolorosa? |
| Superficie d'errore | Quanti nuovi stati falliti introduce? (li impone `error_classifier.py`) |
| Coerenza | Somiglia al codice/doc circostante o introduce un dialetto nuovo? |

## Regole di rottura pareggio (in ordine)

1. **La causa batte il caso.** A parità, scegli la soluzione che risolve la causa generale.
2. **Meno stati falliti batte più feature.** Riduci la superficie d'errore prima di aggiungere potere.
3. **Reversibile batte ottimale-ma-irreversibile.** Preferisci ciò che si può disfare.
4. **Framework-neutral vince sempre.** Non è un trade-off: è un invariante (VETO).

## Anti-pattern nella scelta

- Scegliere per "è più veloce da scrivere ora" ignorando il costo di manutenzione → debito.
- Aggiungere un flag per non decidere → rimanda il trade-off all'utente.
- "Facciamo entrambe" → raddoppia la superficie d'errore.

Collegati: [first-principles](first-principles.md) · [failure-patterns](failure-patterns.md) · [decision-framework](decision-framework.md)
