# Competitive Intelligence — Index

> **Owner:** competitive intelligence knowledge base. Da rileggere **prima di ogni decisione architetturale
> importante** (gate MARKET del [../../BRAIN.md](../../BRAIN.md)).
> **Fonti:** due Deep Research interni (uno sugli *agenti da terminale*, uno sui *progetti OSS virali*), ora
> **rimossi** e consolidati integralmente in questa KB — ogni scheda è self-contained.
> **Nota metodologica (leggere prima dei numeri):** quei Deep Research erano generati da AI e contenevano dati
> dubbi o allucinati. Ogni scheda ha un box **affidabilità**. I punteggi sotto sono una **valutazione
> ingegneristica propria** (1–5), non estratti dai report; per i progetti non verificati sono *sospesi*.

---

## 1. Mappa dei competitor

```
                        AGENTI DA TERMINALE (competitor diretti/indiretti)
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  Cloud-brand CLI        Local-first / OSS         IDE-centric            │
   │  ─ Gemini CLI (Google)  ─ Goose (Block) ★vicino   ─ Cline (VS Code)      │
   │  ─ Codex CLI (OpenAI)   ─ Aider (git-native)      ─ Continue (IDE→CLI)   │
   │                         ─ OpenHands (platform)                            │
   │  Non verificati 🔴: Mistral Vibe · IronClaw                              │
   └─────────────────────────────────────────────────────────────────────────┘
                        FRONTIERA (NON agenti → case study di crescita)
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  Agente consumer 🔴: OpenClaw   │  Framework: LangChain (AI design)      │
   │  Modelli ML (N/A agent): SAM · Stable Diffusion · AlphaFold · YOLO       │
   └─────────────────────────────────────────────────────────────────────────┘
   ★ = Sistemista compete più direttamente qui (local-first, terminal, autonomo)
```

**Legenda affidabilità:** ✅ verificabile · ⚠️ report impreciso (corretto nella scheda) · 🔴 non verificato/probabile allucinazione.

| Progetto | Scheda | Categoria | Affidabilità | Competitor? |
|---|---|---|---|---|
| Gemini CLI | [gemini-cli.md](gemini-cli.md) | Cloud CLI | ⚠️ | diretto |
| Codex CLI | [codex-cli.md](codex-cli.md) | Cloud CLI | ⚠️ | diretto |
| Goose | [goose.md](goose.md) | Local-first CLI | ⚠️ | **diretto (il più vicino)** |
| OpenHands | [openhands.md](openhands.md) | Dev-agent platform | ⚠️ | diretto (pesante) |
| OpenDevin | [opendevin.md](opendevin.md) | = OpenHands (ex nome) | — | pointer |
| Cline | [cline.md](cline.md) | IDE agent | ⚠️ | indiretto (IDE) |
| Aider | [aider.md](aider.md) | git-native CLI | ✅ | indiretto (repo) |
| Continue | [continue.md](continue.md) | IDE→CLI | ⚠️ | indiretto |
| Mistral Vibe | [mistral-vibe.md](mistral-vibe.md) | CLI agent | 🔴 | ignoto |
| IronClaw | [ironclaw.md](ironclaw.md) | "Agent OS" | 🔴 | ignoto |
| OpenClaw | [openclaw.md](openclaw.md) | Consumer agent | 🔴 | indiretto |
| LangChain | [langchain.md](langchain.md) | LLM framework | ✅ | indiretto |
| SAM | [segment-anything.md](segment-anything.md) | CV model | ✅ | no (case study) |
| Stable Diffusion | [stable-diffusion.md](stable-diffusion.md) | GenAI model | ✅ | no (case study) |
| AlphaFold | [alphafold.md](alphafold.md) | Sci model | ✅ | no (case study) |
| YOLO | [yolo-ultralytics.md](yolo-ultralytics.md) | CV model | ✅ | no (case study) |

---

## 2. Tabella comparativa (agenti da terminale)

