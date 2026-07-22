"""Routes each prompt template to the model that should answer it.

Sistemista is a subagent. It owns two small execution-tier models and borrows the parent
agent's large model as an escalation oracle:

    NAV     Qwen3-4B      general-purpose orchestrator: which key to press, is this
                          destructive, task specialisation, the terminal select-options, and
                          — with no borrowed oracle — planning/verify/recovery. Never authors
                          code. (Was a 0.6B navigator; the dense 4B lets it plan. RFC-001.)
    CODER   Qwen2.5-3B    authors and repairs one concrete shell command. Never navigates
                          a screen (asked "what to do at this spinner" it chose CTRL_C).
    ORACLE  parent's 8B   OPTIONAL escalation for planning/reflection/verification. Reached
                          over HTTP; never loaded, never costs us VRAM. Absent → NAV (the 4B).

The oracle is a *step-level* speculation boundary, not a token-level one. NAV and CODER
propose; the deterministic runtime (grammar, template_guard, safety_gate, error_classifier,
_artifact_check) accepts or rejects for free; only what survives ambiguity escalates. Token-
level speculative decoding was measured and rejected — a 0.6B drafting for an 8B ran 34%
SLOWER than the 8B alone, because the draft is only 3.2x faster than the target where
speculation needs ~10x. See `config.coder_server_args` for the numbers.

Every JSON-returning call is decoded under a GBNF grammar compiled from its schema, so a
syntactically invalid object cannot be sampled. The parsers that used to repair unclosed
strings, raw newlines and Python-style assignments are gone.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import time
from typing import Any

from jinja2 import Environment, FileSystemLoader

from . import trace, workspace_paths
from .config import (
    ARTIFACT_CAPTURE,
    CALL_DEADLINE_S,
    CODER_PORT,
    DETERMINISTIC,
    GREEDY,
    NAV_PORT,
    ORACLE_ENABLED,
    ORACLE_TOKEN,
    ORACLE_URL,
    ORACLE_VERIFIES,
    PLANNING,
    PROMPTS_DIR,
    SEED,
    STRUCTURED,
    coder_server_args,
    nav_server_args,
)
from .llm_backend import Completion, ManagedServer, Provider, ProviderContextError, ProviderError
from .redact import redact
from .tools import predicates

_jinja = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
)

_NAV = ManagedServer(name="nav-4b", port=NAV_PORT, args=nav_server_args())
_CODER = ManagedServer(name="coder-3b", port=CODER_PORT, args=coder_server_args())
_oracle_warned = False

# The one name that marks the borrowed provider. A ProviderError from THIS name degrades to the
# owned NAV (the oracle is optional by design); a ProviderError from an owned server is a real
# fault. Single source so `_oracle()` and `_complete()` cannot drift.
_ORACLE_NAME = "oracle"


def _nav() -> Provider:
    return _NAV.ensure_ready()


def _coder() -> Provider:
    return _CODER.ensure_ready()


def _oracle() -> Provider:
    """OPTIONAL escalation to the parent's model. Absent → the owned 4B NAV, which is the
    self-contained default (RFC-001), not a silent degradation."""
    global _oracle_warned
    if ORACLE_ENABLED:
        p = Provider(_ORACLE_NAME, ORACLE_URL, token=ORACLE_TOKEN)
        if p.health():
            return p
    if not _oracle_warned:
        _oracle_warned = True
        print(
            f"[oracle] none at {ORACLE_URL} — planning/verification run on the owned 4B "
            f"orchestrator (the self-contained default). A borrowed parent model would be "
            f"stronger: start its llama-server, or set SISTEMISTA_ORACLE=0 to silence this.",
            file=sys.stderr,
        )
    return _nav()


# ── Schemas → GBNF. Faithful to the SCHEMA blocks in prompts/*.jinja. ────────
# `success` items are typed predicates, not prose. The enum comes from `tools.predicates`,
# the same table the runtime evaluates against — so the decoder physically cannot emit a
# criterion the verifier does not understand. Measured before this change: 0 of 19 declared
# criteria were machine-checkable, which made invariant #9 vacuous. See predicates.py.
_SUCCESS = {"type": "array", "items": predicates.SCHEMA}

_PLAN_STEP = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "objective": {"type": "string"},
        "launcher": {"type": "string"},
        "vars": {"type": "object"},
        "step_type": {"enum": ["DISCOVERY", "MODIFY", "VERIFY", "RECOVER"]},
        "success": _SUCCESS,
        # The runtime performs the redirection — not the shell, not the model. MEASURED:
        # 27 of 48 benchmark failures share one signature, `X.txt missing/empty`, and on most
        # of them every tool is present: the coder simply never emits `> X.txt`. Remembering
        # a redirection is not a reasoning task. It is a deterministic operation the runtime
        # already has the information to perform, because the step declares
        # `file_has_content(X.txt)`.
        #
        # DECLARED, never inferred. Inferring the target from the predicate would write the
        # log of `pip install` into `requirements.txt` and turn a correct failure into a
        # false success — the vacuous-truth defect, reintroduced one layer down.
        #
        # Present only when the mechanism is on. The A/B control arm must not be able to
        # declare it: measured on the first control run, the planner filled the field on 13
        # steps despite being told not to, and 12 of those launchers then omitted their own
        # redirection. The runtime ignored the field, the file was never written, and the
        # control lost tasks it would otherwise have passed. An effect size measured against
        # that control would have been inflated by the mechanism's own absence.
        **({"capture_stdout_to": {"type": "string"}} if ARTIFACT_CAPTURE else {}),
        "rollback": {"type": "string"},
        "delegation": {"enum": ["executor", "fileops"]},
    },
    "required": ["id", "objective", "launcher", "step_type", "delegation"],
}

SUPERVISOR_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"enum": ["planning", "done"]},
        "goal": {"type": "string"},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "success": _SUCCESS,
        "plan": {"type": "array", "items": _PLAN_STEP},
    },
    "required": ["mode", "goal", "plan"],
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "achieved": {"type": "boolean"},
        "reason": {"type": "string"},
        "action": {"type": "string"},
    },
    "required": ["achieved", "reason", "action"],
}

SAFETY_SCHEMA = {
    "type": "object",
    "properties": {
        "risk": {"enum": ["SAFE", "RECOVERABLE", "DESTRUCTIVE"]},
        "reason": {"type": "string"},
    },
    "required": ["risk", "reason"],
}

ENHANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "specialist_role": {"type": "string"},
        "refined_objective": {"type": "string"},
        "key_considerations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["specialist_role", "refined_objective", "key_considerations"],
}


_CAPTURE_GUIDANCE = """REPORT FILES — the runtime writes them, you do not.
  When a step must leave its output in a file, set `"capture_stdout_to":"<that file>"` and
  assert `file_has_content` on the same path. The runtime captures the command's stdout and
  stderr and writes them there, deterministically, after the command runs.
  The launcher MUST then be the bare command. Do NOT add `> file`, `| Out-File file`,
  `| Tee-Object`, or `Set-Content`: the redirection is the runtime's job, and a command that
  redirects will produce the file itself and the runtime will leave it alone.
  This holds even when the command FAILS. If a probe reports that a tool is absent, that
  output IS the finding the goal asked for — it belongs in the file.
  Leave `capture_stdout_to` empty for steps that do not produce a report."""

_REDIRECT_GUIDANCE = """REPORT FILES — the command must write them.
  When a step must leave its output in a file, the launcher itself must redirect into it
  (`> file` or `| Out-File file`), and the step asserts `file_has_content` on that path.
  Always leave `capture_stdout_to` empty."""


def _render(template_name: str, ctx: dict) -> str:
    """Render, then strip the workspace's absolute path from the result.

    Scrubbing AFTER rendering (rather than sanitising each ctx key) is what makes this a
    single owner: `history`, `workspace_state`, `snapshot` and `memory` all carry paths the
    caller never thinks about, and every one of them feeds the escape loop. See
    `workspace_paths` for the measurement that motivated it.

    `predicate_reference` is injected here rather than by each caller: the prompt's success
    vocabulary and the runtime's evaluator must be the same table, always."""
    ctx = {
        "predicate_reference": predicates.prompt_reference(),
        # A constant per process, so it does not move the prefix-cache boundary.
        "capture_guidance": _CAPTURE_GUIDANCE if ARTIFACT_CAPTURE else _REDIRECT_GUIDANCE,
        **ctx,
    }
    # Two transformations, two different jobs, one funnel. `scrub` replaces the workspace root
    # for tokenizer/anti-hallucination reasons (its own docstring says so); `redact` withholds
    # credentials. Applied here because this is the single place a prompt becomes bytes bound
    # for a model — which, when an oracle is configured, is a process outside this machine.
    # Doing it per template or per ctx key would be as many owners as there are call sites.
    return redact(workspace_paths.scrub(_jinja.get_template(template_name).render(**ctx)))


