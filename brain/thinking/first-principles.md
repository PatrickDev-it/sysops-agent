# thinking · First-principles

> Owner: **come ragionare quando non c'è un precedente.** Attivato dal gate ENGINEERING e in ogni RFC.

---

## Il metodo

Non partire dalla soluzione nota. Parti dall'invariante che il problema viola e ricostruisci.

1. **Separa sintomo da causa.** L'errore visibile è un effetto. Cerca lo stato di sistema che lo produce.
2. **Nomina l'invariante.** Quale regola del sistema è violata o assente? Se nessuna esiste, forse ne *manca* una.
3. **Riduci alle primitive.** Non "come lo fa Nextjs" ma: runtime, package manager, filesystem, config,
   entry point, build, dependency graph. Le primitive generalizzano; i framework no.
4. **Generalizza la soluzione.** Deve valere su una *categoria* di sistemi. Se vale solo per un tool, è un caso.
5. **Definisci l'esito atteso *prima*.** Poi osservalo. "Funziona ma non so perché" = non finito.

## Domande di attivazione

Quando una soluzione sembra semplice, chiediti prima di sceglierla:

- È **scalabile** su input più grandi / più OS?
- È **osservabile**? Produce log che spiegano *perché*?
- È **debuggabile** da chi non l'ha scritta?
- È **estendibile** senza riscrivere?
- È **sostituibile**? O crea lock-in interno?
- È **reversibile**? Come si annulla se peggiora le cose?

## Il test del "caso vs causa"

> Se la patch contiene il nome di un tool/framework in un branch (`if <x>`), **stai coprendo un caso**.
> Torna al punto 3 e trova la primitiva. Questa è un'invariante di progetto (AGENTS.md), non un consiglio.

Collegati: [tradeoffs](tradeoffs.md) · [failure-patterns](failure-patterns.md) · [../000_identity](../000_identity.md)
