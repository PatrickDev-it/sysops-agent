# Baseline v1 — Report quantitativo (M0/F0)

> ⚠️ **Documento storico — congelato.** Scritto prima della riorganizzazione del 2026-07-10;
> numeri, prosa e conclusioni sono lasciati esattamente com'erano. I path che cita si leggono così:
> `.workspace/` → `workspace/` · `validation/telemetry/` → `var/telemetry/` ·
> `validation/benchmark/` → `var/benchmark/` · `src/tests/` → `tests/` · `_test_workspaces/` → `_sandbox/`.
> I comandi di riproduzione al suo interno non sono più eseguibili alla lettera.

> Scopo: **validare empiricamente la tesi architetturale v2 *prima* di formalizzarla** (RFC-0004).
> Metodo: OBSERVE prima di CHANGE. Numeri reali, con confine esplicito tra *misurato ora* e *richiede run live 4B*.
> Generato: 2026-07-03 · Tooling: `benchmarks/` · Fonti: `validation/telemetry/` (68 run), suite 50-task.

---

## 0. PATCH-008 — cleanup dead-code (fatto)

Rimossi 4 moduli morti (importati ma mai invocati) + sfilato `executor` da firme/call-site dell'orchestrator:

| File rimosso | LOC | Stato |
|---|---|---|
| `src/screen_parser.py` | 521 | dead (superato da pyte) |
| `src/state_machine.py` | 280 | dead |
| `src/executor.py` | 58 | path esecuzione morto |
| `src/parser.py` | 43 | serviva solo executor |
| **Totale** | **902** | rimosse |

Verifica: `compileall src` OK · `import src.orchestrator` OK · nessun riferimento residuo ai moduli.
Riallinea codice e doc (chiude il drift vs RFC-0001). Comportamento invariato.

**Regression check:** `pytest tests/test_rebuild_units.py tests/test_ocke.py src/tests/test_reasoning.py`
→ **83 passed, 5 failed**. I 5 fallimenti sono **pre-esistenti e NON causati dal cleanup**: sono isolati a
`BeliefSystem.is_refuted/is_proven` (`src/reasoning.py`, mai toccato; non importa i moduli rimossi).
Reperto rilevante: l'invariante *"solo PROVEN guida l'esecuzione, REFUTED blocca i retry"* (moat #1) è
**parzialmente rotto in v1** → è precisamente ciò che il v2 `state-engine.md` centralizza e testa al 100%.

---

## 1. Baseline metriche (dai 68 telemetry reali)

`python -m benchmarks.arr_aggregator`

| Metrica | Valore | Note |
|---|---|---|
| Run analizzati | 68 | COMPLETE=21 · INCOMPLETE=46 · REFUSED=1 |
| **ARR (tutti i run)** | **31.3%** | COMPLETE/(COMPLETE+INCOMPLETE) |
| **ARR (per goal distinto)** | **56.5%** | 24 goal distinti, ultimo verdetto |
| Steps/task (media / mediana) | 7.94 / 6.0 | azioni per run |
| **Latency/task (media / mediana)** | **43.07s / 24.86s** | somma durate azioni |
| Action error rate | 30.9% | azioni con exit≠0 o success=False |
| Tokens/task | **N/A** | non catturato dallo schema v1 |
| Parse-error rate (vero) | **N/A** | non catturato dallo schema v1 |

> ⚠️ **Caveat sul corpus.** Questi 68 run sono in larga parte goal di *scaffold dev* (Next.js), non task
> sysops puliti. Sono un riferimento utile ma **non** il denominatore autoritativo per la tesi. Il baseline
> valido per il confronto è la **suite 50-task sysops** (§3), da eseguire con lo schema strumentato (§2).
> Inoltre v1 **non registra token né parse-error** → i due target chiave non sono misurabili sui dati storici:
> è precisamente il buco che lo schema unificato colma.

---

## 2. Telemetry schema unificato v2 (fatto)

