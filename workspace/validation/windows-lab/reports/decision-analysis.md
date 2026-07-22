# Decision Analysis — perché il supervisor sbaglia strategia al primo colpo

> ⚠️ **Documento storico — congelato.** Scritto prima della riorganizzazione del 2026-07-10;
> numeri, prosa e conclusioni sono lasciati esattamente com'erano. I path che cita si leggono così:
> `.workspace/` → `workspace/` · `validation/telemetry/` → `var/telemetry/` ·
> `validation/benchmark/` → `var/benchmark/` · `src/tests/` → `tests/` · `_test_workspaces/` → `_sandbox/`.
> I comandi di riproduzione al suo interno non sono più eseguibili alla lettera.

> Documento principale della prossima iterazione. Analizza la **decisione**, non il comando.
> Fonte: run `full-safe30` (30 casi Windows live su GPU, agente mai aiutato). Corpus:
> `validation/windows-lab/failure-db/`. **Nessun codice modificato per produrre questo documento.**

---

## 0. Reperto meta (blocca tutto il resto)

**La telemetria NON registra le decisioni.** Il record per-run ha `history` (azioni: comando,
stdout/stderr, exit) e `facts`, ma il campo **`decisions` è sempre `[]`**. Non esiste traccia
persistita di: il *plan object* del supervisor, la rationale di scelta, lo stato dei belief, il
context inviato al modello. `telemetry_schema.py` v2 definisce un tipo `Decision{kind, tokens,
parse_ok, retries}` **ma non è cablato** nel writer runtime (`telemetry.record_run`).

Conseguenza: *non si può analizzare una decisione da una telemetria di sole azioni.* Il plan è stato
**parzialmente ricostruito** dai `facts` (`discovery::<titolo step>` = i passi che il supervisor ha
prodotto) + il log del run. Tutto ciò che segue su "confidence" riflette questa ricostruzione parziale.

> **Prerequisito iterazione #1:** cablare `Decision` in `record_run` (plan + rationale + belief-delta
> per step). Senza, ogni analisi decisionale resta inferenza. È il primo intervento, prima di ogni fix.

---

## 1. L'Expected Decision Tree è quasi sempre lo stesso

19 dei 22 casi sono task **pure-OBSERVE**. Il loro `expected_reasoning` è identico nella forma:

```
GOAL: "metti X in file.txt"
 └─ [D-a] Classifica: è OBSERVE → nessun cambiamento di sistema
     └─ [D-b] DISCOVER: esegui il comando diagnostico che produce X
         └─ [D-c] Il valore X diventa un FATTO NOTO (provato)
             └─ [D-d] WRITE: scrivi X **verbatim** nel file
                 └─ [D-e] VERIFY: il file contiene X reale (non un placeholder)
```

Il testo del caso lo dice letteralmente: *"Write the collected facts **verbatim** to `X.txt`."*
Non serve nessuna capability nuova. Il nodo critico è **l'ordine dataflow `D-b → D-c → D-d`**: il
valore deve *esistere come fatto* prima di essere scritto.

---

## 2. Le 5 classi di divergenza (dove l'Actual Tree rompe l'Expected)

| ID | Divergence Point | Layer colpevole | La decisione era sbagliata? |
|----|------------------|-----------------|------------------------------|
| **D1** | `D-d` eseguito prima di `D-c` — WRITE-before-KNOW | **Planner + Context** | Sì |
| **D2** | `D-d` **assente** dal plan — NEVER-WRITE | **Planner** | Sì |
| **D3** | `D-b` ripetuto all'infinito — REDISCOVERY LOOP | **Belief** | Sì |
| **D4** | `D-a` sbagliato — FABRICATE invece di DIAGNOSE | **Supervisor/Planner** | Sì |
| **D5** | `D-b/D-d` corretti ma output perso in esecuzione | **Executor/tool** | **No** — decisione sana |

