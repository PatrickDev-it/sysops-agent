# runtime.md

> Owner: **il substrato d'esecuzione — l'umbrella sopra i canali batch/interactive/remote.** È il layer che
> l'Executor usa. I due layer sottostanti dell'interazione a terminale sono [terminal-runtime.md](terminal-runtime.md)
> (sessione/prompt) e [pty-runtime.md](pty-runtime.md) (bytes/pyte). *Tre layer di uno stack, non tre viste.*

---

## Lo stack di esecuzione (chi sta sopra chi)

```
   Executor
      │ Action
   ┌──▼─────────────────────────── runtime.md (questo) ──────────────────────────┐
   │  Channel selection:  BATCH  │  INTERACTIVE  │  REMOTE(SSH)  │  SANDBOX        │
   └──────┬───────────────┬──────────────┬───────────────┬──────────────────────┘
          │               │              │               │
     one-shot cmd    terminal-runtime   ssh transport   sandbox wrapper
     (subprocess)    (wizard/pty)       (remote host)   (namespaces/container)
                          │
                     ┌────▼──── terminal-runtime.md ────┐   sessione, prompt-detection, driver
                     │        pty-runtime.md            │   pyte, bytes VT100, screen virtuale
                     └─────────────────────────────────┘
```

## Responsabilità del runtime (questo doc)

- **Channel selection:** dato il `kind` dell'azione, sceglie il canale (batch subprocess, interactive PTY, SSH,
  sandbox). Astratto dietro una porta → l'Executor non sa quale canale.
- **Session lifecycle:** apertura/chiusura/recovery delle sessioni persistenti; una shell viva per continuità dove
  serve, effimera dove no.
- **Transport uniforme:** locale e remoto (SSH) espongono la **stessa interfaccia** → un'azione è indifferente a
  dove gira (chiave per la fleet, [scalability.md](scalability.md)).
- **Environment seeding:** OS/shell/priv/cwd noti iniettati come Fact all'avvio (evita lo "shell flailing" di v1).

## Perché tre layer separati

Single-owner: "quale canale" (runtime) ≠ "come guido un wizard" (terminal-runtime) ≠ "come interpreto i bytes VT100"
(pty-runtime). In v1 questi erano parzialmente mescolati (più `session.py`, `terminal.py`, `wizard_driver.py`,
`terminal_runtime/`), con dead code (`screen_parser`/`state_machine`). Qui: confini netti, un owner per layer.

## Confronto competitor

- **OpenHands** ha il miglior *runtime pluggable* (local/docker/remote) → riferimento diretto per questa astrazione.
- **Warp/terminali AI:** ottima UX terminale ma non un runtime agentico multi-canale.
- **v1:** canali presenti ma senza un'astrazione di selezione pulita e con residui legacy → li unifichiamo.

## Pattern

Strategy (channel) · Adapter/Port (transport locale/SSH/sandbox) · Bridge (runtime ↔ terminal-runtime) · Object pool
(sessioni) · Uniform interface (locale == remoto).

## Alternative scartate

- **Un solo canale (solo batch, o solo PTY):** i wizard interattivi richiedono PTY, i comandi secchi no; forzarne uno
  è inefficiente o incapace. **Rifiutato** — selezione esplicita.
- **Accoppiare il runtime al modello/goal:** rompe la sostituibilità. **Rifiutato** — il runtime è puro trasporto.

## Trade-off / Benchmark / Evoluzioni

Trade-off: più canali = più adapter da mantenere; ripagato dalla portabilità (stesso agente, locale e su 100 host).
Benchmark: overhead di apertura sessione ammortizzato dal pool. Evoluzioni: runtime WASM-sandbox per tool non fidati,
runtime "mux" (una connessione SSH multiplexa più azioni), runtime che emette Fact di costo (per il Cost Optimizer).