`benchmarks/telemetry_schema.py` — record `RunRecord` con `decisions[]` tipizzate che catturano ciò che
mancava: `prompt_tokens`, `completion_tokens`, `latency_ms`, `parse_ok`, `context_mode` (per l'A/B).
Metriche derivate: `tokens_total`, `model_call_ratio`, `parse_error_rate`, `model_latency_ms`.
Include `normalize_legacy()` (upgrade dei record v1) e il **punto d'integrazione** documentato in `model_router`
(non ancora cablato, per non destabilizzare il sistema vivo prima dell'A/B). Self-test OK.

---

## 3. Baseline benchmark suite — 50 task sysops (fatto: definizione + harness)

`benchmarks/suite_50.py` (50 task, 20 categorie) · `benchmarks/run_suite.py` (harness).

- 47 **safe** (read-only/diagnostici) · 2 **RECOVERABLE** (in workspace isolato) · 1 **DESTRUCTIVE** (T50, test di rifiuto).
- Categorie: os, path, deps/packages, services, processes, ports, network, docker/k8s, ssh, cron, logs,
  permissions, monitoring, troubleshooting, incident, automation, filesystem, safety.
- Verifica **deterministica** (artifact/file_contains/refused), nessun LLM nel giudizio.

Stato: definizioni e harness validati (`--dry-run` OK, 48 task applicabili su Windows). **L'esecuzione live
richiede i modelli GGUF + GPU** → runbook in §6.

---

## 4. A/B contesto: current vs compiled (misurato ora)

`benchmarks/context_compiler.py` (prototype) + `benchmarks/ab_context.py`, eseguito sui **68 belief state reali**.

| Metrica | Valore |
|---|---|
| Contesto CURRENT (media / mediana) | 1193.9 / 826.0 token |
| Contesto COMPILED (media / mediana) | 342.9 / 245.5 token |
| **Riduzione aggregata (token totali)** | **71.3%** |
| Riduzione media per-run | 70.9% |
| Target -40% token | ✅ superato (indicatore anticipatore) |

> ⚠️ **Caveat.** (1) Misura la *dimensione del contesto assemblato* (termine dominante di tokens/task, ma non
> l'intero prompt: system/output sono condivisi tra i due arm). (2) Tokenizer **euristico (chars/4)**; il conteggio
> esatto col tokenizer del 4B si ottiene con `--model-tokenizer` (carica il modello). (3) Misura la *size*, **non**
> ARR/parse-error/latency — quelli richiedono la generazione live del 4B (§6).
> Nota: il contesto v1 **cresce con la history** (i run lunghi hanno media più alta) — su incident sysops reali il
> divario sarebbe maggiore, quindi il 71% è semmai conservativo per il dominio target.

---

## 5. Scorecard condizione di avanzamento

Target per formalizzare RFC-0004 e avviare la migrazione:

| Target | Soglia | Stato | Evidenza |
|---|---|---|---|
| Token/task | **-40%** | ✅ **superato** (indicatore anticipatore: -71% sul contesto) | §4, dati reali |
| ARR | **+20%** | ⏳ **da misurare** (serve run live 4B su suite, 2 arm) | §6 |
| Parse-error rate | **-60%** | ⏳ **da misurare** (serve schema strumentato + generazione) | §6 |
| Latency/task | **-25%** | ⏳ **da misurare** (baseline 43s noto; delta serve run live) | §6 |

**Verdetto interim:** la *gamba token* della tesi è **empiricamente supportata** su dati reali (–71% contesto).
Le altre tre metriche dipendono dalla **generazione live del 4B**, non eseguibile in questo ambiente (GPU +
mutazione di sistema). **Non formalizzare RFC-0004** finché tutte e quattro le soglie non sono verificate.

---

## 6. Runbook per completare la validazione (sulla macchina target)

```powershell
cd .workspace ; . .\.venv\Scripts\Activate.ps1

# (a) Token exact col tokenizer del 4B
python -m benchmarks.ab_context --model-tokenizer --json validation/ab_context_exact.json

# (b) Baseline ARR della suite, arm CURRENT (safe-only prima; poi --allow-mutating)
python -m benchmarks.run_suite --label baseline_current
#   → prima di questo va cablato il punto d'integrazione telemetry (token/parse) in model_router
#     (vedi INTEGRATION in telemetry_schema.py). ~1 giornata di lavoro, non rischioso.

# (c) Arm COMPILED: instradare compile_context() dove supervisor.plan() assembla il ctx,
#     rilanciare la suite con label baseline_compiled.

# (d) A/B parse-error + latency
python -m benchmarks.ab_context --generate

# (e) Aggregare e confrontare i due suite_report.json → verificare le 4 soglie.
```

Solo se **ARR +20% ∧ token -40% ∧ parse-error -60% ∧ latency -25%** → si formalizza RFC-0004 e parte la migrazione
(fasi F1→F8 in [../../brain/architecture-next/migration-plan.md](../../brain/architecture-next/migration-plan.md)).
Altrimenti: la tesi va rivista *prima* di scrivere altro codice — che è esattamente lo scopo di questo M0.
