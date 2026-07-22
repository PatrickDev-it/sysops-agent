# Session log

Operational changelog, append-only, chronological order — never delete previous entries.

Every entry must include: timestamp, patch goal, changes made + files touched, breaking changes, regressions introduced/removed, validation performed, final status.

---

## 2026-07-10 — Riorganizzazione del layout: source/state split

**Goal.** Portare il codice sotto `src/`, la venv in root, e separare ciò che è sorgente da ciò che è
stato scritto a runtime.

**Invariante introdotto.** Una directory è *sorgente* (versionata, sola lettura a runtime) **oppure**
*stato* (scritta a runtime, buttabile). Mai entrambe. Nulla sotto `src/` viene mai scritto.

**Cambiamenti.**
- `( workspace )/` → `workspace/` — il nome conteneva parentesi e spazi, che rompono ogni shell non quotata.
- `.venv/` → root del repo, accanto a `pyproject.toml` / `requirements.txt` (anch'essi spostati in root).
- Sorgente in `src/`: `prompts/` → `src/prompts/`, `knowledge/{commands,tools,shells}` → `src/knowledge/kb/`.
- Stato in `var/`: `src/runtime/`, `memory/`, `knowledge/memory/`, `validation/{telemetry,benchmark}`.
- `_test_workspaces/` → `_sandbox/`.
- `src/tests/` (28 file) accorpata in `tests/`; nuovo `tests/conftest.py`.
- `src/config.py` è ora l'owner unico del layout: nessun altro modulo ricalcola i path da `__file__`.

**Semplificazione.**
- Rimossi 8 bootstrap `sys.path.insert` duplicati (uno per file di test) → 1 `conftest.py`.
- Rimossi 10 anchor `parents[N]` contati a mano → import da `src.config`.
- Rimossi 6 `ROOT = Path(__file__)...` nei benchmark → import da `src.config`.
- Rimosso `session.WORKSPACE_ROOT` (definito, mai letto) e il `ROOT` di `session.py`, che significava
  `src/` mentre in ogni altro file significava la repo root.
- Owner duplicati rimossi: 3 (layout, sys.path dei test, dir di telemetria). Invarianti: +2 (#15, #16).

**Breaking.** `python -m src.main` va lanciato da `workspace/`; la venv si attiva dalla root.

**Difetti trovati e corretti** (nessuno introdotto da questa patch):
- `orchestrator._has_fabricated_workspace_path` cercava il segmento letterale `.workspace`: il rename
  l'avrebbe disattivato in silenzio. Ora è ancorato a `config.ROOT`. Riscrivendolo è emerso che
  confrontava prefissi di stringa grezzi, quindi un path inventato `.../_try_old/src` passava come
  legittimo perché `.../_try` ne è prefisso. Ora il confronto è per componenti. Non aveva test: +5.
- `benchmarks/run_suite.py` aveva `\r\r\n` su tutte e 189 le righe (conversione doppia). Normalizzato.
- La KB faceva `rglob("*.yaml")` su un albero che conteneva la propria directory di scrittura.
- Gli shim `.exe` della venv erano rotti; tornando in root si sono riparati (`pip.exe` funziona).

**Validazione.** Baseline preso *prima* della riorganizzazione: 361 passed, 1 skipped.
Dopo: **366 passed, 1 skipped** (361 + 5 nuovi test sul guard), suite eseguita anche a freddo dopo aver
cancellato i `__pycache__`. CLI (`python -m src.main --help`) viva; i 7 moduli `benchmarks.*` importano;
`tests/certification` colleziona 33 test. Verificato via grafo Sinapsi (`COVERAGE: complete`) che
`PROMPTS_DIR`/`MEMORY_DIR`/`RUNTIME_DIR`/`TELEMETRY_DIR` sono definiti solo in `src/config.py`.

**Status.** ✅ completo.

---

## 2026-07-10 — Riallineamento della documentazione

**Goal.** Far sì che i `.md` descrivano il progetto che esiste.

**Causa radice.** La reading order di `AGENTS.md` ordinava di leggere nove file in `docs/` e una `RFCs/`.
Non esistono, e non esistono in archivio: il sistema di documentazione era stato sostituito da
`.sinapsi/` + `brain/` senza aggiornare il contratto. `brain/` era costruito su "nodi pointer" che
puntavano tutti nel vuoto.

**Cambiamenti.**
- Reading order e documentation contract di `AGENTS.md` riscritti sugli owner reali.
- **Struttura e comportamento non hanno più un doc owner**: l'owner è il codice, interrogato dal grafo.
  Un `.md` che descrive il runtime diverge dal runtime, e questo è precisamente ciò che era successo.
  I `.md` possiedono solo ciò che il codice non sa dire di sé: invarianti, glossario, perché, strategia.
- `AGENTS.md` è ora l'owner canonico di invarianti e glossario (prima delegava a file inesistenti).
- 23 file: path `.workspace/` → `workspace/`, `validation/telemetry` → `var/telemetry`, ecc.
- 11 file `brain/`: link ripuntati; prosa dei nodi pointer riscritta.
- I report di misurazione storici (`validation/*.md`, `windows-lab/reports/*.md`) sono **congelati**:
  numeri e conclusioni intatti, con una nota d'intestazione che mappa i vecchi path sui nuovi. Riscriverli
  avrebbe falsificato il record. Riparati 7 link relativi la cui profondità era sbagliata già da prima.
- Grafo Sinapsi ricostruito sul nuovo layout (3114 nodi); `project-map.md` rigenerato.

**Validazione.** Link checker su tutti i `.md` autoriali: **da 61 link rotti a 0** (499/499 risolvono).

**Debito residuo.** `pyproject.toml` dichiara `build-backend = "setuptools.backends.legacy:build"`, che non
è un backend valido, e `setuptools` non è installato nella venv: il packaging non è mai stato esercitato.
`sinapsi index` non è mai stato eseguito → il grafo riporta `STRUCTURE: absent` (solo relazioni `defines`).

**Status.** ✅ completo.

---

## 2026-07-10 — Verifica dello stato di Sinapsi

**Goal.** Controllare se il debito su Sinapsi è chiuso, interrogando il grafo invece di ispezionare i file.

**Osservato.** Binario 0.2.3 → 0.2.4. `sinapsi index` è stato eseguito: `index.scip` (4 MB) esiste.
Edges 3805 → **5286**; nodi 3114 → 2973. Le query sul codice ora rispondono `STRUCTURE: resolved` invece di
`STRUCTURE: absent` — le relazioni `calls` sono risolte dal front-end del compilatore, non indovinate.

**Verificato via grafo** (non via grep), a conferma della patch precedente:
- `_has_fabricated_workspace_path` → `calls _is_within` (`orchestrator.py:L652`), `COVERAGE: complete`.
- `MEMORY_DIR`/`KB_MEMORY_DIR`/`BENCHMARK_DIR` derivano tutti da `VAR`, definiti solo in `config.py`.
- `WORKSPACE_ROOT` → **`No matching nodes`**: il codice morto non esiste più nemmeno per il grafo.
- `conftest.WORKSPACE` è l'unico owner del `sys.path` di test.

**Cambiamenti.** `.gitignore`: aggiunti `index.scip` e lo shim `scip-python-windows-shim.cjs` (generati).

**Non risolto.**
- I tool MCP non sono esposti in *questa* sessione: la lista si carica all'avvio. Compariranno alla prossima.
- Nessun watcher attivo → `FRESHNESS` resta `current` solo finché nessuno tocca il codice.
- `validation/stress/` porta 86 nodi di fixture scaffoldate nel grafo, che competono nel ranking.
  `_sandbox/` invece è uscito: Sinapsi legge il `.gitignore`, dove l'avevamo elencato.

**Status.** ✅ verificato.

---

## 2026-07-10 — Check complessivo + Sinapsi via MCP

**Goal.** Regressione completa dopo la riorganizzazione, e valutare l'MCP ora che è esposto.

**Check.** Suite a freddo (`__pycache__` cancellati): **366 passed, 1 skipped**. `tests/certification`
colleziona 33 test. CLI viva. 7/7 moduli `benchmarks.*` importano. Invariante source/state verificato a
runtime (nessuno stato residuo sotto `src/`). Link markdown: **506/506** risolvono.

**Sinapsi.** MCP attivo; `FRESHNESS: watched` (watcher vivo, pid 23116). `STRUCTURE: resolved`.
`get_neighbors(_has_fabricated_workspace_path)` restituisce il blast radius esatto in ~90 token:
2 caller di produzione (`Orchestrator._author_command`, `._get_fix`) + i 5 test nuovi.

**Misurato** con `sinapsi verify` (tiktoken, `--expect` come ground truth), non stimato:

| Domanda | Riduzione | Seed rank |
|---|---|---|
| comportamento: "blocca un path assoluto inventato" | 17.1× (94.2%) | **MISSED** |
| comportamento: "guard rifiuta directory sorella inventata" | 4.4× (77%) | **MISSED** |
| nome: "which module owns the directory layout constants" | 5.5× (81.9%) | MISSED |
| nome + simboli: "PROMPTS_DIR MEMORY_DIR layout constants owner" | 7.0× (85.7%) | **#1**, read-avoid ✅ |

Il risparmio di token è reale e grande. La *precisione* dipende dal fatto che il nome del simbolo compaia
nella domanda: `COVERAGE: complete` garantisce che il budget non abbia tagliato, **non** che il ranker abbia
nominato la risposta. Registrato in `known-issues.md`.

**Cambiamenti.** Nessuno al codice. `.gitignore`: `index.scip` + shim. `known-issues.md`: nuova voce.

**Status.** ✅ verificato.

---

## 2026-07-10 — Sinapsi 0.2.5: rename `.sinapsi-out/` → `.sinapsi/` e ri-misura

**Goal.** Regressione completa dopo l'aggiornamento, e verificare se il limite di retrieval documentato il
turno scorso è cambiato.

**Check.** Suite a freddo: **366 passed, 1 skipped**. Certification: 33 test. CLI viva. 7/7 benchmark
importano. Invariante source/state verificato a runtime. Link markdown: **506/506**.

**Rename.** 0.2.5 sposta la memoria operativa in `.sinapsi/`. Il tool migra **la propria** configurazione
(`.mcp.json`, `.gitignore`, `.claude/settings.json`, i blocchi marcati in `AGENTS.md`) ma non i doc del
developer, come dichiara §4. Erano rimasti **70 riferimenti** a `.sinapsi-out/` in `AGENTS.md` e in 11 file
di `brain/`. Riscritti; link di nuovo 506/506, zero riferimenti residui.

**Cosa migliora in 0.2.5.** Una quarta riga di header, `RELEVANCE`, che dichiara se il retriever si è
ancorato su una parola davvero presente nella domanda o sta tirando a indovinare — esattamente il buco che
avevo misurato e registrato in `known-issues.md`. E una tabella che impone di scegliere il tool in base a
*cosa sai già*: nome → `get_neighbors`/`get_node`; solo comportamento → `query_graph`.

**Ri-misurato** con `sinapsi verify --expect` (tiktoken), stesse quattro domande del turno scorso:

| Domanda | 0.2.4 | 0.2.5 |
|---|---|---|
| comportamento: "blocca un path assoluto inventato" | MISSED · 17.1× | **#1** · 17.9× |
| comportamento: "guard rifiuta sorella inventata" | MISSED · 4.4× | **#1** · 2.7× |
| comportamento: "owns the directory layout constants" | MISSED · 5.5× | MISSED · 5.4× |
| nome + simboli: "PROMPTS_DIR MEMORY_DIR layout owner" | #1 · 7.0× | **#1** · 4.9× |

Da 1/4 a 3/4 di risposte trovate. Il ranker è migliorato; il limite **lessicale** no — la domanda che manca
ancora non contiene nessuna parola che il codice usi, e `RELEVANCE: weak` lo dichiara correttamente. Il
fattore di riduzione cala dove il pack si allarga: trovare la risposta costa qualche token in più, e conviene.

**Trovato.** Il rumore di `validation/stress/` non è cosmetico: **dirotta il ranker**. Sulla query "directory
layout constants", 5 delle 12 card sono `layout.tsx`/`root.tsx` di Next e Remix, e `PROMPTS_DIR` non compare.
Aggiornato il debito #6 in `handoff.md`.

**Cambiamenti.** Nessuno al codice. 70 riferimenti `.sinapsi-out` → `.sinapsi`. `known-issues.md`: la voce
sul retrieval riscritta (causa reale = lessicale, non "seed per nome"), più una voce sulla scelta del tool.

**Status.** ✅ verificato.

---

## 2026-07-14 — Riassestamenti minori + primo commit git

**Goal.** Chiudere una serie di piccoli debiti a basso rischio emersi da un check di stato, e dare al repo
il version control che non aveva mai avuto.

**Cambiamenti (nessuno al codice runtime).**
- `pyproject.toml`: `build-backend` da `setuptools.backends.legacy:build` (**non è un backend valido**) a
  `setuptools.build_meta`. Sincronizzate le dipendenze con `requirements.txt`: aggiunte `ddgs>=9.0.0` e
  `pyyaml>=6.0` (mancavano → un install da wheel avrebbe fatto ImportError a runtime) e reso `pywinpty`
  condizionato `; sys_platform == "win32"` (senza marker `pip install` **falliva su Linux/macOS**, contro
  la tesi "any OS").
- `.gitignore`: escluso `workspace/validation/stress/` — **75.141 file** di scaffold rigenerabili
  (node_modules di remix/angular/nextjs). Fuori dal primo commit, e poiché Sinapsi legge il `.gitignore`,
  fuori dal grafo: le card `layout.tsx`/`root.tsx` non dirottano più il ranker (debito #6, chiuso).
- `AGENTS.md`: glossario + intro riallineati alla topologia reale dei modelli. Il glossario diceva
  «Supervisor = Modello **4B** owned»: falso. Il 4B (`Qwen3.5-4B`) era stato rimosso perché la sua arch SSM
  rompeva il prefix cache. Realtà (da `config.py` + `model_router.py`): due modelli owned di esecuzione —
  `Qwen3-0.6B` (NAV, ragionamento d'azione, non scrive codice) e `Qwen2.5-Coder-3B` (CODER, autore/riparatore
  comandi) — più un oracolo **preso in prestito** dal parent via HTTP che esegue plan/verify/reflection
  (`supervisor_call`/`verify_call`/`reflection_call` → `_oracle`), degradando a NAV se irraggiungibile.
  Aggiunte righe *Navigator* e *Oracle*; "Supervisor" ora è descritto come ruolo, non come modello.
- `.sinapsi/verification.md`: riempiti i comandi reali del repo (il placeholder «auto-filled by sinapsi init»
  non era mai stato riempito) e resa onesta la riga lint/typecheck — **nessun linter è configurato**, quindi
  la casella è stata rimossa invece di restare non spuntabile.

**Version control.** `git init` + primo commit. Era la priorità #1 dell'handoff da 4 giorni. Il `.gitignore`
tiene fuori `var/`, `models/` (3.1 GB), `_sandbox/`, `_attic/`, `.venv/`, `validation/stress/`.

**Validazione.**
- Regressione: **366 passed, 1 skipped** — identica alla baseline (le modifiche non toccano codice runtime).
- **Packaging esercitato per la prima volta**: `pip wheel . --no-deps` costruisce (232 KB; la build isolation
  fetcha `setuptools`, che non è nella venv). Wheel ispezionato: contiene **8 `.jinja` + 8 `.yaml`** (il
  `package-data` di prompts e KB funziona) e registra `sistemista = src.main:cli_entry`. Debito #1 chiuso.

**Difetti trovati oltre a quelli previsti.**
- `requirements.txt` e `pyproject.toml` erano **due owner di dipendenze divergenti**. Sincronizzati a mano;
  l'unificazione a un solo owner è rimandata (vedi `decisions.md`): `requirements.txt` codifica anche la
  ricetta del wheel CUDA di `llama-cpp-python` su cui si appoggia il README.
- `Orchestrator._author_command` ha un commento stale «via executor (fast **1.7B**)»: il coder è **3B**.
  Non toccato (è un commento di codice, fuori dallo scope doc) — registrato in `handoff.md` come debito.

**Status.** ✅ completo.

---

## 2026-07-14 — Run init-framework con oracolo 8B + fissazione del nuovo target (RFC-001)

**Goal.** Rieseguire `benchmarks/stress_frameworks.py` per vedere se gli init dei framework noti passano.

**Setup.** Nessun modello grande locale (il 4B era stato rimosso); l'oracolo si prende in prestito. Su
richiesta del developer, usato come oracolo `Qwen3-8B-Q4_K_M.gguf` dal checkout Cowork, lanciato a mano su
:8081 **su CPU** (`--gpu-layers 0`) perché su 8 GB di GPU non ci stanno 8B+3B+0.6B insieme. Velocità
oracolo misurata: **~5 tok/s** decode (CPU) → ~6 min/caso.

**Osservato (2 casi girati, oracolo attivo).**
- `react`: **FAIL** (347s, workspace vuoto, verdetto INCOMPLETE). Il piano dell'8B era coerente e conteneva
  lo scaffold, ma non ci arriva mai: **deadlock mkdir-guard ⇄ replan** — il guard `recreates_the_workspace_dir`
  rifiuta la `mkdir` nuda in testa (giusto), il rifiuto è fatale, il replan la ripropone. Non è qualità del
  modello. Registrato in `known-issues.md` + debito #7 dell'handoff.
- `node_backend`: **PASS** (package.json + server.js alla root), perché il piano non parte con una mkdir.
- Confermato che il degrado senza oracolo (prova precedente sul 0.6B) produce placeholder leak allo step 1
  → invariante #2 correttamente attivo, ma piano povero.

**Fine run.** Il developer ha fermato tutto e cambiato piano. Oracolo + ogni `llama-server` terminati, GPU
a baseline, working tree pulito (i run scrivono solo in `validation/stress/`, gitignored).

**Cambiamento (solo documentazione).** Registrato il **nuovo target architetturale** in **RFC-001**:
orchestratore **4B owned** (`Qwen3-4B-Q5_K_M`) + coder `Qwen2.5-Coder-3B-Q6_K`, self-contained,
alleggerito per **8 GB di RAM** via QLora + diskcache + offload. Puntatori in `decisions.md`, priorità #0 in
`handoff.md`. Scelto un 4B **denso** (non l'SSM `Qwen3.5-4B` rimosso): il difetto era l'arch, non la taglia.
Il glossario di `AGENTS.md`/`config.py` **non** toccati — restano owner dello stato attuale finché il target
non è implementato.

**Nessuna modifica al codice.** Nessun fix del deadlock applicato (piano cambiato prima).

**Status.** ✅ documentazione aggiornata; target registrato, non implementato.

---

## 2026-07-14 — Implementazione del target: NAV owned = Qwen3-4B (era 0.6B)

**Goal.** "Plasmare" il progetto sul target di RFC-001. Il developer aveva già messo `Qwen3-4B-Q5_K_M.gguf`
in `models/` e **rimosso** il `Qwen3-0.6B` → il runtime era rotto (`NAV_MODEL` puntava a un file assente).

**Cambiamenti al codice.**
- `config.py`: `NAV_MODEL` → `Qwen3-4B-Q5_K_M.gguf`. Ripuliti dal docstring di `nav_server_args` i numeri
  del 0.6B (466 MiB, 268 t/s) — cancellati, non sostituiti con stime. Commento del ruolo NAV riscritto:
  ora è l'**orchestratore general-purpose owned** (azione + select-options + planning/verify senza oracolo).
- `model_router.py`: `_NAV` name → `nav-4b`; docstring del modulo (NAV = 4B); `_oracle()` — il no-oracle
  non è più "degrado" ma il **default self-contained** (messaggio riscritto); docstring di `supervisor_call`.
- `main.py`: descrizione CLI stale «Supervisor (Qwen3.5-4B) + Executor (Qwen3-1.7B)» → «Qwen3-4B orchestrator
  + Qwen2.5-Coder-3B». (Era sbagliata su entrambi i modelli.)
- `AGENTS.md`: intro + glossario (righe Supervisor/Navigator) allineati al 4B owned.
- **NON toccato `_decide_select`** (driver PTY): è deterministico per design (invariante #3, principio #3).
  Le select-options gestite da un *modello* sono il ruolo NAV (`executor_pty_fallback_call`), ora il 4B —
  quindi "il 4B nelle select-options" è ottenuto ripuntando NAV, senza cablare un LLM nel driver.
- **Commenti storici del "era 0.6B" lasciati intatti** (backstop backslash in `workspace_paths.py`+test,
  note speculative decoding): sono record accurati del *perché* esistono guard/test.

**Validazione.**
- Regressione: **366 passed, 1 skipped** (nessun cambio di logica). `config.NAV_MODEL` risolve a un file
  esistente → runtime non più rotto.
- 4B lanciato con `nav_server_args`: carica, healthy. **RFC-001 test #1 (prefix cache sul 4B denso) → PASS**
  (`cache_n=387` alla 2ª call); decode ~58-89 t/s GPU.
- **Footprint (GPU pulita, baseline 991 MiB): 4B solo = 5220 MiB; 4B + coder 3B insieme, entrambi healthy,
  coder inferisce = 7756/8192 MiB → CI STANNO su 8 GB VRAM, nessun OOM.**

**Errata corrige (rilevata dal developer).** Una prima misura dava 7778 MiB "per il solo 4B" e la
conclusione errata "coder non co-fitta → OOM". Era **contaminata** da ~2.5 GB di un `llama-server` residuo.
Rimisurata su GPU pulita: vedi sopra. RFC-001 aggiornata con i numeri corretti e con la distinzione **8 GB
VRAM (già raggiunto) vs 8 GB RAM di sistema (richiede ancora QLora/offload)**.

**Run end-to-end (4B self-contained, `node_backend`).** La pipeline **gira**: safety→enhance→plan (4B)→
execute (coder)→verify (4B), **nessun oracolo**, **46.8s** (~7× più veloce dell'oracolo 8B su CPU), **no
OOM** (GPU ~5.2 GB durante). Piano del 4B corretto (5 step, incluso "create a minimal HTTP server script").
**Ma task FAIL**: al passo 4 il coder ha authored un comando malformato per `server.js` (mischiato con flag
npm → ha finito per eseguire `npm --version`), il file non è stato creato; il `_artifact_check` deterministico
l'ha **beccato** (`file_has_content(server.js) — not a file`) ma il **verify finale del 4B ha dichiarato
COMPLETE** basandosi solo su `package.json` (falso positivo). `node_backend` **passava con l'oracolo 8B** →
col 4B self-contained **fallisce**: primo dato del test #3 di RFC-001 (qualità < baseline 8B), single sample,
non conclusivo. Difetto secondario: `npm install http` (built-in di Node, non un pacchetto npm).

**Committato.** Sì — vedi la voce git in questa stessa data.

**Status.** ✅ target implementato sul lato modello, verificato su 8 GB VRAM e girato end-to-end (pipeline OK,
qualità del 4B sotto la baseline 8B su questo caso). QLora/offload per gli 8 GB di RAM di sistema resta
aperto (RFC-001), così come il rinforzo della misura per rendere conclusivo il test #3.

---

## 2026-07-14 — RFC-002: proposta di architettura V2 (solo design, nessun codice)

**Goal.** Review completa della V1 + riprogettazione V2 su richiesta ("Principal Architect", distruggi
l'architettura corrente, progetta la V2 con pattern moderni *solo se* danno beneficio misurabile).

**Evidenza raccolta (grafo).** `_run_loop` chiama 38+ funzioni (god-loop); `orchestrator` degree 90;
`_execute_step` ~480 righe. Più le misure di questa giornata (VRAM 7756/8192, verify indulgente, deadlock).

**Prodotto.** `.sinapsi/rfc/002-v2-architecture.md` — 20 sezioni: review (10 difetti V1 con evidenza), 8
principi, diagramma, componenti, flusso, FSM, pipeline, scheduler, inference layer (VRAM/KV budget),
memoria, errori, recovery, logging, telemetria, testing, benchmark, scalabilità, **verdetto pattern-per-
pattern**, roadmap strangler-fig, test di falsificazione.

**Tesi.** Sistema mono-processo/mono-utente/sequenziale, VRAM al 95%: la concorrenza reale è overlap di I/O,
non calcolo parallelo. Perciò **FSM event-sourced single-thread async** + supervisione dei processi +
budget VRAM/KV + circuit breaker/retry bounded. **Rifiutati** Actor/Message-Bus/CQRS/Plugin-framework
(problemi che questo box non ha; un pool di LLM è impossibile su ~436 MiB liberi). Roadmap incrementale,
misura (debito #3) prima di ogni claim.

**Nessun codice** (per istruzione). Prossimo passo: approvazione RFC → F0 (rinforzo misura) → F1 (event log
+ telemetria, additivo, zero rischio).

**Status.** ✅ RFC-002 proposta, in attesa di approvazione.

---

## 2026-07-14 — Ownership mode: 3 fix di affidabilità/correttezza (codice, non report)

Il developer ha imposto modalità Lead Engineer: decidere e implementare, misurare, continuare. Attaccati i
colli di bottiglia misurati oggi, in ordine di priorità (affidabilità > correttezza).

**Fix #1 — falso COMPLETE (correttezza del segnale di successo).** Il veto finale "il filesystem batte il
verifier" controllava solo `global_success` (criteri a livello-goal). `node_backend` era COMPLETE con
`server.js` mancante perché quel requisito viveva solo nel `success` di uno step. Ora il veto valuta
l'**unione** di `global_success` + i predicati filesystem di *tutti gli step eseguiti* (`_declared_success`
in `orchestrator._run_loop`). *Misurato:* node_backend passa da `FAIL (COMPLETE)` (mente) a
`FAIL (INCOMPLETE)` (onesto) → e innesca la recovery.

**Fix A — deadlock mkdir (affidabilità, debt #7 chiuso).** Il guard `recreates_the_workspace_dir` (una
`mkdir <nome-workspace>` dentro il workspace) restituiva exit **126** → prerequisite MODIFY fallito → halt
fatale → replan con la stessa mkdir → deadlock (`workspace is empty`) su tutti gli scaffold-at-root. Ora
restituisce exit **0 (no-op success)**: la project root esiste già, il piano prosegue all'initializer, e
`workspace_shape` hoista un eventuale annidamento. `session.py:417`. **+ unit test** `tests/test_workspace_dir_noop.py`
(10 test, incluso il comportamentale su `Session`: exit 0, non 126).

**Fix B — loop empty-file (segnale di recovery).** Il path attivo `_author_command` passava al coder
`stderr=run_out` (l'output del `New-Item` *riuscito*), mai il motivo `_artifact_check` "file esiste ma è
VUOTO (0B)". Il coder ripeteva lo stesso comando empty-file. Ora lo `stderr` è arricchito con `check_failures`
quando il comando esce pulito ma l'artefatto manca/è vuoto. *Misurato:* il coder **ora tenta il contenuto**
(`New-Item ... -Value "..."`) invece del file vuoto — pelando lo strato successivo (sotto).

**Strato successivo esposto (prossimo intervento).** La scrittura di un file con contenuto **multi-linea**
via comando shell (`New-Item -Value "..."` con virgolette/newline) è fragile e fallisce (server.js "not a
file"). Va instradata sul path robusto `write_file|path|content` (scrittura via Python, niente quoting-hell
della shell). In corso.

**Validazione.** Parse OK; nuovo test 10/10; **regressione 376 passed, 1 skipped** (era 366 + 10). e2e:
node_backend onesto-INCOMPLETE; react progredisce (crea tsconfig/vite.config) senza più il deadlock.

**Status.** ✅ 3 fix committati; prossimo: robustezza scrittura-file (write_file).

---

## 2026-07-14 — Fix C (write robustness) + diagnosi deterministica del muro (3B)

**Fix C — commit `0594654`.** `_intercept_content_cmd` esteso: `New-Item -ItemType File -Path X -Value
"<content>"` multi-linea → instradato a `write_file` nativo (Python), come già Set-Content/Add-Content/
Out-File. Causa (dal trace): un `New-Item -Value "..."` di 4 righe mandato a PowerShell si rompe (stringa
non terminata sulla 1ª riga) → file mai creato. Test `tests/test_newitem_value_intercept.py` (4). Suite 380.

**Misura resa riproducibile.** L'e2e non-seeded è inaffidabile (il 4B senza oracolo pianifica diverso ogni
run — su tre run di node_backend, tre cause di fallimento diverse). Passato a `SISTEMISTA_DETERMINISTIC=1`
(seed 42, greedy): traiettoria stabile → si può fixare e ri-confermare sullo stesso seed.

**Diagnosi deterministica (seed 42), il muro.** node_backend: lo scorer dà PASS (package.json + server.js
*esistono*) ma l'agente dà correttamente INCOMPLETE, perché il coder 3B authora `New-Item -Path server.js
-ItemType File` — file **VUOTO, senza -Value** — ripetutamente, e una volta allucina `FILE_CREATE_CMD`.
Notevole: Fix #1 (veto) è attivo e corretto qui — *"verifier said achieved, filesystem disagrees:
file_has_content(server.js)"* blocca il falso COMPLETE del verifier LLM.

**Fix D tentato e REVERTATO.** Reso prescrittivo il segnale di recovery empty-file ("il file è VUOTO, usa
-Value") — cache-safe (solo tail, invariante #13 intatto). Misurato sullo stesso seed 42 (det2 vs det1):
**nessun cambiamento** — il coder ripete l'empty New-Item, e il fallimento va in *replan* (nuovo piano dal
4B), non nel retry within-step dove il segnale inietta. Prova deterministica che il collo di bottiglia è la
**capacità del 3B di authorare contenuto di file**, non il segnale né un bug di runtime. Non spedito (value
= codice misurato).

**Conclusione (fine del whack-a-mole di runtime).** I 4 fix runtime di affidabilità/correttezza sono fatti,
provati, committati (`da227d7`, `0594654`). Il prossimo lever è **fuori dal runtime** ed è una scelta di
direzione a ROI equivalente/incerto: (a) prompt-engineering di `executor.jinja` (cache-sensitive,
model-dependent), (b) authoring sull'oracolo/modello più grande (RFC-001), (c) fine-tune 3B (RFC-001 QLora),
(d) rinforzo della misura (debito #3) per quantificare prima di altre modifiche. Decisione del developer.

**Status.** ✅ 4 fix committati, suite 380; muro identificato deterministicamente = qualità coder 3B.

---

## 2026-07-14 — Il "muro del 3B" era architettura, NON il modello (provato) + content-authoring path

**Sfida metodologica (accettata).** Un team esterno ha contestato — giustamente — che avevo provato *una
sola* classe di soluzione (prompt) e concluso "limite del 3B". Falsificavo "il prompt è il problema", non
"l'architettura dell'authoring è il problema". Mandato: escludere le ipotesi architetturali (H1–H10) *prima*
di attribuire il limite al modello. Lo stesso gate vale per il training (fine-tunare per mascherare un bug
architetturale è l'anti-pattern ML).

**Esperimento di controllo decisivo (H1/H10).** Isolato il coder 3B dal pipeline. Stesso modello, stesso
greedy, seed 42, unica differenza il **framing**:
- framing pipeline attuale (`executor.jinja`: *"produce the SINGLE shell command"*) → `New-Item -ItemType
  File server.js` = **file vuoto**.
- framing contenuto (*"write the file body"*) → **server Node.js corretto** (`http.createServer`,`listen`).

**"Limite del 3B" FALSIFICATO.** Il 3B sa scrivere il contenuto; il pipeline lo forza a codificare un file
multi-linea in un comando shell (il primitivo sbagliato) e non gli mostra mai `write_file`. Causa radice in
`executor.jinja` righe 2/5/12.

**Fix architetturale (content-authoring path).** Per uno step MODIFY che dichiara `file_has_content(X)` con
un launcher di scrittura-file (whitelist: New-Item/Set-Content/Out-File/touch/echo>/write_file, esclusi
scaffolder/pkg/append/Directory), il runtime chiede al coder il **corpo di X** (`executor_content.jinja` +
`model_router.content_call`, multi-linea, no `_first_command`) e lo scrive via `write_file` nativo. Additivo:
su risultato vuoto ricade sul path shell → zero regressioni. File: `_content_write_target` +
`_author_and_write_content` in `orchestrator.py`.

**Misura end-to-end, stesso seed 42 (det1 → det_content).**
| | det1 (prima) | det_content (dopo) |
|---|---|---|
| server.js | 0B (New-Item vuoto 3× + `FILE_CREATE_CMD`) | **299B, server HTTP valido** |
| verdetto | INCOMPLETE | **COMPLETE** (43.2s) |

Il content-path intercetta il `New-Item` vuoto del coder e riformula come richiesta di contenuto → 299B →
`✓ Step complete` → TASK COMPLETE. **Prima volta che node_backend raggiunge un COMPLETE onesto.**

**Validazione.** +15 test `tests/test_content_authoring.py` (routing); suite **381 passed, 1 skipped**.

**Conseguenza sul mandato training.** La premessa che giustificava il fine-tuning ("limite del 3B") è
**disprovata sperimentalmente** per il bottleneck dominante. Il training NON è giustificato per questo bug.
Il prossimo passo ML responsabile è **l'infrastruttura di misura** (benchmark interno per-categoria con le
metriche richieste: empty_file_rate, false_COMPLETE_rate, ecc.) + trace→dataset builder — prerequisito per
provare un eventuale limite residuo del modello e per il loop RL-da-ambiente. Debito #3 diventa il fronte.

**Status.** ✅ fix architetturale provato in isolamento E end-to-end (seed 42, COMPLETE). Training rimandato
(premessa disprovata); prossimo = infrastruttura di misura.

---

## 2026-07-14 — Infrastruttura di misura + baseline: il fix generalizza, restano bottleneck architetturali

**Costruito e committato (`c359f37`).** `benchmarks/agent_eval.py` (benchmark interno deterministico:
pass@1, false_COMPLETE_rate, empty_file_rate, hallucination_rate, content_authored_rate, wall; baseline +
delta) e `benchmarks/trace_to_dataset.py` (log → dataset con reward verificabile dall'ambiente + analisi
fallimenti per categoria). È la mossa ML responsabile *prima* del training.

**Analisi dataset (220 record, 44 log della sessione).** Indica i prossimi bottleneck architetturali:
`filesystem 27% ok`, `package_management 37% ok` (EPERM install globali), `code_authoring` 12 file vuoti
(per lo più pre-fix). `discovery 100%`.

**Baseline interna (node_backend, react, django; seed 42).**
`pass_rate 0.333 · false_complete_rate 0.0 · empty_file_rate 0.0 · hallucination_rate 0.0`.
- ✅ **Il fix generalizza:** `empty_file_rate` e `false_complete_rate` a **0** su tre casi diversi — il
  bottleneck dominante (file vuoti / falso COMPLETE) è chiuso.
- react/django falliscono ancora, ma per **altri** motivi (scaffold/package/filesystem) → prossimi H.

**Due difetti trovati DAL benchmark:**
1. **Riproducibilità imperfetta (bug di misura mio):** il path assoluto del workspace entra nel prompt
   (WORKSPACE SNAPSHOT), quindi `var/benchmark/…` vs `validation/stress/…` produce piani diversi *anche con
   seed 42*. node_backend: 43.2s COMPLETE (un path) vs 600s timeout (altro path). **Debito: normalizzare il
   path del workspace nel prompt** (es. token `$WORKSPACE`) perché il deterministico sia davvero tale.
2. **Terminazione:** in un piano, node_backend produce gli artefatti (content-authored, PASS filesystem) ma
   non raggiunge TASK COMPLETE entro il timeout — loop post-completamento su step VERIFY. Da investigare.

**Verdetto sul training.** Il fix architetturale ha portato il bottleneck dominante a zero senza toccare il
modello. La premessa del fine-tuning resta **disprovata dai dati**. Il loop corretto è *architettura →
misura → ripeti*; l'infrastruttura è in piedi. Il training si giustifica solo se, esauriti i fix
architetturali, il benchmark mostra un gap residuo — che al momento non esiste.

**Status.** ✅ infra di misura + baseline; fix generalizza (empty/false-complete a 0); prossimi fronti
identificati dai dati (filesystem/package/scaffold) + 2 debiti (riproducibilità path, terminazione).

---

## 2026-07-14 — Certification step 1: il "path-leak" era già chiuso; il leak vero è il wall-clock

**Mandato (developer).** Dopo una valutazione strategica, scelta la direzione **certification-first
minimale, gated per patch**. Step 1 = "fix del path-leak di riproducibilità" (debito #1 della voce
precedente: *«il path assoluto del workspace entra nel prompt (WORKSPACE SNAPSHOT) → var/benchmark vs
validation/stress producono piani diversi anche con seed 42»*).

**OSSERVA prima di CAMBIARE — la premessa è stata falsificata.** Esplorato via grafo Sinapsi il percorso
prompt→modello: `model_router._render` (unico choke-point di tutte le call) applica **già**
`workspace_paths.scrub`, single owner che sostituisce ogni grafia del root (`native`, forward-slash,
JSON-escaped, case-insensitive) con `.`. È wired via `set_root(self._workspace)` in
`Orchestrator.__init__` (orchestrator.py:1118) e **coperto da 9 test** (`test_workspace_paths.py`:
native/forward-slash/JSON-escaped/bare/nested/outside/idempotent). **Il path-leak è già chiuso.** Il fix
proposto (token `$WORKSPACE`) sarebbe un **owner duplicato** e, peggio, un placeholder non risolto che
l'**invariante #2** bloccherebbe all'esecuzione. NON fatto — sarebbe stato un regresso.

**Il leak di riproducibilità reale (confermato leggendo il codice, non ipotizzato).** Tre sorgenti che
lo scrub non tocca, in ordine di blast radius:
1. **`system_spec.build()` inietta `TODAY: {date.today()}` in OGNI prompt** (system_spec.py:74) → due run
   in **giorni diversi** = prompt diversi. Wall-clock, colpisce plan/verify/executor/tutti. **← FIXATO.**
2. **`INSTALLED_VERSIONS`** = versioni tool della macchina viva (probe di `node/npm/git/...`) in ogni
   prompt → rompe la riproducibilità **cross-machine**. Lasciato **live di proposito**: freezarle
   misurerebbe una macchina fittizia; la baseline di `agent_eval` è già **machine-scoped** per costruzione.
3. **Memoria persistente condivisa** (`ROOT/var/memory`, non isolata per-caso): `regressions.md` entra in
   `ctx["memory"]` via `get_regressions()[:1024]` (supervisor.py:176). Ora **assente** sul disco (non è
   perdita viva), ma `episodic.db` è 1.1 MB accumulato e `clear_session_events()` azzera **solo**
   events+cache, non regressions né le tabelle v2. **Latente → deferito** al prossimo gate.
La divergenza osservata dal developer (COMPLETE vs timeout, "stesso seed") era **cross-harness**
(agent_eval vs validation/stress): memoria/giorno/spelling-del-path diversi, non il path scrubato.

**Cambiamento (minimo, single-owner).**
- `config.py`: `SPEC_DATE: str | None` — la data da iniettare, `None` = data viva. Sotto DETERMINISTIC
  pinnata (`2026-07-01`), overridabile con `SISTEMISTA_SPEC_DATE`. Owner della riproducibilità = `config`,
  già proprietario di `SEED`/`DETERMINISTIC` (esteso, non un nuovo owner).
- `system_spec.py`: `today = config.SPEC_DATE or date.today().isoformat()` (+ `from .. import config`).
  Legge il knob a call-time; il resto invariato. Le versioni restano live (vedi sopra).
- `tests/test_spec_determinism.py` (3): data pinnata quando configurata; data viva quando no; **due build
  indipendenti col pin danno output byte-identico**.

**Validazione.** Mirati (spec+reproducibility+workspace_paths): **17 passed**. Regressione completa:
**399 passed, 1 skipped**, zero fallimenti. Fix verificato a livello unitario (data pinnata + stabile
tra build); il re-baseline e2e cross-day è una raccomandazione di gate (richiede llama-server+oracolo).

**Metriche di semplificazione.** LOC +~60 (di cui 45 test, ~12 commento in config, 3 di logica); owner
duplicati rimossi 0 / **owner nuovi 0** (config esteso); branch di runtime +0; **sorgente di non-determinismo
rimossa: 1** (wall-clock nel prompt sotto misura); invarianti +0; debito residuo: versioni cross-machine
(machine-scoped, documentato), isolamento memoria per-run (deferito), `ts` degli eventi nei replan (minore).

**Status.** ✅ step 1 chiuso sul leG dominante (wall-clock pinnato + test-guard); path-leak dimostrato
già risolto. Gated: fermo per conferma prima dello step successivo (fix terminazione / crescita n /
decisione isolamento memoria).

---

## 2026-07-14 — Diagnosi step 2 (scaffold cluster): DUE ipotesi falsificate + baseline invalida

**Metodo (directive owner).** Modo standing adottato: target scelto **dai dati** (rank del cluster per
impatto su pass_rate), cadenza **gated**, **falsifica prima di implementare**. Salvato in memoria
(`feedback_operating_loop.md`). Target scelto dal dato: "scaffold-at-root cluster" (react+django, 2/3 fail).

**OSSERVA (log reali `var/benchmark/agent_eval/{react,django}.log`). Ipotesi falsificate:**
- **`fix termination` (scelta umana) → falsa come target di pass_rate.** node_backend è `passed=true`
  (lo scorer trova i file); il timeout 600s costa latenza/onestà, non pass_rate.
- **`scaffold-at-root cluster` (mia scelta dai dati aggregati) → falsa.** Nessuno dei due è hoisting.
  - **react** = **acquisizione-tool su macchina non-admin.** `vite create` (bare, non su PATH, exit 1) →
    `npm install -g vite@latest` → **EPERM** (`mkdir C:\Program Files\nodejs\node_modules\vite`, no admin),
    ripetuto su 3 replan, **mai** il runner effimero (`npm create`/`npx`). L'unico `npm init vite@latest`
    (PTY) ha mis-navigato il menu `select` → ha scelto **`create-marko`** invece di react-ts.
  - **django** = **NON un fallimento dell'agente: CRASH dell'harness.** `supervisor.plan → _oracle() →
    llm_backend._post → urlopen → ConnectionResetError [WinError 10054]`, **non gestita** → processo morto
    in planning (verdetto `?`).

**Scoperta che invalida il baseline.** **react girava sul 4B owned** ("[oracle] none", `:8081` assente);
**django tentava l'oracolo** e crashava per reset di connessione. Il baseline n=3 misura una **miscela di
config (oracle-on/off) + un crash** → non riproducibile, non confrontabile. Health-check-then-use ha un
TOCTOU: l'oracolo passa il check, poi la chiamata reale viene resettata, e la fallback "usa il 4B" (che
esiste per l'*assenza*) non copre l'*errore di rete a runtime*.

**Ranking reale (dai dati, non da intuizione).** Il target #1 NON è un comportamento dell'agente: è la
**affidabilità della misura** (certification-first). (a) l'errore di rete dell'oracolo deve **degradare al
4B owned**, mai crashare il run (traceback: `model_router._complete` cattura solo `ProviderContextError`,
non gli errori di rete); (b) config oracolo **deterministica** nel benchmark (default self-contained
oracle-off = ciò che spedisce e gira su hardware modesto, oppure oracolo gestito dall'harness con
fail-fast). Solo DOPO si può misurare pulito il cluster reale di react (global-install anti-pattern +
mis-nav PTY del menu).

**Nessun codice cambiato** (diagnosi + gate). Fix proposto, in attesa di decisione owner sulla direzione
config-oracolo. Le entry `known-issues.md` verranno scritte col fix (symptom→cause→fix reale).

**Status.** ✅ diagnosi: due ipotesi falsificate (vittoria diagnostica), baseline invalida per config
mista, target #1 = affidabilità del benchmark (crash-safety oracolo + config deterministica). Gated.

---

## 2026-07-14 — Fix affidabilità misura: crash-safety oracolo (runtime) + benchmark self-contained

**Decisione owner (gate).** Config benchmark = **self-contained (oracle-off)**; crash-safety a livello
**runtime** (prod + benchmark).

**Cambiamenti.**
- `llm_backend._post`: nuovo `except (OSError, http.client.HTTPException) → ProviderError`, DOPO gli
  `except HTTPError/URLError` (ordine: HTTPError⊂URLError⊂OSError). Un reset di connessione mid-response
  (l'esatto crash di django) non è un `URLError` → prima propagava non gestito. Ora è un `ProviderError`
  tipizzato al singolo boundary HTTP. `+import http.client`.
- `model_router._complete`: nuovo `except ProviderError` (dopo `ProviderContextError`, che ne è
  sottoclasse). Se il provider è l'oracolo (`provider.name == _ORACLE_NAME`) → **degrada** a `_nav()` e
  ritenta nel loop `range(4)`; altrimenti (server owned) rilancia. Mai crash, mai maschera un guasto
  locale. Nuova costante `_ORACLE_NAME` (unica fonte, usata anche da `_oracle()` — no drift). `+import
  ProviderError`.
- `benchmarks/agent_eval.py`: `SISTEMISTA_ORACLE="1"` → `"0"`. Il benchmark misura il 4B owned da solo —
  ciò che spedisce e gira su hardware modesto. Niente dipendenza da server esterno, niente config mista.
- `tests/test_oracle_degradation.py` (3): reset→ProviderError (riproduce django); oracolo→degrada al nav;
  server owned che cade → rilancia (non mascherato).

**Validazione.** Mirati **3 passed** (incl. la riproduzione esatta di `ConnectionResetError [10054]`).
Regressione completa **402 passed, 1 skipped** (399 + 3), zero regressioni. **e2e re-baseline NON
eseguito**: nav/coder/oracle tutti giù (8090/8091/8081); richiede spawn dei llama-server (binario esterno,
debito #1) + minuti/caso. Validato a livello unitario; il re-baseline pulito (oracle-off) è la misura di
follow-up quando i server sono su.

**Metriche di semplificazione.** Owner nuovi **0** (llm_backend resta l'owner HTTP, model_router quello
della policy di escalation — separazione, non duplicazione); branch runtime +1 (degrade, intenzionale =
resilienza); crash-path eliminato **1**; sorgente di non-riproducibilità del benchmark rimossa **1**
(config oracolo mista); invarianti +0. `known-issues.md`: +2 entry (oracle-crash, react global-install).

**Status.** ✅ crash-safety + benchmark self-contained, provati a livello unitario. Il baseline n=3 va
**ri-preso** oracle-off (era invalido). Prossimo cluster di capacità reale = react global-install/PTY,
misurabile dopo il re-baseline. Gated: fermo per conferma.

---

## 2026-07-14 — Riproducibilità della pipeline: risoluzione portabile del binario llama-server

**Limite epistemico attaccato (scelto dai dati, non da TODO).** Il maggiore fattore che rende la misura
inaffidabile: la pipeline non gira riproducibile su nessuna macchina tranne una. `config.LLAMA_SERVER_BIN`
= `env → path assoluto esterno hardcoded` (checkout Cowork), senza fallback PATH/vendored; il messaggio
d'errore prometteva `workspace/bin/` **non implementato**. Un benchmark che dipende da un ambiente esterno
è un aneddoto.

**OSSERVA + falsifica (2 volte).** (1) I server **auto-spawnano** (ManagedServer lazy) — non "manuali",
come avevo detto prima. (2) Il `llama-server.exe` da **9 KB non è rotto**: è il launcher sottile di
llama.cpp che carica ~1.2 GB di DLL **sorelle** (`ggml-cuda.dll` 575MB, `cublasLt64_12.dll` 473MB, …) —
reale e funzionante (per questo `_spawn` mette `cwd=parent`). Falso allarme evitato verificando i magic
bytes + il contenuto della dir.

**Cambiamenti.**
- `config.py`: `_resolve_llama_server_bin()` — `env → workspace/bin/ vendored → shutil.which → path
  vendored inesistente (fail-loud)`. **Rimosso il path esterno hardcoded.** `+import shutil`. Un path
  machine-specific vive nell'ENV, non nel sorgente versionato.
- `benchmarks/agent_eval.py`: `_preflight()` — verifica binario + pesi risolvibili PRIMA di spawnare N
  subprocess; stampa istruzioni esatte ed `exit(2)`. Fail-fast, self-describing.
- `workspace/models/README.md` + `workspace/bin/README.md`: contratto di bootstrap (nomi/dimensioni GGUF;
  binario + DLL sorelle, DLL-adjacency). `.gitignore`: `models/*`+`bin/*` esclusi, **README tracciati**.
- **Difetto latente esposto e corretto:** `test_pty_backstops._drive` mockava `_text_call` ma
  `executor_pty_fallback_call` valuta `_nav()` come *argomento* prima del mock → spawnava un server vero
  (passava solo perché il binario Cowork esisteva). Ora mocka anche `_nav` → test **ermetico** (i backstop
  sono model-independent). È riproducibilità applicata alla suite: 11 test che dipendevano da un server
  vivo ora non dipendono più.
- `tests/test_llama_server_resolution.py` (4): ordine di risoluzione + **guard di regressione** (il path
  Cowork non deve mai più tornare).

**Validazione.** Regressione **406 passed, 1 skipped** (402 + 4). Import sanity: `LLAMA_SERVER_BIN` →
`workspace/bin/llama-server.exe` (fail-loud), niente più Cowork. e2e non eseguibile finché il binario non
è risolto sulla macchina (vedi migrazione).

**MIGRAZIONE (developer, una tantum).** Il tuo setup ora richiede UNA cosa: puntare
`SISTEMISTA_LLAMA_SERVER_BIN` al tuo `llama-server.exe` (o metterlo su PATH, o vendorizzarlo in
`workspace/bin/` con le sue DLL). Il path Cowork non è più nel sorgente — è config di macchina, e quella
vive nell'ambiente.

**Metriche di semplificazione.** Owner nuovi 0 (config resta owner del binario); **dipendenza esterna
hardcoded rimossa 1**; preflight self-describing +1; test non-ermetico → ermetico (fragilità rimossa, 11
test); debito #1 chiuso lato **risoluzione + doc** (resta il fetch di pesi/binario, esterni per natura);
invarianti +0.

**Status.** ✅ pipeline di misura portabile + fail-loud + documentata; suite ermetica. Gated: fermo.

---

## 2026-07-20 — Audit integrale + branch `hardening/production-readiness` (7 commit, 574 test)

**Metodo.** Audit del sorgente con 8 revisori paralleli su file disgiunti (14.457 LOC letti
integralmente, non campionati), poi esecuzione **per dipendenza causale**, non nell'ordine
dell'audit: infrastruttura di misura → primitive di config → proprietà dei path → redazione →
audit trail → sicurezza dell'esecuzione → identità dei belief → PTY. La redazione precede
l'attivazione del trace per costruzione: accendere il trail senza di essa avrebbe scritto
credenziali su disco.

**Il reperto centrale.** Non "ci sono bug": il sistema **riportava successo dove non ce n'era**,
in quattro meccanismi indipendenti — suite di certificazione (33 test, zero assert, verdi
incondizionatamente), baseline (`pass_rate 0.333` il cui unico pass era un timeout a 600,0 s →
reale 0/3), audit trail (`trace.begin()` mai chiamato fuori dal benchmark), confinamento (inerte
per default in produzione). Quattro invarianti dichiarate in `AGENTS.md` (#2, #4, #8, #11, #14)
erano false o non cablate.

**Convergenza indipendente:** 4 revisori su 8, su file disgiunti, hanno riportato autonomamente
il buco dell'audit trail. Un revisore ne ha **smentito** un altro (`pyproject.toml` esiste, sta in
root); la correzione è stata verificata prima di essere recepita.

**Difetti trovati dai test mentre venivano scritti, corretti nel codice e non nel test:**
- `_backoff` applicava il cap 8 s *prima* del jitter → picchi a 12 s;
- la sostituzione di redazione usava il gruppo del valore invece del separatore → riemetteva il
  segreto accanto al placeholder (e il primo helper di test, che verificava solo la presenza del
  placeholder, non se ne accorgeva);
- la regola URL della redazione era quadratica: **23,9 s su 100 KB senza URL** — DoS su un hot
  path che processa output di modello e contenuto web;
- `Confinement.current()` derivava inizialmente la root dalla cwd del chiamante, che annulla il
  filtro;
- `shlex.split(posix=False)` conserva le virgolette su Windows → argv non trovava l'interprete;
- il pattern `{SLOT}` matchava dentro `${WORKSPACE_PATH}`, segnalando uno slot già sostituito.

**Validazione.** 574 passed, 1 skipped, **senza alcun flag di esclusione** — la suite di
certificazione è nella suite. Diffstat: 58 file, +2.814 / −4.766 (il saldo negativo è quasi tutto
codice finto rimosso: 4.455 LOC di certificazione auto-referenziale + il runner duplicato).

**Metriche di semplificazione.** Owner rimossi: 3 canonicalizzatori di identità → 1; 5 costanti di
path congelate all'import → funzioni risolte a runtime; un secondo framework di test → pytest.
Guard resi effettivi: 4 (confinamento, safety gate, placeholder, quarto owner di esecuzione).
Test da grep-su-sorgente convertiti a comportamentali: 2 file. Codice morto cancellato: ~4.500 LOC.
Invarianti +0 dichiarate, ma 5 rese vere.

**Non fatto, e perché.** La pipeline OCKE deterministica resta scollegata (debito #1): cablarla
cambia *come i comandi vengono prodotti* e non è validabile senza i server dei modelli. Il loop
PTY resta aperto (detection corrette, controllo no). `orchestrator.py` non è stato scomposto.
Tutti e tre rientrano nella condizione di terminazione dichiarata: redesign deliberato.

**Status.** ✅ I quattro falsi verdi sono chiusi e difesi da test. Prossimo passo obbligato: il
re-baseline pulito — è ora, per la prima volta, una misura interpretabile.

---

## 2026-07-20 (seguito) — WU7/8/9: le tre "impossibilità" erano ipotesi

**Il reperto di metodo, che vale più delle singole patch.** L'iterazione precedente aveva
chiuso il lavoro dichiarando tre voci «richiedono un redesign fuori dall'architettura».
Erano ipotesi non verificate. In tutti e tre i casi **la giuntura per l'inversione di
dipendenza esisteva già nel codice**: `TerminalSession` prendeva `write_fn`/`read_fn` dal
costruttore, `_run_loop` prendeva `session`/`terminal`/`supervisor` come parametri. Nessuno vi
aveva mai collegato nulla che non fosse l'oggetto reale. "Non testabile" significava "non ho
provato a costruire il finto".

**WU8 — loop PTY chiuso.** Clock iniettabile + `tests/fake_pty.py` (terminale scriptato che
emette ANSI vero e ridisegna a ogni tasto, in due stili di cursore, con e senza wrap).
`_send_key_and_measure` attende che il terminale *dimostri* il movimento; `_drive_select`
rileva l'avvolgimento e si arrende invece di indovinare. Piano attributi SGR esposto: i menu
clack/BubbleTea, prima con cursore strutturalmente invisibile, ora sono navigabili.
Blocco di opzioni riconosciuto *come blocco*, quindi le opzioni sopra il cursore non spariscono
più. 21 test, convergenza da tutte e 11 le posizioni di partenza.

**Difetto di performance trovato dall'harness:** `pyte.Screen.display` esegue `wcwidth` su ogni
attributo di ogni cella come assert interno — **608 ms per render** su 220×50, contro 0,049 ms
di una lettura diretta del buffer. Il controller legge lo schermo a ogni poll: un wizard con
venti ridisegni passava dodici secondi dentro un assert di debug. Sostituito e cachato per
feed. Il render scritto a mano è validato **differenzialmente** contro quello di pyte, e quel
test ha subito trovato un bug reale (i caratteri wide venivano spaziati).

**WU9 — OCKE deciso per misura, non per opinione.** La pipeline dormiente copre **0 degli 11
goal misurati** (il KB descrive primitive OS, il carico è scaffolding di progetto); il suo
`render()` interpolava variabili in una stringa di shell **senza quoting** e i suoi unici due
chiamanti erano nel ranker morto — l'iniezione viveva esclusivamente in codice morto e
cablarla è precisamente ciò che l'avrebbe resa viva; `record_outcome` non poteva scattare, per
cui due campi del prompt del planner descrivevano un learning loop inesistente. Cancellata
(−710 LOC). Ciò che sopravvive è provato cablato da test che lo chiamano.

**WU7 — belief rifondati.** `BeliefKey(subject canonico, Predicate enum)` come valore frozen:
l'identità non dipende più dalla formattazione. `EvidenceKind` ordinato sostituisce lo `score`
scelto dal chiamante, quindi "PROVEN è infalsificabile" diventa "vince l'evidenza più forte".
**La scoperta vera:** `MUTATION` non è la cima della classifica ma una categoria diversa —
ordinare `which yt-dlp` (assente, t0) contro `pip install` (riuscito, t1) *per forza* è un
errore di categoria, entrambe sono vere su mondi diversi. La prima versione del refactor ha
riprodotto il deadlock originale in forma nuova proprio per questo. Ordinamento per contatore,
non per `time.time()` (15 ms di risoluzione su Windows: "chi è più recente" era testa o croce).

**Copertura, prima → dopo:** orchestrator 11% → 46%, supervisor 7% → 61%, main 0% → 59%,
terminal_runtime/session 18% → 82%, totale 54% → 66%. Suite 574 → 654.

**Difetti trovati dai nuovi harness e corretti nel codice:** dimensione dei file-credenziale
(`.env`, `id_rsa`, `*.pem`) esposta in ogni prompt del planner; goal di soli spazi accettato
(`"   "` è truthy, passava entrambi i controlli); `_run_loop` con una precondizione implicita
(`init_db`) ora dichiarata.

**Status.** ⚠️ **Non è un ottimo locale.** Restano voci risolvibili localmente e sono elencate
in `handoff.md`: scomposizione dell'orchestratore, `wizard_driver` come database di framework,
CI, LICENSE. La sola voce genuinamente fuori architettura è il confine kernel (sandbox).


---

## 2026-07-20 (seguito) — Il primo baseline onesto, e la scoperta che lo rende inutilizzabile da solo

**Il mandato di questa iterazione** era massimizzare `success_rate × velocità × determinismo ×
efficienza hardware` togliendo call LLM e token. Il risultato più importante non è una patch: è che
**tre delle cinque metriche di quel prodotto non sono attualmente misurabili su questa suite**, e
ora sappiamo di quanto.

### Il ledger per-call non esisteva: `Orchestrator.run` rubava il trail al harness

`var/benchmark/<label>/traces/*.jsonl` era **0 byte** in ogni run archiviata. `run_suite` apre il
trail per task, poi `Orchestrator.run` ne apre un altro, e `trace.begin()` era **last-wins**: ogni
evento finiva in `var/trace/`. La suite esiste per produrre quel ledger e non lo produceva.
`begin()` è ora **first-wins** e registra il tentativo rifiutato *nel trail attivo*. Senza questo
fix nessuna delle misure sotto sarebbe esistita.

### Baseline onesto: 40/48 = 83,3 % ARR

Solo modelli owned (nessun oracolo), seed 42, greedy, scoring deterministico sul filesystem.
43,4 s/task · 12,4 call LLM/task · 5,7 comandi/task. Ripartizione del tempo di inferenza (1.493 s):
**supervisor 870 s (58 %)**, enhancer 180 s (12 %), verify 165 s (11 %), coder 151 s (10 %),
content 79 s (5 %), safety 48 s (3 %).

### Il reperto: due run a codice IDENTICO differiscono di 5 task e del 30 % di wall-clock

`arm_gate` 34/48 · `arm_repeat` 39/48 — stessa configurazione, stesso seed, cache off, unica
differenza un `trace.emit` osservativo. McNemar: 7 coppie discordanti, p = 0,125.

Peggio, la decomposizione sui **41 task il cui esito NON è cambiato**:

| contatore | delta aggregato | media \|diff relativa\| per task | identico su |
|---|---|---|---|
| call LLM | −8,1 % | 29,3 % | 9/41 |
| token di prefill | −10,4 % | 34,3 % | **1/41** |
| wall-clock | −30,2 % | 55,7 % | **0/41** |

**`DETERMINISTIC` non produce determinismo su questo carico.** `config.py` afferma che la modalità
rende una run «riproducibile bit-for-bit»; è vero per l'RNG e falso per la run. Il seed fissa il
campionamento, non l'**ambiente**: i task interrogano lo stato vivo della macchina (porte, processi,
log eventi, servizi, versioni dei tool), quell'output rientra nei prompt, prompt diversi producono
token diversi — ed è visibile direttamente, perché il *prefill* differisce su 40 task su 41.

Conseguenza operativa: **il floor di rumore è ~5 task su una ripetizione pura** (il floor
precedentemente registrato, ~5, era stato stimato confrontando modifiche *diverse* — ora è
misurato a modifica nulla, e coincide). Su 3 run, 36 task su 48 non discriminano mai (32 sempre
verdi, 4 sempre rossi) e 12 oscillano. La capacità informativa dello strumento è quei 12 task
rumorosi.

### Una regressione attribuita male, e come è stata smontata a costo zero

`arm_gate` sembrava dire che la patch al gate del coder costava 6 task. Rieseguendo il predicato
**vecchio** su ogni comando accettato della suite: la patch ha ribaltato **2 decisioni in totale**,
nessuna in un task regredito. Il vero movente era nello stesso braccio — la rimozione del codice
morto toglieva `memory.get_regressions()` dal prompt del supervisor, e siccome lo scrittore era già
morto quel campo valeva `""`: **il prompt ha perso due caratteri di a-capo e 7 task si sono
ribaltati**. Lezione già scritta in `test_benchmark_noise_floor.py` e violata di nuovo; ora è in
`known-issues.md` come regola: mai una modifica che tocca un prompt nello stesso braccio della
modifica sotto test.

### Patch

1. **`trace.begin()` first-wins** — il ledger del benchmark esiste (sopra).
2. **Gate del coder, due falsi positivi** — la regex non ammetteva `$var = …` e il backtick contava
   come markdown, ma in PowerShell è l'escape. Classificando i **334 rigetti reali**: zero prosa,
   95 % eco dell'hint, 5 % comandi validi respinti. L'estrattore prosa→comando che stavo per
   costruire era inutile: ipotesi falsificata dai dati prima di scrivere il codice.
3. **`_stderr_only_output()`** — exit 0 + target della redirezione vuoto + redirezione del solo
   stdout ⇒ l'output è andato su stderr; unisce gli stream e riprova. Regola **sugli stream**,
   nessun nome di tool nel codice; provata *prima* dell'LLM. Sostituisce una call al modello con
   uno `stat()`. Idioma verificato empiricamente in PowerShell (0 → 333 byte).
4. **Fingerprint del piano in traccia** — 12 caratteri che identificano i *comandi* di un piano,
   insensibili alla prosa. Serviva perché `output` è tagliato a 1200 caratteri e **82 piani su 86
   erano illeggibili**: la domanda «questo re-plan ha prodotto qualcosa di nuovo?» — quella che
   decide se il re-planning debba diventare *riparazione* — era rispondibile su 4 campioni, di cui
   2 identici. Ora è misurabile su ogni run.
5. **Flag `SISTEMISTA_ENHANCER`** — la call NAV incondizionata (12 % del tempo) ora è spegnibile.
6. **−80 LOC di percorso morto** — `reflection_call`, `Supervisor.recover`, `reflection.jinja`, la
   tabella `regressions` e i suoi due accessor: scrittore morto, lettore che iniettava sempre vuoto.

**Validazione.** 679 test verdi, 1 skip (era 654). Quattro file di test nuovi, tutti costruiti sui
casi *misurati* nel ledger, non immaginati.

### Non fatto, e perché

Nessuna delle patch sopra ha un effetto su ARR dimostrabile: lo strumento non risolve differenze
sotto ~5 task, e nessuna di esse ne vale 5. Restano difendibili per costruzione (un comando valido
non va respinto; un artefatto vuoto con exit 0 ha una causa nota e una riparazione deterministica),
non per misura — e questo va detto così.

**La priorità che ne discende non è una patch ma lo strumento:** finché una ripetizione pura muove
5 task e il 30 % del wall-clock, «ogni commit migliora almeno una metrica» non è verificabile.
Le strade sono isolare l'ambiente (container/VM con stato congelato — fuori dall'architettura
attuale, come il confine kernel) oppure separare i task ermetici da quelli che interrogano lo stato
vivo e misurare solo sui primi.


---

## 2026-07-20 (fine giornata) — Il floor di rumore non era una proprietà della suite: era un difetto

Una review esterna elenca dieci proprietà mancanti e chiude con cinque vincoli, l'ultimo dei quali è
«nessuna modifica è un miglioramento senza benchmark ripetibili». Corretto — e auto-bloccante, perché
il benchmark non era ripetibile. `RFC-003` riordina le dieci voci per dipendenza invece di eseguirle
in sequenza. Questa entry registra la fase 0.

### Come è stata trovata la causa (tre ipotesi, due mie, tutte falsificate)

Localizzando la divergenza **per template, sulla prima call di ogni task**, fra due run a codice
identico:

| template | prompt identici | output identici, dove il prompt lo era |
|---|---|---|
| `safety.jinja` | 48/48 | 48/48 |
| `prompt_enhancer.jinja` | 47/47 | 47/47 |
| `supervisor.jinja` | **0/47** | — |

Due conclusioni immediate. **A prompt identico l'output è identico, 95 su 95**: lo stack di inferenza
è deterministico, `DETERMINISTIC` fa quello che promette. E `system_spec` è già congelato e stabile,
perché safety ed enhancer ricevono solo quello.

L'unica cosa che il planner riceve e loro no è **`history`** — `memory.get_recent_events()`, uno store
di processo che si accumula fra i 48 task e **sopravvive alla run successiva**. Prova diretta:
`var/memory/context_cache.json` conteneva eventi di `arm_repeat/T46` e `T47`, cioè il T01 di ogni run
pianificava leggendo ciò che il T47 della run **precedente** aveva lasciato.

La suite non misurava 48 prove indipendenti. Misurava **una sequenza dipendente di 48 passi,
inizializzata da residui**.

Le ipotesi cadute lungo la strada: (a) la review dice «non è il modello, è il mondo» e la prima
versione di RFC-003 ne deduceva di dover congelare l'ambiente — falso, l'ambiente era già stabile;
(b) prima ancora, l'estrattore prosa→comando e la tabella di token d'ambiente, entrambi smontati dal
ledger prima di scrivere il codice.

### La correzione

Una directory di memoria per task, in `run_suite.task_memory_dir`. Vive nel **harness, non nel
prodotto**: un agente che ricorda i task precedenti è una funzionalità in produzione ed è
contaminazione in un benchmark che li punteggia come indipendenti.

### Il risultato, misurato

Due run consecutive a codice identico, dopo la correzione:

| | prima (arm_gate / arm_repeat) | dopo (iso_a / iso_b) |
|---|---|---|
| ARR | 34 vs 39 (**swing 5 task**) | **32 vs 32** |
| McNemar | 8 discordanti, p = 0,07, sbilanciato 7-1 | 6 discordanti, **p = 1,000**, bilanciato 3-3 |
| prompt del planner identici | **0/47** | **39/39** |
| prefill identico (task concordanti) | 1/41 (2 %) | 25/42 (60 %) |
| call LLM identiche | 9/41 (22 %) | 32/42 (76 %) |

**Il criterio dichiarato prima di guardare era ≥ 90 % di prefill identico, e non è raggiunto (60 %).**
Ma il criterio era mal specificato: mescola il percorso di *pianificazione* — che il runtime controlla
e che ora è deterministico (supervisor 39/39, safety 48/48, enhancer 45/45: **132 su 132**) — con
quello di *esecuzione*, che riceve stdout/stderr di comandi reali su una macchina viva. Il residuo
sta tutto lì: `executor.jinja` 29/35, `verify.jinja` 37/39, differenza media **5,2 e 0,6 token**.
Quella parte non va congelata: è il mestiere dell'agente, e congelarla misurerebbe una macchina
fittizia.

### Il numero che va corretto verso il basso

**L'ARR onesto è 32/48 = 66,7 %, non 83,3 %.** Il baseline di stamattina era gonfiato dalla
contaminazione: i task si aiutavano a vicenda leggendo la storia dei precedenti. Va detto che il
confronto non è pulito — le run isolate contengono anche le altre patch della giornata — ma la
direzione non è in dubbio e l'ordine di grandezza nemmeno.

### Validazione

686 test verdi. I numeri sopra sono ora un **contratto eseguibile** in
`tests/test_benchmark_noise_floor.py` (che li possedeva già per la stima precedente) e
`tests/test_benchmark_task_isolation.py` fallisce se qualcuno ricongela `MEMORY_DIR` all'import e
rompe il meccanismo senza accorgersene.

### Cosa cambia nella roadmap

Il container **resta P0 per la distribuzione** — shell arbitraria sull'host non è distribuibile — ma
**non è più anche la soluzione al problema di misura**, quindi non blocca il lavoro sull'inferenza.
Lo snapshot dell'ambiente scende da P0 a debito di **latenza**, con una motivazione diversa emersa
dall'audit: esistono **cinque owner indipendenti** di «cos'è questa macchina», che si contraddicono
(`shell` = `powershell` per uno, `pwsh` per l'altro) e costano ~45 `shutil.which` più fino a 13
subprocess `--version` per `detect()`, mentre `observe()` rilegge l'intero workspace ~3 volte per
step, contenuto dei file compreso.

Il prossimo bersaglio è quello con il numero più grande: **il planner, 58 % del tempo di inferenza,
53 re-plan che rigenerano invece di riparare**. Ora, per la prima volta, un suo miglioramento è
distinguibile dal rumore.

---

## 2026-07-22 — RFC-004: il link pubblico non anticipa il GO

**Mandato.** Consolidare il progetto nel portfolio come `( 2026 ) Sistemista`, eliminare la
copia parziale precedente e iniziare l'operatività fino alla pubblicazione e al GO reale.

**Integrità.** La copia interrotta sotto `projects/Sistemista` mancava di 43 file versionati
del Windows validation lab. I file sono stati recuperati, il repository canonico è ora
`projects/( 2026 ) Sistemista`, HEAD `faaf00d`, branch `hardening/production-readiness`, e
`git fsck --no-dangling --full --strict` è verde. Il duplicato è stato eliminato forzatamente
dopo confronto esplicito degli HEAD; la root canonica è rimasta intatta.

**Due-diligence misurato.** Run cold: 680 passed, 3 failed, 1 skipped. La rilocazione sotto un
path con spazi e parentesi ha falsificato il guard anti-path-fabrication: `_ABS_PATH_RE` tronca
al primo spazio. Coverage 66,1% (orchestrator 48,6%, session 35,3%, terminal 20%). Ruff: 4
errori e 138 file da formattare. Mypy: 30 errori. Gitleaks full-history: 10 finding non
triaged. Wheel isolato costruito con prompt e KB, ma senza licenza. Nessun remote, workflow,
tag o release.

**Decisione.** RFC-004 approvata: pubblicazione progressiva. Prima alpha pubblica onesta su
`development`, poi `validation` soltanto dopo RFC-005 Secure Execution Boundary, infine
`production` al GO completo. Visibilità e production-readiness restano stati distinti.

**Semplificazione.** LOC runtime +0; owner runtime +0; branch runtime +0; decisioni LLM→
deterministiche +0. Debito aggiunto: 0. È stato aggiunto solo il contratto di release che
impedisce ai claim di precedere l'evidenza.

**Validazione della patch.** Modifica documentale; nessun runtime toccato. I gate rossi sopra
sono registrati come blocker di RFC-004 e saranno chiusi prima del push pubblico.

---

## 2026-07-22 — RFC-004: gate locale dell'alpha pubblica chiuso

**Correzione funzionale.** Il guard anti-fabrication non usa più la regex che troncava path
assoluti al primo spazio. Normalizza separatori/case, confronta boundary reali e valuta tutte
le occorrenze: un path vero non può più nasconderne uno inventato. Aggiunti test per sibling
con prefisso comune, ancestor e riferimenti misti reali/fabbricati.

**Qualità.** Ruff è configurato su Python 3.12 con regole E4/E7/E9/F/I; 138 file legacy sono
stati formattati e i quattro errori corretti. Il warning `invalid escape` è chiuso. Risultato
finale: Ruff verde, 148 file format-check verdi, **692 test passati e 3 skip dichiarati**.

**Security e privacy.** I dieci finding Gitleaks erano fixture sintetiche e due record di
validation generati; nessun token reale. Le fixture hanno allow inline puntuali, i valori
generati sono stati neutralizzati e gli identificatori utente nei report sostituiti senza
toccare risultati o verdetti. `.claude/settings.json` e `.mcp.json` usano ora `sinapsi` da PATH,
non path macchina. La superficie pubblicabile completa (17,62 MB) passa Gitleaks con zero
finding. La storia pre-pubblicazione resterà nel branch locale `archive/pre-publication`; la
storia pubblica parte da una root commit curata, così i finding sintetici storici non vengono
esportati.

**Supply chain.** Aggiunti Apache-2.0, NOTICE per Qwen/llama.cpp, SECURITY, CONTRIBUTING,
Code of Conduct, EditorConfig, CODEOWNERS, template PR e Dependabot. `diskcache==5.6.3`, non
importato dal runtime, è stato rimosso dopo il finding `PYSEC-2026-2447` senza fix disponibile.
`pip-audit` riporta ora zero vulnerabilità note. Wheel e sdist `0.1.0a1` costruiscono in ambiente
isolato; il wheel include 8 prompt, 8 KB YAML, LICENSE e NOTICE.

**Presentazione e automazione.** README riscritto come alpha verificabile: limiti e trust boundary
prima dei claim, setup coerente con `llama-server`, configurazione, exit code e branch policy.
CI least-privilege esegue lint/format, test Windows+Ubuntu, build e dependency audit; Security
esegue Gitleaks full-history. Tutte le action sono pinned a commit SHA immutabili.

**Stato.** Il gate locale di RFC-004 è verde. Restano da verificare sul remoto: creazione URL,
Actions, private vulnerability reporting e ruleset. Nessuna promozione a `validation` prima di
RFC-005 Secure Execution Boundary.

### 2026-07-22 — Contratto line-ending

Aggiunto `.gitattributes`: testo normalizzato LF su ogni piattaforma, eccezione CRLF per launcher
batch e classificazione binaria esplicita per asset/GGUF. Evita che `core.autocrlf` trasformi una
formattazione repository-wide in diff di contenuto.

Il gate `git diff --check` ha rilevato e rimosso l'unica riga vuota eccedente a EOF in RFC-004.

---

## 2026-07-22 — RFC-004: repository pubblico e governance remota

Creato `https://github.com/Ignoryx/sistemista` via endpoint organizzazione, dopo che il comando
high-level `repo create` ha restituito un 403 spurio sul lookup `/users/Ignoryx`. Pubblicata solo
la root commit curata; i 27 commit pre-pubblicazione non sono sul remoto. `development` è default;
`validation` e `production` esistono allo stesso baseline senza falsa promozione di maturità.

Attivati Apache-2.0 detection, topics, Discussions, private vulnerability reporting, secret
scanning, push protection e Dependabot security updates. Ruleset `Protected release flow` attivo
sui tre branch: no delete/force-push, history lineare, PR + CODEOWNER + una review + last-push
approval + thread resolution, sei check obbligatori; organization admin può bypassare soltanto
tramite PR, lasciando audit trail.

GitHub non ha creato run per i push che precedevano la selezione del default branch. Aggiunto
`workflow_dispatch` a CI su un branch operativo: la PR verso `development` verifica ora insieme
workflow e ruleset prima della chiusura di RFC-004.

---

## 2026-07-22 — RFC-005: execution boundary fail-closed

**Policy.** Soltanto goal `SAFE` raggiungono il planner. `RECOVERABLE`, classifier offline e
risposte malformate terminano `REFUSED` senza comandi. Rimosso l'opt-out
`SISTEMISTA_UNCONFINED`; destinazioni dinamiche di write e mutazioni host note sono rifiutate.
PowerShell non viene più avviato con `ExecutionPolicy Bypass`.

**Contratto.** Il boundary resta una policy applicativa read-anywhere/write-workspace, non una
sandbox. Isolamento di processo/filesystem/network e input ostile non sono certificati; una
capability di mutazione host richiederà backend kernel/VM e RFC separata.

**Validazione.** Boundary mirato **83 passed**; suite completa **712 passed, 3 skipped**; Ruff e
format verdi su 149 file; wheel/sdist, pip-audit e Gitleaks verdi. I test di composizione provano
che i verdetti non-SAFE fermano planner ed executor.

**Remoto.** CI è registrato dopo la PR bootstrap, ma il dispatch GitHub restituisce HTTP 500 e
Security non viene indicizzato mentre Ignoryx è flagged. RFC-005 è implementata localmente;
promozione a `validation` vietata fino a run remoti verdi.
