"""
Persistent memory — SQLite tables + context cache.

ORIGINAL (v1):
  events       — episodic execution log (preserved, unchanged)

NEW (v2):
  semantic_facts      — typed propositions extracted from events (not raw logs)
  failed_assumptions  — assumptions that were proven false + their invalidation condition
  decisions           — decisions made during a run + their outcomes (scored retrospectively)
  causal_edges        — action → state_change → result triples (causal graph)

Public API additions (fully backward-compatible):
  save_semantic_fact(run_id, key, value, confidence, goal)
  get_semantic_facts(goal=None, run_id=None) → list[dict]
  save_failed_assumption(run_id, assumption, evidence, error_class, invalid_until, goal)
  get_failed_assumptions(goal=None, run_id=None) → list[dict]
  save_decision(run_id, step_id, decision, reason, expected_outcome, goal) → int
  resolve_decision(decision_id, actual_outcome, success)
  get_decision_score(decision_pattern) → float
  save_causal_edge(run_id, action, action_class, state_before, state_after, result, error_class, goal)
  get_causal_pattern(action_class, error_class=None) → list[dict]

Retention policy:
  events          — pruned after 7 days (configurable)
  semantic_facts  — pruned after 30 days; last-known value for a key is kept forever
  failed_assumptions — pruned after 14 days; same key+goal combo deduped
  decisions       — kept indefinitely (lightweight; used for pattern scoring)
  causal_edges    — pruned after 30 days
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import config
from .config import (
    MEMORY_WINDOW,
)
from .redact import redact


# ── Where the store lives — resolved per CALL, never frozen at import ────────
# These were five module constants computed from `config.MEMORY_DIR` at import time. That
# made config the *nominal* owner of the layout and this module the effective one: reassigning
# `config.MEMORY_DIR` afterwards had no effect, because the paths had already been baked.
#
# The cost was not theoretical. `tests/conftest.py` redirects only `sys.path`, so the test
# suite and `benchmarks/run_suite.py` both opened the PRODUCTION store — and `Orchestrator.run`
# calls `clear_session_events()` on startup. Every benchmark run wiped the operator's episodic
# events and wrote its own synthetic cases in their place, which then appeared as `history` in
# the next real run's planner prompt. The measurement contaminated the thing it measured, and
# the indirection missing here is the mechanical reason it could not be fixed from config.
def _memory_dir() -> Path:
    d = config.MEMORY_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _db_path() -> Path:
    return _memory_dir() / "episodic.db"


def _cache_path() -> Path:
    return _memory_dir() / "context_cache.json"


def _objective_path() -> Path:
    return _memory_dir() / "objective.md"


def _terminal_state_path() -> Path:
    return _memory_dir() / "terminal_state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    # WAL + a real busy timeout: the default rollback journal takes an exclusive lock for every
    # write, so a second agent (or a benchmark running beside a session) hit
    # `database is locked` after 5 s and aborted the run mid-step — possibly after a partial
    # system mutation. save_event is called from eighteen sites with no handler.
    conn = sqlite3.connect(_db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# ── Schema ─────────────────────────────────────────────────────────────────


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            -- ── v1 tables (unchanged) ─────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT,
                goal        TEXT,
                cwd         TEXT,
                command     TEXT,
                stdout      TEXT,
                exit_code   INTEGER,
                outcome     TEXT,
                step_index  INTEGER
            );
            -- ── v2 tables (additive) ───────────────────────────────────────────

            -- Semantic memory: typed propositions extracted from observations.
            -- key examples: "tool_scope:yt-dlp", "tool_path:python", "tool_version:git"
            -- value: the extracted value ("venv", "C:/Python312/python.exe", "2.43.0")
            -- Unique per key: UPSERT on conflict so newest value wins.
            CREATE TABLE IF NOT EXISTS semantic_facts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          TEXT,
                key             TEXT NOT NULL,
                value           TEXT NOT NULL,
                confidence      REAL DEFAULT 1.0,
                source          TEXT DEFAULT '',
                goal            TEXT DEFAULT '',
                created_at      TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_key
                ON semantic_facts(key);

            -- Negative memory: assumptions proven false.
            -- assumption: "yt-dlp exists on PATH"
            -- invalid_until: "global install of yt-dlp completes"
            CREATE TABLE IF NOT EXISTS failed_assumptions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          TEXT,
                assumption      TEXT NOT NULL,
                evidence        TEXT DEFAULT '',
                error_class     TEXT DEFAULT '',
                invalid_until   TEXT DEFAULT '',
                goal            TEXT DEFAULT '',
                failed_at       TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_fa_goal
                ON failed_assumptions(goal);

            -- Decision memory: every non-trivial decision with outcome.
            -- success: -1=pending, 0=failed, 1=succeeded
            CREATE TABLE IF NOT EXISTS decisions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          TEXT,
                step_id         TEXT,
                decision        TEXT NOT NULL,
                reason          TEXT DEFAULT '',
                evidence        TEXT DEFAULT '',   -- JSON array of fact keys
                expected_outcome TEXT DEFAULT '',
                actual_outcome  TEXT DEFAULT '',
                success         INTEGER DEFAULT -1,
                goal            TEXT DEFAULT '',
                ts              TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_dec_decision
                ON decisions(decision);

            -- Causal graph: action → state_change → result triples.
            -- state_before/state_after: JSON snapshots of relevant world-model subset.
            CREATE TABLE IF NOT EXISTS causal_edges (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          TEXT,
                action          TEXT NOT NULL,
                action_class    TEXT DEFAULT '',   -- "package_install", "discovery", etc.
                state_before    TEXT DEFAULT '{}', -- JSON
                state_after     TEXT DEFAULT '{}', -- JSON
                result          TEXT DEFAULT '',   -- "success" | "failure" | "partial"
                error_class     TEXT DEFAULT '',
                goal            TEXT DEFAULT '',
                ts              TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ce_action_class
                ON causal_edges(action_class, result);
        """)


