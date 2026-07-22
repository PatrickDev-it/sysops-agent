"""Runtime configuration — model paths, llama-server flags, sampler presets.

Sistemista is a SUBAGENT: it is spawned by an agent that already owns a large model.
It therefore owns only two small, fast, execution-tier models and *borrows* the parent's
big model as an escalation oracle over HTTP. Three consequences shape this file:

  1. No model is loaded in-process. Each owned model lives in a supervised `llama-server`
     (see `llm_backend.py`), spoken to over the native `/completion` endpoint. This is what
     unlocks prefix caching, GBNF-constrained decoding and per-process lifecycle — none of
     which llama-cpp-python gave us. The CUDA DLL bootstrap that used to live here is gone:
     loading CUDA is llama-server's problem now.
  2. The models are DENSE (standard attention). A hybrid SSM/linear-attention GGUF (arch
     `qwen35`, keys `*.ssm.*`) cannot rewind its recurrent state, so llama-server answers
     `cache_reuse is not supported by this context` and every call re-prefills the whole
     fixed instruction block. Measured on the previous `Qwen3.5-4B`: that alone dominated
     step latency. "Newer" is not a criterion — architecture is.
  3. Every flag below was measured on the target box (RTX 3070 Ti 8 GB, ~448 GB/s), not
     guessed. The governing fact is that decode is memory-bandwidth-bound: tok/s ≈
     bandwidth / model_size. See the block comments on each preset.
"""

import ipaddress
import os
import shutil
import urllib.parse
from pathlib import Path

# ── Directory layout — single owner of this invariant ────────────────────────
# A directory is either SOURCE (versioned, read-only at runtime) or STATE (written at
# runtime, disposable). The two never mix, and nothing under `src/` is ever written to:
# a package that mutates itself cannot be reinstalled, cached, or reasoned about. The
# state that used to live in `src/runtime/` — and beside the read-only knowledge base,
# under `knowledge/memory/` — now has one home, `var/`, which can be deleted whole
# without losing anything the repo owns. Every path below is derived here and imported;
# no other module recomputes the layout from `__file__`.
SRC = Path(__file__).resolve().parent  # source tree
ROOT = SRC.parent  # workspace/

# All runtime state hangs off ONE relocatable root. SISTEMISTA_VAR_DIR moves the whole tree,
# which is what a benchmark, a CI job or a second concurrent agent needs: previously every
# process on the machine shared `workspace/var`, so `benchmarks/agent_eval.py` — which spawns
# `src.main` as a subprocess — ran against the operator's episodic memory, and
# `Orchestrator.run` wipes the event table on startup. One knob, because state that can be
# relocated per-directory is state with several owners.
VAR = Path(os.environ.get("SISTEMISTA_VAR_DIR") or (ROOT / "var")).resolve()


class ConfigError(RuntimeError):
    """Configuration is unusable. Raised at import or from `validate()` — never swallowed.

    A misconfigured agent must refuse to start. The alternative is what this file used to do:
    coerce an unparsable value into a plausible one and run with a setting nobody chose.
    """


# Every knob below is read from the environment, and the environment is hostile: it carries
# typos, values copied from another tool's conventions, and shell quoting accidents. These
# three helpers are the single place that turns text into a typed value, and they name the
# offending variable when they cannot.
_TRUE = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSE = frozenset({"0", "false", "no", "off", "n", "f", ""})


def _env_flag(name: str, default: bool = True) -> bool:
    """Parse a boolean knob STRICTLY.

    The previous implementation was `os.environ.get(...) not in ("0", "false", "no")`, which
    is case-sensitive and enumerates only three falsey spellings. Every one of `"False"`,
    `"FALSE"`, `"off"`, `"Off"`, `"N"`, and `""` therefore evaluated to **True**. That is not a
    cosmetic bug: this function governs ORACLE_ENABLED, ORACLE_VERIFIES, DETERMINISTIC,
    ARTIFACT_CAPTURE and the two EXECUTOR_* flags. An operator setting `SISTEMISTA_ORACLE=False`
    to stop sending workspace context off the box — the exact mitigation for an untrusted
    oracle — silently got the oracle ENABLED. A benchmark exporting `DETERMINISTIC=off` ran
    non-deterministically and its numbers were noise.

    An unrecognised value now raises. A knob whose value you cannot parse is a knob whose
    setting you do not know.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ConfigError(
        f"{name}={raw!r} is not a boolean. Use one of {sorted(_TRUE)} / {sorted(_FALSE)}."
    )


def _env_int(
    name: str, default: int, *, minimum: int | None = None, maximum: int | None = None
) -> int:
    """Parse an integer knob, naming the variable on failure.

    A bare `int(os.environ[...])` raises `ValueError: invalid literal for int() with base 10:
    '80a0'` from an *import statement*, with a traceback that names config.py and not the
    variable the operator mistyped.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError:
            raise ConfigError(f"{name}={raw!r} is not an integer") from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name}={value} is below the minimum {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name}={value} is above the maximum {maximum}")
    return value


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = float(raw.strip())
        except ValueError:
            raise ConfigError(f"{name}={raw!r} is not a number") from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name}={value} is below the minimum {minimum}")
    return value


