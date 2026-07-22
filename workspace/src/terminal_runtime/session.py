"""
Level 5 — Terminal Session.

The event loop that connects:
  PTY byte stream → VirtualScreen → PromptDetector → Driver → PTY input

Features:
  - Exponential backoff polling (not fixed WAIT 500ms)
  - Screen diff: only invoke detector when screen changes meaningfully
  - Dedup: same prompt answered N times without progress → LLM fallback
  - LLM fallback: raw transcript shown to model, constrained to PTY actions only
  - Session recorder: every frame saved to replay later

No rule in this file references a specific CLI, framework, or tool.
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Callable, Optional, Protocol

from .driver import PTYAction, _decide_select, decide
from .prompt_detector import _try_select, detect
from .prompts import ErrorPrompt, SelectPrompt, ShellPrompt, SpinnerPrompt
from .virtual_screen import VirtualScreen

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_ACTIONS = 600  # hard cap per wizard step (iteration count)
MAX_WALL_SECONDS = 150  # hard WALL-CLOCK cap per wizard step. Iteration count


# alone doesn't bound time (WAITs + backoff sleeps can
# ride 600 iters far past any budget). A single wizard
# interaction over 2.5 min is stuck — abort so the
# orchestrator re-plans instead of hanging to the outer cap.
class Clock(Protocol):
    """The passage of time, as a dependency.

    A closed-loop controller is defined by what it observes AFTER acting, so its correctness
    is inseparable from its timing. With `time` called directly, the only way to test "the
    cursor did not move, so do not fire again" was to actually wait — which makes the test
    slow, flaky, and dependent on the host scheduler. Injected, the same code runs against a
    clock that advances instantly and reproducibly.
    """

    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class _RealClock:
    """Production clock. Behaviour is exactly what it was before the seam existed."""

    @staticmethod
    def monotonic() -> float:
        return time.monotonic()

    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(seconds)


# ── Closed-loop navigation ───────────────────────────────────────────────────
# How long to wait for the terminal to redraw after a keystroke, and how finely to poll.
# These bound the OBSERVATION, not the action: the loop stops as soon as the screen changes.
NAV_SETTLE_S = 0.02  # poll interval while waiting for a redraw
NAV_TIMEOUT_S = 1.5  # a redraw that has not arrived by now is not coming

DEDUP_LIMIT = 2  # same prompt ANSWERED this many times → LLM fallback
STABLE_LIMIT = 20  # unchanged screen for this many polls → LLM fallback

# Cursor movement is not an answer. Excluded from the dedup count, or a menu that needs three
# arrow presses exhausts DEDUP_LIMIT before it reaches the option the objective asked for.
_NAV_KEYS = frozenset({"ARROW_UP", "ARROW_DOWN", "ARROW_LEFT", "ARROW_RIGHT"})
# (high value: npm install can take minutes with no screen change)
STUCK_LOOP_LIMIT = 5  # same prompt KIND seen this many times consecutively → PTY_STUCK_ANOMALY

# Exponential backoff for polling when screen is stable
_BACKOFF_BASE = 0.15  # seconds
_BACKOFF_MAX = 2.0
_BACKOFF_FACTOR = 1.5

# Spinner chars — used for screen diff to avoid triggering on spinner updates
_SPINNER_RE = re.compile(r"[⠀-⣿|/\\\-⠙⠹⠸⠼⠴⠦⠧⠇⠏⠋]+")


class TerminalSession:
    """
    Drives an interactive PTY wizard from start (shell launches tool)
    to finish (shell prompt returns).

    The caller provides:
      - write_fn:  writes bytes/str to PTY stdin
      - read_fn:   returns bytes/str of new PTY output (non-blocking, returns b"" if none)
      - llm_fn:    (optional) called when deterministic path fails; receives transcript,
                   must return a PTYAction-compatible string like "WRITE(y\r)" or "KEY(ENTER)"

    Usage:
        session = TerminalSession(write_fn, read_fn, llm_fn)
        success, transcript = session.run(objective, constraints, goal)
    """

    def __init__(
        self,
        write_fn: Callable[[str], None],
        read_fn: Callable[[], bytes | str],
        llm_fn: Optional[Callable[[str, str, str], str]] = None,
        log_fn: Optional[Callable[[str], None]] = None,
        clock: Optional["Clock"] = None,
    ) -> None:
        self._write = write_fn
        self._read = read_fn
        self._llm = llm_fn
        self._log = log_fn or (lambda msg: None)
        # The clock is injected for the same reason write/read are: a control loop whose
        # timing cannot be controlled cannot be tested. With the real module the behaviour is
        # unchanged; a test supplies a clock that advances instantly, so the whole interactive
        # subsystem becomes verifiable at zero wall-clock and with no scheduler jitter.
        self._clock = clock or _RealClock()

        self._screen = VirtualScreen()
        self._frames: deque[list[str]] = deque(maxlen=2)  # [prev, current]
        self._transcript: list[str] = []  # raw text output log

    def run(
        self,
        objective: str,
        constraints: list[str],
        goal: str,
    ) -> tuple[bool, str]:
        """
        Drive the wizard until done or max actions reached.

        Returns:
            (success, transcript_text)
            success = True if ShellPrompt detected (process exited cleanly)
        """
        answered: dict[str, int] = {}  # prompt_key → times answered
        stable_count = 0
        last_content_hash = ""
        backoff = _BACKOFF_BASE
        # Stuck-loop tracking: consecutive detections of the same prompt KIND
        _consecutive_kind: str = ""
        _consecutive_count: int = 0
        _deadline = self._clock.monotonic() + MAX_WALL_SECONDS

        for _action_n in range(MAX_ACTIONS):
            # ── Wall-clock bound: never ride past the per-step time budget ──
            if self._clock.monotonic() > _deadline:
                self._log(f"  [PTY_TIMEOUT] wizard exceeded {MAX_WALL_SECONDS}s — aborting")
                self._write("\x03")  # CTRL_C to release the stuck process
                self._clock.sleep(0.3)
                return False, "PTY_TIMEOUT: " + self._transcript_text()

            # ── Read PTY output ────────────────────────────────────────────
            new_data = self._read()
            if new_data:
                self._screen.feed(new_data)
                if isinstance(new_data, bytes):
                    new_data = new_data.decode("utf-8", errors="replace")
                self._transcript.append(new_data)

            # ── Screen diff ────────────────────────────────────────────────
            rows = self._screen.rows
            content_hash = _content_hash(rows)

            if content_hash == last_content_hash:
                stable_count += 1
                # Exponential backoff when nothing changes
                self._clock.sleep(min(backoff, _BACKOFF_MAX))
                backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)
                if stable_count < STABLE_LIMIT:
                    continue
                # Stable for too long — let detector run anyway
            else:
                stable_count = 0
                backoff = _BACKOFF_BASE
                last_content_hash = content_hash

            # ── Detect prompt ──────────────────────────────────────────────
            prev_rows = self._frames[-1] if self._frames else None
            self._frames.append(rows)

            # Every available cursor signal, not just the text plane.
            prompt = detect(rows, prev_rows, self._screen.highlighted_rows_text())

            self._log(f"  screen: {prompt.kind}  {_prompt_summary(prompt)}")

            # ── Patch 3: ShellPrompt is an unconditional short-circuit ─────
            # The shell prompt means the subprocess has exited and returned
            # control. We must return immediately — no backoff, no LLM call.
            if isinstance(prompt, ShellPrompt):
                # Drain remaining PTY bytes before returning so the transcript
                # is complete (some tools flush final output after the prompt).
                _drain = self._read()
                if _drain:
                    self._screen.feed(_drain)
                    if isinstance(_drain, bytes):
                        _drain = _drain.decode("utf-8", errors="replace")
                    self._transcript.append(_drain)
                return True, self._transcript_text()

            if isinstance(prompt, ErrorPrompt):
                self._log(f"  [error] {prompt.message[:80]}")
                return False, self._transcript_text()

            # ── Patch 4: Stuck-loop detector ───────────────────────────────
            # If the same prompt KIND appears STUCK_LOOP_LIMIT times in a row
            # without the screen changing meaningfully, the tool has entered an
            # interactive loop that the driver cannot escape deterministically.
            # Abort with PTY_STUCK_ANOMALY so the orchestrator can re-plan.
            if prompt.kind == _consecutive_kind:
                _consecutive_count += 1
            else:
                _consecutive_kind = prompt.kind
                _consecutive_count = 1

            if (
                _consecutive_count >= STUCK_LOOP_LIMIT
                and not isinstance(prompt, SpinnerPrompt)  # spinners are expected to repeat
            ):
                self._log(
                    f"  [PTY_STUCK_ANOMALY] '{prompt.kind}' repeated "
                    f"{_consecutive_count}× — aborting"
                )
                # Send CTRL_C to terminate the stuck process before returning
                self._write("\x03")
                self._clock.sleep(0.5)
                return False, "PTY_STUCK_ANOMALY: " + self._transcript_text()

            # ── Select menus are driven as a CLOSED LOOP, not one key per outer
            #    iteration. Emitting a single arrow and re-entering this loop means the
            #    next decision is taken from whatever frame happens to have arrived, which
            #    is how a two-key navigation into a WRAPPING list produced `create-marko`.
            #    _drive_select measures the cursor after every key and refuses to guess.
            if isinstance(prompt, SelectPrompt):
                ok, why = self._drive_select(prompt, objective, goal)
                self._log(f"  select: {'✓' if ok else '✗'} {why}")
                if not ok:
                    # Deterministic navigation could not converge on an OBSERVED position.
                    # Hand the rendered screen to the model rather than committing a
                    # selection nobody can justify.
                    action = self._llm_fallback(objective, constraints, goal)
                    self._log(f"  action: {action}")
                    self._execute(action)
                last_content_hash = ""
                stable_count = 0
                backoff = _BACKOFF_BASE
                _consecutive_count = 0
                continue

            # ── Dedup: same prompt answered too many times ─────────────────
            prompt_key = f"{prompt.kind}:{_prompt_summary(prompt)[:80]}"
            times = answered.get(prompt_key, 0)

            if times >= DEDUP_LIMIT:
                # Deterministic path failed — call LLM
                action = self._llm_fallback(objective, constraints, goal)
                answered.pop(prompt_key, None)
                # `times` was read from the dict BEFORE the pop and is never re-read, so the
                # write-back below computed `times + 1` from the stale value: 2 → 3 → 4 → …
                # The counter could only ever grow, so once a prompt crossed DEDUP_LIMIT the
                # deterministic driver was disabled for it PERMANENTLY. Observed in production
                # (react.log:63-73): four consecutive `calling LLM` with no return to decide().
                times = -1
            elif stable_count >= STABLE_LIMIT and isinstance(prompt, SpinnerPrompt):
                # Stuck in spinner — LLM diagnose
                action = self._llm_fallback(objective, constraints, goal)
                stable_count = 0
            else:
                action = decide(prompt, objective, constraints, goal, answered)

            self._log(f"  action: {action}")

            # ── Execute action ─────────────────────────────────────────────
            self._execute(action)

            # Track answered prompts. Navigation is NOT an answer: moving the cursor one row
            # does not respond to the question. Counting it meant any menu needing more than
            # DEDUP_LIMIT (2) cursor moves was unreachable by the deterministic driver — which
            # is most menus.
            _is_navigation = action.kind == "KEY" and action.value.upper() in _NAV_KEYS
            if (
                action.kind in ("WRITE", "KEY")
                and not _is_navigation
                and not isinstance(prompt, SpinnerPrompt)
            ):
                answered[prompt_key] = times + 1

            # Reset stability after writing; also reset stuck-loop counter
            # because we just sent input — the screen is expected to change.
            if action.kind in ("WRITE", "KEY"):
                last_content_hash = ""
                stable_count = 0
                backoff = _BACKOFF_BASE
                _consecutive_count = 0

            if action.kind == "DONE":
                success = action.value != "error"
                return success, self._transcript_text()

        self._log("  [warn] max actions reached")
        return False, self._transcript_text()

    # ── Closed-loop primitives ───────────────────────────────────────────────

    def _pump(self) -> None:
        """Read whatever the child has produced and fold it into the screen."""
        data = self._read()
        if not data:
            return
        self._screen.feed(data)
        self._transcript.append(
            data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
        )

    def _observe_selection(self) -> tuple[int, int] | None:
        """The cursor's index and the option count, measured from the CURRENT screen.

        Returns None when the cursor is not observable — which is information, not an error,
        and is the case the old code silently replaced with "index 0".
        """
        rows = [r for r in self._screen.rows if r.strip()]
        prompt = _try_select(rows, self._screen.highlighted_rows_text())
        if prompt is None:
            return None
        return prompt.selected, len(prompt.choices)

    def _send_key_and_measure(self, key: str) -> tuple[int, int] | None:
        """Emit one key, then WAIT until the terminal proves it moved.

        This is the whole difference between the old navigation and this one. Before: write a
        key, `sleep(0.2)`, assume it landed, and — worse — clear `last_content_hash` so the
        next iteration was forced past the screen-diff gate whether or not the child had
        redrawn. The controller then decided again from a possibly stale frame, and fired
        again. Nothing in the loop ever compared an emitted key against its effect.

        Returns the new (index, count), or None if the cursor became unobservable.
        """
        before = self._observe_selection()
        seq = _KEY_MAP.get(key.upper(), "")
        if seq:
            self._write(seq)

        deadline = self._clock.monotonic() + NAV_TIMEOUT_S
        while self._clock.monotonic() < deadline:
            self._clock.sleep(NAV_SETTLE_S)
            self._pump()
            after = self._observe_selection()
            if after is not None and after != before:
                return after
        return before

    def _drive_select(self, prompt: SelectPrompt, objective: str, goal: str) -> tuple[bool, str]:
        """Walk the cursor to the option the objective asks for, one MEASURED step at a time.

        Terminates for one of four reasons, all of them observed rather than assumed:
          * the cursor reaches the target       -> commit with ENTER
          * a keystroke does not move it        -> abort (never fire a second key blind)
          * the cursor revisits an index        -> the list WRAPPED; position is no longer
                                                   trustworthy, so abort instead of guessing
          * the step budget is exhausted        -> abort

        The wrap check is the one that produced `create-marko`: vite's framework list wraps, and
        two blind ARROW_UPs from index 0 land on `Marko`. A controller that measures cannot make
        that mistake, because after the first UP it observes an index it did not expect.
        """
        target = _decide_select(prompt.title, prompt.choices, objective, goal)
        current, count = prompt.selected, len(prompt.choices)
        seen: set[int] = set()

        for _ in range(count + 1):
            if current == target:
                self._write(_KEY_MAP["ENTER"])
                self._clock.sleep(0.3)
                self._pump()
                return True, f"selected {prompt.choices[target]!r}"

            if current in seen:
                return False, (
                    f"cursor wrapped at index {current}; position is unreliable "
                    f"(target {target!r} of {count} options)"
                )
            seen.add(current)

            key = "ARROW_DOWN" if target > current else "ARROW_UP"
            measured = self._send_key_and_measure(key)
            if measured is None:
                return False, "cursor stopped being observable mid-navigation"
            new_index, count = measured
            if new_index == current:
                return False, f"{key} did not move the cursor from index {current}"
            current = new_index

        return False, f"did not converge on index {target} within {count + 1} steps"

    def _execute(self, action: PTYAction) -> None:
        """Send the action to the PTY."""
        match action.kind:
            case "WRITE":
                self._write(action.value)
                self._clock.sleep(0.3 if not action.value.endswith("\r") else 0.8)
            case "KEY":
                seq = _KEY_MAP.get(action.value.upper(), "")
                if seq:
                    self._write(seq)
                self._clock.sleep(0.2)
            case "WAIT":
                try:
                    ms = min(int(action.value), 5000)
                except (ValueError, TypeError):
                    ms = 1000
                self._clock.sleep(ms / 1000)
            case "DONE":
                pass

    # Live-work verbs — progress lines a tool prints WHILE working. Deliberately
    # only present-tense verbs, NOT nouns like "packages"/"dependencies"/
    # "node_modules": those appear in stale scrollback (a finished npm install
    # leaves them on screen) and were causing WAIT-forever on a prompt that had
    # already appeared. Matched against the CURRENT screen only, not scrollback.
    _ACTIVE_WORK_RE = re.compile(
        r"installing|downloading|compiling|building|fetching|resolving|"
        r"auditing|generating|scaffolding|cloning|extracting",
        re.IGNORECASE,
    )

    def _current_screen_working(self) -> bool:
        """True only if the CURRENT visible screen shows live work (a live-work
        verb or an animating spinner) — not stale scrollback."""
        try:
            cur = "\n".join(self._screen.rows)
        except Exception:
            cur = ""
        if self._ACTIVE_WORK_RE.search(cur):
            return True
        # A live spinner glyph on the current screen also = working.
        return bool(re.search(r"[⠀-⣿]", cur)) and not _has_answerable_prompt(self._screen.rows)

    def _llm_fallback(
        self,
        objective: str,
        constraints: list[str],
        goal: str,
    ) -> PTYAction:
        """Call the LLM with the raw transcript. Parse its response into a PTYAction."""
        transcript = self._transcript_text()

        # Safety: if the CURRENT screen shows live work (not stale scrollback),
        # never call LLM — just wait. But if an answerable prompt is on screen,
        # fall through and let the LLM/driver answer it.
        if self._current_screen_working():
            self._log("  [fallback] process is actively working — WAIT instead of LLM")
            return PTYAction("WAIT", "3000")

        if self._llm is None:
            self._log("  [fallback] no LLM configured, sending CTRL_C")
            return PTYAction("KEY", "CTRL_C")

        self._log("  [fallback] calling LLM with transcript")
        raw = self._llm(objective, "\n".join(f"- {c}" for c in constraints), transcript[-1500:])

        # Parse response: expect WRITE(...) KEY(...) WAIT(...) DONE()
        m = re.search(r"(WRITE|KEY|WAIT|DONE)\(([^)]*)\)", raw, re.IGNORECASE)
        if m:
            kind = m.group(1).upper()
            val = m.group(2).strip().strip("'\"")
            # Safety: block CTRL_C if the current screen shows live work
            if kind == "KEY" and val.upper() == "CTRL_C":
                if self._current_screen_working():
                    self._log("  [fallback] LLM suggested CTRL_C but process is working — WAIT")
                    return PTYAction("WAIT", "3000")
            return PTYAction(kind, val)  # type: ignore[arg-type]

        self._log(f"  [fallback] LLM response not parseable: {raw[:60]!r}")
        return PTYAction("WAIT", "2000")

    def _transcript_text(self) -> str:
        return "".join(self._transcript)


# ── Helpers ────────────────────────────────────────────────────────────────────

_KEY_MAP: dict[str, str] = {
    "ENTER": "\r",
    "ARROW_DOWN": "\x1b[B",
    "ARROW_UP": "\x1b[A",
    "ARROW_LEFT": "\x1b[D",
    "ARROW_RIGHT": "\x1b[C",
    "SPACE": " ",
    "TAB": "\t",
    "CTRL_C": "\x03",
    "CTRL_D": "\x04",
    "BACKSPACE": "\x7f",
    "ESCAPE": "\x1b",
}


# Answerable-prompt glyphs/patterns: a radio/list cursor, an unselected marker,
# a (y/N) confirm, or a trailing question. If any is on the CURRENT screen, the
# process is waiting for INPUT — it is NOT "actively working", so we must answer
# it (via driver/LLM) rather than WAIT forever.
_ANSWERABLE_RE = re.compile(
    r"[❯●◆►▶○◯]\s*\S"  # radio/list markers with an option
    r"|\(y[/|]n\)|\[y[/|]n\]"  # confirm
    r"|\?\s*$|›\s|»\s",  # trailing question / input caret
    re.IGNORECASE | re.MULTILINE,
)


def _has_answerable_prompt(rows: list[str]) -> bool:
    text = "\n".join(rows[-8:]) if rows else ""
    return bool(_ANSWERABLE_RE.search(text))


def _content_hash(rows: list[str]) -> str:
    """
    Hash the screen content, ignoring spinner characters.
    Stable when only spinners change.
    """
    joined = "\n".join(rows)
    stripped = _SPINNER_RE.sub("", joined)
    return str(hash(stripped[-800:]))


def _prompt_summary(prompt) -> str:
    """One-line summary of a prompt for logging."""
    match prompt:
        case ShellPrompt(cwd=cwd):
            return f"cwd={cwd}"
        case ErrorPrompt(message=m):
            return m[:60]
        case SpinnerPrompt(text=t):
            return t[:60]
        case _ if hasattr(prompt, "question"):
            return getattr(prompt, "question", "")[:60]
        case _ if hasattr(prompt, "title"):
            return getattr(prompt, "title", "")[:60]
        case _:
            return ""
