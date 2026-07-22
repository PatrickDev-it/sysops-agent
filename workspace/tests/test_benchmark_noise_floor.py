"""The benchmark's noise floor, measured — and the rule that follows from it.

Two CONTROL runs of the 48-task suite, both with the artifact-capture mechanism disabled at
runtime, both at seed 42, greedy decoding, prefix cache off, oracle active. They differ only
in whether the plan grammar exposes `capture_stdout_to`, a field the runtime ignores when the
mechanism is off:

    capture OFF, field present in the grammar   32/48
    capture OFF, field absent                   28/48

Four tasks, from a change that does nothing at execution time. A fixed seed pins the RNG, not
the sample: any edit to a prompt or a grammar reshuffles which tokens are sampled, which plan
is produced, and which tasks pass.

Therefore: **no ARR difference of fewer than ~5 tasks on a single seeded run of this suite is
evidence of anything.** Three earlier conclusions in this project's history were drawn from
smaller deltas across single runs, and all three were noise:
  * "prediction confirmed / falsified", six draws read as six results (10-task pilot, temp 0.7);
  * "ARR unchanged after the predicate rework" (it went 21/48 → 32/48 once measured properly);
  * "the capture mechanism hurts, 29 vs 32" (within the floor, and the controls disagree by 4).

These constants are a contract with the next person who wants to quote a number.
"""

from src.config import ROOT

NOISE_FLOOR_TASKS = 5
SUITE_SIZE = 48

# label -> passed, all at seed 42, DETERMINISTIC=1, oracle active.
MEASURED_RUNS = {
    "cap_off": 32,  # capture off, grammar exposes the unused field
    "cap_off2": 28,  # capture off, field absent  <- inert change, -4 tasks
    "cap_on": 29,  # capture on, first implementation
    "cap_on2": 26,  # capture on, with the exit-0 gate and the self-truncation guard
}

# ── 2026-07-20: the floor was not a property of the suite. It was a defect. ──
#
# Two runs of IDENTICAL code scored 34 and 39. Localising the divergence per template, on the
# first call of each task, found it entering at exactly one place:
#
#     safety.jinja        prompts identical  48/48     (receives no history)
#     prompt_enhancer     prompts identical  47/47     (receives no history)
#     supervisor.jinja    prompts identical   0/47     (receives history)
#
# and where the prompts were identical the outputs were identical 95 times out of 95 — the
# inference stack was never implicated. `Supervisor.plan` feeds `memory.get_recent_events()`
# into the planner prompt, and that store is process-wide: it accumulated across the 48 tasks
# and SURVIVED INTO THE NEXT RUN. Task T01 planned on the events T47 of the previous run left
# behind. The suite was not 48 independent trials; it was one dependent 48-step sequence,
# seeded by whatever was lying around.
#
# With one memory directory per task (`run_suite.task_memory_dir`):
ISOLATED_RUNS = {"iso_a": 32, "iso_b": 32}

# Per-template prompt stability after the fix, first call of each task:
#     supervisor.jinja   39/39 identical   (was 0/47)
#     safety.jinja       48/48
#     prompt_enhancer    45/45
#     executor.jinja     29/35   mean diff 5.2 tokens
#     verify.jinja       37/39   mean diff 0.6 tokens
#
# The planning path is now deterministic. The residue sits in the EXECUTION templates, which
# receive the stdout/stderr of real commands run against a live machine — a probe of the
# process table genuinely returns different bytes each time. That part is the agent's job,
# not a defect, and freezing it would measure a fictional machine.
PLANNING_PROMPTS_IDENTICAL = (39, 39)  # supervisor.jinja, after the fix
PLANNING_PROMPTS_IDENTICAL_BEFORE = (0, 47)


def test_an_inert_change_moved_the_score_by_more_than_the_effect_under_test():
    inert_delta = abs(MEASURED_RUNS["cap_off"] - MEASURED_RUNS["cap_off2"])
    effect_delta = abs(MEASURED_RUNS["cap_off"] - MEASURED_RUNS["cap_on"])
    assert inert_delta >= effect_delta, (
        "if this ever fails, the suite got quieter and the noise floor can be lowered"
    )
    assert inert_delta < NOISE_FLOOR_TASKS + 1


def test_no_run_beat_the_control():
    control = max(MEASURED_RUNS["cap_off"], MEASURED_RUNS["cap_off2"])
    assert max(MEASURED_RUNS["cap_on"], MEASURED_RUNS["cap_on2"]) < control


def test_the_mechanism_ships_disabled_until_it_has_evidence():
    from src import config

    assert not config.ARTIFACT_CAPTURE


def test_isolating_the_tasks_removed_the_run_to_run_swing():
    """The pair that differs by nothing must now score the same."""
    scores = sorted(ISOLATED_RUNS.values())
    assert scores[-1] - scores[0] == 0, (
        "two runs of identical code disagreeing again means task independence regressed"
    )


def test_the_planner_prompt_is_deterministic_now():
    same, total = PLANNING_PROMPTS_IDENTICAL
    assert same == total, "the planner's first prompt must not vary between runs"
    before_same, before_total = PLANNING_PROMPTS_IDENTICAL_BEFORE
    assert before_same < before_total, "the 'before' figure must record a real defect"


def test_the_benchmark_harness_still_isolates_memory_per_task():
    """A behavioural guard lives in tests/test_benchmark_task_isolation.py; this one keeps the
    numbers above honest by pinning that the seam is still wired where they were measured."""
    from benchmarks.run_suite import task_memory_dir

    assert task_memory_dir("x", "T01") != task_memory_dir("x", "T02")


def test_the_paired_analyser_exists_and_refuses_underpowered_claims():
    src = ROOT / "benchmarks" / "ab_paired.py"
    text = src.read_text(encoding="utf-8")
    assert "McNemar" in text
    assert "cannot resolve an effect smaller than that" in text
