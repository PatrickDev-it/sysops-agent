# RFC 003 — Dieci proprietà, e l'ordine in cui sono implementabili

> Stato: **proposta**, 2026-07-20. Nasce da una review esterna che elenca dieci proprietà mancanti,
> tutte condivisibili, presentate come un elenco. Questa RFC non le discute una per una: le **ordina**
> per dipendenza, perché eseguite nell'ordine dato due di esse si bloccano a vicenda.

## Context

La review esterna coglie la cosa giusta: i problemi rimasti non sono bug, sono **proprietà del
sistema**. Elenca dieci direzioni (runtime isolato, snapshot dell'ambiente, piano incrementale,
world model persistente, PTY tipizzato, executor a grammatica, scheduler, telemetria, prompt minimi,
metrica vettoriale) e chiude con cinque vincoli non negoziabili.

Il quinto vincolo è: *«nessuna modifica è un miglioramento senza benchmark ripetibili»*.

**Questo vincolo, oggi, rende le altre nove voci non implementabili secondo la propria regola.**
Misurato il 2026-07-20 su due run della suite a 48 task con **codice identico**, stesso seed, greedy,
prefix cache spenta:

| | run A | run B |
|---|---|---|
| ARR | 34/48 | 39/48 |

E sui **41 task il cui esito non è cambiato**:

| contatore | identico su | media \|diff relativa\| per task |
|---|---|---|
| token di prefill | **1/41** | 34,3 % |
| wall-clock | **0/41** | 55,7 % |
| call LLM | 9/41 | 29,3 % |

Non esiste oggi un benchmark ripetibile su questo progetto. Il vincolo 5 non è un criterio di
accettazione: è il **primo lavoro da fare**.

### Perché diverge — misurato, dopo due ipotesi sbagliate

Non è il modello. Misurato per template sulla prima call di ogni task:

| template | prompt identici | output identici, dove il prompt lo era |
|---|---|---|
| `safety.jinja` | **48/48** | **48/48** |
| `prompt_enhancer.jinja` | **47/47** | **47/47** |
| `supervisor.jinja` | **0/47** | — |

**A prompt identico l'output è identico, 95 volte su 95.** Lo stack di inferenza è deterministico e
`DETERMINISTIC` funziona esattamente come documentato.

Non è nemmeno l'ambiente osservato. `safety.jinja` e `prompt_enhancer.jinja` ricevono
`{goal, system_spec}` e nient'altro, e sono **byte-identici**: la descrizione della macchina è già
congelata e stabile (`system_spec` è costruito una volta per run e conservato come fatto).

La differenza fra quei due template e il planner è **`history`**. `Supervisor.plan` inserisce
`memory.get_recent_events()` nel prompt, e quella memoria è **un unico store di processo**: si
accumula fra i task di una run e **sopravvive alla run successiva**. Prova diretta: a fine
esperimento `var/memory/context_cache.json` conteneva eventi di `arm_repeat/T46` e `T47` — cioè il
task T01 di ogni run pianificava leggendo ciò che il T47 della run **precedente** aveva lasciato.

La suite non misurava 48 prove indipendenti: misurava **una sequenza dipendente di 48 passi,
inizializzata da ciò che era rimasto in giro**. È questo che faceva muovere 5 task a una ripetizione
pura.

> **Nota di metodo.** La review dice *«non è il modello che diverge, è il mondo»*, e la prima
> versione di questa RFC ne ha dedotto che il lavoro fosse congelare l'ambiente. La misura ha
> falsificato entrambe: non è il modello **e non è il mondo esterno** — è lo stato interno che
> l'agente stesso si porta dietro. Sono tre ipotesi falsificate in una giornata (l'estrattore
> prosa→comando, la tabella dei token d'ambiente, lo snapshot dell'ambiente): il valore non è
> nell'aver indovinato, è nell'aver chiesto al ledger prima di scrivere il codice.

## Proposal

Le dieci voci si ordinano da sole se si chiede a ciascuna: *cosa deve esistere prima perché io sia
verificabile?*

### Fase 0 — rendere possibile la misura (blocca tutto il resto)

**0a. Indipendenza dei task nel benchmark. — FATTO, in attesa di verifica.**
Ogni task riceve la propria directory di memoria; `config.MEMORY_DIR` è già risolto a runtime, quindi
la correzione vive **nel harness**, non nel prodotto. Questa è la distinzione che conta: un agente che
ricorda i task precedenti è una **funzionalità** in produzione ed è **contaminazione** in un
benchmark che li punteggia come prove indipendenti. Il prodotto non cambia.

