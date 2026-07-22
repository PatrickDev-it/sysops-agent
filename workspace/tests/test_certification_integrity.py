"""A test that never imports the product certifies nothing. Structural guards against relapse.

MEASURED on 2026-07-09 and again on 2026-07-20: `tests/certification/` reported a green suite
while asserting nothing. Thirty-three functions named `test_*` computed a verdict and RETURNED
it; pytest warns on a non-None return and passes the test regardless. Twenty-five of them never
imported `src` at all — `test_group1_shell_os.py` defined its own `_probe_shell_signals`,
`_translate_command` and `_reconstruct_paths`, a second implementation of the logic under test,
itself untested, and then certified that.

Those seven groups are deleted, along with `runner.py`/`score.py` — a second test framework
whose job (discover, run, score, report) pytest already does. The eight checks that exercised
real `src` code survive, converted to typed predicate criteria and asserted through one boundary
per module. Five of them failed on first honest execution; they had been written against the
prose-criteria API that `predicates.py` replaced, and had never run.

This file is what stops the pattern coming back. It asserts structure, not counts: there is no
ratchet to relax, because the properties below are either true or the suite is lying again.
"""

import ast
import importlib
import pathlib

import pytest
from src.config import ROOT

CERT = ROOT / "tests" / "certification"
GROUPS = sorted(CERT.glob("test_group*.py"))


def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_src(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "src":
            return True
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "src" for a in node.names):
            return True
    return False


def _functions(tree: ast.Module, prefix: str) -> list[ast.FunctionDef]:
    return [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith(prefix)]


def _parametrized_checks(tree: ast.Module) -> set[str]:
    """Names passed to `@pytest.mark.parametrize("check", [...])` — i.e. the checks that run."""
    names: set[str] = set()
    for fn in _functions(tree, "test_"):
        for dec in fn.decorator_list:
            if not isinstance(dec, ast.Call) or not dec.args:
                continue
            for arg in dec.args:
                if isinstance(arg, (ast.List, ast.Tuple)):
                    names |= {e.id for e in arg.elts if isinstance(e, ast.Name)}
    return names


def test_at_least_one_certification_group_survives():
    """A guard over an empty directory passes vacuously — the failure mode this whole file
    exists to prevent. If the last group is ever deleted, delete this file with it."""
    assert GROUPS, "no certification groups found; this guard would pass vacuously"


@pytest.mark.parametrize("path", GROUPS, ids=lambda p: p.name)
def test_every_certification_module_is_importable(path):
    """`test_group9_realworld.py` once imported `src.behavior_verifier`, a module path that had
    not existed for some time. The runner raised on import, so the suite was unrunnable and
    reported nothing. Nobody noticed, because nobody ran it."""
    importlib.import_module(f"tests.certification.{path.stem}")


@pytest.mark.parametrize("path", GROUPS, ids=lambda p: p.name)
def test_every_certification_module_exercises_the_product(path):
    assert _imports_src(_tree(path)), (
        f"{path.name} never imports `src`. A module that reimplements the logic it certifies "
        f"certifies its own copy — that is what produced 25 green tests covering nothing."
    )


@pytest.mark.parametrize("path", GROUPS, ids=lambda p: p.name)
def test_no_certification_test_returns_a_verdict_instead_of_asserting(path):
    """The exact mechanism of the lie: `def test_X(): ... return CertRecord(...)`. Checks are
    named `check_*` so pytest cannot collect them; only the asserting boundary is a `test_*`."""
    for fn in _functions(_tree(path), "test_"):
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and node.value is not None:
                pytest.fail(
                    f"{path.name}::{fn.name} returns a value at line {node.lineno}. "
                    f"pytest passes such a test regardless of the value. Assert instead, "
                    f"or rename it `check_*` and drive it from the module's test boundary."
                )


@pytest.mark.parametrize("path", GROUPS, ids=lambda p: p.name)
def test_every_check_is_actually_executed(path):
    """A check that exists but is not in the parametrize list never runs, and its absence looks
    exactly like a passing suite. This is the same defect class as a guard that is correct and
    unwired — the one this repository has now found in four separate domains."""
    tree = _tree(path)
    defined = {fn.name for fn in _functions(tree, "check_")}
    executed = _parametrized_checks(tree)
    assert defined, f"{path.name} defines no `check_*` function"
    orphaned = defined - executed
    assert not orphaned, (
        f"{path.name} defines {sorted(orphaned)} but never passes them to a test boundary — "
        f"they do not run, and the suite still reports green."
    )
    assert not (executed - defined), (
        f"{path.name} parametrizes {sorted(executed - defined)}, which it does not define"
    )
