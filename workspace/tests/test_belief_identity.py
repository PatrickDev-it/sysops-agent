"""The agent's primary workflow: the tool is missing, install it, then use it.

It deadlocked, permanently, on every tool whose name contains a dash.

Belief keys were bare f-strings built at seven call sites with NO normalization, while
`world.norm_alias` folded dashes to underscores because pip reports `yt-dlp` as `yt_dlp`.
Inside ONE function, `_extract_facts_from_success`, both spellings were written:

    reasoning.py:722  pkg_from_cmd = match.group(1).lower().replace("-", "_")   -> "yt_dlp"
    reasoning.py:725  assert_belief(f"{pkg_from_cmd}:exists", 1.0,
                                    evidence="pip install succeeded — clearing any prior REFUTED")
    reasoning.py:931  tool = _real_tool(command)                                -> "yt-dlp"
    reasoning.py:933  if beliefs.is_refuted(f"{tool}:exists"):                  -> the OTHER key

So: DISCOVERY fails, `yt-dlp:exists` is REFUTED, recovery runs `pip install yt-dlp`, it
SUCCEEDS, `yt_dlp:exists` becomes PROVEN — and `yt-dlp:exists` is still REFUTED, so every
subsequent MODIFY step is vetoed and the plan halts. The comment at line 726 described a
clearing the code could not perform.

`test_world.py` asserted on `"yt_dlp:exists"`, the WRITER's spelling, and passed. Nothing
tested the writer and the reader against each other, which is the only thing that mattered.
"""

import pytest
from src.error_classifier import ErrorClass
from src.reasoning import BeliefKey, EvidenceKind, Predicate, ReasoningContext, _bkey
from src.world import norm_alias


def _ctx() -> ReasoningContext:
    return ReasoningContext(objective="download a video", run_id="test_run")


@pytest.mark.parametrize(
    "spelling", ["yt-dlp", "yt_dlp", "YT-DLP", "yt-dlp.exe", "/usr/local/bin/yt-dlp"]
)
def test_every_spelling_of_a_tool_is_one_belief_subject(spelling):
    assert _bkey(spelling, "exists") == BeliefKey("yt_dlp", Predicate.EXISTS)


def test_the_belief_key_agrees_with_the_world_graph():
    """Two identity models is the defect. There is one canonicaliser, and both use it."""
    assert _bkey("yt-dlp", "exists").subject == norm_alias("yt-dlp")


def _discovery_fails(ctx, tool: str) -> None:
    ctx.post_step_update(
        step_id="step_0",
        command=f"locate|{tool}",
        success=False,
        error_class=ErrorClass.FILE_NOT_FOUND,
        output=f"{tool}: not found",
        step_type="DISCOVERY",
    )


def _install_succeeds(ctx, tool: str) -> None:
    ctx.post_step_update(
        step_id="step_1",
        command=f"pip install {tool}",
        success=True,
        error_class=None,
        output=f"Successfully installed {tool}-2024.1.1",
        step_type="RECOVER",
    )


@pytest.mark.parametrize(
    "tool,invocation",
    [
        ("yt-dlp", "yt-dlp -x https://example/v"),  # the dashed name: deadlocked
        ("ffmpeg", "ffmpeg -i in.mp4 out.mp4"),  # control: never affected
    ],
)
def test_install_after_a_failed_discovery_unblocks_execution(tool, invocation):
    """The deadlock, end to end. This is the assertion nobody had written.

    The dashless control case is parametrised alongside it so the fix is shown to be about
    IDENTITY and not about pip: both must behave identically, and before the change only the
    second one did.
    """
    ctx = _ctx()
    _discovery_fails(ctx, tool)
    assert ctx.beliefs.is_refuted(_bkey(tool, "exists"))

    allowed, _ = ctx.pre_execute_check(invocation, "step_a", "MODIFY")
    assert not allowed, "a confirmed-absent tool must be blocked before it is invoked"

    _install_succeeds(ctx, tool)

    allowed, reason = ctx.pre_execute_check(invocation, "step_b", "MODIFY")
    assert allowed, (
        f"{tool}: the install succeeded but execution is still blocked ({reason}). That is the "
        f"deadlock — the success was recorded under one spelling and the veto reads another."
    )