# ── v1 API (unchanged) ─────────────────────────────────────────────────────


def prune_old_events(days: int = 7) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _connect() as conn:
        conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))


def clear_session_events() -> None:
    """Wipe episodic events at the start of a new run. Regressions and v2 tables kept."""
    with _connect() as conn:
        conn.execute("DELETE FROM events")
    _save_cache({"last_events": [], "summary": "", "objective": ""})


def save_event(
    goal: str,
    cwd: str,
    command: str,
    stdout: str,
    exit_code: int,
    outcome: str,
    step_index: int = 0,
) -> None:
    # Redact at the sink, not at the call sites. `save_event` is reached from eighteen places
    # in the orchestrator, and a rule that every one of them must remember to apply is a rule
    # that holds until someone adds the nineteenth. The command line is the exposure that
    # matters here: `git clone https://user:token@host/repo` and `--password` flags were being
    # stored verbatim, and this table is read back into the planner prompt as `history`.
    goal, cwd, command = redact(goal), redact(cwd), redact(command)
    stdout = redact(stdout[:512])
    with _connect() as conn:
        conn.execute(
            "INSERT INTO events "
            "(ts,goal,cwd,command,stdout,exit_code,outcome,step_index) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (_now(), goal, cwd, command, stdout, exit_code, outcome, step_index),
        )
    _update_cache(goal, cwd, command, exit_code, outcome)


def _update_cache(goal: str, cwd: str, command: str, exit_code: int, outcome: str) -> None:
    cache = _load_cache()
    cache["last_events"].append(
        {
            "ts": _now(),
            "goal": goal,
            "cwd": cwd,
            "command": command,
            "exit_code": exit_code,
            "outcome": outcome,
        }
    )
    if len(cache["last_events"]) > MEMORY_WINDOW:
        cache["last_events"] = cache["last_events"][-MEMORY_WINDOW:]
    _save_cache(cache)


def _load_cache() -> dict:
    if _cache_path().exists():
        try:
            return json.loads(_cache_path().read_text())
        except Exception:
            pass
    return {"summary": "", "last_events": []}


def _save_cache(cache: dict) -> None:
    _cache_path().write_text(json.dumps(cache, indent=2))


def get_recent_events(n: int = MEMORY_WINDOW) -> list[dict]:
    return _load_cache()["last_events"][-n:]


def get_summary() -> str:
    return _load_cache().get("summary", "")


def consolidate(new_summary: str) -> None:
    cache = _load_cache()
    cache["summary"] = new_summary
    cache["last_events"] = cache["last_events"][-MEMORY_WINDOW:]
    _save_cache(cache)


def save_terminal_state(snapshot: str, cwd: str) -> None:
    _terminal_state_path().write_text(
        json.dumps(
            {
                "snapshot": snapshot,
                "cwd": cwd,
                "ts": _now(),
            },
            indent=2,
        )
    )


def get_terminal_state() -> dict:
    if _terminal_state_path().exists():
        try:
            return json.loads(_terminal_state_path().read_text())
        except Exception:
            pass
    return {"snapshot": "", "cwd": "", "ts": ""}


def set_objective(goal: str) -> None:
    _objective_path().write_text(f"# Current Objective\n\n{goal}\n")


def get_objective() -> str:
    if _objective_path().exists():
        text = _objective_path().read_text()
        lines = [line for line in text.splitlines() if line and not line.startswith("#")]
        return " ".join(lines).strip()
    return ""


# ── v2 API — Semantic Memory ──────────────────────────────────────────────


def save_semantic_fact(
    run_id: str,
    key: str,
    value: str,
    confidence: float = 1.0,
    goal: str = "",
    source: str = "",
) -> None:
    """Upsert a semantic fact. Latest value for a key always wins."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO semantic_facts (run_id, key, value, confidence, source, goal, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value=excluded.value,
                 confidence=excluded.confidence,
                 source=excluded.source,
                 run_id=excluded.run_id,
                 created_at=excluded.created_at""",
            (run_id, key, value, confidence, source, goal, _now()),
        )


