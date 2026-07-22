# Model weights (GGUF) — bootstrap

These files are **external artifacts**, not source: large, quantized, gitignored. A fresh clone
must place them here (`workspace/models/`) before the agent or the benchmark can run.

| Role | File | Size | Quant | Base model |
|---|---|---|---|---|
| NAV (orchestrator) | `Qwen3-4B-Q5_K_M.gguf` | ~2.9 GB | Q5_K_M | [Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF) |
| CODER | `Qwen2.5-CODER-3B-Q6_k.gguf` | ~2.8 GB | Q6_K | [Qwen2.5-Coder-3B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF) |

The filenames are load-bearing: `src/config.py` (`NAV_MODEL`, `CODER_MODEL`) expects these exact
names. Fetch them from the linked upstream Qwen repositories and place them here. Both upstream
model repositories declare Apache-2.0; model files remain external artifacts and are not covered
by this repository's release process.

Verify the downloaded file digest before use and record it with the validation result:

```powershell
Get-FileHash .\Qwen3-4B-Q5_K_M.gguf -Algorithm SHA256
Get-FileHash .\Qwen2.5-CODER-3B-Q6_k.gguf -Algorithm SHA256
```

`benchmarks/agent_eval.py` preflights their presence and fails with a pointer to this file if
either is missing, preventing a silent measurement of an incomplete environment.