# ── Owned models (execution tier) ────────────────────────────────────────────
# NAV: the owned general-purpose ORCHESTRATOR — action-level reasoning (which key to press
# at this screen state), goal-safety classification, task specialisation, the interactive
# terminal select-options, and — when no borrowed oracle is reachable — planning /
# verification / recovery too. NOT code authoring. Was a 0.6B navigator; now a *dense* 4B
# (Qwen3-4B, not the removed SSM Qwen3.5-4B) so the self-contained path can actually plan.
# See RFC-001 — the 8 GB-RAM promise rides on QLora + diskcache + offload, still to build.
# CODER: authors and repairs concrete shell commands. NOT screen navigation (asked "what
# to do at this spinner" it produced a destructive CTRL_C — hence the split).
# The GGUFs stay outside `src/`: weights are an external artifact, not source.
NAV_MODEL = ROOT / "models" / "Qwen3-4B-Q5_K_M.gguf"
CODER_MODEL = ROOT / "models" / "Qwen2.5-CODER-3B-Q6_k.gguf"

# Source — read at runtime, never written.
PROMPTS_DIR = SRC / "prompts"
KB_DIR = SRC / "knowledge" / "kb"

# State — written at runtime, safe to delete.
MEMORY_DIR = VAR / "memory"
RUNTIME_DIR = VAR / "runtime"
KB_MEMORY_DIR = VAR / "knowledge"
TELEMETRY_DIR = VAR / "telemetry"
BENCHMARK_DIR = VAR / "benchmark"


# llama-server binary + its CUDA/ggml DLLs (the `.exe` is a thin launcher that loads the heavy
# DLLs sitting BESIDE it — so wherever it lives, its siblings must live too; `_spawn` sets
# cwd=parent for exactly this). A machine-specific absolute path belongs in the ENVIRONMENT, not
# in versioned source: a hardcoded external path made the eval pipeline unrunnable on any machine
# but one, which is the opposite of a reproducible benchmark.
def _resolve_llama_server_bin() -> Path:
    """Resolve the binary from portable, documented sources, in priority order:
      1. SISTEMISTA_LLAMA_SERVER_BIN — explicit machine-local override
      2. workspace/bin/llama-server[.exe] — vendored in-repo (self-contained; DLLs beside it)
      3. `llama-server` on PATH — the standard reproducible install
    None of the above → return the vendored path (which does not exist) so `_spawn`/the benchmark
    preflight fail LOUDLY, naming exactly where to put it. Never a silent external dependency.
    """
    override = os.environ.get("SISTEMISTA_LLAMA_SERVER_BIN")
    if override:
        return Path(override)
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    vendored = ROOT / "bin" / exe
    if vendored.exists():
        return vendored
    on_path = shutil.which("llama-server")
    if on_path:
        return Path(on_path)
    return vendored


LLAMA_SERVER_BIN = _resolve_llama_server_bin()

NAV_PORT = _env_int("SISTEMISTA_NAV_PORT", 8090, minimum=1, maximum=65535)
CODER_PORT = _env_int("SISTEMISTA_CODER_PORT", 8091, minimum=1, maximum=65535)

