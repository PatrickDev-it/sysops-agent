# Known issues & pitfalls

Operational memory: what bit us, so it never bites twice.
Format per entry: `symptom → root cause → fix / how to avoid`. Consult before debugging.

---

### Un debug dump dichiarato serializzabile conserva key dataclass
**Sintomo.** `ReasoningContext.debug_dump()` restituisce un dict che `json.dumps` non può codificare.
**Causa.** `BeliefSystem` usa correttamente `BeliefKey` come identità interna, ma il boundary telemetry
copiava quelle key senza renderle; inoltre leggeva ancora il vecchio attributo `score` già rimosso.
**Fix.** Renderizzare le key con `str()` e conservare provenance `support`/`against`; il test deve
serializzare e rileggere l'intero payload, non limitarsi a verificarne la forma Python.

---

### GitHub Actions non parte e il dispatch restituisce HTTP 500
**Sintomo.** CI è registrato dopo la PR bootstrap, Security non compare e `workflow_dispatch`
restituisce HTTP 500 senza creare run.
**Causa.** L'organizzazione Ignoryx è flagged e nascosta; repository, ruleset e Actions permissions
sono configurati, quindi il blocco è nel backend GitHub e richiede il ticket di reinstatement.
**Fix.** Non indebolire required checks né dichiarare verde il remoto. Conservare i gate locali,
attendere il ripristino e rieseguire CI + Security prima di promuovere a `validation`.

**Risoluzione operativa 2026-07-22.** Il repository personale esegue i workflow: Security è verde
e CI ha prodotto log reali. Il blocco resta storico per la copia organizzativa, destinata alla
cancellazione dopo la verifica della migrazione.

---

### Una destinazione dinamica può aggirare un controllo path basato sul testo
**Sintomo.** Un comando come `Out-File $target` non espone al parser il path effettivo della write.
**Causa.** Il confinement statico vede il nome della variabile, non il valore risolto dalla shell.
**Fix.** RFC-005 rifiuta destinazioni dinamiche per mutatori e redirection; valori dinamici non
usati come sink restano ammessi. Nessun parser applicativo va descritto come sandbox.

---

### `Access to the path '...' is denied` rinominando una directory su Windows
**Sintomo.** `mv` / `Rename-Item` falliscono su una directory, mentre rinominare una sua *sottodirectory*
o una directory nuova nello stesso parent funziona.
**Causa.** Un processo ha quella directory come **current working directory**. Windows non consente di
rinominare la cwd di un processo vivo. Nel nostro caso era un `du -sm` andato in timeout dopo 2 minuti
(exit 143) ma rimasto in esecuzione a scandire 3 GB di GGUF.
**Fix.** Non tirare a indovinare né uccidere processi a caso (abbiamo terminato due language server di
VSCode innocenti). Restringi prima il problema — se un figlio si rinomina, il lock è sulla dir stessa —
poi trova il colpevole:
`Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(du|find|bash|python)\.exe$' }`

---

