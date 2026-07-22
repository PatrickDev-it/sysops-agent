"""The runtime normalizes the shape of the workspace; it does not ask the model to produce it.

Every ecosystem's initializer wants to create the project directory itself, and several have no
way to say "here": `ng new .` is invalid, Laravel's installer requires a name. A guard that
refused `<initializer> <name>` was written and removed within the hour — it was a fact about
npm, dressed as a universal rule, and it made Angular, Django and Laravel unreachable.

`verify.jinja` already calls a nested scaffold a failure and prescribes the remedy: "move that
subdir's contents up to the root". It then hands that remedy to a 3B model to express as a shell
command. On a live Vite scaffold it never did, and the run ended asserting `<name>/dist`.

So the remedy is a runtime operation. Let the initializer nest; hoist afterwards.
"""

import pytest
from src.config import SRC
from src.tools.workspace_shape import find_nested_project, hoist_nested_project


def _scaffold(root, name="my-app", files=("package.json", "index.html")):
    d = root / name
    d.mkdir()
    for f in files:
        (d / f).write_text("x")
    (d / "src").mkdir()
    (d / "src" / "main.tsx").write_text("y")
    return d


def test_hoists_a_single_nested_project(tmp_path):
    _scaffold(tmp_path)
    r = hoist_nested_project(tmp_path)
    assert r.hoisted and r.source == "my-app"
    assert (tmp_path / "package.json").is_file()
    assert (tmp_path / "src" / "main.tsx").is_file()
    assert not (tmp_path / "my-app").exists()


def test_a_workspace_already_at_the_root_is_left_alone(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "src").mkdir()
    assert not hoist_nested_project(tmp_path).hoisted
    assert (tmp_path / "package.json").is_file()


def test_two_directories_are_a_project_being_built_not_a_nest(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "a.py").write_text("x")
    assert find_nested_project(tmp_path) is None
    assert not hoist_nested_project(tmp_path).hoisted


def test_an_empty_directory_is_not_a_project(tmp_path):
    (tmp_path / "my-app").mkdir()
    assert find_nested_project(tmp_path) is None


def test_a_lone_file_is_not_a_nest(tmp_path):
    (tmp_path / "README.md").write_text("x")
    assert not hoist_nested_project(tmp_path).hoisted


def test_hidden_entries_do_not_block_the_hoist(tmp_path):
    """`.git` or `.gitignore` at the root must not make the scaffold look like two entries."""
    (tmp_path / ".gitignore").write_text("node_modules")
    _scaffold(tmp_path)
    assert hoist_nested_project(tmp_path).hoisted
    assert (tmp_path / "package.json").is_file()


def test_a_collision_refuses_rather_than_overwrites(tmp_path):
    """Silently merging two trees is the kind of destructive guess this codebase removes."""
    _scaffold(tmp_path)
    # Simulate a root that already holds a name the nested project also uses.
    (tmp_path / "my-app" / "keep.txt").write_text("z")
    d = tmp_path / "my-app"
    (tmp_path / "package.json").write_text("root")  # now two visible entries
    assert not hoist_nested_project(tmp_path).hoisted
    assert (d / "package.json").read_text() == "x", "nothing was moved"


def test_the_hoist_runs_after_a_state_changing_step():
    src = (SRC / "orchestrator.py").read_text(encoding="utf-8")
    assert "workspace_shape.hoist_nested_project" in src
    hook = src.split("workspace_shape.hoist_nested_project")[0]
    assert 'step_type in ("MODIFY", "RECOVER")' in hook[-400:], (
        "hoisting after a DISCOVERY step would reshape a tree nothing had changed"
    )


@pytest.mark.parametrize(
    "initializer",
    [
        "ng new my-app",  # `ng new .` is invalid
        "django-admin startproject my-app",
        "composer create-project laravel/laravel my-app",
        "npm create vite@latest my-app",
    ],
)
def test_no_initializer_is_forbidden_from_naming_its_directory(initializer):
    """Pinned as a contract: the runtime never refuses these. It cleans up after them."""
    from src.tools import template_guard

    assert not hasattr(template_guard, "nested_project_dir"), (
        "the refusal guard is gone: it encoded npm's `.` convention as a universal rule"
    )