def test_no_belief_key_is_built_without_the_canonicaliser():
    """Structural guard: a raw f-string key would reintroduce the writer/reader split silently.

    Checked over the AST, not the text. The explanatory comments in `reasoning.py` quote the
    original defective lines verbatim, and a guard that flags its own documentation is a guard
    somebody deletes.
    """
    import ast

    from src import config

    tree = ast.parse((config.SRC / "reasoning.py").read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        # A belief lookup whose argument is a literal string rather than a BeliefKey.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("is_proven", "is_refuted", "observe")
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            offenders.append(f"line {node.lineno}: {node.func.attr}({node.args[0].value!r})")
        # An f-string passed AS A KEY to a belief call. Restricted to call arguments on
        # purpose: `conclusions.append(f"REFUTED: {tool}:exists")` is human-readable log text,
        # and a guard that cannot tell a key from a sentence gets switched off.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("is_proven", "is_refuted", "observe", "get")
            and node.args
            and isinstance(node.args[0], ast.JoinedStr)
        ):
            offenders.append(f"line {node.lineno}: f-string passed to {node.func.attr}()")
    assert not offenders, (
        f"belief key(s) built without BeliefKey: {offenders}. Every key must go through the "
        f"one canonicaliser, or the writer and the reader drift apart again."
    )


# ── Beliefs cannot exist independently of world entities ─────────────────────


def test_every_belief_subject_is_known_to_the_world():
    """Two identity models is the defect; one shared population is the fix.

    A belief is now expressible only about a name the world graph carries. Registration is
    deliberately weaker than node creation: "the agent has a belief about yt-dlp" is not the
    claim "yt-dlp exists as an executable at a path", and conflating the two would make the
    world graph assert things nobody observed.
    """
    from src.state import SystemState

    ss = SystemState(".")
    ss.init_reasoning("install yt-dlp and use it")
    ss.reasoning.observe_belief(
        BeliefKey.of("yt-dlp", Predicate.EXISTS),
        holds=True,
        kind=EvidenceKind.PROBE_DIRECT,
        detail="located",
    )
    ss.reasoning.observe_belief(
        BeliefKey.of("FFmpeg.exe", Predicate.INSTALLED),
        holds=True,
        kind=EvidenceKind.PACKAGE_MANAGER,
        detail="pip report",
    )

    subjects = ss.reasoning.beliefs.subjects()
    assert subjects <= ss.world.known_subjects(), (
        f"belief subjects {subjects - ss.world.known_subjects()} are unknown to the world graph"
    )


def test_the_world_records_the_canonical_spelling_not_the_one_written():
    from src.state import SystemState

    ss = SystemState(".")
    ss.init_reasoning("g")
    ss.reasoning.observe_belief(
        BeliefKey.of("/usr/local/bin/YT-DLP.exe", Predicate.EXISTS),
        holds=True,
        kind=EvidenceKind.PROBE_DIRECT,
        detail="located",
    )
    assert ss.world.known_subjects() == {"yt_dlp"}


def test_a_predicate_outside_the_vocabulary_is_rejected():
    """`f"{tool}:instaled"` was previously a belief nobody would ever read."""
    with pytest.raises(ValueError):
        _bkey("yt-dlp", "instaled")


def test_belief_keys_are_values_not_strings():
    """Identity cannot depend on formatting: two keys built from different spellings of the
    same thing must be the SAME value, and usable as a dict key."""
    a = _bkey("yt-dlp", "exists")
    b = _bkey("YT_DLP.exe", "exists")
    assert a == b and hash(a) == hash(b)
    assert {a: 1}[b] == 1
