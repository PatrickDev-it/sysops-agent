"""
Verification tests for the WorldGraph — the single owner of world identity.

Each test pins one deterministic behavior that previously required a heuristic
scan (substring key matching, arrow-grepping raw discovery text, duplicated
write-block logic) or did not exist at all (uninstall-invalidation cascade).

Run: python -m pytest tests/test_world.py -v
"""

import os

from src.world import (
    EdgeKind,
    EntityKind,
    EntityState,
    WorldGraph,
)


def _graph() -> WorldGraph:
    return WorldGraph()


# ── Identity: one node, many names ────────────────────────────────────────────


def test_alias_variants_resolve_to_same_node():
    g = _graph()
    node = g.observe_executable("yt-dlp", r"C:\Tools\yt-dlp.exe", provenance="locate")
    assert g.resolve("yt-dlp") is node
    assert g.resolve("yt_dlp") is node  # pip normalization
    assert g.resolve("yt-dlp.exe") is node
    assert g.resolve("YT-DLP") is node
    assert g.resolve(r"C:\Tools\yt-dlp.exe") is node
    assert g.resolve("c:/tools/yt-dlp.exe") is node  # path separators/case


def test_resolve_never_matches_by_substring():
    g = _graph()
    g.observe_executable("git", r"C:\Program Files\Git\bin\git.exe")
    # "git-lfs" contains "git" but is a different thing — must NOT resolve.
    assert g.resolve("git-lfs") is None


def test_package_and_executable_same_alias_do_not_merge():
    g = _graph()
    pkg = g.observe_package("yt-dlp", scope="global", provenance="pip install yt-dlp")
    exe = g.resolve("yt-dlp", kind=EntityKind.EXECUTABLE)
    assert pkg.kind == EntityKind.PACKAGE
    assert exe is not None and exe.kind == EntityKind.EXECUTABLE
    assert pkg.id != exe.id
    assert exe in g.provides(pkg.id)


def test_locate_after_pip_converges_identity():
    """pip creates the exe node without a path; a later locate attaches the
    real path to the SAME node (no duplicate identity)."""
    g = _graph()
    g.observe_package("yt-dlp")
    exe_before = g.resolve("yt-dlp", kind=EntityKind.EXECUTABLE)
    g.observe_executable("yt-dlp", r"C:\Python312\Scripts\yt-dlp.exe")
    exe_after = g.resolve("yt-dlp", kind=EntityKind.EXECUTABLE)
    assert exe_after is exe_before
    assert exe_after.path.endswith("yt-dlp.exe")


# ── Lifecycle: stickiness and explicit transitions ────────────────────────────


def test_positive_knowledge_sticky_against_rediscovery():
    g = _graph()
    n = g.ensure(
        EntityKind.EXECUTABLE, name="node", path="c:/nodejs/node.exe", state=EntityState.INSTALLED
    )
    g.observe_executable("node", "c:/nodejs/node.exe")  # plain re-discovery
    assert n.state == EntityState.INSTALLED  # not downgraded


def test_relocate_after_deleted_reestablishes_presence():
    g = _graph()
    n = g.observe_executable("tool", "c:/bin/tool.exe")
    g.set_state(n.id, EntityState.DELETED)
    assert not n.exists
    g.observe_executable("tool", "c:/bin/tool.exe")  # found again
    assert n.exists and n.state == EntityState.DISCOVERED


# ── Cascade: uninstall invalidation is a traversal, not a regex ───────────────


def test_package_deletion_cascades_missing_to_provided_executable():
    g = _graph()
    pkg = g.observe_package("yt-dlp", provenance="pip install yt-dlp")
    exe = g.resolve("yt-dlp", kind=EntityKind.EXECUTABLE)
    transitions = g.set_state(pkg.id, EntityState.DELETED, provenance="pip uninstall")
    assert exe.state == EntityState.MISSING
    cascaded = [t for t in transitions if t.cause]
    assert any(t.node_id == exe.id and t.new == EntityState.MISSING for t in cascaded)


def test_cascade_is_transitive_and_bounded():
    g = _graph()
    a = g.ensure(EntityKind.PACKAGE, name="a", state=EntityState.INSTALLED)
    b = g.ensure(EntityKind.PACKAGE, name="b", state=EntityState.INSTALLED)
    c = g.ensure(EntityKind.EXECUTABLE, name="c", state=EntityState.INSTALLED)
    g.link(a.id, EdgeKind.PROVIDES, b.id)
    g.link(b.id, EdgeKind.PROVIDES, c.id)
    g.link(c.id, EdgeKind.PROVIDES, a.id)  # cycle — must not loop forever
    g.set_state(a.id, EntityState.DELETED)
    assert b.state == EntityState.MISSING
    assert c.state == EntityState.MISSING


