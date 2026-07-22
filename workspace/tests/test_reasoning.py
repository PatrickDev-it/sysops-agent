"""
Verification tests for the reasoning system.

Run: python -m pytest tests/test_reasoning.py -v
"""

import json
import sys

from src.error_classifier import ErrorClass
from src.reasoning import (
    AttentionManager,
    BeliefState,
    BeliefSystem,
    EvidenceKind,
    ReasoningContext,
    SemanticFact,
    WorkingMemory,
    _bkey,
)


def _ctx(goal: str = "test goal") -> ReasoningContext:
    return ReasoningContext(objective=goal, run_id="test_run")


# ── BeliefSystem ─────────────────────────────────────────────────────────────

# ── InferenceEngine — semantic fact extraction ────────────────────────────────


def test_locate_output_sets_tool_path_belief():
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        "locate|python",
        True,
        None,
        "python -> C:/Python312/python.exe\ndirectory: C:/Python312",
        "DISCOVERY",
    )
    assert ctx.beliefs.is_proven(_bkey("python", "exists"))
    assert "tool_path:python" in ctx.semantic_facts
    assert ctx.semantic_facts["tool_path:python"].value == "C:/Python312/python.exe"


def test_pip_install_success_sets_scope():
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        "pip install yt-dlp --break-system-packages",
        True,
        None,
        "Successfully installed yt-dlp-2024.8.6",
        "MODIFY",
    )
    assert ctx.beliefs.is_proven(_bkey("yt_dlp", "installed"))
    assert "tool_scope:yt-dlp" in ctx.semantic_facts
    assert ctx.semantic_facts["tool_scope:yt-dlp"].value == "global"


def test_venv_pip_install_sets_venv_scope():
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        ".venv/Scripts/pip install requests",
        True,
        None,
        "Successfully installed requests-2.31.0",
        "MODIFY",
    )
    assert ctx.beliefs.is_proven(_bkey("requests", "installed"))
    b = ctx.beliefs.get(_bkey("requests", "scope_is_venv"))
    assert b is not None and b.state == BeliefState.PROVEN


def test_verify_step_extracts_version():
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        "yt-dlp --version",
        True,
        None,
        "yt-dlp 2024.8.6",
        "VERIFY",
    )
    assert "tool_version:yt-dlp" in ctx.semantic_facts
    assert ctx.semantic_facts["tool_version:yt-dlp"].value == "2024.8.6"
    # A version string scraped out of stdout is OUTPUT_HEURISTIC, the weakest evidence
    # class. It used to be asserted at score 1.0, indistinguishable from a direct probe.
    b = ctx.beliefs.get(_bkey("yt_dlp", "version_known"))
    assert b is not None and b.state == BeliefState.POSSIBLE
    assert b.support.kind is EvidenceKind.OUTPUT_HEURISTIC


def test_reasoning_debug_dump_is_json_serializable():
    ctx = _ctx()
    ctx.observe_belief(
        _bkey("python", "exists"),
        holds=True,
        kind=EvidenceKind.PROBE_DIRECT,
        detail="located on PATH",
    )

    payload = ctx.debug_dump()

    assert json.loads(json.dumps(payload))["beliefs"]["python:exists"] == {
        "state": "proven",
        "support": "PROBE_DIRECT",
        "against": None,
    }


# ── InferenceEngine — failure inference ───────────────────────────────────────


def test_discovery_fail_refutes_existence():
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        "locate|yt-dlp",
        False,
        ErrorClass.FILE_NOT_FOUND,
        "yt-dlp: not found",
        "DISCOVERY",
    )
    assert ctx.beliefs.is_refuted(_bkey("yt_dlp", "exists"))


# ── P-C regression guard: empty/filtered discovery must NOT refute real tools ──
# (measured pathology in full-safe30-p013: netstat/Get-NetRoute/reg wrongly
#  refuted because a filter matched nothing; single owner = error_classifier.)


def test_missing_tool_signal_owner():
    from src.error_classifier import is_missing_tool_signal

    # genuine absence
    assert is_missing_tool_signal("'foo' is not recognized as a cmdlet", "foo x")
    assert is_missing_tool_signal("bash: bar: command not found", "bar")
    assert is_missing_tool_signal("yt-dlp: not found on PATH", "locate|yt-dlp")
    # inconclusive / not-tool-absence  → must be False
    assert not is_missing_tool_signal("", "netstat -an | findstr DNS")
    assert not is_missing_tool_signal("Cannot find path 'C:\\x'", "Get-Content x")  # file, not tool
    assert not is_missing_tool_signal(
        "grep: is not recognized", "grep foo"
    )  # unix builtin → wrong shell