### Gli shim `.exe` della venv smettono di funzionare dopo aver spostato `.venv/`
**Sintomo.** `pip`, `pytest` falliscono, mentre `python -m pip` funziona.
**Causa.** Gli eseguibili in `.venv\Scripts\` embeddano il path **assoluto** dell'interprete calcolato
alla creazione della venv. `python.exe` trova il proprio prefix dalla sua posizione, quindi sopravvive
allo spostamento; gli shim no.
**Fix.** Riporta la venv nel path in cui è stata creata (`pyvenv.cfg` → riga `command =` lo dice), oppure
ricreala. Il workaround `python -m <tool>` cura il sintomo, non la causa.

---

### Un guard di sicurezza smette di guardare, in silenzio
**Sintomo.** Nessuno. Il check passa sempre.
**Causa.** `_has_fabricated_workspace_path` cercava un segmento di path letterale (`.workspace`). Rinominata
la directory, la regex non ha più matchato nulla e il guard è diventato inerte, senza un errore, senza un
test che lo dicesse.
**Fix.** Un guard si ancora a un valore derivato (`config.ROOT`), mai a un nome scritto a mano.
Invariante #16 in `AGENTS.md`. Corollario: **un guard senza test non è un guard.**

---

### Confronto di path per prefisso di stringa: `.../ws_old` risulta "dentro" `.../ws`
**Sintomo.** Un path inventato dal modello passa come legittimo.
**Causa.** `candidate.startswith(real)` è vero anche quando i due path sono directory sorelle che
condividono un prefisso testuale.
**Fix.** Confronta per **componenti**, normalizzando separatore e case: `p == r or p.startswith(r + "/")`.
Vedi `orchestrator._is_within`.

---

### `read_text()` non trova una stringa che `cat` mostra chiaramente nel file
**Sintomo.** Una sostituzione esatta trova 0 occorrenze; il file "sembra" giusto.
**Causa.** `benchmarks/run_suite.py` aveva `\r\r\n` a fine di ogni riga (conversione LF→CRLF applicata due
volte). Python, in universal-newlines, traduce sia `\r` sia `\r\n`, quindi legge una riga vuota fra ogni
coppia di righe: il pattern `linea1\nlinea2` non matcha mai.
**Fix.** `Path.read_bytes()` e conta `\r\r\n` prima di dubitare del tuo pattern. Riparato con
`raw.replace(b"\r\r\n", b"\r\n")`.
**Da evitare.** Scrivere replace su file senza uno `assert` sul numero di occorrenze attese: un match
mancato passa inosservato.

---

### Un `SyntaxWarning` compare "dal nulla" dopo una riorganizzazione
**Sintomo.** `invalid escape sequence` in un file che non hai toccato.
**Causa.** Il warning è emesso alla **compilazione**. Finché il `.pyc` è in cache non ricompare. Spostare
i sorgenti invalida `__pycache__` e lo fa riemergere.
**Fix.** Non è una regressione della tua patch. Risolto rendendo raw la docstring in
`tests/test_pty_backstops.py`; la suite cold non emette più il warning.

---

### Il retrieval di Sinapsi è lessicale: se le tue parole non sono le parole del codice, non trova
**Sintomo.** Chiedi *"which module owns the directory layout constants"* e il pack contiene cinque card di
`layout.tsx` di Next.js e zero costanti di `config.py`. `Seed rank: MISSED`.
**Causa.** I seed si ancorano ai **nomi**. La parola "layout" esiste nel repo — come `layout.tsx` — e batte
il commento `── Directory layout ──` di `config.py`. Nessuna parola della domanda somiglia a `PROMPTS_DIR`.
**Fix.** Leggi la riga `RELEVANCE` (Sinapsi ≥ 0.2.5): qui dice `weak` **e ha ragione**. Riformula con le
parole che l'autore avrebbe scritto, oppure cita un simbolo. Misurato con `sinapsi verify --expect`, stesso
grafo: `"…directory layout constants"` → `MISSED`; `"PROMPTS_DIR MEMORY_DIR layout constants owner"` → `#1`.
**Da evitare.** Leggere `COVERAGE: complete` come "il grafo ha risposto": è una garanzia sul *packer*
(il budget non ha tagliato), non sul *ranker*. Solo `RELEVANCE` parla del ranker.
**Aggravante.** Le fixture scaffoldate in `validation/stress/` (86 nodi) competono nel ranking e rubano i
seed su parole generiche — "layout", "root", "app". Vedi il debito #6 in `handoff.md`.
**Nota storica.** In 0.2.4 anche *"dove blocchiamo un comando che inventa un path assoluto"* mancava il
bersaglio. In 0.2.5 lo seeda al **#1**: il ranker è migliorato, il limite lessicale resta.

---