def get_semantic_facts(
    goal: Optional[str] = None,
    run_id: Optional[str] = None,
) -> list[dict]:
    """Return semantic facts, optionally filtered by goal or run_id."""
    with _connect() as conn:
        if goal and run_id:
            rows = conn.execute(
                "SELECT * FROM semantic_facts WHERE goal=? OR run_id=? ORDER BY created_at DESC",
                (goal, run_id),
            ).fetchall()
        elif goal:
            rows = conn.execute(
                "SELECT * FROM semantic_facts WHERE goal=? ORDER BY created_at DESC", (goal,)
            ).fetchall()
        elif run_id:
            rows = conn.execute(
                "SELECT * FROM semantic_facts WHERE run_id=? ORDER BY created_at DESC", (run_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM semantic_facts ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [dict(r) for r in rows]


def prune_semantic_facts(days: int = 30) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _connect() as conn:
        # Keep at least one row per key (the most recent)
        conn.execute(
            """
            DELETE FROM semantic_facts
            WHERE created_at < ?
              AND id NOT IN (
                SELECT MAX(id) FROM semantic_facts GROUP BY key
              )
        """,
            (cutoff,),
        )


# ── v2 API — Negative Memory ──────────────────────────────────────────────


def save_failed_assumption(
    run_id: str,
    assumption: str,
    evidence: str,
    error_class: str,
    invalid_until: str,
    goal: str = "",
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO failed_assumptions
               (run_id, assumption, evidence, error_class, invalid_until, goal, failed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, assumption, evidence[:400], error_class, invalid_until, goal, _now()),
        )


def get_failed_assumptions(
    goal: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    with _connect() as conn:
        if goal:
            rows = conn.execute(
                "SELECT * FROM failed_assumptions WHERE goal=? ORDER BY failed_at DESC LIMIT ?",
                (goal, limit),
            ).fetchall()
        elif run_id:
            rows = conn.execute(
                "SELECT * FROM failed_assumptions WHERE run_id=? ORDER BY failed_at DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM failed_assumptions ORDER BY failed_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def prune_failed_assumptions(days: int = 14) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _connect() as conn:
        conn.execute("DELETE FROM failed_assumptions WHERE failed_at < ?", (cutoff,))


# ── v2 API — Decision Memory ──────────────────────────────────────────────


def save_decision(
    run_id: str,
    step_id: str,
    decision: str,
    reason: str = "",
    expected_outcome: str = "",
    goal: str = "",
    evidence: Optional[list[str]] = None,
) -> int:
    """Returns the row id of the saved decision (for later resolution)."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO decisions
               (run_id, step_id, decision, reason, evidence, expected_outcome, goal, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                step_id,
                decision,
                reason,
                json.dumps(evidence or []),
                expected_outcome,
                goal,
                _now(),
            ),
        )
        return cur.lastrowid or -1


def resolve_decision(decision_id: int, actual_outcome: str, success: bool) -> None:
    """Record what actually happened after a decision was made."""
    with _connect() as conn:
        conn.execute(
            "UPDATE decisions SET actual_outcome=?, success=? WHERE id=?",
            (actual_outcome[:300], 1 if success else 0, decision_id),
        )


def get_decision_score(decision_pattern: str) -> float:
    """
    Return the historical success rate (0.0–1.0) for decisions matching this pattern.
    Returns 0.5 if no history (neutral — no evidence either way).
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT success FROM decisions WHERE decision LIKE ? AND success != -1",
            (f"%{decision_pattern}%",),
        ).fetchall()
    if not rows:
        return 0.5  # no evidence
    successes = sum(1 for r in rows if r["success"] == 1)
    return successes / len(rows)


def get_decisions(run_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    with _connect() as conn:
        if run_id:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE run_id=? ORDER BY ts DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


# ── v2 API — Causal Graph ─────────────────────────────────────────────────


def save_causal_edge(
    run_id: str,
    action: str,
    action_class: str,
    state_before: dict,
    state_after: dict,
    result: str,
    error_class: str = "",
    goal: str = "",
) -> None:
    """Store an action→state_change→result triple in the causal graph."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO causal_edges
               (run_id, action, action_class, state_before, state_after, result, error_class, goal, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                action[:200],
                action_class,
                json.dumps(state_before),
                json.dumps(state_after),
                result,
                error_class,
                goal,
                _now(),
            ),
        )


def get_causal_pattern(
    action_class: str,
    error_class: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """
    Return historical causal edges matching this action class (and optionally error class).
    Used by the supervisor to reason about what typically follows from a given action type.
    """
    with _connect() as conn:
        if error_class:
            rows = conn.execute(
                """SELECT action, result, error_class, state_after
                   FROM causal_edges
                   WHERE action_class=? AND error_class=?
                   ORDER BY ts DESC LIMIT ?""",
                (action_class, error_class, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT action, result, error_class, state_after
                   FROM causal_edges
                   WHERE action_class=?
                   ORDER BY ts DESC LIMIT ?""",
                (action_class, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def prune_causal_edges(days: int = 30) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _connect() as conn:
        conn.execute("DELETE FROM causal_edges WHERE ts < ?", (cutoff,))