Criterio di uscita (misura, non opinione): due run consecutive a codice identico devono produrre lo
stesso numero di token di prefill su **≥ 90 % dei task** (prima della correzione: 1 task su 41, il
2 %). Se non ci arriva, la causa non era solo la memoria e si ricomincia dal ledger.

**0b. Runtime isolato (container/VM).**
La review lo classifica P0 ed è corretto: è l'unico blocker di **sicurezza** vero, e nessuna regex lo
sostituisce. Resta P0 — ma va detto che, alla luce di 0a, **non è più anche la soluzione al problema
di misura**: la contaminazione non veniva dalla macchina, veniva dallo store interno dell'agente. Il
container va fatto perché un agente che esegue shell arbitraria sull'host non è distribuibile, non
perché renda ripetibile il benchmark.

**0c. Consolidare i cinque owner dell'ambiente. — declassato da P0 a debito di latenza.**
L'audit del sorgente trova **cinque owner indipendenti** di «cos'è questa macchina»
(`state.Environment`, `knowledge/environment_detector`, `knowledge/system_spec`,
`supervisor._workspace_context`, `tools/observer.observe`), più sonde ad-hoc in altri sei moduli, con
disaccordi reali (`shell` vale `"powershell"` per uno e `"pwsh"` per l'altro) e costi reali
(~45 `shutil.which` per `detect()`, fino a 13 subprocess `--version`, e `observe()` che rilegge
l'intero workspace ~3 volte per step, contenuto dei file compreso).

Era la Fase 0a di questa RFC, motivata dal determinismo. **La misura ha tolto quella motivazione:**
`system_spec` è già stabile e congelato. Resta però un problema vero — duplicazione di owner (vietata
da `AGENTS.md`) e latenza di I/O ripetuta — quindi la voce sopravvive con una giustificazione
diversa e una priorità più bassa. Va misurata come **latenza**, non come determinismo, e il numero da
battere va preso prima di toccarla.

### Fase 1 — la voce con il numero più grande dietro

**1. Piano incrementale (StepGraph + stati per step).**
La review la indica come la scoperta più importante del report ed è d'accordo con la misura: il
supervisor è **870 s su 1.493 s (58 %) del tempo di inferenza**, con 101 call per 48 task, di cui
**53 re-plan** che rigenerano il piano intero invece di ripararne una parte.

È già misurabile: il fingerprint del piano (12 caratteri, solo comandi e tipi di step, insensibile
alla prosa) è in traccia da oggi, perché il campo `output` è tagliato a 1200 caratteri e **82 piani su
86 erano illeggibili** — la domanda «questo re-plan ha prodotto qualcosa di nuovo?» era rispondibile
su 4 campioni, di cui 2 identici byte a byte. n=4 non decide nulla; con lo strumento in piedi, la
prossima run lo decide.

**Prerequisito di misura:** fase 0, altrimenti «i re-plan sono scesi da 53 a 20» non è distinguibile
dal rumore.

### Fase 2 — riduzioni di inferenza, ciascuna con il proprio esperimento

Ordinate per quota misurata del tempo di inferenza, non per intuizione:

| voce (review) | quota misurata | come si testa |
|---|---|---|
| **6.** Executor a grammatica (il 3B sparisce quasi sempre) | coder = **10 %** (151 s), ma **39 % di tutte le call**, e il **57 % delle sue proposte è respinto dai gate** | flag `SISTEMISTA_EXECUTOR_AUTHORS_ACTIONS=0` — **esiste già**, zero codice |
| **9.** Prompt minimi | enhancer = **12 %** (180 s), effetto sull'esito mai misurato | flag `SISTEMISTA_ENHANCER=0` — aggiunto oggi |
| **4.** World model persistente al posto dello stato nel prompt | verify = 11 %, supervisor = 58 % (lo stato è dentro) | dipende da 0a: senza snapshot congelato non si sa cosa il prompt possa smettere di portare |
| **5.** PTY tipizzato (schermata → tipo, mai ANSI al modello) | non nella suite corrente (0 task interattivi) | serve prima un carico che lo eserciti, altrimenti si ottimizza alla cieca |

### Fase 3 — infrastruttura che non cambia il comportamento

**7. Scheduler** e **8. telemetria estesa**. Entrambe corrette e nessuna delle due urgente: uno
scheduler con priorità/deadline/backoff paga quando c'è concorrenza, e RFC-002 §0 stabilisce che qui
la concorrenza reale è **overlap di I/O**, non parallelismo — con 2 slot modello e ~436 MiB liberi
non c'è VRAM per un terzo contesto. La telemetria per-fase (LLM ms / PTY ms / shell ms / cache
hit/miss / plan reused vs regenerated) è invece a costo quasi zero e va agganciata al trace
esistente, non a un secondo sistema.

### Trasversale

**10. Metrica vettoriale.** Da adottare subito come *forma* del giudizio — è il presidio contro
«+1 % di successo pagato con il doppio dei token». Ma va scritta sapendo che **oggi ogni componente
del vettore ha una barra d'errore più grande di qualsiasi effetto che vorremmo misurare** (token
±34 %, latenza ±56 %, ARR ±5 task). Il vettore diventa utilizzabile dopo la fase 0, non prima.

