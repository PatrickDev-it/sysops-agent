# terminal-runtime.md

> Owner: **la sessione interattiva: prompt-detection, driving dei wizard, ciclo evento del terminale.** Sta *sopra*
> [pty-runtime.md](pty-runtime.md) (bytes/pyte) e *sotto* [runtime.md](runtime.md) (selezione canale).

---

## Responsabilità

Guidare programmi **interattivi** (installer, wizard, REPL, prompt sudo, conferme `[y/N]`) senza loop infiniti:

- **Prompt detection:** riconoscere *quando* il programma aspetta input (shell prompt vs domanda vs spinner vs
  pager), leggendo lo schermo virtuale del pty-runtime.
- **Driver:** decidere la risposta (da un Fact/piano, non improvvisando) e inviarla.
- **Stuck/loop detection:** riconoscere ripetizioni anomale (stesso prompt N volte) → abortire (generalizza lo
  stuck-detector di v1).
- **Event loop:** feed → detect → act → observe, fino a prompt di shell stabile o completamento.

## Prompt-detection come classificatore deterministico

Il rilevamento del prompt è **deterministico** (pattern sullo schermo virtuale), non una chiamata al modello: è
System-1. Solo se il prompt è *ambiguo/sconosciuto* si escala al Supervisor (System-2) per decidere la risposta →
frugalità: il modello interviene raramente, sui casi genuinamente nuovi.

## Perché separato dal pty-runtime

- **pty-runtime** = "cosa c'è sullo schermo" (bytes VT100 → griglia di caratteri via pyte).
- **terminal-runtime** = "cosa significa e cosa faccio" (è un prompt? rispondo cosa?).
Mescolarli (rischio v1) rende impossibile testare la logica di driving senza un PTY reale. Separati: la
prompt-detection si testa su schermate registrate.

## Confronto competitor

- **Quasi nessun competitor guida wizard interattivi:** i coding agent evitano l'interattività (Aider/Cline/Codex
  lavorano su file/comandi non interattivi). **Questo è un nostro vantaggio di dominio**: il sysops *è* pieno di
  prompt interattivi (apt, ssh host-key, sudo, fdisk, installer).
- **v1** aveva già `terminal_runtime/` con pyte + PromptDetector + Driver — **la base giusta**, da mantenere e
  ripulire dai residui (`screen_parser`/`state_machine` morti).

## Pattern

State machine (schermo→azione) · Deterministic classifier (prompt) · Event loop · Escalation to System-2 su ambiguità
· Guard/timeout (anti-loop).

## Alternative scartate

- **Inviare tutto l'output al modello e chiedergli "cosa rispondo":** costoso e lento per ogni prompt banale
  `[y/N]`. **Rifiutato** — detection deterministica, modello solo su ambiguità.
- **`expect`-style scripting per tool:** casi speciali per programma. **Rifiutato** — detection per *classe di prompt*,
  framework-neutral.

## Trade-off / Benchmark / Evoluzioni

Trade-off: la detection deterministica ha falsi negativi su prompt esotici → fallback all'escalation. Benchmark:
% di prompt gestiti senza modello (target >90%). Evoluzioni: libreria di *pattern di prompt* estesa dall'esperienza,
gestione di TUI complesse (ncurses) via pyte, replay di sessioni interattive per test.
