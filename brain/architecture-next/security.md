# security.md

> Owner: **il modello Zero-Trust: ogni azione verificata, ogni side-effect classificato, ogni rischio con un punteggio.**
> È il Policy/Safety Engine (L2), gate obbligatorio prima di ogni azione.

---

## Principio: Zero-Trust sull'azione

Un agente sysops con privilegi è la superficie più pericolosa possibile: esegue comandi *come root* su sistemi reali.
Assunzione: **nessuna azione è fidata finché non è classificata e gated.** Non ci fidiamo né dell'utente (goal
ambiguo/avverso) né del modello (può allucinare un `rm -rf`).

## Risk vector (non un booleano)

Ogni azione riceve un **vettore di rischio**, non un sì/no:

```
RiskVector {
  reversibility:  REVERSIBLE | HARD | IRREVERSIBLE     # si può annullare?
  blast_radius:   FILE | SERVICE | HOST | FLEET         # quanto si estende?
  privilege:      USER | ROOT                           # che privilegi richiede?
  data_loss:      NONE | POSSIBLE | CERTAIN
  network:        NONE | EGRESS | INGRESS
  idempotent:     bool
}  → score → decision: ALLOW | CONFIRM | SANDBOX | REFUSE
```

Il punteggio deriva dal **Knowledge Graph** (ogni intento/comando ha effetti/reversibilità noti) + dal **World Model**
(blast radius reale: "questo servizio ha 3 dipendenti nel grafo" → alza il rischio). Non è un keyword-blacklist (che
v1 giustamente evitava): è un giudizio strutturato ancorato ai fatti.

## Le quattro decisioni

| Decisione | Quando | Azione |
|---|---|---|
| **ALLOW** | rischio basso, reversibile | esegui |
| **CONFIRM** | rischio medio/alto ma legittimo | mostra *cosa* e *perché* (dai Fact) → attende conferma |
| **SANDBOX** | tool non fidato / effetto incerto | esegui isolato, poi valuta |
| **REFUSE** | irreversibile + blast host/fleet + non giustificato | rifiuta, motiva (goal DESTRUCTIVE mai pianificato) |

## Sandbox degradabile (il nostro vantaggio)

- Dove disponibile: isolamento OS-native (namespaces/seccomp/landlock Linux, seatbelt macOS, job objects Windows) —
  ispirato a [Codex](../research/competitors/codex-cli.md) ma **non OS-hard-coded**: astratto per capability.
- Concetto capability-based (WASM) preso da [IronClaw](../research/competitors/ironclaw.md), ma **senza il suo peso**
  (niente Postgres/Node obbligatori).
- **Degradabile:** su una VPS nuda senza sandbox forte, si degrada a CONFIRM + dry-run + rollback. **Funziona
  comunque**, con più cautela. È il moat: sicurezza *anche dove non c'è infrastruttura*.

## Secret hygiene

L'LLM **non vede mai i segreti** (chiavi, password): vivono in un vault fuori dal belief state; le azioni li
referenziano per handle, il runtime li inietta al momento dell'esecuzione. (Principio da IronClaw, generalizzato.)

## Dry-run e simulazione

Per azioni IRREVERSIBLE, quando il tool lo supporta (`--dry-run`, `-n`, `terraform plan`), si simula *prima* e si
mostra il diff previsto. Dove non supportato, si costruisce la reversibilità (snapshot/backup) o si richiede CONFIRM.

## Confronto competitor

| | Gate rischio | Sandbox | Secret isolation | Degradabile |
|---|---|---|---|---|
| **Sistemista v2** | risk vector ancorato ai Fact | OS-native astratta | sì | **sì** |
| Codex | approval modes | OS-native | parziale | no (cloud) |
| IronClaw (concept) | — | WASM (pesante) | sì | **no** |
| Goose/Cline/Aider | HITL manuale | ❌ | ❌ | — |

## Pattern

Zero-Trust · Policy engine · Capability-based security · Risk scoring (vettoriale) · Dry-run/simulation ·
Principle of least privilege · Compensating transactions (rollback).

## Alternative scartate

- **Keyword blacklist:** fragile, falsi positivi/negativi. **Rifiutato** — giudizio strutturato.
- **Fidarsi del modello ("chiedigli se è pericoloso"):** un modello allucinante non è un controllo di sicurezza.
  **Rifiutato** — il gate è deterministico sul risk vector, il modello al più *propone*.
- **Sandbox obbligatoria pesante (IronClaw):** esclude le VPS nude, il nostro caso d'uso primario. **Rifiutato** —
  degradabile.

## Trade-off / Benchmark / Evoluzioni

Trade-off: CONFIRM troppo frequente uccide l'autonomia; troppo raro è pericoloso → calibrazione della soglia dal
rischio reale (blast dal World Model). Benchmark: zero azioni IRREVERSIBLE non gated; % di CONFIRM appropriati.
Evoluzioni: policy-as-data per-organizzazione, attestazione delle azioni (audit firmato), rilevamento prompt-injection
dal contenuto di file/output non fidati.
