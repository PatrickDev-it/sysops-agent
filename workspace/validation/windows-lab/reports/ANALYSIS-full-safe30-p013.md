# ANALYSIS — full-safe30-p013 (post PATCH-012/013, live GPU)

> ⚠️ **Documento storico — congelato.** Scritto prima della riorganizzazione del 2026-07-10;
> numeri, prosa e conclusioni sono lasciati esattamente com'erano. I path che cita si leggono così:
> `.workspace/` → `workspace/` · `validation/telemetry/` → `var/telemetry/` ·
> `validation/benchmark/` → `var/benchmark/` · `src/tests/` → `tests/` · `_test_workspaces/` → `_sandbox/`.
> I comandi di riproduzione al suo interno non sono più eseguibili alla lettera.

> Run: 30 Windows SAFE cases, dual-GGUF su RTX 3070 Ti, stesso set esatto della baseline
> `full-safe30`. Prima run con **DecisionGraph OBSERVED** (PATCH-013) → l'analisi non è più
> ricostruita a mano ma letta dai nodi decisione. Metodo: behavior → codice esatto → frequenza → KPI.

## 1. Delta di risultato (stesso set, single-run vs single-run)

| Metrica | baseline full-safe30 | full-safe30-p013 | Δ |
|---|---|---|---|
| **ARR** | 63.3% (19/30) | **83.3% (25/30)** | **+20.0 pt** |
| **FTFR** | 26.7% | **30.0%** | +3.3 pt |
| **RAF** | 2.11 | 2.27 | +0.16 |
| deviations | 22 | 21 | −1 |

**Caveat di onestà:** entrambe le run sono single-shot su modelli stocastici (sampling). Il set di
casi è identico (30/30 ID verificati), quindi il confound di selezione è escluso, ma **+20 ARR contiene
varianza del modello**: non è un A/B a n=1 conclusivo. Il segnale robusto — indipendente dal pass/fail —
è il comportamento interno del DecisionGraph, sotto.

## 2. Segnale robusto: DecisionGraph (412 decisioni, prima misura in assoluto)

- confirmed **263** · diverged **143** · blocked **5**
- **first_shot_accuracy medio 0.667** (min 0.44, max 1.00 su 29 run con decisioni chiuse)
- **divergenze per ErrorClass: UNKNOWN 105 · COMMAND_SYNTAX 30 · FILE_NOT_FOUND 8**

Lettura: **il 73% delle divergenze (105/143) è UNKNOWN.** Il recovery layer riceve un segnale
strutturato solo su 1 fallimento su 4. Questo è il collo di bottiglia dominante di **Recovery Accuracy**.

## 3. Patologie ordinate per leva architetturale

### P-C — False refutazione di tool reali  ⟵ target laser #1
**Behavior:** comandi discovery che *filtrano a vuoto* (`Where-Object`, `Select-String`, `findstr`
senza match) vengono letti come "tool assente" e il tool reale viene marcato REFUTED; il policy guard
poi **blocca** gli usi successivi legittimi.

**Frequenza (30 casi):**
- 4 built-in Windows refutati: `netstat`, `Get-Service`, `Get-ChildItem`, `reg`
- **4 refuted-then-succeeded (provabilmente falsi):** `get-content`, `get-eventlog`, `reg` refutati e
  poi *eseguiti con successo nella stessa run*
- **9 empty-discovery → refute senza alcun segnale d'errore** (`Get-NetIPAddress|Where`,
  `Get-NetRoute|Where`, `Get-Content|Select-String`, `Get-EventLog|Where`, …)
- **5 policy-block a valle, TUTTI su tool reali** falsamente refutati: `Get-ComputerInfo`,
  `Get-Content`, `certutil`, `reg`×2 → 5 step legittimi bloccati, ognuno forza un giro di recovery

**Codice esatto:**
- [tools/observer.py:185-188](../../../src/tools/observer.py#L185) — DISCOVERY con stdout vuoto →
  `(False, "discovery step produced no output")`. Equipara "nessun output" a "fallito".
- [reasoning.py:631-652](../../../src/reasoning.py#L631) — branch `step_type=="DISCOVERY"` in
  `_infer_from_failure`: refuta `tool:exists` **senza guardare il perché** l'output è vuoto.
- [reasoning.py:896-902](../../../src/reasoning.py#L896) — `ExecutionPolicyGuard.check` blocca poi
  `run:<tool>` sui belief REFUTED.

**Causa radice:** il codice conflaziona *"DISCOVERY senza output"* con *"tool assente"*. Ma il caso
davvero-assente è **già** coperto con evidenza dal branch FILE_NOT_FOUND / not-recognized. Il branch
DISCOVERY è quindi ridondante **e** produce falsi negativi che corrompono l'identità nel belief store.
**KPI colpiti:** Belief Consistency, FTFR (forza recovery inutili), Runtime Reliability.
**Nota architetturale:** è corruzione d'identità — lo stesso dominio di PATCH-012. Il fix ha un solo
posto se `X:exists` vive nel WorldGraph con provenienza, non come stringa belief separata.

### P-E — Template leak che buca il write-guard  ⟵ target laser #2
**Behavior:** file scritti con placeholder non risolti; li prende solo la LLM-verify a valle → un giro
di recovery sprecato per ogni occorrenza.

**Frequenza:** **6 leak su 5 casi** — pattern osservati: `[DATE_FROM_STEP_3]` (bracket),
`$cpu_cores`/`$ram_total` (var minuscole), `$(Get-Date …)` (subexpression), `{command placeholders}`.

**Codice esatto:** [tools/template_guard.py:33-46](../../../src/tools/template_guard.py#L33) —
`_ANGLE_PLACEHOLDER` copre `<UPPER>`, `_BRACE_PLACEHOLDER` copre `{UPPER}`, `_SHELL_VAR_TOKEN` non
copre `[BRACKET]`, `$(...)`, né `$var` minuscolo. Tre classi di placeholder passano il guard.
**KPI colpiti:** FTFR, Context Efficiency (recovery evitabile).

### P-F — curl-alias trap → UNKNOWN  ⟵ minore in questa run
**Behavior:** `curl -s -o NUL "http://…"` fallisce (`Invoke-WebRequest: missing Uri`), classificato
UNKNOWN. **Frequenza: 1** (il modello ha evitato curl quasi ovunque questa volta).
**Codice:** [error_classifier.py](../../../src/error_classifier.py) (nessuna firma per la trap) +
`knowledge/` (nessun rewrite `curl`→`curl.exe`, il binario reale su Win10+).

### P-A — DISCOVERY achieved=True con run_ok=False  ⟵ semantico, basso costo diretto
**Behavior:** un cmdlet che stampa il proprio errore su stdout conta come DISCOVERY riuscita (nodo
CONFIRMED su comando fallito). **Codice:** [observer.py:180,185](../../../src/tools/observer.py#L180)
(DISCOVERY = stdout non vuoto, ignora exit code).

## 4. Il collo di bottiglia dominante (per il prossimo mirino)

Ordine per leva:
1. **error_classifier UNKNOWN = 73% delle divergenze.** Recovery cieca su 3 fallimenti su 4. Il più
   grande, ma diffuso: richiede molte firme nuove o un approccio diverso alla classificazione.
2. **P-C false refutation** — 9 empty-discovery + 4 provabilmente-falsi + 5 block a valle. Alta
   confidenza, fix pulito, colpisce FTFR direttamente. **Il target laser più netto.**
3. **P-E template leak** — 6 occorrenze, fix deterministico (3 pattern mancanti nel guard).
