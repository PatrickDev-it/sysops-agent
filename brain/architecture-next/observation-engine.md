# observation-engine.md

> Owner: **bytes → Fact tipizzati**, e la verifica delle post-condizioni (Validator). È il confine tra il mondo
> (testo/bytes) e la cognizione (fatti). *Nessun testo grezzo attraversa questo confine verso l'alto.*

---

## Principio: osservazione ≠ testo

Un comando non produce "output": produce **evidenza**. L'Observation Engine trasforma i bytes del terminale in
**Fact tipizzati** con provenienza. Il resto del sistema non vede mai `stdout` grezzo (se non un *bounded snapshot*
esplicitamente richiesto per un caso difficile).

```
bytes (pyte screen) ──► parse per command-class ──► Fact[]
  "systemctl status nginx" → { entity:service:nginx = FAILED, exit=3, since=…, main_pid=… }
  "ss -ltnp"               → { entity:port:443 = LISTEN by pid 1234 (nginx) }  (archi nel World Model)
  "apt-get install X"      → { capability:X = INSTALLED v.1.2, side_effect: pkgs[…] }
```

## Parser per classe di comando (non per tool)

I parser sono organizzati per **classe di output** (tabellare, key-value, exit-only, streaming-log), non per singolo
tool → framework-neutral. Il Knowledge Graph dice *che forma* ha l'output di un intento; il parser giusto ne estrae i
Fact. Un nuovo tool con output tabellare non richiede codice nuovo: riusa il parser tabellare.

## Error-noise rejection

Un DISCOVERY "riesce" solo con **dati reali**, non con testo d'errore (fix di un difetto v1: "discovery succeeded su
error output"). L'Observation Engine separa segnale (Fact) da rumore (stderr/errori) e marca l'esito di conseguenza.

## Validator (post-condizioni)

La verifica non è "il file esiste" ma "**gli effetti attesi del piano sono Fact osservati**". Il nodo di piano
dichiara `effects` e `verify_predicate`; il Validator li controlla producendo Fact `verify.*`. Content-aware: per
"scrivi diagnosi in X" verifica il *contenuto*, non la dimensione (fix v1 Pattern A/D). L'artifact-check sovrascrive
l'exit code (invariante).

## Confronto competitor

- **OpenHands** ha Observation nel suo event stream — ma **testo**; il modello re-parsa ad ogni giro. Noi parsiamo
  **una volta** in struttura riusabile → meno token, meno errore.
- **Aider** osserva lint/test (strutturato per il codice); noi generalizziamo a *qualsiasi* comando di sistema.
- **v1** aveva `observer`/`success_checker`/`behavior_verifier` — funzioni giuste ma sparse e testo-centriche; le
  unifichiamo dietro un contratto "bytes→Fact" con un solo owner.

## Pattern

Anti-corruption layer (mondo↔cognizione) · Parser combinator per classe · Structured logging · Post-condition
verification (design-by-contract) · Provenance tagging.

## Alternative scartate

- **Passare stdout grezzo al modello ("il modello legge l'output"):** è l'anti-pattern token/allucinazione (v1/tutti).
  **Rifiutato** — solo Fact, snapshot bounded on-demand.
- **Un parser per ogni tool:** esplosione di casi speciali. **Rifiutato** — parser per *classe di output*, guidati dal KG.

## Trade-off

- Parser strutturati = lavoro iniziale e casi limite (output malformati, locale, colori ANSI). Mitigazione: pyte
  normalizza lo schermo; fallback a snapshot bounded quando il parse fallisce, con un Fact `parse:low_confidence`.
- Rischio: un parser sbagliato produce un Fact sbagliato. Mitigazione: confidence + il Reasoning Engine può richiedere
  ri-osservazione se un Fact contraddice belief PROVEN.

## Benchmark teorico

Compressione osservazionale: da ~KB di output a ~decine di token di Fact. È il gemello del Context Engine: uno
*comprime in ingresso* (bytes→Fact), l'altro *seleziona in uscita* (Fact→prompt). Insieme = il budget token che regge 3B/4B.

## Evoluzioni

Parser generati/estesi dall'esperienza · osservazione da fonti non-terminale come adapter (journald, /proc, WMI,
Prometheus) che emettono gli **stessi Fact** → il reasoning non distingue la fonte · anomaly detection sui Fact temporali.