## Alternatives

**Eseguire l'elenco nell'ordine dato (1→10).** Rifiutata: si comincerebbe dal container (giusto), ma
le voci 3-9 verrebbero valutate con uno strumento che non risolve i loro effetti, e si accumulerebbero
modifiche non validate — esattamente il modo in cui questo progetto ha già prodotto tre conclusioni
false, registrate in `test_benchmark_noise_floor.py`.

**Partire dal piano incrementale (voce 3), che ha il numero più grande.** Rifiutata per la stessa
ragione: è la voce che vale di più *e* quella il cui effetto è più facile confondere col rumore,
perché tocca il planner, cioè la sorgente di ogni divergenza a valle.

**Partizionare la suite in task ermetici / stato-vivo invece di congelare l'ambiente.** Più
economica e ha un merito reale (la partizione **esiste già nei dati**: 32 task passano sempre, 4
falliscono sempre, 12 oscillano). Rifiutata come sostituto, tenuta come **complemento**: misurare
solo sui task ermetici riduce la suite a ciò che non tocca il carico reale di un agente sysops, il
cui lavoro *è* interrogare la macchina viva. Congelare l'osservazione è la mossa che conserva il
dominio; la partizione è utile subito come controllo incrociato.

## Decision

Ordine di lavoro: **0a → 1 → 2 → 0b → 0c → 3**, con la metrica vettoriale (10) adottata come forma
del giudizio da 0a in poi.

0b (container) resta P0 per la **distribuzione** ma non blocca il lavoro di riduzione dell'inferenza,
ora che si è visto che non era la causa del rumore; 0c scende dietro alla fase 2 perché la sua
giustificazione è passata da "determinismo" a "latenza duplicata".

Il criterio di uscita della fase 0a è quello scritto sopra: **stesso prefill su ≥ 90 % dei task fra
due run consecutive**. Finché quel numero non sale, nessuna delle fasi successive è dichiarabile
riuscita — e questa RFC va riaperta, non aggirata.

## Consequences

- **Il vincolo 5 della review diventa applicabile** invece che auto-bloccante. È l'unico cambiamento
  che questa RFC fa alla proposta esterna; le dieci voci restano tutte, nessuna è respinta.
- **Costo:** la fase 0 non migliora ARR, latenza né token. È lavoro che non muove nessuna metrica del
  vettore e va difeso proprio per questo — rende vere le metriche.
- **Rischio:** congelare l'ambiente può *nascondere* difetti reali che dipendono dallo stato vivo (un
  agente che funziona solo su snapshot e non sulla macchina). Mitigazione: lo snapshot è pinnato
  **solo in modalità benchmark**; in produzione si osserva una volta e si congela **per la durata
  della run**, che è già un miglioramento sul comportamento attuale (osservazioni ripetute e
  incoerenti fra loro dentro la stessa run).
- **Ciò che falsifica questa RFC:** se dopo 0a la ripetizione pura continua a divergere sopra il 10 %
  dei task, allora la causa non era l'ambiente osservato e l'analisi qui sopra è sbagliata — si
  ricomincia dai dati.

## Nota fattuale sulla voce 9 della review

La review progetta i prompt per «Fable5, forte con poco contesto». Fable 5 **non è nel runtime di
Sistemista**: i modelli owned sono `Qwen3-4B-Q5_K_M` (NAV) e `Qwen2.5-Coder-3B` (executor); Fable 5
è l'agente che sviluppa il progetto e, al più, l'*oracolo* opzionale via HTTP — che per RFC-001 è
esplicitamente non necessario (default self-contained). La raccomandazione **sopravvive alla
correzione e si rafforza**: un 4B ha bisogno di prompt corti e strutturati più di quanto ne abbia
bisogno un modello di frontiera. Ma il bersaglio da tenere in mente quando si taglia il contesto è
il 4B, non Fable 5 — e le due cose hanno soglie diverse.