def test_empty_discovery_does_not_refute_real_tool():
    ctx = _ctx()
    # netstat exists; the pipe filter simply matched nothing → empty output.
    ctx.post_step_update(
        "s0",
        'netstat -an | Select-String -Pattern "DNS"',
        False,
        None,
        "",
        "DISCOVERY",
    )
    assert not ctx.beliefs.is_refuted(_bkey("netstat", "exists"))
    # and a later invocation of the same tool is NOT policy-blocked
    allow, _ = ctx.pre_execute_check("netstat -an", "s1", "MODIFY")
    assert allow


def test_genuine_missing_signal_still_refutes_in_discovery():
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        "winget --version",
        False,
        ErrorClass.FILE_NOT_FOUND,
        "The term 'winget' is not recognized as the name of a cmdlet",
        "DISCOVERY",
    )
    assert ctx.beliefs.is_refuted(_bkey("winget", "exists"))


def test_env_scope_mismatch_refutes_global_and_adds_constraint():
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        "pip install yt-dlp",
        False,
        ErrorClass.ENV_SCOPE_MISMATCH,
        "not recognized as a cmdlet",
        "MODIFY",
    )
    assert ctx.beliefs.is_refuted(_bkey("pip", "available_globally"))
    assert any("global" in c.lower() for c in ctx.working_memory.active_constraints)


def test_invalid_exe_blocks_write_file_to_path():
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        "C:/tools/yt-dlp.exe",
        False,
        ErrorClass.INVALID_EXECUTABLE,
        "is not a valid win32 application",
        "MODIFY",
    )
    # write_file:path should be in blocked_actions
    blocked, _ = ctx.working_memory.is_blocked("write_file:C:/tools/yt-dlp.exe")
    assert blocked


def test_syntax_error_blocks_unchanged_retry():
    ctx = _ctx()
    cmd = "pip install --badarg yt-dlp"
    ctx.post_step_update(
        "s0", cmd, False, ErrorClass.COMMAND_SYNTAX, "invalid option --badarg", "MODIFY"
    )
    import hashlib

    h = hashlib.md5(cmd.encode()).hexdigest()[:8]
    blocked, _ = ctx.working_memory.is_blocked(f"retry_exact:{h}")
    assert blocked


# ── ExecutionPolicyGuard ──────────────────────────────────────────────────────


def test_refuted_tool_blocks_invocation_but_not_verify():
    ctx = _ctx()
    ctx.post_step_update(
        "s0", "locate|yt-dlp", False, ErrorClass.FILE_NOT_FOUND, "not found", "DISCOVERY"
    )
    assert ctx.beliefs.is_refuted(_bkey("yt_dlp", "exists"))
    # Invoking the tool for its primary purpose (MODIFY) is blocked…
    allow, reason = ctx.pre_execute_check("yt-dlp https://example.com/video", "step_run", "MODIFY")
    assert not allow
    assert "REFUTED" in reason or "BLOCKED" in reason
    # …but VERIFY stays allowed by design: it is the mechanism that recovers
    # from a false REFUTED state (guard anti-deadlock exemption).
    allow, _ = ctx.pre_execute_check("yt-dlp --version", "step_v", "VERIFY")
    assert allow


def test_refuted_tool_allows_install():
    ctx = _ctx()
    ctx.post_step_update(
        "s0", "locate|yt-dlp", False, ErrorClass.FILE_NOT_FOUND, "not found", "DISCOVERY"
    )
    # Install should still be allowed (it's how we fix the refuted state)
    allow, _ = ctx.pre_execute_check("pip install yt-dlp", "step_install", "MODIFY")
    assert allow


def test_refuted_tool_allows_discovery():
    ctx = _ctx()
    ctx.beliefs.observe(
        _bkey("tool", "exists"), holds=False, kind=EvidenceKind.PROBE_DIRECT, detail="initial setup"
    )
    # A DISCOVERY step for the same tool should still be allowed
    allow, _ = ctx.pre_execute_check("locate|tool", "step_d", "DISCOVERY")
    assert allow