### Usare `query_graph` quando il nome lo conosci già
**Sintomo.** Paghi un pack ranked da ~2.300 token per sapere chi chiama una funzione.
**Causa.** `query_graph` è lessicale e approssimativo: serve a trovare la *regione*. Il blast radius non è un
problema di ranking, è una lettura di archi.
**Fix.** Con un nome esatto in mano usa `get_neighbors` (chi chiama / chi chiama chi, ~90 token, nessun
ranking che possa sbagliare) o `get_node` (dove vive). ~10× più economico, ed **esatto** anziché probabile.

---

### Init di framework: `TASK INCOMPLETE: workspace is empty` — deadlock mkdir-guard ⇄ replan
**Sintomo.** Un caso di `benchmarks/stress_frameworks.py` che scaffolda nella root (react, e per
estensione gli scaffold stile `npm create`: vue/svelte/angular/remix/tanstack/nextjs) finisce con
workspace **vuoto**, dopo 2-3 replan che ripropongono sempre "create directory". Misurato il 2026-07-14
**con l'oracolo 8B attivo** (quindi *non* è qualità del modello): react FAIL in 347s, 0 file.
**Causa.** Il planner mette in testa una **`mkdir` nuda** (`New-Item -Path "react"` dentro il workspace
`.../react`). Il guard [`recreates_the_workspace_dir`](../../workspace/src/tools/session.py) la rifiuta
**giustamente** (`exit 126`, "DIRECTORY NOT NEEDED — run the initializer here"). Ma l'orchestratore tratta
quel prerequisite MODIFY rifiutato come **fatale** → ferma il piano **prima** dello step di scaffold vero
(che sarebbe stato hoistato alla root da `orchestrator.hoist_nested_project`). Il replan rimette la mkdir
in testa perché la recovery riceve il generico *"workspace is empty"*, **non** il messaggio del guard.
Loop → INCOMPLETE. Confronto: `node_backend` **PASSA**, perché il suo piano non parte con una mkdir
(`npm init -y` + `echo > server.js` in loco) e il guard non scatta.
**Fix — RISOLTO 2026-07-14.** Il guard `recreates_the_workspace_dir` restituisce ora exit **0 (no-op
success)** invece di 126 (`session.py:417`): il prerequisite "crea la project dir" è già soddisfatto (il
workspace È la root), quindi non è un fallimento — il piano prosegue all'initializer e `workspace_shape`
hoista un eventuale annidamento. Coperto da `tests/test_workspace_dir_noop.py`. Era lo stesso `workspace is
empty` dei log storici di giugno (`p015-nextjs`, `p018`).

---

### La documentazione ordina di leggere file che non esistono
**Sintomo.** `AGENTS.md` elencava nove doc in `docs/` come reading order obbligatoria. `docs/` non esiste,
né in archivio. `brain/` era costruito su pointer verso quei file: 61 link rotti.
**Causa.** Il sistema di documentazione è stato sostituito (`.sinapsi/` + `brain/`) senza aggiornare
il contratto che lo governava. Nessun controllo automatico se ne è accorto.
**Fix.** I `.md` non descrivono più il runtime — l'owner è il codice. E i link si verificano: risolvere
ogni link relativo di ogni `.md` autoriale è un check che si esegue in un secondo.

---

### Un errore di rete verso l'oracolo crasha l'intero run (verdetto fantasma nel benchmark)
**Sintomo.** Un caso muore in planning con `ConnectionResetError [WinError 10054]`; verdetto `?`
(nessuna riga TASK emessa), contato come FAIL di *capacità* dell'agente quando è un guasto di *misura*.
**Causa.** `Provider._post` catturava solo `HTTPError`/`URLError`. Un reset di connessione avviene
durante la **lettura** del body (dopo che `urlopen` ha connesso) e sale come `OSError` grezzo — **non**
un `URLError` — quindi propagava non gestito fino al crash del processo. Aggravante: `_oracle()` fa
health-check-then-use (TOCTOU): l'oracolo passa il check, poi la chiamata reale viene resettata, e la
fallback "usa il 4B" copriva solo l'**assenza** dell'oracolo, non l'errore di rete a runtime.
**Fix.** `_post` normalizza `(OSError, http.client.HTTPException)` → `ProviderError` (unico boundary
HTTP). `model_router._complete` **degrada** un `ProviderError` proveniente dall'**oracolo** al 4B owned
(mai crash, mirror del path "assenza"); un `ProviderError` da un server *owned* resta un errore reale e
riemerge. Test `test_oracle_degradation.py` (riproduce il reset esatto). Inoltre `agent_eval` gira ora
**oracle-off** (self-contained) → il benchmark non dipende da un server esterno né mischia config.