| | Lingua | Licenza | Modello | Locale/Offline | Autonomia | Sandbox | Estendibilità | Focus |
|---|---|---|---|---|---|---|---|---|
| **Gemini CLI** | TS/Node | Apache-2.0 | Gemini (cloud) | ❌ | media | opzionale | MCP | coding |
| **Codex CLI** | Rust | Apache-2.0 | OpenAI (cloud) | ❌ | calibrabile | **OS-native** | MCP | coding |
| **Goose** | Rust | Apache-2.0 | multi | ✅ | alta | ⚠️ debole | **MCP ricco** | generalista |
| **OpenHands** | Py+TS | MIT | multi | ⚙️ (Docker) | alta | **Docker** | agent/runtime | dev end-to-end |
| **Cline** | TS | Apache-2.0 | multi | ⚙️ (IDE) | bassa (HITL) | ❌ | MCP | coding IDE |
| **Aider** | Python | Apache-2.0 | multi | ⚙️ | bassa | ❌ (git) | limitata | editing repo |
| **Continue** | TS | Apache-2.0 | multi | ⚙️ | media | ❌ | context-providers | assist IDE |
| 🔴 Mistral Vibe | Python | Apache-2.0? | Mistral | ? | ? | Docker? | skills? | coding |
| 🔴 IronClaw | Rust | Apache-2.0? | multi | ✅? | alta? | **WASM** | MCP? | secure agent |
| **→ Sistemista** | Python | *(interna)* | **GGUF locale** | **✅** | **alta+causale** | OCKE/PTY | *(MCP futuro)* | **sysops** |

HITL = human-in-the-loop. ⚙️ = locale ma legato a IDE/Docker/repo.

---

## 3. Matrici di valutazione (1–5; 🔴 = sospeso, dati non verificabili)

> Le matrici sono i "radar" in forma tabellare (dati confrontabili). Valutazione ingegneristica propria.

### 3.1 Architettura

| | Loop/Planner | Executor | Memory | Context eng. | Modularità | Media |
|---|---|---|---|---|---|---|
| Gemini CLI | 3 | 3 | 2 | 3 | 3 | 2.8 |
| Codex CLI | 4 | 4 | 2 | 3 | 4 | 3.4 |
| Goose | 4 | 4 | 3 | 4 | **5** | **4.0** |
| OpenHands | **5** | **5** | 4 | 4 | 4 | **4.4** |
| Cline | 4 | 4 | 3 | 3 | 3 | 3.4 |
| Aider | 3 | 4 | 2 | **5** | 3 | 3.4 |
| Continue | 3 | 3 | 3 | 4 | 4 | 3.4 |
| **Sistemista** | **5** (causale) | 4 | 4 (belief/episodic) | 3 (da potenziare) | 4 | **4.0** |

### 3.2 AI Design

| | Planning | Recovery | Self-correction | Tool selection | Long context | Media |
|---|---|---|---|---|---|---|
| Gemini CLI | 3 | 3 | 3 | 3 | **5** | 3.4 |
| Codex CLI | 4 | 4 | 4 | 4 | 4 | 4.0 |
| Goose | 3 | 2 | 3 | 4 | 4 | 3.2 |
| OpenHands | 4 | 4 | **5** | **5** | 4 | **4.4** |
| Cline | 4 | 3 | 4 | 4 | 3 | 3.6 |
| Aider | 3 | 4 | 4 | 3 | 3 | 3.4 |
| **Sistemista** | **5** (belief PROVEN) | **5** (error_classifier) | 4 | 3 | 3 | **4.0** |

### 3.3 UX

| | CLI/TUI | Streaming | Trasparenza | Error UX | Recovery UX | Media |
|---|---|---|---|---|---|---|
| Gemini CLI | 4 | 4 | 3 | 3 | 3 | 3.4 |
| Codex CLI | 4 | 4 | 4 | 4 | 4 | 4.0 |
| Goose | 4 | 4 | 4 | 4 | 3 | 3.8 |
| OpenHands | 3 | 4 | 4 | 4 | 4 | 3.8 |
| Cline | **5** | **5** | **5** | 4 | **5** | **4.8** |
| Aider | 4 | 3 | 4 | 4 | 4 | 3.8 |
| **Sistemista** | 3 | 3 | 4 (mostra il piano) | 4 (artifact) | 4 | 3.6 |

### 3.4 Security

| | Sandbox | Command exec | Secrets | Permissions | Media |
|---|---|---|---|---|---|
| Gemini CLI | 3 | 3 | 3 | 2 | 2.8 |
| Codex CLI | **5** (seatbelt/landlock) | **5** | 4 | **5** (approval) | **4.8** |
| Goose | 2 | 2 | 3 | 2 | 2.2 |
| OpenHands | 4 (Docker) | 4 | 3 | 3 | 3.5 |
| Cline | 3 (HITL) | 3 | 3 | 4 | 3.2 |
| Aider | 3 (git) | 3 | 3 | 3 | 3.0 |
| 🔴 IronClaw | 5 (WASM)? | 5? | 5? | 5? | *sospeso* |
| **Sistemista** | 3 (no sandbox forte) | 4 (safety_gate) | 3 | 4 (no-overwrite) | 3.5 |

