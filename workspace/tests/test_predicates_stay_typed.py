"""Success criteria are predicate OBJECTS from the planner to the evaluator. Never strings.

`_flatten_strings` exists to normalise a list the model may fill with strings or dicts. Applied
to a predicate it collapses

    {"check": "file_has_content", "path": "package.json"}   ->   "file_has_content"

and `predicates.evaluate` correctly refuses it: *"criterion is not a predicate object"*.

Observed live, on a React + Vite scaffold: the main plan was fine, but the RECOVERY path still
ran its criteria through `_flatten_strings`, so every recovery step lost its artifact check and
reported `not achieved` for a reason that had nothing to do with the filesystem. Two recovery
passes, both unverifiable, on a task the agent might otherwise have finished.

The rendering to text happens at the edges — prompts, the decision graph, the console — and
nowhere else. This test walks the source so a fourth call site cannot quietly reappear.
"""

import ast

import pytest
from src.config import SRC
from src.orchestrator import _flatten_strings
from src.tools import predicates

ORCHESTRATOR = SRC / "orchestrator.py"


def test_flatten_strings_destroys_a_predicate():
    """Pinned so the hazard is visible where the function is read, not only where it is used."""
    assert _flatten_strings([{"check": "file_has_content", "path": "a.txt"}]) == [
        "file_has_content"
    ]


def test_the_evaluator_rejects_a_flattened_predicate(tmp_path):
    ok, reason = predicates.evaluate(
        _flatten_strings([{"check": "file_has_content", "path": "a.txt"}]), tmp_path
    )
    assert not ok and "not a predicate object" in reason


def test_no_success_criteria_are_ever_flattened():
    """Static check: `_flatten_strings` may be called on `constraints`, never on `success`."""
    tree = ast.parse(ORCHESTRATOR.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_flatten_strings"
        ):
            continue
        arg = node.args[0] if node.args else None
        src = ast.unparse(arg) if arg is not None else ""
        if "success" in src:
            offenders.append((node.lineno, src))
    assert not offenders, (
        f"success criteria flattened to strings at {offenders}. They must stay predicate "
        f"objects all the way to predicates.evaluate; render them only at the edges."
    )


@pytest.mark.parametrize("name", ["render", "evaluate"])
def test_rendering_is_the_only_way_criteria_become_text(name):
    assert hasattr(predicates, name)
    assert predicates.render([{"check": "file_contains", "path": "a", "text": "b"}]) == [
        "file_contains(a, 'b')"
    ]