def test_write_file_to_blocked_exe_path_is_blocked():
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        "C:/tools/yt-dlp.exe",
        False,
        ErrorClass.INVALID_EXECUTABLE,
        "is not a valid win32 application",
        "MODIFY",
    )
    allow, reason = ctx.pre_execute_check(
        "write_file|C:/tools/yt-dlp.exe|fake repair content", "step_w", "RECOVER"
    )
    assert not allow
    assert "BLOCKED" in reason


def test_exact_syntax_retry_is_blocked():
    ctx = _ctx()
    bad_cmd = "pip install --garbage-flag yt-dlp"
    ctx.post_step_update(
        "s0", bad_cmd, False, ErrorClass.COMMAND_SYNTAX, "invalid option --garbage-flag", "MODIFY"
    )
    allow, reason = ctx.pre_execute_check(bad_cmd, "step_retry", "MODIFY")
    assert not allow
    assert "retry" in reason.lower() or "BLOCKED" in reason


def test_correct_global_install_is_allowed_after_failures():
    ctx = _ctx()
    ctx.post_step_update(
        "s0", "locate|yt-dlp", False, ErrorClass.FILE_NOT_FOUND, "not found", "DISCOVERY"
    )
    ctx.post_step_update(
        "s1", "pip install yt-dlp", False, ErrorClass.ENV_SCOPE_MISMATCH, "not recognized", "MODIFY"
    )
    # Correct global install must be allowed
    allow, _ = ctx.pre_execute_check(
        "pip install yt-dlp --break-system-packages", "step_global", "MODIFY"
    )
    assert allow


def test_proven_tool_verify_still_allowed():
    ctx = _ctx()
    # If we have NOT proven or refuted the tool, VERIFY should be allowed
    allow, _ = ctx.pre_execute_check("git --version", "step_v", "VERIFY")
    assert allow


# ── WorkingMemory ─────────────────────────────────────────────────────────────


def test_working_memory_capacity_limits():
    wm = WorkingMemory("test")
    for i in range(30):
        wm.record_failure(f"s{i}", f"cmd_{i}", f"reason_{i}", "UNKNOWN")
    assert len(wm.known_failures) <= wm.MAX_FAILURES


def test_working_memory_prompt_within_budget():
    wm = WorkingMemory("test objective")
    for i in range(20):
        wm.record_failure(f"s{i}", f"cmd_{i}", f"reason_{i}", "UNKNOWN")
        wm.add_constraint(f"constraint_{i}")
    prompt = wm.to_prompt()
    assert len(prompt) <= wm.TOKEN_BUDGET


# ── AttentionManager ──────────────────────────────────────────────────────────


def test_attention_manager_respects_budget():
    ctx = _ctx("install yt-dlp globally")
    # Flood with facts and failures
    for i in range(20):
        ctx.semantic_facts[f"tool_path:tool_{i}"] = SemanticFact(
            key=f"tool_path:tool_{i}", value=f"/usr/bin/tool_{i}", confidence=1.0
        )
        ctx.working_memory.record_failure(f"s{i}", f"cmd_{i}", f"reason_{i}", "UNKNOWN")
        ctx.beliefs.observe(
            _bkey(f"tool_{i}", "exists"),
            holds=False,
            kind=EvidenceKind.PROBE_DIRECT,
            detail=f"not found {i}",
        )
    result = ctx.get_prompt_context()
    assert len(result) <= AttentionManager.TOTAL_CHAR_BUDGET


# ── Full scenario ─────────────────────────────────────────────────────────────