---

### Init framework fallisce con `EPERM` su install globale (macchina non-admin)
**Sintomo.** react: `npm install -g vite@latest` → `EPERM mkdir C:\Program Files\nodejs\node_modules\vite`,
ripetuto su più replan; `package.json` mai creato → INCOMPLETE.
**Causa.** L'agente raggiunge un **install globale** (richiede admin) invece del runner **effimero**
(`npm create vite@latest` / `npx`), che non installa nulla. Su hardware modesto / non-admin — l'ambiente
target — l'install globale non può riuscire, e l'agente ci va in loop. Secondario: l'unico
`npm init vite@latest` lanciato in PTY ha **mis-navigato il menu `select`** e scelto `create-marko`
invece di react-ts.
**Fix.** APERTO — è il prossimo cluster di capacità reale, misurabile solo dopo il re-baseline pulito
(oracle-off). Direzione: preferire il runner effimero al global-install; robustezza del driver PTY sui
menu `select`. Non attribuire al modello prima di aver escluso queste due cause architetturali.

---

### Un test "unit" spawna un vero llama-server (mock di `_text_call` che non basta)
**Sintomo.** `test_pty_backstops` (11 test) passa da verde a `ProviderError: llama-server not found`
appena il path del binario diventa portabile/fail-loud invece di puntare a un file esterno che *esisteva*.
**Causa.** `_drive` mockava `mr._text_call`, ma il codice fa `_text_call(_nav(), ...)`: Python valuta
l'**argomento `_nav()` PRIMA** di chiamare `_text_call`, quindi il mock non lo intercetta e `_nav()` →
`ensure_ready()` → `_spawn()` gira davvero. Passava solo perché il binario Cowork esisteva su questa
macchina — un test **non ermetico**, verde per accidente d'ambiente.
**Fix.** Mocka anche il provider: `monkeypatch.setattr(mr, "_nav", lambda: None)`. Regola generale: se
mocchi `_text_call`/`_json_call`, mocca anche `_nav`/`_coder`/`_oracle` che compaiono come argomenti — o
il server viene spawnato. Un test che dipende da un server vivo o da un path di macchina non è riproducibile.

---

### `LLAMA_SERVER_BIN` risolto a un path esterno hardcoded (misura non portabile)
**Sintomo.** Il benchmark/agente gira solo su una macchina; su un clone fresco `_spawn` fallisce o (peggio)
punta a un file che non c'è.
**Causa.** `config.LLAMA_SERVER_BIN` faceva `env → path assoluto del checkout Cowork`. Un path
machine-specific nel sorgente versionato rende la misura non riproducibile.
**Fix.** `_resolve_llama_server_bin()`: env → `workspace/bin/` vendored → `shutil.which` → path vendored
inesistente (fail-loud che nomina dove metterlo). La config di macchina vive nell'**ambiente**
(`SISTEMISTA_LLAMA_SERVER_BIN`), non in `config.py`. Nota: l'`.exe` di llama.cpp è un launcher sottile che
carica le sue DLL dalla **stessa dir** → wherever lo metti, le DLL gli stanno accanto (`_spawn` usa
`cwd=parent`). Bootstrap in `workspace/bin/README.md` e `workspace/models/README.md`.


---

