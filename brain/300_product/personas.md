# 300 · Personas

> Owner: **per chi costruiamo.** Gate PRODUCT usa questo per "serve la persona reale?".

---

## Persona primaria — "lo sviluppatore bloccato dal sistema"

- **Chi:** sviluppatore/DevOps che vuole *lavorare*, non debuggare l'ambiente.
- **Job-to-be-done:** "il mio sistema è in uno stato rotto (deps in conflitto, PATH sbagliato, tool non
  installato) — voglio tornare produttivo senza diventare esperto di quel sottosistema."
- **Cosa lo frustra:** consigli generici da forum che non si applicano al *suo* stato; fix che rompono altro;
  agenti che "provano comandi" e peggiorano la situazione.
- **Cosa lo delizia:** dare un obiettivo e riottenere un sistema funzionante, con la spiegazione del *perché*.

## Persona secondaria — "l'operatore su macchina non sua"

- **Chi:** chi amministra VPS/macchine altrui via SSH.
- **JTBD:** risolvere via terminale (nessuna GUI), in sicurezza, senza effetti collaterali distruttivi.
- **Vincolo forte:** ambiente sconosciuto → il ragionamento causale e il safety gate sono *la* feature.

## Non-persona (per chi NON costruiamo)

- Chi vuole un chatbot conversazionale generico.
- Chi vuole uno scaffolder specifico-per-framework con mille template.

## Uso nel gate

> Questa patch riduce un attrito di una persona sopra? Se serve solo una non-persona → fuori scope.

Collegati: [product-philosophy](product-philosophy.md) · [../200_business/north-star](../200_business/north-star.md)