def test_full_yt_dlp_scenario():
    """
    Mirrors the 7-bug failure scenario:
    1. Discovery fails → tool REFUTED
    2. Env scope mismatch → pip:global REFUTED
    3. Invalid exe → write_file blocked
    4. Syntax error → exact retry blocked
    5. VERIFY allowed (anti-deadlock), MODIFY invocation blocked (tool REFUTED)
    6. Correct install succeeds → tool PROVEN
    7. Verify is now allowed
    """
    ctx = _ctx("install yt-dlp globally")

    # 1. Discovery fails
    ctx.post_step_update(
        "s0", "locate|yt-dlp", False, ErrorClass.FILE_NOT_FOUND, "not found", "DISCOVERY"
    )
    assert ctx.beliefs.is_refuted(_bkey("yt_dlp", "exists"))

    # 2. Env scope mismatch
    ctx.post_step_update(
        "s1", "pip install yt-dlp", False, ErrorClass.ENV_SCOPE_MISMATCH, "not recognized", "MODIFY"
    )
    assert ctx.beliefs.is_refuted(_bkey("pip", "available_globally"))

    # 3. Invalid executable
    ctx.post_step_update(
        "s2",
        "C:/tools/yt-dlp.exe",
        False,
        ErrorClass.INVALID_EXECUTABLE,
        "not a valid win32 application",
        "MODIFY",
    )

    # 4. Syntax error
    bad_cmd = "pip install --garbage yt-dlp"
    ctx.post_step_update(
        "s3", bad_cmd, False, ErrorClass.COMMAND_SYNTAX, "invalid option", "MODIFY"
    )

    # 5. VERIFY stays allowed (anti-deadlock: it re-establishes truth after a
    #    false REFUTED); invoking the tool for real work (MODIFY) is blocked.
    allow, _ = ctx.pre_execute_check("yt-dlp --version", "sv", "VERIFY")
    assert allow
    allow, _ = ctx.pre_execute_check("yt-dlp https://example.com/v", "smod", "MODIFY")
    assert not allow

    # Write_file to corrupt exe blocked
    allow, _ = ctx.pre_execute_check("write_file|C:/tools/yt-dlp.exe|fake", "sw", "RECOVER")
    assert not allow

    # Exact retry blocked
    allow, _ = ctx.pre_execute_check(bad_cmd, "sr", "MODIFY")
    assert not allow

    # 6. Correct global install
    allow, _ = ctx.pre_execute_check("pip install yt-dlp --break-system-packages", "sg", "MODIFY")
    assert allow, "correct global install must be allowed"

    ctx.post_step_update(
        "s4",
        "pip install yt-dlp --break-system-packages",
        True,
        None,
        "Successfully installed yt-dlp-2024.8.6",
        "MODIFY",
    )
    assert ctx.beliefs.is_proven(_bkey("yt_dlp", "installed"))

    # 7. After successful install, verify existence now allowed
    ctx.beliefs.observe(
        _bkey("yt_dlp", "exists"),
        holds=True,
        kind=EvidenceKind.MUTATION,
        detail="installed successfully",
    )
    allow, _ = ctx.pre_execute_check("yt-dlp --version", "sv2", "VERIFY")
    assert allow, "verify should be allowed after proven install"


def test_compound_command_extracts_real_tool():
    """$env:VAR=value; winget install X → tool=winget, not $env:VAR=value;"""
    ctx = _ctx()
    # Simulate what happens when winget is called with PowerShell env var prefix
    ctx.post_step_update(
        "s0",
        "$env:WINGET_ACCEPT_TERMS=$true; winget install yt-dlp.YTDL",
        False,
        ErrorClass.FILE_NOT_FOUND,  # winget not found → FILE_NOT_FOUND (new classifier)
        "The term 'winget' is not recognized as the name of a cmdlet",
        "MODIFY",
    )
    # A bare-invocation "not recognized" on a MODIFY step only proves the tool
    # didn't resolve on THIS subprocess's PATH by bare name — not that it does
    # not exist anywhere (e.g. a project-local copy). So :available_globally is
    # refuted (tool=winget extracted correctly, not $env:...), while :exists is
    # left alone — only a real multi-tier probe (locate/DISCOVERY) may refute it.
    assert ctx.beliefs.is_refuted(_bkey("winget", "available_globally")), (
        "winget:available_globally should be REFUTED after FILE_NOT_FOUND"
    )
    assert not ctx.beliefs.is_refuted(_bkey("winget", "exists")), (
        "winget:exists must NOT be refuted by a bare-invocation MODIFY failure"
    )
    # A subsequent bare winget invocation is NOT blocked — evidence doesn't
    # support "winget cannot possibly exist", only "not globally on PATH".
    allow, reason = ctx.pre_execute_check("$env:ACCEPT=1; winget install yt-dlp", "s1", "MODIFY")
    assert allow, "winget is not :exists-REFUTED — bare invocation must be allowed"
    # pip is unaffected (different tool)
    allow, _ = ctx.pre_execute_check("pip install yt-dlp", "s2", "MODIFY")
    assert allow, "pip should be allowed as alternative"


