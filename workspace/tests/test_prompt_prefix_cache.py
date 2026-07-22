"""The prefix cache is worth 37x on prefill (608 ms → 16.4 ms, cache_n 1225/1226), but only
for the tokens BEFORE the first variable byte. `verify.jinja` used to interpolate the success
criteria inside its system block, at rule 0 — so its shared prefix ended nine lines in and it
reused 21.7% of its prompt, against 76.6% for `supervisor.jinja` and 91.2% for the navigator's.

This test makes the layout an invariant instead of a habit: every template's system block is
byte-identical across calls, and all variance lives in the user block, where it is also closest
to the generation and anchors better.
"""

import re
from pathlib import Path

import pytest
from src.config import PROMPTS_DIR

# Rendered once, from a constant table or a module-level string, so they are byte-identical on
# every call within a process and cannot move the prefix boundary. Anything added here must be
# provably constant per process — a variable smuggled in through this set silently costs the
# 37x prefill win and nothing would fail.
CONSTANT_INJECTIONS = {"predicate_reference", "capture_guidance"}

TEMPLATES = sorted(Path(PROMPTS_DIR).glob("*.jinja"))
assert TEMPLATES, "no prompt templates found"

_JINJA = re.compile(r"{{\s*([a-zA-Z0-9_]+)|{%-?\s*(if|for|elif|else|endif|endfor)")


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_system_block_is_byte_identical_across_calls(path):
    text = path.read_text(encoding="utf-8")
    marker = "<|im_start|>user"
    assert marker in text, f"{path.name}: no user block — cannot locate the prefix boundary"

    system_block = text.split(marker, 1)[0]
    offenders = []
    for m in _JINJA.finditer(system_block):
        name, control = m.group(1), m.group(2)
        if control:
            offenders.append(f"{{% {control} %}}")
        elif name not in CONSTANT_INJECTIONS:
            offenders.append(f"{{{{ {name} }}}}")

    assert not offenders, (
        f"{path.name}: variable content in the shared prefix ({', '.join(sorted(set(offenders)))}). "
        f"Move it into the user block: everything after the first variable byte is re-prefilled "
        f"on every call."
    )