def _backoff(attempt: int) -> float:
    """Exponential backoff, capped at 8 s.

    Jitter is skipped under DETERMINISTIC: the whole point of that mode is that two runs are
    the same run, and a random sleep would reintroduce the variation the seed removes. In
    production the jitter spreads retries so a restarting server is not hit in lockstep.
    """
    base = min(8.0, 0.5 * (2**attempt))
    if DETERMINISTIC:
        return base
    # Cap AFTER jitter, not before: `min(8, base) * (0.5 + random())` peaks at 12 s, so the
    # documented ceiling would have been exceeded by half on every late attempt.
    return min(8.0, base * (0.5 + random.random()))


def _complete(
    provider: Provider,
    prompt: str,
    *,
    template: str,
    n_predict: int,
    sampler: dict,
    schema: dict | None = None,
    stop: list[str] | None = None,
) -> Completion:
    """One call, with the historical context-overflow retry: shrink the output budget
    first, then trim the prompt HEAD-first is wrong (it holds the instructions) — trim the
    tail-most variable state by keeping the most recent slice, as the previous code did."""
    tokens = n_predict
    # `urllib`'s timeout is per socket operation, not per request: a server trickling one byte
    # every REQUEST_TIMEOUT_S-1 seconds never trips it, and four such attempts have no bound at
    # all. This is the wall-clock ceiling for the whole logical call, retries included.
    deadline = time.monotonic() + CALL_DEADLINE_S
    for attempt in range(4):
        if time.monotonic() > deadline:
            raise ProviderError(
                f"{template}: exceeded the {CALL_DEADLINE_S:.0f}s call deadline after "
                f"{attempt} attempt(s) against {provider.name}"
            )
        try:
            t0 = time.perf_counter()
            # In DETERMINISTIC mode the prefix cache is off: it is the dominant source of
            # run-to-run variation, and a benchmark that is not reproducible measures nothing.
            # The cost is real — prefill goes back to 608 ms from 16.4 ms — so a deterministic
            # run's latency is NOT comparable to production latency.
            out = provider.complete(
                prompt,
                n_predict=tokens,
                stop=stop,
                json_schema=schema,
                seed=SEED,
                cache_prompt=not DETERMINISTIC,
                **sampler,
            )
            trace.emit(
                "llm",
                role=provider.name,
                template=template,
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                prompt_n=out.prompt_n,
                predicted_n=out.predicted_n,
                cache_n=out.cache_n,
                prefill_ms=round(out.prefill_ms, 1),
                decode_tps=round(out.decode_tps, 2),
                grammar=schema is not None,
                temperature=sampler.get("temperature"),
                output=out.text[:1200],
            )
            return out
        except ProviderContextError:
            trace.emit(
                "llm",
                role=provider.name,
                template=template,
                context_overflow=True,
                n_predict=tokens,
                prompt_chars=len(prompt),
            )
            if tokens > 256:
                tokens = max(256, tokens // 2)
                continue
            if len(prompt) <= 512:
                raise
            prompt = prompt[-int(len(prompt) * 0.75) :]
            tokens = min(tokens, 256)
        except ProviderError as exc:
            # A borrowed-oracle transport failure must DEGRADE to the owned model, never crash
            # the run — this mirrors _oracle()'s absence path (the oracle is optional by design,
            # RFC-001). A ProviderError from an OWNED server is a real local fault: surface it,
            # and after degrading, a second failure lands here as nav-4b and re-raises. Bounded
            # by the same range(4) as the context-overflow retry.
            if provider.name != _ORACLE_NAME:
                raise
            time.sleep(_backoff(attempt))
            fallback = _nav()
            trace.emit(
                "override",
                role=provider.name,
                template=template,
                rule="oracle_unreachable_degrade",
                detail=str(exc)[:200],
            )
            print(f"[oracle] {exc} — degrading to owned {fallback.name}", file=sys.stderr)
            provider = fallback
            continue
    raise RuntimeError("could not fit prompt + output into the context window")


def _plan_fingerprint(obj: dict) -> str:
    """A stable 12-hex digest of the STEPS a plan proposes — not of its prose.

    Two plans that differ only in wording, ordering of unrelated keys, or the reason text
    hash the same; two plans that would run different commands do not. The digest is what
    makes "did this re-plan produce anything new?" a measurable question.
    """
    steps = obj.get("plan")
    if not isinstance(steps, list):
        return ""
    shape = [
        (str(s.get("launcher") or ""), str(s.get("step_type") or ""))
        for s in steps
        if isinstance(s, dict)
    ]
    return hashlib.sha256(
        json.dumps(shape, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]


def _traced(template: str, obj: dict) -> dict:
    """Record the decision the object carries, compactly.

    The raw `output` field on the llm event is capped at 1200 characters, and a plan is
    routinely longer than that: measured on the 48-task baseline, 82 of 86 planner outputs
    were unparsable from the trace for that reason alone, so "how often does a re-plan
    repeat the plan it just replaced?" — the question that decides whether re-planning
    should become plan REPAIR — could be asked of only 4 samples. A fingerprint answers it
    for every run, forever, in twelve characters.
    """
    if isinstance(obj, dict) and isinstance(obj.get("plan"), list):
        trace.emit(
            "plan",
            template=template,
            fingerprint=_plan_fingerprint(obj),
            n_steps=len(obj["plan"]),
            mode=str(obj.get("mode") or "")[:24],
        )
    return obj


def _json_call(
    provider: Provider, template: str, ctx: dict, *, n_predict: int, schema: dict, sampler: dict
) -> dict:
    """Grammar-constrained, so a COMPLETED object is well-formed by construction.

    The one failure mode the grammar cannot cover is truncation: a run that exhausts
    `n_predict` is cut mid-object. Retry once with double the budget, then fail loudly —
    silently returning a stub would hide a planner stuck in a generation loop, which is
    exactly what truncation usually means."""
    prompt = _render(template, ctx)
    budget = n_predict
    for attempt in (1, 2):
        out = _complete(
            provider,
            prompt,
            template=template,
            n_predict=budget,
            sampler=sampler,
            schema=schema,
            stop=["<|im_end|>"],
        )
        if out.truncated:
            trace.emit(
                "truncation",
                template=template,
                role=provider.name,
                n_predict=budget,
                attempt=attempt,
            )
            if attempt == 1:
                budget = min(budget * 2, 8192)
                continue
            raise RuntimeError(
                f"{template}: generation hit the {budget}-token limit twice and the JSON "
                f"object was never closed. The model is looping, not planning. "
                f"Tail: {out.text[-200:]!r}"
            )
        try:
            return _traced(template, json.loads(_strip_think(out.text)))
        except json.JSONDecodeError:
            parsed = _extract_json_object(out.text)
            if parsed is not None:
                return _traced(template, parsed)
            raise RuntimeError(
                f"{template}: the decoder emitted a complete generation that is not valid "
                f"JSON, despite the grammar. Raw: {out.text[:300]}"
            ) from None
    raise AssertionError("unreachable")


def _text_call(
    provider: Provider, template: str, ctx: dict, *, n_predict: int, sampler: dict, stop: list[str]
) -> str:
    out = _complete(
        provider,
        _render(template, ctx),
        template=template,
        n_predict=n_predict,
        sampler=sampler,
        stop=stop,
    )
    return _strip_think(out.text)


def _strip_think(text: str) -> str:
    """Safety net. The templates carry `/no_think`, so this should be a no-op; a truncated
    thinking block still must not reach a parser as if it were content."""
    raw = (text or "").strip()
    if "<think>" in raw and "</think>" in raw:
        return raw.split("</think>", 1)[-1].strip()
    if "<think>" in raw:
        return raw.split("<think>", 1)[0].strip()
    return raw


def _first_command(raw: str) -> str:
    """First non-empty, non-comment line, stripped of stray fences/backticks."""
    for line in _strip_md_fences(raw).splitlines():
        line = line.strip().strip("`").strip()
        if line and not line.startswith("#"):
            return line
    return ""


# ── Public API (unchanged signatures) ────────────────────────────────────────


def supervisor_call(ctx: dict) -> dict:
    """Plan. Escalates to the oracle when one is present; otherwise the owned 4B plans — the
    decision a 0.6B could not make, which is precisely why the navigator is now a 4B (RFC-001).

    Budget 2048, not 4096. Real plans measure 160-490 tokens; the old ceiling only ever
    bought a runaway generation 25 seconds to run before `_json_call` noticed. Truncation
    now doubles the budget once, so a genuinely long plan still succeeds, while a loop dies
    fast and loudly."""
    return _json_call(
        _oracle(),
        "supervisor.jinja",
        ctx,
        n_predict=2048,
        schema=SUPERVISOR_SCHEMA,
        sampler=PLANNING,
    )


def verify_call(ctx: dict) -> dict:
    """Post-step verification. The observer only reports; this is where the real
    post-execution reasoning happens, so it escalates by default."""
    provider = _oracle() if ORACLE_VERIFIES else _nav()
    result = _json_call(
        provider, "verify.jinja", ctx, n_predict=1024, schema=VERIFY_SCHEMA, sampler=STRUCTURED
    )
    return _coerce_verify_result(result)


def safety_call(ctx: dict) -> dict:
    """Pre-planning risk classification: three-way, one sentence. NAV handles it."""
    try:
        return _json_call(
            _nav(), "safety.jinja", ctx, n_predict=128, schema=SAFETY_SCHEMA, sampler=STRUCTURED
        )
    except Exception as exc:
        # A safety classifier that cannot answer must not silently open the gate.
        print(f"[safety] classifier unavailable: {exc}", file=sys.stderr)
        return {
            "risk": "RECOVERABLE",
            "reason": "classifier unavailable — refusing unclassified goal",
        }


def enhance_call(ctx: dict) -> dict:
    """Single-call task specialization. prompt_enhancer.py owns validation and fallback;
    this function only does model I/O."""
    try:
        return _json_call(
            _nav(),
            "prompt_enhancer.jinja",
            ctx,
            n_predict=512,
            schema=ENHANCE_SCHEMA,
            sampler=STRUCTURED,
        )
    except Exception:
        return {}


def executor_call(ctx: dict) -> str:
    """Coder authors ONE shell command from the real stderr + checkpoint."""
    raw = _text_call(
        _coder(), "executor.jinja", ctx, n_predict=256, sampler=GREEDY, stop=["<|im_end|>", "\n\n"]
    )
    return _first_command(raw)


def executor_fix_call(ctx: dict) -> str:
    """Legacy corrector path (executor_fix.jinja). Same model, same determinism."""
    raw = _text_call(
        _coder(),
        "executor_fix.jinja",
        ctx,
        n_predict=256,
        sampler=GREEDY,
        stop=["<|im_end|>", "\n\n"],
    )
    return _first_command(raw)


def content_call(ctx: dict) -> str:
    """Author the CONTENT of one file (its whole body), NOT a shell command.

    Control experiment (seed 42): the same coder, asked for "the single shell command" to
    create server.js, emits an empty `New-Item -ItemType File`; asked for the file's CONTENT
    it emits a correct Node.js HTTP server. The bottleneck was the framing, not the 3B.

    Content is multi-line, so: a large budget, stop ONLY on the turn end (never on `\\n\\n`,
    which would truncate a file at its first blank line), and NO `_first_command` (that keeps
    only line one). Markdown fences are stripped in case the coder wraps the body anyway.
    ctx keys: path, objective, research_notes?, system_spec?"""
    raw = _text_call(
        _coder(), "executor_content.jinja", ctx, n_predict=1024, sampler=GREEDY, stop=["<|im_end|>"]
    )
    return _strip_md_fences(raw).strip()


def executor_pty_fallback_call(ctx: dict) -> str:
    """One PTY action from a raw terminal transcript. NAV, not CODER: driving a wizard's
    screen state is general reasoning, not code authoring.
    ctx keys: objective, constraints, transcript
    """
    global _consecutive_spinner_waits
    raw = _text_call(
        _nav(),
        "executor_pty_fallback.jinja",
        ctx,
        n_predict=64,
        sampler=GREEDY,
        stop=["<|im_end|>", "\n\n"],
    )
    action = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    working = _transcript_shows_active_work(ctx.get("transcript", ""))

    # Deterministic backstops, model-independent. A spinner frame is, by definition, active
    # work: the process is NOT stuck, and what to do about a running process is a wall-clock
    # decision the runtime owns, never an LLM guess from one screenshot.
    #
    # 1. Aborting active work is always wrong. No cap, no exception.
    if working and "ctrl_c" in action.lower():
        trace.emit(
            "override", rule="no_abort_during_work", model_said=action, runtime_did="WAIT(2000)"
        )
        return "WAIT(2000)"

    # 2. Sending INPUT into active work is almost always wrong, and it is how a live React +
    #    Vite scaffold hung for ten minutes: the navigator answered every spinner frame with
    #    KEY(ENTER), the wizard advanced nothing, and the transcript never changed. Bounded,
    #    not absolute — some wizards do render a spinner while genuinely awaiting an answer,
    #    so after `_MAX_SPINNER_WAITS` the model's judgement is restored. The bound is what
    #    turns an unbounded hang into a delay of known length.
    if working and _INPUT_ACTION.match(action):
        if _consecutive_spinner_waits < _MAX_SPINNER_WAITS:
            _consecutive_spinner_waits += 1
            trace.emit(
                "override",
                rule="no_input_during_work",
                model_said=action,
                runtime_did="WAIT(1500)",
                consecutive=_consecutive_spinner_waits,
            )
            return "WAIT(1500)"
        trace.emit(
            "override",
            rule="spinner_wait_budget_exhausted",
            model_said=action,
            consecutive=_consecutive_spinner_waits,
        )

    _consecutive_spinner_waits = 0
    return action


# ── Deterministic helpers ────────────────────────────────────────────────────

# Spinner frames = a process actively working (installing, generating, compiling). A universal
# terminal idiom, not a per-tool signal.
#
# Braille frames are unambiguous. The ASCII frames `|/-\` are also ordinary punctuation, so they
# count only when a line consists of the frame alone, optionally followed by a label. Treating
# them as a bare character class made `(Y/n)` — an idle prompt — look like active work.
_BRAILLE_SPINNER = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
_ASCII_SPINNER_LINE = re.compile(r"^\s*[|/\-\\](?:\s|$)")

# Any action that pushes bytes into the child process. WAIT/READ/DONE observe; these commit.
_INPUT_ACTION = re.compile(r"^\s*(WRITE|KEY)\s*\(", re.IGNORECASE)

# ~30 seconds of spinner at 1500 ms per wait. Long enough for an install to move on, short
# enough that a wizard genuinely blocked on input is not starved.
_MAX_SPINNER_WAITS = 20
_consecutive_spinner_waits = 0


def _transcript_shows_active_work(transcript: str) -> bool:
    """Is the child process working, right now?

    The ASCII spinner frames `|`, `/`, `-`, `\\` are also ordinary punctuation. The previous
    version asked `any(ch in _SPINNER_CHARS for ch in transcript)`, so `(Y/n)` — the most
    common idle prompt on earth — read as active work, and so did almost every other line of
    terminal output. The backstop that depends on this predicate was therefore firing on
    screens where the wizard was blocked waiting for an answer.

    An ASCII frame counts only when it stands ALONE on a line, optionally followed by a
    label ("- Installing"). Braille frames are unambiguous and always count.
    """
    t = transcript or ""
    low = t.lower()
    if any(
        kw in low
        for kw in (
            "installing",
            "downloading",
            "compiling",
            "building",
            "resolving",
            "fetching",
            "creating",
        )
    ):
        return True
    if any(ch in _BRAILLE_SPINNER for ch in t):
        return True
    return any(_ASCII_SPINNER_LINE.match(line) for line in t.splitlines())


def _coerce_verify_result(result: dict) -> dict:
    """Normalise verify response so 'achieved' is always a Python bool."""
    v = result.get("achieved", False)
    if isinstance(v, str):
        v = v.strip().lower() in ("true", "1", "yes")
    else:
        v = bool(v)
    return {
        "achieved": v,
        "reason": str(result.get("reason", "")),
        "action": str(result.get("action", "")) if not v else "",
    }


def _strip_md_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        cleaned = cleaned.replace("```", "").strip()
    return cleaned


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Brace-balanced extraction of the first top-level JSON object.

    Retained because `orchestrator.py` parses a JSON string carried inside a verify result.
    It is no longer part of any model-output repair path — grammars made those obsolete.
    """
    s = _strip_md_fences(text)
    start = s.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(s[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
