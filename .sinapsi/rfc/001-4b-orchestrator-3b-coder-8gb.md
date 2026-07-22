# RFC 001 — Target: orchestratore 4B owned + coder 3B, leggero per 8 GB (QLora + diskcache + offload)

> Stato: **target / direzione**, fissato dal developer il 2026-07-14. **Non ancora implementato né
> misurato.** Il glossario di `AGENTS.md` e `config.py` restano owner dello stato *attuale* — vanno
> aggiornati solo a implementazione avvenuta, non su questa RFC. Il lavoro abilitante (QLora + offload)
> è un "lavorone" e resta gated sui **test di falsificazione** in fondo: se uno fallisce, il target si
> rivede, non si forza.

## Context

La promessa di Sistemista è girare **agevolmente anche su una macchina da 8 GB di RAM**. La topologia
attuale non la mantiene ed è mista owned/prestato:

- **Owned oggi**: NAV `Qwen3-0.6B` (ragionamento d'azione, non scrive codice) + CODER
  `Qwen2.5-Coder-3B` (comandi shell).
- **Oracolo**: il modello grande del *parent* (`Qwen3-8B`) **preso in prestito via HTTP** per
  planning / verifica / recupero (`supervisor_call`/`verify_call`/`reflection_call` → `_oracle`).

Due conseguenze, misurate o note:

1. **Non è self-contained.** Senza il parent l'oracolo non c'è e i ruoli degradano al 0.6B. Misurato il
   2026-07-14: in degrado il 0.6B produce piani poveri (placeholder leak allo step 1 del caso react).
2. **Un 4B owned era già stato provato e rimosso.** `Qwen3.5-4B` aveva architettura **SSM** che rompeva
   il prefix cache (`cache_reuse is not supported`), dominando la latenza di step (vedi il docstring di
   `config.py`). La lezione era "architettura, non novità" — *non* "il 4B è troppo grosso".

## Proposal

Sostituire **sia** il NAV 0.6B **sia** l'oracolo 8B prestato con **un unico modello 4B owned**, lasciando
invariato il coder:

| Ruolo | Modello target | Compito |
|---|---|---|
| Orchestratore / general purpose | **`Qwen3-4B-Q5_K_M`** | planning, verifica, recupero **e** le *select options* interattive in terminale (navigazione PTY) |
| Coder | **`Qwen2.5-Coder-3B-Q6_K`** (invariato) | scrittura e riparazione di comandi shell / coding |

`Qwen3-4B` è **denso**, non SSM: quindi *a priori* non ricade nel difetto di prefix-cache che affossò
`Qwen3.5-4B`. Va **verificato** (test #1), non assunto.

Per farlo stare in 8 GB serve un **alleggerimento consistente** ("un lavorone"):
- **QLora** — uno strato adapter che riduce l'impronta di memoria, **accettando meno velocità / tok-s**
  in cambio di footprint.
- **diskcache** spinto + **offload** — appoggiare pesi/stato su disco anziché tenerli tutti in RAM.
- Trade-off **dichiarato e accettato**: più lento in tok/s, ma entra in 8 GB.

Effetto di sistema: Sistemista diventa **self-contained** (niente più modello del parent), il che chiude
il lato "oracolo prestato" del debito #1 dell'handoff (non self-contained).

## Alternatives

- **Tenere 0.6B + oracolo 8B prestato** — rifiutato: non self-contained; degrada male senza il parent.
- **Riusare `Qwen3.5-4B`** — rifiutato: SSM, rompe il prefix cache (già rimosso proprio per questo).
- **4B a piena precisione / quant alto senza QLora+offload** — rifiutato: non entra in 8 GB.
- **Un solo 3B che fa anche l'orchestratore** — fallback da tenere in tasca, ma un coder non è un buon
  pianificatore (in passato, chiedere navigazione al coder produsse un `CTRL_C` distruttivo — è la ragione
  per cui NAV e CODER furono separati). Il senso del 4B è proprio dare un *general purpose* vero.

## Decision

Direzione **adottata** dal developer: target = coder 3B + orchestratore 4B owned, alleggerito via
QLora + diskcache + offload per stare in 8 GB. L'implementazione è **gated** sui test di falsificazione
sotto.

## Consequences

**Cosa cambierà quando (e solo quando) implementato:**
- `config.py`: nuovo `Qwen3-4B-Q5_K_M` come orchestratore owned; NAV 0.6B rimosso e path oracolo prestato
  rimosso o declassato a opzionale. `config.py` resta l'owner unico dei path.
- Nuovo layer QLora + gestione offload/diskcache: codice **e stato** nuovi — vanno progettati per non
  violare l'invariante source/state (#15: lo stato di offload/cache vive in `var/`, mai in `src/`).
- `AGENTS.md` (glossario) e l'intro vanno riallineati **a implementazione avvenuta**, non prima.

**Prerequisiti / debiti abilitanti:**
- `Qwen3-4B-Q5_K_M` **non è ancora** sotto `models/` (oggi ci sono solo 0.6B e 3B; l'8B sta nel checkout
  Cowork). Va ottenuto/quantizzato.
- Il QLora + offload è la parte grossa e **non validata**.

**Il test che proverebbe sbagliato questo target (§5 — obbligatorio):**
1. **Prefix cache sopravvive.** Su `Qwen3-4B-Q5_K_M` in `llama-server`, una seconda call con prefisso
   condiviso deve dare `cache_n > 0` e **nessun** `cache_reuse is not supported`. Se il 4B non cachea la
   latenza esplode → target da rivedere (è esattamente ciò che uccise il 4B precedente).
2. **Footprint 8 GB reale.** Coder 3B + orchestratore 4B (QLora + offload) devono risiedere e girare su
   una macchina da **8 GB di RAM** senza swap patologico. Misura: RAM residente + tok/s. "Agevolmente" va
   reso una soglia numerica (es. latenza di un plan < X s, coder > Y tok/s) — altrimenti non è falsificabile.
3. **Qualità non sotto la baseline.** Sul benchmark riproducibile (`SISTEMISTA_DETERMINISTIC=1`) la
   combinazione 3B + 4B-QLora non deve scendere sotto lo scaffold-rate ottenuto con l'oracolo 8B. Se QLora
   costa più qualità di quanta RAM salvi, il target non regge.
4. **Latenza di offload nel budget.** Il rallentamento da offload/diskcache è accettato ma **limitato**:
   fissare un tetto oltre il quale l'esperienza "agevole" non tiene.

**Dipendenza dalla misura.** I test #2 e #3 non sono decidibili finché il debito "misura debole"
(handoff #3: un solo benchmark riproducibile, niente potenza statistica) non è chiuso. **La misura va
rinforzata prima di poter dichiarare raggiunto questo target**, non dopo.

---

## Aggiornamento 2026-07-14 — wiring implementato + prime misure (RTX 3070 Ti, 8 GB VRAM)

Il developer ha messo `Qwen3-4B-Q5_K_M.gguf` in `models/` e rimosso il `Qwen3-0.6B`. Wirato il target
(codice, verificato — vedi `session.md`):
- `config.NAV_MODEL` → `Qwen3-4B-Q5_K_M.gguf`; docstring/commenti di `nav_server_args` ripuliti dalle cifre
  del 0.6B (non rimpiazzate con numeri inventati).
- `model_router`: `_NAV` → `nav-4b`; il no-oracle non è più "degrado" ma il **default self-contained**;
  `supervisor_call` pianifica sul 4B quando l'oracolo manca. `main.py` + glossario `AGENTS.md` allineati.
- `_decide_select` (driver PTY) **NON toccato**: è deterministico per design (invariante #3). Le
  "select-options in terminale" gestite da un *modello* sono il ruolo NAV (`executor_pty_fallback_call`),
  che ora è il 4B — obiettivo raggiunto **senza** cablare un LLM nel driver.

**Test di falsificazione — prime misure (GPU pulita, baseline 991 MiB):**
1. **Prefix cache sul 4B denso → PASS.** Due call con prefisso condiviso: call2 `cache_n=387`, `prompt_n=6`,
   nessun `cache_reuse is not supported`. Il difetto SSM che uccise `Qwen3.5-4B` non si ripresenta.
   Decode ~58-89 t/s su GPU.
2. **Footprint su 8 GB di VRAM → PASS (meglio del previsto).** 4B **da solo** = 5220 MiB; **4B + coder 3B
   caricati insieme, entrambi healthy, coder inferisce (~40 t/s) = 7756 / 8192 MiB** (~436 MiB di margine).
   Il target **gira già su questa GPU 8 GB con la config full-offload attuale, nessun OOM.**
   > Errata: una prima misura dava 7778 MiB "per il solo 4B" → conclusione sbagliata ("co-residenza
   > impossibile"). Era contaminata da ~2.5 GB di un `llama-server` residuo. Rifatta su GPU pulita.
3. **Qualità vs baseline → primo dato NEGATIVO (single sample, non conclusivo).** Run end-to-end
   `node_backend` col 4B self-contained: **FAIL** in 46.8s (7× più veloce dell'oracolo 8B su CPU). Il piano
   era corretto, ma (a) il coder ha authored un comando malformato per `server.js` e (b) il **verify del 4B
   ha dichiarato COMPLETE** con l'artefatto entry mancante (falso positivo). Lo stesso caso **passava con
   l'oracolo 8B**. Direzione: il 4B self-contained è sotto la baseline 8B. Serve il rinforzo della misura
   (debito #3) per un giudizio con potenza statistica, e va indagato il verify-troppo-indulgente del 4B.
4. **Latenza** non ancora caratterizzata a soglia, ma il 4B su GPU è ~7× l'oracolo 8B-CPU (46.8s vs 348s).

**Ridefinizione dello scope, alla luce della misura.** Vanno distinti due target che prima erano confusi:
- **8 GB di VRAM (GPU)** → **già raggiunto**: 4B+3B stanno in 7756 MiB e girano veloci. Nessun QLora/offload
  necessario qui.
- **8 GB di RAM di sistema (macchina CPU-bound, GPU assente/piccola)** → è il caso **duro** per cui servono
  QLora + diskcache + offload. Questo resta il "lavorone" aperto della RFC; le misure sopra NON lo coprono.

Quindi: su GPU 8 GB il wiring è **fatto e verificato**. Il QLora/offload serve per la promessa "8 GB di RAM"
su hardware senza GPU adeguata — resta da costruire e misurare.