### 3.5 Performance / Scalabilità / Modularità / Estendibilità / Community / Business (sintesi)

| | Performance | Scalabilità | Modularità | Estendibilità | Community | Business/Backing |
|---|---|---|---|---|---|---|
| Gemini CLI | 4 | 4 | 3 | 3 (MCP) | 4 | **5** (Google) |
| Codex CLI | **5** (Rust) | 4 | 4 | 3 (MCP) | 4 | **5** (OpenAI) |
| Goose | 4 | 3 | **5** | **5** (MCP) | 4 | 4 (Block) |
| OpenHands | 2 (Docker) | 4 | 4 | 4 | **5** | 4 (All Hands) |
| Cline | 3 | 3 | 3 | 4 (MCP) | **5** | 3 |
| Aider | 4 | 2 | 3 | 2 | 4 | 2 (indie) |
| Continue | 3 | 3 | 4 | 4 | 3 | 3 (VC) |
| **Sistemista** | 4 (locale) | 3 | 4 | 2 (da costruire) | 1 (early) | 1 (early) |

---

## 4. Radar — Punti di forza / Debolezze (sintesi qualitativa)

**Radar punti di forza** (dove ciascuno eccelle):
- **Gemini CLI** → long context, free tier, brand.
- **Codex CLI** → **sicurezza dell'esecuzione** (sandbox OS-native), approval modes, Rust.
- **Goose** → **modularità/estendibilità MCP**, local-first, multi-provider.
- **OpenHands** → **potenza & osservabilità** (event stream, CodeAct), benchmark.
- **Cline** → **UX & trasparenza** (plan/act, diff, checkpoint).
- **Aider** → **context engineering** (repo-map), edit-format affidabile, git.
- **Sistemista** → **reasoning causale ispezionabile + verifica per artifact + sysops + offline**.

