# pty-runtime.md

> Owner: **il layer più basso: pseudo-terminale, bytes VT100, schermo virtuale.** Sta *sotto*
> [terminal-runtime.md](terminal-runtime.md). Non sa nulla di prompt o goal: trasforma bytes in una griglia di
> caratteri fedele e viceversa.

---

## Responsabilità

- **PTY allocation:** aprire uno pseudo-terminale (pty/conpty su Windows) attorno a un processo interattivo.
- **Screen emulation:** interpretare i bytes ANSI/VT100 in una **griglia di caratteri** deterministica (via `pyte`),
  così i layer sopra vedono "lo schermo come lo vedrebbe un umano", non uno stream di escape.
- **I/O bytes:** scrivere input, leggere output, gestire flush/backpressure.

## Invariante fondamentale

> **pyte riceve bytes grezzi con ANSI intatti, mai testo già decodificato.** (Invariante ereditato da v1.)
> Decodificare prima di pyte corrompe lo schermo (colori, cursori, redraw). È l'errore classico che questo layer previene.

## Perché è un layer a sé

È l'**anti-corruption layer** tra il caos dei bytes di terminale e il mondo pulito e strutturato sopra. Ogni cosa che
tocca escape sequences/cursori/redraw vive *solo* qui. Sopra, nessuno vede più un byte ANSI: vede una griglia stabile.
Questo rende testabile tutto il resto (registri i bytes una volta, li rigiochi in pyte, hai lo schermo).

## Confronto competitor

- La maggior parte degli agenti **non emula un vero terminale**: catturano stdout come stringa e perdono la fedeltà
  di redraw/cursore → falliscono su TUI e progress-bar. Noi abbiamo uno **schermo virtuale reale**.
- **Warp** è un terminale reale (nativo) ma non un runtime agentico headless; noi ci serve headless e programmabile.
- **v1** usa già pyte/VirtualScreen correttamente → **lo manteniamo**; è uno dei pezzi migliori della v1.

## Pattern

Anti-corruption layer · Terminal emulation (VT100) · Adapter (pty/conpty per-OS) · Immutable snapshot dello schermo.

## Alternative scartate

- **Catturare stdout come stringa (no PTY):** rompe su interattivo/TUI/colori; molti programmi cambiano
  comportamento se non vedono un tty. **Rifiutato.**
- **Scrivere un emulatore VT100 proprio:** reinventare pyte, buggy. **Rifiutato** — pyte è maturo e sufficiente.

## Trade-off / Benchmark / Evoluzioni

Trade-off: un PTY per sessione ha costo (fd, memoria) → mitigato dal pool e da sessioni effimere quando l'interattività
non serve. Benchmark: fedeltà = capacità di guidare installer/TUI reali (test su casi noti). Evoluzioni: conpty
avanzato su Windows, cattura di sequenze OSC (title, hyperlink) come Fact, registrazione/replay asciinema per debug.
