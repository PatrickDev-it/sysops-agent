# 100 · Moat — perché Sistemista è difendibile

> Owner: **il vantaggio competitivo e cosa lo erode.** Gate MARKET (ADVISORY, ma "erosione del moat" = red flag).

---

## Le fonti di moat (in ordine di forza)

1. **Ragionamento causale, non pattern-matching.** La maggior parte degli agenti "prova comandi finché
   passa". Sistemista mantiene un *modello del sistema* (SystemState + reasoning belief system) e agisce solo
   su belief PROVEN. → Difficile da replicare: è architettura, non un prompt.
2. **Framework-neutrality come disciplina.** I competitor accumulano casi speciali (`if nextjs`) che invecchiano.
   Il rifiuto strutturale di quel debito è un vantaggio composto nel tempo.
3. **Locale e autonomo.** Nessuna dipendenza da un LLM cloud per ragionare → sovranità, privacy, costo zero
   per-token, funziona offline. Un moat verso i wrapper cloud.
4. **Verifica per artifact, non per exit code.** Dichiara "fatto" solo se i file previsti esistono. Riduce i
   silent failure che affliggono gli agenti mainstream.
5. **Recovery vincolata dall'errore osservato.** La recovery deriva dall'`error_classifier`, non da retry ciechi.

## Cosa erode il moat (red flag di prodotto)

- Aggiungere un caso speciale per un framework → converte il moat #2 in debito.
- Introdurre una dipendenza cloud per il ragionamento → distrugge il moat #3.
- Dichiarare "fatto" senza artifact check → distrugge il moat #4.
- Copiare una feature di un competitor senza chiedersi *perché noi diversamente* → dissolve la differenziazione.

## Domande del gate

> Questa patch **aumenta** un moat sopra, o ne **erode** uno? Se erode → red flag, motiva prima di procedere.

Collegati: [competitors/](competitors/) · [../000_identity](../000_identity.md) · [../300_product/product-philosophy](../300_product/product-philosophy.md)
