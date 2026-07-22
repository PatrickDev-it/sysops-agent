# 300 · Product philosophy

> Owner: **cosa rende Sistemista un buon prodotto (non solo codice corretto).** Gate PRODUCT (VETO).

---

## Principi

1. **Un obiettivo, non una procedura.** L'utente dice *cosa* vuole ("risolvi il conflitto di dipendenze"),
   mai *come*. Ogni feature che richiede all'utente di sapere il "come" è un fallimento di prodotto.
2. **Silenzio = fiducia mal riposta.** Il prodotto deve *mostrare* perché crede di aver finito (artifact check
   visibile), non affermarlo. La trasparenza del ragionamento è UX, non logging.
3. **Fallire bene.** Quando non può risolvere, deve dire *cosa* ha osservato e *perché* si è fermato — mai un
   crash muto o un risultato parziale spacciato per successo.
4. **Niente sorprese distruttive.** Nessun overwrite di eseguibili, nessun goal distruttivo eseguito: la
   sicurezza è una feature di prodotto, non un vincolo tecnico.
5. **Neutralità = longevità.** Ragionare per primitive (non per framework) significa che il prodotto non
   invecchia quando esce il framework nuovo. La neutralità è una promessa all'utente, non solo al codice.

## La promessa in una riga

> *"Dimmi il problema. Non serve che tu sappia risolverlo. Ti mostro cosa faccio e perché, e non rompo nulla."*

## Uso nel gate

> Questa patch serve la persona reale ([personas](personas.md)) senza rompere una promessa sopra?
> Se introduce un passo "che l'utente deve capire", o un silent failure, o un caso speciale → **VETO**.

Collegati: [personas](personas.md) · [../000_identity](../000_identity.md) · [../thinking/failure-patterns](../thinking/failure-patterns.md)
