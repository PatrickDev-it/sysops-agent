# 400 · Architecture — POINTER

> ⚠️ **Nodo pointer, non owner.** Qui **nessun contenuto tecnico**: solo rotte. Scrivere fatti
> architetturali qui = drift. Se sei tentato, scrivilo dove sta l'owner.
>
> L'owner non è più un doc. Struttura e comportamento sono di proprietà del **codice**: un `.md` che
> descrive il runtime diverge dal runtime e nessuno se ne accorge finché non lo legge. È già successo —
> vedi la nota storica in [AGENTS.md § Reading order](../../AGENTS.md#reading-order).

Gate ARCHITECTURE (VETO) → consulta:

| Cerchi… | Vai a |
|---|---|
| Invarianti (il set canonico) | [AGENTS.md § Invarianti core](../../AGENTS.md#invarianti-core) |
| Lifecycle, sequenze, forbidden states, decision matrix | [orchestrator.py](../../workspace/src/orchestrator.py) + i suoi test |
| Struttura: layout, componenti, data models, flag | [config.py](../../workspace/src/config.py) (owner del layout) · MCP `query_graph` per il resto |
| Sottosistema PTY | [terminal_runtime/](../../workspace/src/terminal_runtime/) |
| Perché (ADR) | [.sinapsi/decisions.md](../../.sinapsi/decisions.md) |

Regola del gate: se la patch viola un invariante → **STOP o RFC** ([.sinapsi/rfc/](../../.sinapsi/rfc/)).
