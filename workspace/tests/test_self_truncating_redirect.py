"""`Get-Content x | Out-File x` empties x.

The shell opens the redirection target for writing before the reader produces a byte. Measured
on T01 and T20: an artifact the runtime had captured correctly a moment earlier ended the run
at 0 bytes, because the model authored exactly this pipeline. It is a property of shells, not
of any product, so the runtime refuses it instead of teaching a 3B model to avoid it.
"""

import pytest
from src.config import SRC
from src.tools.template_guard import self_truncating_redirect as check


@pytest.mark.parametrize(
    "cmd",
    [
        "Get-Content os_info.txt | Out-File os_info.txt",
        "Get-Content log.txt | Set-Content log.txt",
        "type x.txt > x.txt",
        "cat notes.md >> notes.md",
    ],
)
def test_refuses_a_command_that_reads_its_own_redirection_target(cmd):
    assert check(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "Get-Content a.txt | Out-File b.txt",
        "Get-Service Dnscache | Out-File dns_service.txt",
        "whoami > whoami.txt",
        "python -m pip list > pkgs.txt",
        "",
    ],
)
def test_allows_an_honest_redirection(cmd):
    assert not check(cmd)


def test_the_guard_runs_where_a_command_becomes_a_process():
    src = SRC / "tools" / "session.py"
    assert "self_truncating_redirect" in src.read_text(encoding="utf-8"), (
        "the guard must sit at the execution seam, not only on coder-authored commands — "
        "the planner emits this pipeline too"
    )