# ── Invariant 3: single write-block implementation ────────────────────────────


def test_write_block_on_tracked_executable():
    g = _graph()
    g.observe_executable("yt-dlp", r"C:\Tools\yt-dlp.exe")
    assert g.write_block_reason(r"C:\Tools\yt-dlp.exe") != ""
    assert g.write_block_reason("c:/tools/yt-dlp.exe") != ""  # any spelling
    assert g.write_block_reason(r"D:\other\yt-dlp.exe") != ""  # same basename
    assert g.write_block_reason(r"C:\Tools\readme.txt") == ""  # unrelated file


def test_write_unblocked_after_delete():
    g = _graph()
    n = g.observe_executable("yt-dlp", r"C:\Tools\yt-dlp.exe")
    g.set_state(n.id, EntityState.DELETED)
    assert g.write_block_reason(r"C:\Tools\yt-dlp.exe") == ""


# ── $VAR resolution: latest_path replaces arrow-grepping raw discovery text ───


def test_latest_path_returns_most_recent_existing_node():
    g = _graph()
    a = g.observe_executable("old-tool", "c:/bin/old-tool.exe")
    b = g.observe_executable("new-tool", "c:/bin/new-tool.exe")
    b.updated = a.updated + 10
    assert g.latest_path() == "c:/bin/new-tool.exe"
    g.set_state(b.id, EntityState.DELETED)
    assert g.latest_path() == "c:/bin/old-tool.exe"  # absent nodes never win
    g.set_state(a.id, EntityState.DELETED)
    assert g.latest_path() == ""


# ── Integration: SystemState delegates + belief coupling ─────────────────────


def test_systemstate_transition_refutes_beliefs_on_cascade():
    from src.reasoning import BeliefKey, EvidenceKind, Predicate
    from src.state import SystemState

    ss = SystemState(os.getcwd())
    ss.init_reasoning("install yt-dlp")
    ss.reasoning.observe_belief(
        BeliefKey.of("yt_dlp", Predicate.EXISTS),
        holds=True,
        kind=EvidenceKind.PROBE_DIRECT,
        detail="test setup",
    )
    ss.world.observe_package("yt-dlp", provenance="pip install yt-dlp")
    pkg = ss.world.resolve("yt-dlp", kind=EntityKind.PACKAGE)
    ss.transition_entity(pkg.id, EntityState.DELETED)
    exe = ss.world.resolve("yt-dlp", kind=EntityKind.EXECUTABLE)
    assert exe.state == EntityState.MISSING
    # World → belief coupling: the existence belief was refuted by the cascade.
    assert ss.reasoning.beliefs.is_refuted(BeliefKey.of("yt_dlp", Predicate.EXISTS))


def test_systemstate_write_block_single_source():
    """assert_safe_overwrite and the policy guard must agree — one implementation."""
    from src.state import SystemState

    ss = SystemState(os.getcwd())
    ss.init_reasoning("reinstall yt-dlp")
    ss.observe_executable("yt-dlp", r"C:\Tools\yt-dlp.exe", provenance="locate")

    safe, reason = ss.assert_safe_overwrite(r"C:\Tools\yt-dlp.exe")
    assert not safe and "SAFETY BLOCK" in reason

    allow, greason = ss.reasoning.pre_execute_check(
        r"write_file|C:\Tools\yt-dlp.exe|#!/usr/bin/env python", "step_x", "MODIFY"
    )
    assert not allow and "executable" in greason.lower()


def test_pip_install_via_inference_populates_graph():
    """post_step_update on a pip-install success must create package+exe+edge."""
    from src.state import SystemState

    ss = SystemState(os.getcwd())
    ss.init_reasoning("install yt-dlp")
    ss.reasoning.post_step_update(
        step_id="s0",
        command="pip install yt-dlp",
        success=True,
        error_class=None,
        output="Successfully installed yt-dlp-2026.1.1",
        step_type="MODIFY",
    )
    pkg = ss.world.resolve("yt_dlp", kind=EntityKind.PACKAGE)
    exe = ss.world.resolve("yt_dlp", kind=EntityKind.EXECUTABLE)
    assert pkg is not None and pkg.state == EntityState.INSTALLED
    assert exe is not None and exe in ss.world.provides(pkg.id)