### D1 — WRITE-BEFORE-KNOW *(dataflow invertito)*
Il supervisor decide di **scrivere il file per primo**, incapsulando la discovery come espressione
shell inline nel contenuto, prima che il valore esista.
- **Expected:** `Get-Service` → (output noto) → `write_file(services.txt, <output>)`.
- **Actual (WIN-ENV_PATH):** azione #1 = `write_file|path.txt|$(Get-Command | Where-Object …)` — tratta
  `write_file` come se **valutasse** il contenuto. Il file riceve il testo letterale → placeholder.
- **Casi:** WIN-ENV_PATH-00001, WIN-USERS-00001, WIN-SERVICES-00003 (`write_file|time.txt|Get-Date…`),
  WIN-PROCESSES-00001 ("script code instead of data"), + primo-tentativo di DNS/STORAGE/PERFORMANCE-002
  (poi recuperati). **Confidence: ALTA.**
- **Perché la decisione nasce così:** il planner non ha un nodo "il valore è NOTO" tra discover e write;
  il context non contiene la regola *"il contenuto di write_file è letterale, mai una espressione"*.
  Non è mancanza di capability — è **assenza del vincolo di dataflow**.

### D2 — NEVER-WRITE *(step terminale mancante)*
Il plan è una sequenza di soli "Discover X"; **manca del tutto il nodo "scrivi i fatti nel file"**.
- **Actual (WIN-GROUPS/SCHEDULER/SERVICES-001/002, NETWORKING-001):** discovery ripetute → `NOTE:
  "workspace is empty — nothing was created"`. Il supervisor non ha mai rappresentato lo *stato finale
  desiderato* (file su disco) come uno step.
- **Confidence: ALTA.** **Layer: Planner** — decomposizione del goal incompleta: il target-state non
  entra nel plan.

### D3 — REDISCOVERY LOOP *(belief non sticky)*
Il plan contiene lo stesso "Discover if X available" ripetuto 2–3 volte.
- **Actual:** WIN-NETWORKING-001 (3× "Discover if Get-NetTCPConnection is available"), WIN-FIREWALL
  (3× discovery firewall), WIN-SCHEDULER (3× sintassi scheduled-task). Il supervisor **ridiscopre** la
  stessa capability perché il successo della prima discovery non è ritenuto come belief **PROVEN**.
- **Confidence: ALTA.** **Layer: Belief** — è la manifestazione diretta dell'**invariante #10 rotto**
  (`BeliefSystem.refute()`/`is_proven` — 5 test falliti, vedi changelog PATCH-011 §Found). Brucia il
  budget in discovery e non arriva mai a `D-d`. **Spiega il RAF 2.11 a livello decisionale.**

### D4 — FABRICATE invece di DIAGNOSE *(strategia sbagliata su task di riparazione)*
Sui task CI/CD (non-OBSERVE) l'expected è *"diagnostica QUALE fattore diverge, poi correggi quello"*.
- **Actual (WIN-CICD-001/002/004):** il supervisor **scrive file plausibili** (`.env`, `package.json`,
  `ci.yml`) invece di diagnosticare il guasto specifico indotto. Pattern-match `dominio CI/CD →
  produci artefatti CI/CD`.
- **Confidence: MEDIA** — in parte i task sono mal-posti sull'host reale (le fixture non sono
  materializzate, quindi non esiste un `ci.yml` rotto da diagnosticare). Ma la scelta `D-a` "authoring"
  invece di "investigation" è visibile. **Layer: Supervisor/Planner (classificazione del task).**

### D5 — EXECUTION LOSS *(la decisione era giusta)*
Plan e primo comando **corretti** (`Get-NetFirewallRule | Out-File`, `Get-Service | Out-File`), ma
l'output non atterra: `Out-File` in sottoprocesso, encoding, o PERMISSION_DENIED (firewall elevato).
- **Casi:** WIN-FIREWALL-001 (+permessi), parti di SERVICES-001, WIN-PROCESSES-002 (`python … > tree.txt`
  vuoto). **Confidence: ALTA.**
