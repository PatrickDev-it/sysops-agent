# Belief Analysis Report

> Template generato. Owner del formato: [belief-transition-model.md](../belief-transition-model.md).
> `provenance`: **RECONSTRUCTED** (corpus full-safe30). I belief-delta reali richiedono
> `debug_dump()` persistito per-step (parte del Prerequisito di osservabilità).

---

## Transizioni (aggregato corpus)

| `BeliefTransition` | Conteggio | Legittima? |
|--------------------|-----------|------------|
| ASSERT / PROVE / STRENGTHEN | {{n}} | ✅ |
| STICKY_BLOCK | {{n}} | ✅ (invariante #10 quando funziona) |
| **REDISCOVER** | **≥ 8 casi** | ❌ anti-pattern |
| PREMATURE_REFUTE | {{n}} | ❌ |
| SILENT_DROP | {{n}} | ❌ |

## Invarianti violati (`BeliefDefect`)

| `BeliefDefect` | Casi | Firma |
|----------------|------|-------|
| `NON_STICKY_PROVEN` | WIN-NETWORKING-001 (3×), WIN-FIREWALL, WIN-SCHEDULER, WIN-SERVICES-001/002, WIN-TLS-001, … | discovery ripetuta di X già PROVEN |
| `PREMATURE_REFUTE` | {{n}} | belief refutato poi ri-provato nello stesso run |
| `PHANTOM_DRIVE` | {{n}} | EXECUTE guidato da belief non-PROVEN |

## RAF decisionale

Ogni `NON_STICKY_PROVEN` è una discovery bruciata. Conteggio → stima `ΔRAF` del fix "belief sticky":

| Metrica | Valore corpus | Dopo fix (previsto) |
|---------|---------------|---------------------|
| RAF medio | ~2.11 | → ~1.3 (elimina i loop di rediscovery) |
| casi con ciclo DAG | 8 | → ~0 |

## Spiegazione (esempio, formato obbligatorio)

```jsonc
{
  "defect": "NON_STICKY_PROVEN",
  "belief": "get-nettcpconnection:exists",
  "at_decision": "WIN-NETWORKING-00001#d4",
  "expected_transition": "STICKY_BLOCK",
  "actual_transition": "REDISCOVER",
  "owner_component": "BELIEF",
  "evidence": ["3× DISCOVER 'Get-NetTCPConnection is available' @ steps 1,3,5"]
}
```

**Owner:** `BELIEF` ([reasoning.py::BeliefSystem](../../../workspace/src/reasoning.py)).
**Fix:** rendere `is_proven`/`refute` sticky (invariante #10) → vedi
[high-leverage-fixes.md](high-leverage-fixes.md#fix-2). È il secondo passo della roadmap dopo
l'osservabilità.