# ── Borrowed model (escalation oracle) ───────────────────────────────────────
# The parent agent's model, reached over HTTP. Sistemista never loads it and never pays
# its VRAM. Planning, recovery reflection and post-step verification escalate here.
# If unreachable, the roles degrade to NAV and say so loudly on stderr — a subagent must
# still run on small hardware, but it must never degrade in silence.
ORACLE_PORT = _env_int("SISTEMISTA_ORACLE_PORT", 8081, minimum=1, maximum=65535)
ORACLE_URL = os.environ.get("SISTEMISTA_ORACLE_URL", f"http://127.0.0.1:{ORACLE_PORT}").rstrip("/")
ORACLE_ENABLED = _env_flag("SISTEMISTA_ORACLE", True)
# Route post-step verification to the oracle too. Off → the owned 4B verifies (self-contained).
ORACLE_VERIFIES = _env_flag("SISTEMISTA_ORACLE_VERIFIES", True)
# Bearer credential for a non-loopback oracle. See `_assert_oracle_transport_is_safe`.
ORACLE_TOKEN = os.environ.get("SISTEMISTA_ORACLE_TOKEN", "")


def _is_loopback(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _assert_oracle_transport_is_safe() -> None:
    """The oracle URL is an unvalidated string from the environment, and everything the agent
    knows travels through it.

    The prompts sent to this endpoint carry the goal, the workspace listing, the terminal
    transcript, the OS username and home directory, and the raw stdout of DISCOVERY steps —
    which is whatever the plan happened to probe, including `Get-ChildItem Env:` output. The
    reply is a PLAN the agent then executes as shell commands. An attacker who controls this
    URL therefore gets both exfiltration and remote code execution by prompt substitution.

    Previously the only admission test was `GET /health` returning `{"status":"ok"}`, which any
    HTTP server on earth satisfies in one line, over cleartext, with no authentication.

    Loopback keeps the old ergonomics: the parent agent owns that process, the traffic never
    leaves the machine, and requiring TLS to talk to 127.0.0.1 would be ceremony. Anything else
    must be authenticated and encrypted, or the agent refuses to start.
    """
    if not ORACLE_ENABLED or _is_loopback(ORACLE_URL):
        return
    scheme = urllib.parse.urlparse(ORACLE_URL).scheme.lower()
    if scheme != "https":
        raise ConfigError(
            f"SISTEMISTA_ORACLE_URL={ORACLE_URL!r} is not loopback and not https. Every prompt "
            f"— goal, workspace listing, discovery stdout — would cross the network in "
            f"cleartext, and the reply is executed as shell commands. Use https, or point the "
            f"oracle at loopback, or set SISTEMISTA_ORACLE=0."
        )
    if not ORACLE_TOKEN:
        raise ConfigError(
            f"SISTEMISTA_ORACLE_URL={ORACLE_URL!r} is remote but SISTEMISTA_ORACLE_TOKEN is "
            f"unset. An unauthenticated endpoint that returns executable plans is an "
            f"unauthenticated code-execution channel."
        )


_assert_oracle_transport_is_safe()

# `urllib`'s `timeout` is a per-socket-operation timeout, not a request deadline: a server that
# trickles one byte every 299 s never trips it. CALL_DEADLINE_S is the wall-clock ceiling the
# router enforces across all retries of a single logical call.
REQUEST_TIMEOUT_S = _env_float("SISTEMISTA_REQUEST_TIMEOUT_S", 180.0, minimum=1.0)
CALL_DEADLINE_S = _env_float("SISTEMISTA_CALL_DEADLINE_S", 420.0, minimum=1.0)


def _common_server_args(port: int, ctx: int, parallel: int) -> list[str]:
    """Flags shared by every owned server. Each one is load-bearing:

    --gpu-layers 999   all weights on GPU. Never a hand-counted number: `34` used to mean
                       "all" only for one specific 33-block GGUF, and would have silently
                       half-offloaded any other model.
    --flash-attn on    required for quantized V-cache, and faster regardless.
    --cache-type-k/v q8_0
                       KV at 8 bits. The prompts carry structured state the model must
                       reason over, so q4_0 (which a throughput-oriented server would pick)
                       is not worth the ~0.6 GB it saves here.
    --batch-size 2048 --ubatch-size 512
                       prefill is compute-bound, unlike decode. 512 is the knee of the
                       curve on Ampere: bigger ubatch stops filling tensor cores and only
                       grows the compute buffer.
    --cache-reuse 256  prefix caching. Every prompt template puts its fixed instruction
                       block FIRST and the variable state in the tail, so the shared prefix
                       is reused across calls. Measured: prefill 608 ms → 16.4 ms (37x),
                       cache_n 1225/1226.
    --slot-prompt-similarity 0.6
                       with >1 slot, routes a request to the slot whose KV already holds
                       its prefix. This is why NAV runs 2 slots despite being single-user:
                       the slots are per prompt-family, not per user. Alternating two
                       templates on one slot would evict the prefix on every call.
    --threads 8        only the non-offloaded ops. 14 threads on a 16-core part bought
                       nothing and contended with the desktop.
    Context shift is disabled by default in this build, and must stay that way: it drops
    the OLDEST tokens on overflow — i.e. exactly the fixed instruction block and the
    invariants. Overflow must raise, not silently lobotomise the prompt.
    """
    return [
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        str(ctx),
        "--parallel",
        str(parallel),
        "--gpu-layers",
        "999",
        "--flash-attn",
        "on",
        "--batch-size",
        "2048",
        "--ubatch-size",
        "512",
        "--threads",
        "8",
        "--cache-type-k",
        "q8_0",
        "--cache-type-v",
        "q8_0",
        "--cache-reuse",
        "256",
        "--slot-prompt-similarity",
        "0.6",
        "--no-warmup",
    ]


def nav_server_args() -> list[str]:
    """Qwen3-4B-Q5_K_M — the owned general-purpose orchestrator (was Qwen3-0.6B).

    Two slots so distinct prompt families (PTY-navigation, safety/enhance, and — in the
    oracle's absence — planning/verify) do not evict each other's prefix cache.

    `--ctx-size 16384` (8192 per slot), not 8192: `supervisor.jinja` needs ~8k, and at
    4096/slot four such calls overflowed outright when the owned model has to plan without a
    borrowed oracle.

    NOTE: the 4B's throughput and resident memory are NOT yet measured — the 0.6B figures
    that used to live here (466 MiB, 268 t/s) no longer apply and were deleted rather than
    guessed. Co-residence of this 4B and the 3B coder does NOT fit an 8 GB GPU at full
    offload; that is the QLora + diskcache + offload work in RFC-001, whose falsification
    tests fill these numbers in.
    """
    return ["--model", str(NAV_MODEL)] + _common_server_args(NAV_PORT, ctx=16384, parallel=2)


def oracle_server_args(model_path: str) -> list[str]:
    """Flags for the escalation oracle, when a caller has to launch it themselves (the
    benchmark harness does; in production the parent agent owns the process).

    `--parallel 2` is the load-bearing flag, and it is not about concurrency. Sistemista is
    single-user and sequential. With one slot, `supervisor.jinja` and `verify.jinja` alternate
    and evict each other's KV: measured 21.7% prefix reuse for verify. The same template on the
    2-slot navigator reused 70.6%. One slot per prompt-family, routed by
    `--slot-prompt-similarity`, is worth ~235 s per 48-task suite.
    """
    return ["--model", model_path] + _common_server_args(ORACLE_PORT, ctx=16384, parallel=2)


def coder_server_args() -> list[str]:
    """Qwen2.5-Coder-3B — 2.60 GiB of weights, ~2.7 GB resident, 130 t/s decode.

    `--spec-type ngram-simple` is the one speculative decoding that pays here: it drafts
    from n-grams already present in the context, so it costs ZERO extra VRAM (no draft
    model). The coder's output copies paths, flags and commands straight out of the prompt,
    which is exactly the case n-gram drafting was built for.
    Measured: 130.28 → 152.58 t/s (+17.1%), acceptance 43.2%, VRAM unchanged at 3945 MiB.

    A real draft model was measured and rejected: Qwen3-0.6B drafting for Qwen3-8B ran at
    55.4 t/s vs 83.8 baseline (-34%) and degraded monotonically with draft length (37.6 t/s,
    18.2% acceptance at n-max 8). Speculative decoding needs the draft to be ~10x faster
    than the target; here it is 3.2x, and it costs 738 MiB — the exact space this coder needs.
    """
    return (
        ["--model", str(CODER_MODEL)]
        + _common_server_args(CODER_PORT, ctx=8192, parallel=1)
        + [
            "--spec-type",
            "ngram-simple",
        ]
    )


# ── Sampler presets ──────────────────────────────────────────────────────────
# These are sent PER REQUEST. They used to sit in the `Llama()` constructor kwargs, where
# `Llama.__init__(**kwargs)` swallowed them without a warning — so every model silently ran
# at llama-cpp-python's generation defaults (temp 0.8 / top_k 40 / top_p 0.95 / min_p 0.05)
# including the ones documented as deterministic. Applying them is a behaviour change.
GREEDY = dict(temperature=0.0, top_k=1, top_p=1.0, min_p=0.0, repeat_penalty=1.0)
# Qwen3 non-thinking preset. repeat_penalty stays 1.0: penalising repetition inside a
# grammar-constrained JSON object fights the grammar over structural tokens.
STRUCTURED = dict(temperature=0.2, top_k=20, top_p=0.8, min_p=0.0, repeat_penalty=1.0)
PLANNING = dict(temperature=0.7, top_k=20, top_p=0.8, min_p=0.0, repeat_penalty=1.0)

# ── Reproducibility ──────────────────────────────────────────────────────────
# The planner samples at temperature 0.7 and no seed was ever pinned. Two benchmark runs
# were therefore two draws from a stochastic process, and a "prediction confirmed / falsified"
# table across them compared samples, not configurations. An entire measurement cycle was
# spent reading noise as signal.
#
# DETERMINISTIC mode makes a run reproducible bit-for-bit: greedy decoding everywhere plus a
# fixed RNG seed per request (llama-server accepts `seed` on /completion). It is OFF in
# production — a planner that always emits the same plan cannot escape a local optimum on a
# retry — and ON for every measurement. A benchmark that is not reproducible measures nothing.
DETERMINISTIC = _env_flag("SISTEMISTA_DETERMINISTIC", False)
SEED: int | None = (
    _env_int("SISTEMISTA_SEED", 0)
    if os.environ.get("SISTEMISTA_SEED", "").strip()
    else (42 if DETERMINISTIC else None)
)

# Wall-clock is a reproducibility leak the seed does not cover. `system_spec` injects TODAY's
# date into EVERY prompt (to defeat the model's frozen-in-time priors), so two DETERMINISTIC
# runs on different DAYS are two different prompts and a delta between them is not a pure effect
# — the path leak was already closed by `workspace_paths.scrub`; the date is the one that
# survived it. Under DETERMINISTIC we PIN the date; production keeps the live date. Overridable
# via SISTEMISTA_SPEC_DATE for a dated study. (Installed tool VERSIONS stay live: freezing them
# would measure a fictional machine, and a baseline is already machine-scoped by construction.)
SPEC_DATE: str | None = os.environ.get("SISTEMISTA_SPEC_DATE") or (
    "2026-07-01" if DETERMINISTIC else None
)

if DETERMINISTIC:
    STRUCTURED = dict(GREEDY)
    PLANNING = dict(GREEDY)

# Namespaced like every other knob. The bare name collided with any unrelated CAPTURE_TIMEOUT
# already exported in the operator's shell.
CAPTURE_TIMEOUT = _env_float("SISTEMISTA_CAPTURE_TIMEOUT", 2.0, minimum=0.1)

# Feature flag (A/B). When on, a failed shell step is re-authored by the executor
# coder reading the real stderr + checkpoint (executor.jinja) instead of the legacy
# product-knowledge corrector (executor_fix.jinja). Toggle off for comparison with
# SISTEMISTA_EXECUTOR_AUTHORED=0.
EXECUTOR_AUTHORED_FIX = _env_flag("SISTEMISTA_EXECUTOR_AUTHORED", True)

# Closes the DISCOVERY→ACTION loop. When on, the executor coder AUTHORS the concrete
# shell command for an action step at execution time, using the research gathered by
# prior DISCOVERY steps (which the plan-time launcher could not see). The planner's
# launcher becomes a hint; the runtime falls back to it whenever the coder returns
# nothing valid, so behaviour is never worse than the frozen-launcher baseline.
EXECUTOR_AUTHORS_ACTIONS = _env_flag("SISTEMISTA_EXECUTOR_AUTHORS_ACTIONS", True)

# Feature flag (A/B). The prompt-enhancer is one unconditional NAV call per task whose
# effect on the outcome has never been measured; its deterministic fallback framing
# already exists in `prompt_enhancer.py`. Off → the fallback brief is used and the call
# is skipped. Default on, so the measured baseline is the shipped behaviour.
ENHANCER = _env_flag("SISTEMISTA_ENHANCER", True)

# Runtime artifact capture — OFF by default, because it is UNPROVEN.
#
# The idea was sound and the target was real: 26 of the 48 benchmark tasks fail with the
# signature `X.txt missing/empty`, and on 24 of them every tool is present and at least one
# command succeeds — the Coder-3B simply never emits `> X.txt`. Asking a 3B model to remember
# a shell redirection is asking for intelligence where a redirection will do.
#
# It did not work. Four seeded runs (48 tasks each, seed 42, greedy, oracle active):
#
#     capture OFF, field present in the grammar   32/48
#     capture OFF, field absent                   28/48
#     capture ON,  first implementation           29/48
#     capture ON,  with both fixes                26/48
#
# The second row is the one that matters. Those two control runs differ ONLY in whether the
# plan grammar exposes a field the runtime ignores. A change that does nothing at execution
# time moved the score by FOUR TASKS, because any edit to a prompt or a grammar reshuffles
# which tokens are sampled and therefore which plans are produced. The effect under test was
# three tasks. **This design cannot resolve it**, and no run in the set beats the control.
#
# It also made the agent slower: 107 s/task against 43 s/task, because the planner emitted more
# steps and more commands. A mechanism meant to require LESS intelligence from the model asked
# it for more.
#
# So: shipped off, kept for a future experiment with enough statistical power (see
# `benchmarks/ab_paired.py`, which refuses to quote a delta the data cannot support). What the
# attempt DID yield are two defects it exposed, both fixed and both valuable on their own:
# `tools/artifact_capture.py` (a failed probe's stderr must never become the artifact) and
# `template_guard.self_truncating_redirect` (`Get-Content x | Out-File x` empties x).
ARTIFACT_CAPTURE = _env_flag("SISTEMISTA_CAPTURE", False)

MAX_CONSECUTIVE_FAILURES = 3
MEMORY_WINDOW = 5
CONSOLIDATION_INTERVAL = 20
MAX_ACTIONS_PER_STEP = 200


# ── Startup preflight ────────────────────────────────────────────────────────
def validate() -> list[str]:
    """Return every reason this configuration cannot run. Empty list → good to start.

    Called once from `main.cli_entry` before anything is constructed. Without it, a missing
    GGUF was not detected at all: `_spawn` only checks that the llama-server BINARY exists,
    so the server started, exited immediately, and the operator waited out the full 180 s
    boot loop to be told the port never came up. A port collision was likewise invisible —
    worse than invisible, because `health()` would succeed against whatever process already
    owned the port and the agent would run its plans on an unknown model.

    Reported as a list rather than raised one-at-a-time so an operator fixing a fresh install
    sees every problem at once instead of rediscovering them one restart at a time.
    """
    errors: list[str] = []

    for path, label in ((NAV_MODEL, "NAV_MODEL"), (CODER_MODEL, "CODER_MODEL")):
        if not path.exists():
            errors.append(f"{label} not found: {path}  (see workspace/models/README.md)")
    if not LLAMA_SERVER_BIN.exists():
        errors.append(
            f"llama-server not found: {LLAMA_SERVER_BIN}\n"
            f"    Set SISTEMISTA_LLAMA_SERVER_BIN, put it on PATH, or vendor it in "
            f"{ROOT / 'bin'} together with its DLLs (see workspace/bin/README.md)."
        )

    ports = {"SISTEMISTA_NAV_PORT": NAV_PORT, "SISTEMISTA_CODER_PORT": CODER_PORT}
    if ORACLE_ENABLED and _is_loopback(ORACLE_URL):
        ports["SISTEMISTA_ORACLE_PORT"] = ORACLE_PORT
    seen: dict[int, str] = {}
    for name, port in ports.items():
        if port in seen:
            errors.append(f"{name} and {seen[port]} are both {port}; each server needs its own")
        seen[port] = name

    if not PROMPTS_DIR.is_dir():
        errors.append(f"prompt templates missing: {PROMPTS_DIR}")
    if not KB_DIR.is_dir():
        errors.append(f"knowledge base missing: {KB_DIR}")

    return errors
