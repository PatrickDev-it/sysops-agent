# 200 · North Star

> Owner: **l'obiettivo unico che ordina le priorità.** Gate BUSINESS (VETO).
> Se una patch non serve la north star, non si implementa — per quanto sia una feature "carina".

---

## North star

> **Massimizzare la frazione di problemi di sistema che un utente risolve digitando *un solo obiettivo*,
> senza intervento umano e senza sapere come.**

Ovvero: ridurre a zero la distanza tra "ho un problema di sistema" e "è risolto", su qualsiasi OS,
via terminale. Ogni patch si giudica per quanto avvicina questo.

## Metrica direzionale (proxy)

La metrica che approssima la north star (da strumentare — vedi `src/telemetry.py`):

- **Autonomous resolution rate**: % di goal chiusi con artifact check verde **senza** fallback all'umano.

Sub-segnali che la muovono nella giusta direzione:
- ↓ silent failure / risultati parziali (qualità)
- ↓ casi speciali per framework (generalità → copre più sistemi)
- ↑ recovery riuscite derivate dall'errore osservato

> ⚠️ **Da compilare con evidenza:** baseline e target numerici non esistono ancora. Non inventarli —
> strumentare la telemetry prima. Coerente con l'ethos "non inventa, confronta".

## Cosa la north star NON è

- Non è "supportare più framework possibile" (sarebbe il database di casi speciali vietato).
- Non è "avere più feature dei competitor".
- Non è una metrica di crescita/utenti: Sistemista è un motore, non ancora un funnel.

## Uso nel gate

> La patch aumenta l'autonomous resolution rate (direttamente o rimuovendo una classe di fallimenti)?
> Se no → deprioritizza o rifiuta.

Collegati: [../000_identity](../000_identity.md) · [roadmap](roadmap.md) · [../900_execution/README](../900_execution/README.md)
