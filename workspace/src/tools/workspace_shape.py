"""The runtime normalizes the shape of the workspace. It does not ask the model to produce it.

Every ecosystem's initializer wants to create the project directory itself:

    npm  create vite@latest my-app
    ng   new my-app
    django-admin startproject my-app
    composer create-project laravel/laravel my-app

Some accept `.` to mean "here". Several do not: `ng new .` is invalid, and Laravel's installer
requires a name. So "always pass `.`" is not a rule — it is a fact about npm, dressed up as one,
and a runtime that enforced it would make Angular, Django and Laravel unreachable. (This module
exists because a guard doing exactly that was written, and removed an hour later.)

The invariant that IS universal: **the workspace is the project root.** `supervisor.jinja` says
it, `verify.jinja` calls a nested scaffold a failure and prescribes the remedy — "move that
subdir's contents up to the root" — and then hands that remedy to a 3B model to express as a
shell command. Observed live: it never did, and the run ended asserting `<name>/dist`.

So the remedy becomes a runtime operation. Let the initializer nest; hoist afterwards. The
model is asked for less, not more.

The predicate is deliberately narrow, because a wrong hoist destroys a tree:
  * the root holds exactly ONE visible entry;
  * that entry is a directory;
  * it is not empty.
Anything else is a workspace the agent is legitimately building, and it is left alone.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import trace


@dataclass(frozen=True)
class HoistResult:
    hoisted: bool
    reason: str
    source: str = ""
    entries: int = 0


def _visible(root: Path) -> list[Path]:
    return [p for p in root.iterdir() if not p.name.startswith(".")]


def find_nested_project(root: str | Path) -> Path | None:
    """The single non-empty directory a scaffolder created, or None."""
    root = Path(root)
    if not root.is_dir():
        return None
    entries = _visible(root)
    if len(entries) != 1:
        return None
    only = entries[0]
    if not only.is_dir():
        return None
    return only if any(only.iterdir()) else None


def hoist_nested_project(root: str | Path) -> HoistResult:
    """Move a single nested project's contents up into the workspace root.

    Refuses on any collision rather than overwriting: a name that exists at both levels means
    the tree is not the shape this function was written for, and silently merging it would be
    the kind of destructive guess this codebase spends its time removing.
    """
    root = Path(root)
    nested = find_nested_project(root)
    if nested is None:
        return HoistResult(False, "no single nested project directory")

    children = list(nested.iterdir())
    collisions = [c.name for c in children if (root / c.name).exists()]
    if collisions:
        trace.emit("hoist", hoisted=False, source=nested.name, reason=f"collision: {collisions}")
        return HoistResult(False, f"name collision at the root: {collisions}", nested.name)

    try:
        for child in children:
            shutil.move(str(child), str(root / child.name))
        nested.rmdir()
    except OSError as exc:
        trace.emit("hoist", hoisted=False, source=nested.name, reason=str(exc))
        return HoistResult(False, f"hoist failed: {exc}", nested.name)

    trace.emit("hoist", hoisted=True, source=nested.name, entries=len(children))
    return HoistResult(True, "workspace is the project root", nested.name, len(children))