def test_file_not_found_refutes_available_globally_not_exists():
    """winget not found by bare name → FILE_NOT_FOUND → refute tool:available_globally.

    :exists is deliberately left untouched: a bare-invocation miss on a
    MODIFY/VERIFY step is not the strong multi-tier evidence a locate()/
    DISCOVERY probe provides, so it must not permanently block every future
    run of a tool that may genuinely exist locally (e.g. a project dependency
    invocable via its ecosystem's local runner or a qualified path).
    """
    ctx = _ctx()
    ctx.post_step_update(
        "s0",
        "winget install yt-dlp",
        False,
        ErrorClass.FILE_NOT_FOUND,
        "is not recognized as the name of a cmdlet",
        "MODIFY",
    )
    assert ctx.beliefs.is_refuted(_bkey("winget", "available_globally"))
    assert not ctx.beliefs.is_refuted(_bkey("winget", "exists"))


if __name__ == "__main__":
    # Run as script: python tests/test_reasoning.py
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)

# ── Belief state is derived from evidence, not asserted by the caller ────────


def test_state_is_derived_from_the_strongest_evidence():
    bs = BeliefSystem()
    k = _bkey("tool", "exists")
    assert (
        bs.observe(
            k, holds=True, kind=EvidenceKind.OUTPUT_HEURISTIC, detail="matched a pattern"
        ).state
        == BeliefState.POSSIBLE
    )
    assert (
        bs.observe(k, holds=True, kind=EvidenceKind.EXIT_CODE, detail="the command ran").state
        == BeliefState.LIKELY
    )
    assert (
        bs.observe(
            k, holds=True, kind=EvidenceKind.PROBE_DIRECT, detail="located at /usr/bin/tool"
        ).state
        == BeliefState.PROVEN
    )


def test_weaker_evidence_never_overturns_stronger():
    """A regex over arbitrary stdout used to be able to mint — and, once PROVEN was sticky,
    to permanently hold — a belief indistinguishable from a direct probe."""
    bs = BeliefSystem()
    k = _bkey("tool", "exists")
    bs.observe(k, holds=True, kind=EvidenceKind.PROBE_DIRECT, detail="located")
    b = bs.observe(k, holds=False, kind=EvidenceKind.OUTPUT_HEURISTIC, detail="regex guess")
    assert b.state == BeliefState.PROVEN


def test_stronger_evidence_does_overturn():
    """The counterpart, and why no override channel is needed: PROVEN is not sticky, it is
    simply the state implied by the best evidence so far."""
    bs = BeliefSystem()
    k = _bkey("tool", "exists")
    bs.observe(k, holds=True, kind=EvidenceKind.OUTPUT_HEURISTIC, detail="regex guess")
    b = bs.observe(k, holds=False, kind=EvidenceKind.PROBE_DIRECT, detail="which: not found")
    assert b.state == BeliefState.REFUTED


def test_equal_strength_evidence_is_superseded_by_the_newer_observation():
    """A tool that was absent and has now been installed must become present."""
    bs = BeliefSystem()
    k = _bkey("yt-dlp", "exists")
    bs.observe(k, holds=False, kind=EvidenceKind.PACKAGE_MANAGER, detail="not installed")
    b = bs.observe(k, holds=True, kind=EvidenceKind.PACKAGE_MANAGER, detail="pip install ok")
    assert b.state == BeliefState.PROVEN


def test_an_unobserved_belief_is_unknown():
    bs = BeliefSystem()
    k = _bkey("tool", "exists")
    assert bs.get(k) is None
    assert not bs.is_proven(k) and not bs.is_refuted(k)


def test_the_disagreement_stays_auditable():
    """Losing evidence is still recorded — the reason a state was NOT changed is as important
    as the state."""
    bs = BeliefSystem()
    k = _bkey("tool", "exists")
    bs.observe(k, holds=True, kind=EvidenceKind.PROBE_DIRECT, detail="located")
    b = bs.observe(k, holds=False, kind=EvidenceKind.OUTPUT_HEURISTIC, detail="regex guess")
    assert any("regex guess" in h for h in b.history)