### Il trace del benchmark restava a 0 byte: `Orchestrator.run` rubava il trail all'harness
**Sintomo.** `var/benchmark/<label>/traces/T01.calls.jsonl` esiste ma è vuoto, mentre `var/trace/`
contiene un file con tutti gli eventi. Il ledger per-call che la suite esiste per produrre non c'è,
e `trace_stats` riporta zero call LLM.
**Causa.** `run_suite.py` chiama `trace.begin(t.id, trace_dir)`, poi `Orchestrator.run` chiama
`trace.begin(sysstate.run_id)` — e `begin()` era **last-wins**: riassegnava `_path` senza guardare
se un trail fosse già attivo. Ogni evento finiva nel secondo file, in silenzio.
**Fix.** `begin()` è **first-wins**: con un trail attivo rifiuta, lo dice su stderr, ed emette
`trace_begin_ignored` **nel trail attivo** — così il tentativo è visibile dove gli eventi sono
davvero andati. Regola generale: una risorsa globale con due proprietari legittimi ha bisogno di una
politica esplicita; "l'ultimo che scrive vince" non è una politica, è l'assenza di una.

---

### Due caratteri di prompt spostano 7 task su 48 (il floor di rumore, di nuovo)
**Sintomo.** Un braccio A/B misura 34/48 contro 40/48 del baseline e sembra una regressione netta.
**Causa.** Il braccio conteneva DUE modifiche: una patch al gate del coder e la rimozione di un
blocco morto dal prompt del supervisor (`memory.get_regressions()`, il cui scrittore era già morto,
restituiva la stringa vuota). Il prompt ha perso **due caratteri di a-capo** — e sotto decoding
greedy questo ri-tokenizza, cambia il piano, e cambia quali task passano. Replay del predicato
vecchio su tutti i comandi accettati: la patch al gate ha ribaltato **2 decisioni in tutta la
suite**, nessuna delle quali in un task regredito. Il gate era innocente.
**Fix.** Nessuno sul codice — la lezione è di metodo, ed è la stessa già registrata in
`test_benchmark_noise_floor.py`: **non mettere mai una modifica che tocca un prompt nello stesso
braccio della modifica sotto test.** E prima di attribuire una regressione, riesegui il predicato
vecchio sul ledger e conta quante decisioni sono davvero cambiate: è gratis e richiede secondi.

---

### Un artefatto vuoto con exit 0: l'output era andato su stderr
**Sintomo.** T40 fallisce in ogni run archiviata. Sette comandi, `exit 0` ogni volta,
`ssh_client.txt` da 0 byte. Il coder, informato che il comando è riuscito, ri-autorizza la stessa
redirezione all'infinito.
**Causa.** `ssh -V` (come `java -version`, `gcc --version` e una lunga coda) stampa su **stderr**;
`... > file` cattura solo stdout, quindi esce 0 e lascia il file vuoto.
**Fix.** `_stderr_only_output()` in `orchestrator.py`: exit 0 + target della redirezione vuoto +
redirezione del solo stdout ⇒ unisce gli stream e riprova. È una regola **sugli stream**, non su un
tool: nessun nome di eseguibile compare nel codice. Deterministica, provata prima dell'LLM nella
stessa posizione di `_extract_tool_suggestion`, e sostituisce una call al modello con uno `stat()`.

---

### `fileops:write tls_diag.txt` risolve a un path su drive `s` (T33, non ancora alla radice)
**Sintomo.** T33 fallisce in ogni run archiviata. Il confinement blocca correttamente un
`path outside the root` la cui radice è un drive di una sola lettera che non compare da nessuna
parte nel goal, nel workspace o nel comando visibile.
**Causa.** Non ancora stabilita. Il trace mostra il fileop già col path mangled; il launcher del
piano che lo ha prodotto è oltre il taglio a 1200 caratteri dell'`output` nel trace. Sospetto
**non verificato**: l'interazione fra la sostituzione di `$WORKSPACE_PATH` — che raddoppia i
backslash (`str(ws).replace` su ogni backslash) — e `Path()`, che su Windows interpreta una
lettera seguita da due punti come drive.
**Come procedere.** Il fingerprint del piano ora in traccia non basta: serve il launcher completo.
Riprodurre con `--ids T33` stampando il piano prima dell'esecuzione.