- **Layer: Executor/tool.** ⚠️ **Da ESCLUDERE dall'analisi "decisione sbagliata"**: qui il supervisor
  ha deciso bene. (È il territorio C1/C5 dell'analisi precedente — *non* è il problema di questa mission.)

---

## 3. Classificazione per-task (la decisione, non il comando)

Legenda colonne: Goal=goal compreso · Strat=strategia corretta · Cap=capability giusta ·
Order=ordine dataflow · Bel=belief · **Owner**=layer che ha sbagliato la *decisione*.

| Case | Goal | Strat | Cap | Order | Bel | Divergenza | **Owner** |
|------|:----:|:----:|:---:|:----:|:---:|-----------|-----------|
| WIN-ENV_PATH-00001 | ✅ | ❌ | ❌ | ❌ | — | D1 write-before-know | **Planner+Context** |
| WIN-USERS-00001 | ✅ | ❌ | ❌ | ❌ | — | D1 | **Planner+Context** |
| WIN-SERVICES-00003 | ✅ | ❌ | ❌ | ❌ | — | D1 (comando come contenuto) | **Planner+Context** |
| WIN-PROCESSES-00001 | ✅ | ❌ | ❌ | ❌ | — | D1 | **Planner+Context** |
| WIN-DNS-00001 | ✅ | ⚠️ | ❌ | ❌ | — | D1→recuperato | **Planner** |
| WIN-STORAGE-00002 | ✅ | ⚠️ | ❌ | ❌ | — | D1→recuperato | **Planner** |
| WIN-PERFORMANCE-00002 | ✅ | ⚠️ | ❌ | ❌ | — | D1→recuperato | **Planner** |
| WIN-GROUPS-00001 | ✅ | ❌ | ✅ | ❌ | ❌ | D2 never-write | **Planner** |
| WIN-SCHEDULER-00001 | ✅ | ❌ | ✅ | ❌ | ❌ | D2+D3 | **Planner+Belief** |
| WIN-SERVICES-00001 | ✅ | ❌ | ✅ | ❌ | ⚠️ | D2/D5 | **Planner+Executor** |
| WIN-SERVICES-00002 | ✅ | ❌ | ✅ | ❌ | ❌ | D2+D3 | **Planner+Belief** |
| WIN-NETWORKING-00001 | ✅ | ❌ | ✅ | ❌ | ❌ | D2+D3 | **Planner+Belief** |
| WIN-TLS-00001 | ✅ | ⚠️ | ⚠️ | ❌ | ❌ | D2+D3 | **Planner+Belief** |
| WIN-NETWORKING-00002 | ✅ | ⚠️ | ✅ | ⚠️ | ❌ | D3→recuperato | **Belief** |
| WIN-RECOVERY-00001 | ✅ | ⚠️ | ✅ | ⚠️ | ❌ | D3 + write parziale | **Belief+Planner** |
| WIN-KERNEL-00001 | ✅ | ⚠️ | ✅ | ⚠️ | ❌ | D3 + write parziale | **Belief+Planner** |
| WIN-PERFORMANCE-00003 | ✅ | ❌ | ✅ | — | ❌ | goal-decomp parziale (manca CPU/mem) | **Planner** |
| WIN-PROCESSES-00002 | ✅ | ❌ | ⚠️ | ❌ | — | D4b over-engineering (python) + D5 | **Supervisor+Executor** |
| WIN-FIREWALL-00001 | ✅ | ✅ | ✅ | ✅ | — | D5 execution/permission | **Executor** |
| WIN-CICD-00001 | ✅ | ❌ | — | — | — | D4 fabricate | **Supervisor** |
| WIN-CICD-00002 | ✅ | ❌ | — | — | — | D4 fabricate | **Supervisor** |
| WIN-CICD-00004 | ✅ | ❌ | — | — | — | D4 fabricate | **Supervisor** |

**Osservazione chiave:** in **21/22 casi il Goal è compreso.** Non è un problema di comprensione né di
model-capacity: è un problema di **struttura del piano** e di **belief**. Solo 1 caso (FIREWALL) è
puramente executor con decisione corretta.

### Conteggio owner della *decisione* sbagliata
- **Planner** (order/decomp/write-back): **16 casi** — dominante.
- **Belief** (rediscovery / non-sticky): **8 casi** (spesso co-occorrenti col planner).
- **Supervisor** (classificazione task D4): **4 casi**.
- **Context** (regola write_file letterale assente): concausa in tutti i D1 (**7**).
- **Executor** (decisione giusta, esecuzione persa): **3 casi** → *fuori scope di questa mission*.
- **Model**: **0 casi attribuibili al modello** in sé — il goal è sempre capito.

---

## 4. La causa profonda (una sola frase)

> **Il supervisor non rappresenta il task come un dataflow con stato.** Non produce il piano
> `X := discover(); assert X PROVEN; write(X); verify(X)`. Emette una lista piatta di "Discover X"
> **senza nodo terminale di WRITE (D2)**, **oppure con un WRITE che incapsula la discovery (D1)**, e
> **ridiscopre perché nulla è marcato PROVEN (D3)**.

D1, D2, D3 non sono tre bug: sono tre sintomi dello stesso vuoto architetturale — **manca un world-model
del task** (quali valori servono, quali sono noti, qual è lo stato finale) e **il belief-state è rotto**
(invariante #10). Il RAF 2.11 è la firma di questo: il primo piano è strutturalmente incompleto, quindi
il successo *deve* passare dal recovery, che per tentativi finisce per aggiungere il WRITE mancante.

---

## 5. Divergence points & alternative migliori (per classe)

| Classe | Divergence node | Alternativa migliore (a livello di decisione) |
|--------|-----------------|-----------------------------------------------|
| D1 | tra `D-c` e `D-d` | Il planner deve **vietare** una `WRITE` il cui contenuto non sia un fatto già in `facts`. Belief-gate: *no write of an unknown*. |
| D2 | `D-d` mancante | Il planner deve **derivare il target-state dal goal** ("in X.txt" ⇒ esiste sempre uno step WRITE finale) e non chiudere il plan senza di esso. |
| D3 | `D-b` ricorrente | Una discovery riuscita deve diventare belief **PROVEN sticky** (fix invariante #10) così il planner non la ripropone. |
| D4 | `D-a` | Su goal di riparazione, gate esplicito *DIAGNOSE-before-CHANGE*: prima isolare il fattore divergente, poi correggere solo quello. |
| D5 | — | *Non è una decisione errata.* Territorio executor (capture/redirect) — **escluso** da questa mission. |

---

## 6. Cosa deve targettizzare la prossima iterazione (a livello di decisione)

In ordine, e **prima di qualsiasi capability nuova**:

1. **Rendere visibili le decisioni** — cablare `Decision` in `record_run` (plan + rationale + belief-delta).
   Senza questo si continua a inferire. *(Prerequisito.)*
2. **Riparare il belief-state (invariante #10)** — `is_proven`/`refute` sticky. Elimina D3 e riduce il RAF.
3. **Planner dataflow-aware** — il piano di un goal "metti X in file" DEVE contenere, in quest'ordine,
   `DISCOVER(X) → X∈facts → WRITE(X) → VERIFY`. Elimina D2 e D1 alla radice (D1 = WRITE senza X∈facts).
4. **Gate DIAGNOSE-before-CHANGE** per i task di riparazione. Riduce D4.

D5 (execution loss / capture) resta **fuori** da questa iterazione: là la decisione era corretta.

> Nota di metodo: le 3 divergenze dominanti (D1/D2/D3) sono **decisioni**, non comandi. Correggere
> PowerShell, i redirect o aggiungere `capture` NON le risolve — un `capture` perfetto scritto
> *prima* che il valore sia noto (D1) o *mai pianificato* (D2) fallisce comunque. Per questo la mission
> era corretta: il problema è a monte, nel piano e nei belief.
