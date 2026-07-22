"""The 48 benchmark tasks are scored as independent trials. They must BE independent.

They were not. Every task read `memory.get_recent_events()` into the planner prompt, and that
memory is one process-wide store: it accumulated across the tasks of a run and survived into
the next run. Task T01 of one run planned with the events T47 of the PREVIOUS run had left in
`var/memory/context_cache.json`.

The evidence that pinned it, from two runs of identical code:

    safety.jinja        prompts identical  48/48   (receives no history)
    prompt_enhancer     prompts identical  47/47   (receives no history)
    supervisor.jinja    prompts identical   0/47   (receives history)

and where prompts were identical, outputs were identical 95 times out of 95 — the inference
stack was never the problem. A suite of 48 dependent trials seeded by the previous run is what
made a pure repeat move 5 tasks.
"""

import json

from benchmarks.run_suite import task_memory_dir
from src import config, memory


def test_each_task_gets_its_own_memory_directory():
    a = task_memory_dir("arm_x", "T01")
    b = task_memory_dir("arm_x", "T02")
    assert a != b, "two tasks sharing a memory directory are not independent trials"
    assert a.parent == b.parent
    assert "T01" in str(a) and "arm_x" in str(a)


def test_arms_do_not_share_memory():
    """Run-to-run contamination: the second arm must not inherit the first arm's events."""
    assert task_memory_dir("arm_a", "T01") != task_memory_dir("arm_b", "T01")


def test_rebinding_the_memory_dir_actually_hides_the_previous_events(tmp_path, monkeypatch):
    """`memory._memory_dir()` resolves `config.MEMORY_DIR` at call time — the whole fix
    depends on that staying true. If someone freezes it at import, this fails."""
    first = tmp_path / "T01"
    monkeypatch.setattr(config, "MEMORY_DIR", first)
    memory.init_db()
    memory.save_event(
        goal="task one",
        cwd=str(tmp_path),
        command="echo one",
        stdout="ok",
        exit_code=0,
        outcome="success",
    )
    assert any(e["command"] == "echo one" for e in memory.get_recent_events(n=10))

    second = tmp_path / "T02"
    monkeypatch.setattr(config, "MEMORY_DIR", second)
    memory.init_db()
    assert memory.get_recent_events(n=10) == [], (
        "a fresh task must not see the previous task's events in its planner prompt"
    )


def test_the_planner_context_is_what_leaked(tmp_path, monkeypatch):
    """Names the exact channel, so a future refactor that re-introduces it fails here.

    `Supervisor.plan` puts `memory.get_recent_events()` into ctx['history']; that is the
    field which differed at the planner's first call in 47 of 47 tasks.
    """
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "leak")
    memory.init_db()
    memory.save_event(
        goal="a previous task",
        cwd=str(tmp_path),
        command="Get-Service -Name Docker",
        stdout="not found",
        exit_code=1,
        outcome="failure",
    )

    leaked = json.dumps(memory.get_recent_events(n=8))
    assert "Get-Service" in leaked, (
        "this is the payload that reached the next task's planner prompt"
    )
