# Terminal taxonomy

osbench evaluates an agent that acts **exclusively through a terminal**. This document
enumerates the terminal-interaction surface a case can exercise, so an agent's PTY handling
(the subsystem in `src/terminal_runtime/`) is itself under test.

## Interaction modes

### 1. Non-interactive command execution
The default: the agent issues a command, reads stdout/stderr and the exit code, decides the
next action. Grading uses the resulting **state**, not the captured text.

### 2. Interactive / wizard prompts
Commands that prompt (`fdisk`, `visudo`, `crypttab` editors, `apt` conflict prompts,
`mysql_secure_installation`, Windows `diskpart`). The agent must detect the prompt and
respond correctly — or choose a non-interactive equivalent (`sed -i`, `--noconfirm`,
`DEBIAN_FRONTEND=noninteractive`). Cases tag whether an interactive path exists.

### 3. Long-running / streaming output
Rebuilds, `journalctl -f`, `iostat 1`, package upgrades. The agent must bound its reading
(not block forever), sample rather than slurp, and not let streaming output blow the context
budget (`context_efficiency`). Big-log cases explicitly reward streaming over loading.

### 4. TTY-sensitive behaviour
Programs that behave differently with/without a controlling TTY (`ssh -t`, `sudo`, color
output, pagers). "Works interactively, fails under the service manager" cases probe exactly
this — the service context lacks a TTY the interactive shell had.

### 5. Shell dialect
`bash` · `zsh` · `fish` · `dash` · `powershell` · `pwsh` · `cmd` · `wsl-bash`. Quoting,
word-splitting, arrays, `[[ ]]` vs `[ ]`, `$env:` vs `$`, path separators. Portability cases
penalize bashisms under `sh` and reward declaring the interpreter.

### 6. Cross-boundary (WSL, containers, remote)
Path translation (`wslpath`, `/mnt/c` ↔ `C:\`), interop PATH, `docker exec`, `kubectl exec`,
SSH/bastion hops. The agent must be explicit about *which* shell/host runs a command.

## Terminal hazards graded

| Hazard | What it tests | Failure |
|---|---|---|
| **hang on prompt** | detecting an interactive prompt | agent blocks; latency blows the budget |
| **swallowed exit code** | checking `$?`/`$LASTEXITCODE` not just output | false success on non-zero exit |
| **broken pipe / SIGPIPE** | handling a closed reader mid-stream | crash / partial result |
| **encoding / mojibake** | locale-correct decoding of output | misparsed values |
| **ANSI/control noise** | parsing values, not escape codes | wrong extraction (see invariant: pyte gets raw bytes) |
| **quoting injection** | safe quoting of paths with spaces/`$` | wrong target / accidental expansion |
| **pager trap** | avoiding `--no-pager`-less commands that block | hang |

## Alignment with the runtime PTY subsystem
The project's terminal stack (pyte `VirtualScreen`, `PromptDetector`, `Driver`,
`TerminalSession` — see `src/terminal_runtime/`) is the component that must survive these
hazards. osbench's interactive and streaming cases are the external check on it. Invariant
under test (project invariant #8): the screen model is fed **raw bytes with ANSI intact**,
never pre-decoded text — a case that extracts a value from colorized output verifies the
agent parsed the value, not the escape sequence.

## Scoring touchpoints
Terminal handling surfaces mainly in `latency` (hangs), `context_efficiency` (streaming
discipline), `command_efficiency` (avoiding retries from a mis-handled prompt), and
`reliability` (a TTY/dialect assumption that works once but not repeatably).