**Radar debolezze** (il tallone d'Achille di ciascuno):
- Gemini CLI / Codex CLI → **dipendenza cloud, no offline, lock-in**.
- Goose → **recovery debole (delegata all'LLM), sicurezza esecuzione**.
- OpenHands → **peso/complessità, Docker obbligatorio, scope dilatato**.
- Cline → **legato all'IDE, HITL obbligatorio (poca autonomia)**.
- Aider → **poca autonomia, solo repo**.
- Continue → **identità sfumata, IDE-centrico**.
- **Sistemista** → **community/ecosistema/estendibilità ancora acerbi** (vedi §7).

---

## 5. Ranking

> Solo agenti **verificabili** (esclusi 🔴 non verificati e i non-agenti). Scala 1–5, valutazione propria.
> Sistemista incluso come benchmark interno.

| Ranking | 1° | 2° | 3° | 4° | 5° |
|---|---|---|---|---|---|
| **Complessivo** | OpenHands | Codex CLI | Goose | Cline | Aider |
| **Engineering** | Codex CLI (Rust) | OpenHands | Goose | Cline | Aider |
| **AI design** | OpenHands | Codex CLI | **Sistemista** (reasoning) | Cline | Aider |
| **UX** | **Cline** | Codex CLI | Goose/Aider | OpenHands | Gemini CLI |
| **Architettura** | OpenHands | Goose/**Sistemista** | Codex CLI | Aider/Cline/Continue | Gemini CLI |
| **Innovazione** | OpenHands (CodeAct) | Aider (repo-map) | **Sistemista** (causale) | Codex (sandbox) | Cline (plan/act) |
| **Qualità codice** | Codex CLI | OpenHands | Goose | Aider | Continue |
| **Potenziale futuro** | OpenHands | Goose | Codex CLI | **Sistemista** (se cresce ecosistema) | Cline |

> **Lettura strategica:** Sistemista **non** compete su maturità/ecosistema/UX (siamo early). Compete e **vince**
> su **AI design (reasoning causale)** e sul verticale **sysops offline** — dove nessuno dei leader è focalizzato.
> Il nostro compito non è battere OpenHands sul suo terreno, ma **occupare il terreno che nessuno presidia** (§7).

---

## 6. Matrice feature (chi ha cosa)

| Feature | Gemini | Codex | Goose | OpenHands | Cline | Aider | Sistemista |
|---|---|---|---|---|---|---|---|
| Offline / no-cloud reasoning | ❌ | ❌ | ✅ | ⚙️ | ⚙️ | ⚙️ | **✅** |
| Provider-neutral | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | **✅ (GGUF)** |
| Reasoning ispezionabile (belief) | ❌ | ❌ | ❌ | ~ | ❌ | ❌ | **✅** |
| Recovery vincolata dall'errore | ~ | ~ | ❌ | ~ | ~ | ✅ | **✅** |
| Verifica per artifact | ❌ | ~ | ❌ | ~ | ❌ | ~ (test) | **✅** |
| Sandbox esecuzione forte | ~ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ (gap) |
| Estendibilità MCP | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ (gap) |
| Context engineering (repo/sys-map) | ~ | ~ | ~ | ✅ | ~ | **✅** | ~ (gap) |
| Focus sysops (deps/PATH/env/OS) | ❌ | ❌ | ~ | ~ | ❌ | ❌ | **✅** |
| Framework/OS-neutrality disciplinata | ❌ | ~ | ❌ | ❌ | ❌ | ❌ | **✅ (OCKE)** |
| PTY per wizard interattivi | ❌ | ~ | ~ | ~ | ~ | ❌ | **✅ (pyte)** |
| Gira su VPS nuda (no Docker/IDE) | ~ | ✅ | ✅ | ❌ | ❌ | ✅ | **✅** |

Legenda: ✅ presente · ~ parziale/implicito · ❌ assente · ⚙️ condizionato (IDE/Docker/repo).

---

## 7. Opportunità di mercato inesplorate (dove nessuno è forte)

Sintesi trasversale a tutte le schede — **questi sono i white space da presidiare**:

1. **Sysops autonomo offline** — tutti i leader sono coding-agent cloud-dipendenti. Nessuno è un agente
   *sysadmin* locale che ripara deps/PATH/env/servizi su una macchina nuda. **← nostra posizione primaria.**
2. **Reasoning causale ispezionabile con modelli piccoli** — Goose/Cline/OpenHands delegano la qualità all'LLM;
   con 3B/4B degradano a trial-and-error. Un belief system che rende affidabili i modelli piccoli è un moat.
3. **Sicurezza *forte + leggera*** — Codex ha sandbox ma cloud-locked; IronClaw (se reale) ha WASM ma pesantissimo.
   Manca: sandbox capability-based **leggera**, senza Docker/Postgres, che gira sul sistema target.
4. **Verifica per artifact come standard** — quasi nessuno dichiara "fatto" solo se i file esistono su disco.
5. **Neutralità OS/framework disciplinata** — tutti accumulano casi speciali; la nostra OCKE è differenziante.
6. **Context engineering per sysops** — Aider ha il repo-map per il codice; **nessuno ha un *system-map* rankato**
   (capabilities/entità dell'OS) → opportunità diretta (potenzia DISCOVERY, mitiga Issue #8).

---

## 8. Gap di copertura della KB (da ricercare, NON nei report)

Progetti citati nella richiesta ma **assenti dai due report** → schede da creare quando esisterà una fonte reale
(non fabbricare da memoria — ethos "non inventa, confronta"):

- **Claude Code** (Anthropic) — agentic CLI, permission model, skills/MCP. *Rilevante: benchmark UX/tool-use.*
- **Cursor** — IDE AI-first. *Rilevante: UX/context.*
- **Devin** (Cognition) — agente autonomo proprietario (OpenHands ne è la risposta open).
- **SWE-agent / Agentless** (Princeton/ricerca) — ACI, approcci SWE-bench. *Rilevante: AI design.*
- **Warp** — terminale AI. *Rilevante: terminal UX.*
- **Roo Code** (fork di Cline), **Crush** (Charm), **AmpCode** — da verificare.

> Azione: aprire un mini-RFC o issue per popolare questi con fonti verificate. Finché non ci sono fonti,
> restano *gap noti*, non schede inventate.

---

## 9. Come usare questa KB (protocollo)

Prima di una decisione architetturale importante, il gate MARKET del [../../BRAIN.md](../../BRAIN.md) impone:

1. La capability che stai per costruire è già fatta meglio da qualcuno? → leggi la sua scheda (§1).
2. Stai **copiando** una loro scelta? → controlla il "**Cosa NON copiare**" della scheda. Motiva la divergenza.
3. C'è un'idea brillante da importare? → "**Cosa vale la pena copiare**" (spesso: Aider repo-map, OpenHands
   event-stream, Codex approval/sandbox, Cline plan/act-trasparenza).
4. La decisione aumenta un moat o presidia un white space (§7)? Se solo pareggia un leader sul *suo* terreno → deprioritizza.

> **Regola aurea:** non inseguire i leader dove sono forti. **Presidiare i white space del §7.**
> E ricordare sempre il box **affidabilità** di ogni scheda: molti "fatti" dei report sono claim non verificati.
