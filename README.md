# Sistemista

Local-first, model-assisted system operations with deterministic execution controls,
verification predicates, recovery loops, and a redacted audit trail.

> **Status: public alpha (`0.1.0a1`).** Sistemista executes commands on the host. It is not
> production-ready, does not provide a security sandbox, and must not be run unattended or
> against untrusted objectives. Use an isolated disposable machine or VM.

[![CI](https://github.com/PatrickDev-it/sistemista/actions/workflows/ci.yml/badge.svg?branch=development)](https://github.com/PatrickDev-it/sistemista/actions/workflows/ci.yml)
[![Security](https://github.com/PatrickDev-it/sistemista/actions/workflows/security.yml/badge.svg?branch=development)](https://github.com/PatrickDev-it/sistemista/actions/workflows/security.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

## What it is

Sistemista is an experimental Python control plane around two locally hosted GGUF models:

| Role | Default artifact | Responsibility |
|---|---|---|
| Navigator | `Qwen3-4B-Q5_K_M.gguf` | planning, reasoning, verification, recovery |
| Coder | `Qwen2.5-CODER-3B-Q6_k.gguf` | bounded command and terminal-action authoring |

Models run in separate `llama-server` processes. An optional escalation oracle can be reached
over HTTP; it is disabled with `SISTEMISTA_ORACLE=0`. Remote oracle use sends redacted prompt
context outside the host and therefore changes the privacy boundary.

The runtime wraps model output with deterministic controls: workspace confinement, command
classification, typed success predicates, bounded recovery, credential redaction, audit events,
and distinct process exit codes.

## Current limitations

- Only goals classified `SAFE` reach planning; review-required, malformed, or unavailable
  classification fails closed before any command runs.
- The current policy is read-anywhere/write-workspace. Host package, service, registry, ACL,
  account, power, and process mutations are refused; there is no unconfined environment flag.
- Windows is the actively exercised platform. Unix paths exist but are not yet certified.
- Hardware capacity and throughput depend on the chosen quantization and llama.cpp backend;
  no minimum-VRAM or performance guarantee is made.
- Model weights and `llama-server` binaries are external artifacts and are not bundled.
- A successful run means declared verification predicates passed; it is not proof that every
  operational side effect was intended or complete.

## Quick start

Prerequisites:

- Python 3.12
- a compatible `llama-server` from [llama.cpp](https://github.com/ggml-org/llama.cpp)
- the two GGUF files named exactly as documented in
  [`workspace/models/README.md`](workspace/models/README.md)

```powershell
git clone https://github.com/PatrickDev-it/sistemista.git
cd sistemista
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e .
$env:SISTEMISTA_LLAMA_SERVER_BIN = "C:\path\to\llama-server.exe"
$env:SISTEMISTA_ORACLE = "0"
.\.venv\Scripts\sistemista "inspect disk pressure" --workspace C:\safe\disposable-workspace
```

On Unix-like hosts, activate `.venv/bin/activate` and use POSIX paths. This path is available
for development, not yet part of the certified support statement.

The process exits with `0` only for `COMPLETE`; `1` means incomplete, `2` refused, `3` runtime
error, and `130` operator interrupt.

## Configuration

The important environment variables are:

| Variable | Default | Purpose |
|---|---|---|
| `SISTEMISTA_LLAMA_SERVER_BIN` | repo binary or `PATH` | explicit llama-server executable |
| `SISTEMISTA_VAR_DIR` | `workspace/var` | relocatable runtime state root |
| `SISTEMISTA_NAV_PORT` | `8090` | navigator server port |
| `SISTEMISTA_CODER_PORT` | `8091` | coder server port |
| `SISTEMISTA_ORACLE` | `1` | enable optional escalation oracle |
| `SISTEMISTA_ORACLE_URL` | `http://127.0.0.1:8081` | oracle endpoint |
| `SISTEMISTA_ORACLE_TOKEN` | unset | bearer token required for a remote oracle |

Non-loopback oracle endpoints must use HTTPS and authentication. Runtime state, weights, and
binaries are ignored by Git.

## Architecture

```text
objective
   |
   v
preflight -> safety classification -> environment discovery
   |                                  |
   v                                  v
planner/navigation model -> typed plan -> deterministic command gates
                                              |
                                              v
                                      PTY/subprocess runtime
                                              |
                                              v
                                 predicates -> verify -> recover
                                              |
                                              v
                                  redacted trace + telemetry
```

Source is under `workspace/src`; hermetic regression tests are under `workspace/tests`;
benchmarks and their evidence are under `workspace/benchmarks` and `workspace/validation`.
Architecture decisions and publication gates are recorded in `.sinapsi/rfc`.

## Development

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\ruff check .
.\.venv\Scripts\ruff format --check .
.\.venv\Scripts\mypy
.\.venv\Scripts\pytest -q
.\.venv\Scripts\python -m build
```

CI runs lint, formatting, static typing, tests on Windows and Ubuntu, package builds, dependency
audit, and a full-history Gitleaks scan. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a
change.

## Branch and release policy

- `development`: integration branch and current public alpha.
- `validation`: candidates that have passed the secure-execution gate.
- `production`: release-only branch after every publication RFC is closed.

The repository being public does not imply production readiness. There is no stable release
until the validation evidence and release supply chain meet the promotion gate.

## Security and privacy

Read [SECURITY.md](SECURITY.md) before deployment or vulnerability reporting. Sistemista is
local-first, but an enabled remote oracle receives redacted operational context. Redaction is a
defense-in-depth control, not a guarantee that arbitrary sensitive content cannot leave the host.
Confinement is an application policy, not kernel isolation.

## License

Apache License 2.0. External model weights and llama.cpp retain their own licenses and are not
distributed by this repository; see [NOTICE](NOTICE).
