# system-map.md

> Owner: **il World Model — il grafo interrogabile del sistema *reale*.** È il "beyond Aider" della tesi.
> L'ontologia astratta (cosa *può* esistere su un OS) è nel [knowledge-graph.md](knowledge-graph.md); qui c'è
> *questo* sistema, ora.

---

## Il salto concettuale

[Aider](../research/competitors/aider.md) ha dimostrato che il collo di bottiglia degli LLM è il **contesto**, e
che una **mappa rankata del repo** batte il caricare tutto. Ma un repo di codice è *statico e testuale*. Un
**sistema** è *vivo, strutturato, causale*: processi, servizi, socket, pacchetti, mount, cron, utenti, container.
Il nostro World Model è un **grafo delle proprietà** del sistema, non un repo-map:

```
        ┌─────────┐  listens_on   ┌────────┐  provided_by  ┌──────────┐
        │ Service │──────────────►│  Port  │               │ Package  │
        │ nginx   │◄───────┐      │ :443   │               │ nginx    │
        └────┬────┘  configured_by│       └────────┘        └────┬─────┘
             │ runs_as            │                              │ depends_on
        ┌────▼────┐          ┌────▼─────┐  mounted_at      ┌─────▼─────┐
        │  User   │          │  Config  │                  │  Package  │
        │ www-data│          │ nginx.conf│                 │ openssl   │
        └─────────┘          └──────────┘                  └───────────┘
   Nodi: Host · Process · Service · Port · Package · Container · Volume · Mount · User · Group ·
         Cron · Config · Log · Interface · Route · File · Capability · EnvVar
   Archi: depends_on · listens_on · configured_by · mounted_at · owned_by · runs_as · exposes ·
          child_of · reads · writes · requires_capability
```

## Interrogabile (il punto)

Il modello **non vede mai il grafo intero**. Emette (o il Context Engine deriva) una **query** che ritorna un
**sottografo minimo** rilevante al goal:

```
map.query("service:nginx", depth=2)          → nginx + ports + config + deps + user
map.neighbors("port:443")                     → chi ascolta, quale processo, quale servizio
map.path("service:nginx" -> "package:openssl")→ catena di dipendenza (per diagnosi SSL)
map.unknowns(goal)                            → cosa NON è ancora mappato ma serve al goal (guida il Mapper)
```

Storage: **grafo persistente locale** (SQLite come backing store + un layer grafo in RAM; niente server esterni —
vincolo 16GB/VPS nuda). Query = ranking per rilevanza (distanza dal focus del goal + confidence + freschezza).

## Come si popola: lazy, guidato dal goal

Il **System Mapper** (L1) esegue **probe deterministici** (nessun LLM) *solo* per i nodi che il goal richiede:
```
goal "il sito è down" → probe: ss -ltnp (port) · systemctl status nginx · journalctl -u nginx --since
→ Fact tipizzati → nodi/archi nel World Model. Mai un "full scan" del sistema.
```
Probe come **capability-based**, portabili: astrazione `probe(service|port|package|…)` con adapter per-OS
(systemd/launchd/sc.exe; apt/dnf/brew/choco). L'adapter è dietro una porta (hexagonal) → il core non sa quale OS.

## Perché batte tutti

| | Sistemista v2 | Aider | Goose/Cline/OpenHands |
|---|---|---|---|
| Oggetto mappato | sistema vivo | repo di codice | nulla di persistente |
| Struttura | grafo tipizzato | ranking di file | history testuale |
| Interrogabile | sì (sottografi) | sì (repo-map) | no |
| Freschezza | TTL, ri-probe | statico | — |
| Contesto derivato | sì (minimo) | sì | no (prompt cresce) |

## Pattern

Property graph · Knowledge representation · Lazy/incremental materialization · CQRS (scrittura via Mapper, lettura
via query) · Adapter per-OS (hexagonal) · Focus+context (mappa ampia, contesto stretto).

## Alternative scartate

- **Full system scan all'avvio:** lento, costoso, invecchia subito, mappa il 99% irrilevante. **Rifiutato**: lazy per-goal.
- **RAG su testo di output dei comandi (vector store):** perde struttura e relazioni; recupera "testo simile" non
  "vicino causale". **Rifiutato**: un grafo causale è superiore per il sysops.
- **Riusare un CMDB esterno:** dipendenza pesante, non degradabile su VPS nuda. Possibile *fonte* opzionale, non il core.

## Trade-off

- Un grafo richiede schema + adapter per-OS = investimento. Ripagato: è **il** moltiplicatore di token-efficiency e
  la base per fleet/knowledge federati.
- Probe = effetti collaterali minimi (comandi read-only) → classificati SAFE dal Policy Engine, ma vanno comunque gated.

## Benchmark teorico

Contesto per una diagnosi tipica: un sottografo di ~10–30 nodi (~200–600 token) vs dump di `systemctl`/`journalctl`
(~5k–50k token). **~1–2 ordini di grandezza** di risparmio, che è ciò che rende fattibile un 4B locale.

## Evoluzioni

Fonti di fatti esterne come *adapter* (Prometheus, journald, /proc, WMI, cloud API) · World Model federato multi-host
(fleet) · diffing temporale ("cosa è cambiato dall'ultimo incidente?") · inferenza di archi mancanti dal Knowledge Graph.
