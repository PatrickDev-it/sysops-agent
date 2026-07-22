# reports/

Generated output — safe to delete and regenerate. Not hand-edited.

- `scorecard_<label>.md` / `.json` — a single agent's run over a selected subset, produced
  by `benchmarks.osbench.run` (or `scoring.report.write_report`). Includes the 11-metric
  breakdown, per-difficulty and per-OS rollups, and the weakest domains by ARR.
- No leaderboard is published. The one that used to live here compared against agents
  that were never run; it is quarantined, with the arithmetic that proves it, in
  `_attic/osbench-synthetic-leaderboard/`. A comparison across agents, produced by
  `scoring.report.write_comparison({agent: scorecard, ...})`.

To (re)generate a demo:

```bash
python -m benchmarks.osbench.run --adapter dry --golden --label demo_golden
```

For a real evaluation, implement an `AgentAdapter` (see `run.py`) that shells into the
agent CLI under test, then run the same subset through each competitor and pass the
resulting scorecards to `write_comparison`.

---

## Come leggere questi file

Ogni scorecard dichiara la propria provenienza: `adapter`, `executed`, `is_measurement`.
Il prefisso `STUB_` nel nome del file significa che **non è stata eseguita alcuna cosa**:
i numeri valutano una trascrizione fittizia, non l'agente. Tutti e tre gli scorecard
attualmente presenti sono STUB, prodotti dall'adapter `dry` (16, 20 e 40 casi;
overall 0.705, 0.534, 0.580). L'adapter `live` esiste e non è mai stato eseguito.

Una misura senza il denominatore non è una misura.
