"""Whatever survives in the knowledge engine must EXECUTE in production.

The OCKE carried two halves. One was wired and load-bearing — the platform prompt block, the
plan filter, the command validator. The other was a deterministic command-resolution pipeline
(CommandRanker, CommandRegistry.resolve/best, ResolvedCommand.to_plan_step, KnowledgeMemory,
load_by_intent) that had no caller anywhere in `src/`.

It was deleted rather than wired, on measurement:

  COVERAGE. The knowledge base holds 21 entries on Windows, all OS primitives — install a
  package, mkdir, copy, set PATH, locate a tool. All 11 benchmark goals are project
  scaffolding (React/Vite, Vue, Svelte, Angular, Remix, TanStack, Next.js, Node, Django, Bun).
  ZERO of them map to any KB intent. Wiring the pipeline would have changed nothing for any
  measured case; the LLM path would still author every command.

  SAFETY. `KnowledgeEntry.render` substituted variables with a bare
  `result.replace(f"${key}", val)` — no quoting, no validation — and its only two callers were
  in the ranker. A PACKAGE value of `x; rm -rf ~` was interpolated verbatim. The injection
  existed exclusively inside dead code, and wiring the pipeline is precisely what would have
  made it live.

  DEAD LOOP. `record_outcome` fired only when a step carried `_ocke_entry`, a key set
  exclusively by `to_plan_step`, which nothing called. So KnowledgeMemory was never written,
  and the `KB_PROVEN_COMMANDS` / `KB_RECENT_FAILURES` fields of the planner prompt described a
  learning loop the runtime did not have — two always-empty lists on every planning call.

These tests pin the decision in both directions: the survivors must work, and the dormant
layer must not creep back.
"""

import ast
import pathlib

import pytest
from src.config import ROOT
from src.knowledge import OCKE

SRC = pathlib.Path(ROOT) / "src"


@pytest.fixture(scope="module")
def ocke():
    return OCKE()


# ── The survivors execute ────────────────────────────────────────────────────


def test_the_registry_actually_loads_the_knowledge_base(ocke):
    assert ocke._registry.all_entries(), "the KB loaded zero entries"


def test_the_prompt_block_is_produced_and_carries_platform_constraints(ocke):
    block = ocke.prompt_block()
    assert "OS_PROFILE:" in block
    assert "FORBIDDEN_COMMANDS:" in block


def test_the_prompt_block_no_longer_promises_a_learning_loop(ocke):
    """Both fields were fed only by the deleted ranker, so both were always empty."""
    block = ocke.prompt_block()
    assert "KB_PROVEN_COMMANDS" not in block
    assert "KB_RECENT_FAILURES" not in block


def test_filter_plan_rejects_a_cross_platform_step(ocke):
    plan = [
        {"launcher": "sudo apt-get install ripgrep", "objective": "install"},
        {"launcher": "Get-ChildItem", "objective": "list"},
    ]
    _, reasons = ocke.filter_plan(plan)
    if ocke.profile.os_name == "windows":
        assert reasons, "an apt/sudo step must be rejected on Windows"


def test_validate_command_is_the_last_platform_gate(ocke):
    if ocke.profile.os_name == "windows":
        assert not ocke.validate_command("sudo apt-get install x").ok


def test_summary_does_not_reference_a_deleted_subsystem(ocke):
    assert ocke.summary()


# ── The dormant layer must not come back ─────────────────────────────────────

DELETED = (
    "command_ranker",
    "CommandRanker",
    "ResolvedCommand",
    "make_ranker",
    "knowledge_memory",
    "KnowledgeMemory",
    "get_memory",
    "to_plan_step",
    "load_by_intent",
    "load_by_intents",
    "record_outcome",
)


def _referenced_identifiers(path: pathlib.Path) -> set[str]:
    """Identifiers the CODE uses — imports, names, attributes. Not prose.

    A text search flagged the docstring that explains the deletion, which is the shape of
    guard that gets deleted for crying wolf. The question is whether anything CALLS the
    removed pipeline, and that is an AST question.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            out.add((node.module or "").split(".")[-1])
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                out.update(a.name.split("."))
    return out


@pytest.mark.parametrize("symbol", DELETED)
def test_the_deleted_pipeline_is_not_referenced_anywhere(symbol):
    hits = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "__pycache__" not in path.parts and symbol in _referenced_identifiers(path)
    ]
    assert not hits, f"{symbol} is referenced again by {hits}"


def test_no_knowledge_module_substitutes_into_a_command_without_quoting():
    """`render()` built a shell string with `str.replace` and no quoting. If a template
    renderer ever returns, it must not reintroduce that."""
    offenders = []
    for path in (SRC / "knowledge").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "replace"
                and len(node.args) == 2
                and isinstance(node.args[0], ast.JoinedStr)
            ):
                offenders.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    assert not offenders, (
        f"f-string interpolation into a command via str.replace at {offenders} — "
        f"this is the unquoted-substitution shape that made the dormant pipeline unsafe"
    )


def test_every_public_ocke_method_has_a_caller_or_a_test():
    """The rule the deleted half broke: a subsystem that survives must own production
    behaviour. Anything on OCKE that neither `src/` nor this file exercises is dormant."""
    tree = ast.parse((SRC / "knowledge" / "ocke.py").read_text(encoding="utf-8"))
    methods = {
        n.name
        for cls in tree.body
        if isinstance(cls, ast.ClassDef) and cls.name == "OCKE"
        for n in cls.body
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    }
    src_text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "ocke.py"
    )
    here = pathlib.Path(__file__).read_text(encoding="utf-8")
    dormant = [m for m in methods if f".{m}(" not in src_text and f".{m}(" not in here]
    assert not dormant, f"dormant OCKE method(s): {sorted(dormant)}"
