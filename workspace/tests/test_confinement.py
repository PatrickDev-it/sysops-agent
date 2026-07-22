"""Confinement is a filter, not a jail — these tests pin the asymmetry it encodes:
reads outside the root are allowed, writes are not, and an unresolvable target inside a
mutating segment fails closed."""

import pytest
from src.tools.confinement import Confinement


@pytest.fixture
def c(tmp_path):
    return Confinement(tmp_path)


# Reads outside the root must pass: 47 of the 50 benchmark tasks depend on them.
@pytest.mark.parametrize(
    "cmd",
    [
        r"Get-ChildItem C:\Users\ExampleUser",
        r"Get-EventLog -LogName System -Newest 20 | Out-File errors.txt",
        r"Get-Process | Sort-Object CPU -Descending | Out-File procs.txt",
        r"whoami > whoami.txt",
        r"python -m pip list --format=json > pkgs.txt",
        r"New-Item -ItemType Directory scripts",
        r"Set-Content -Path .\out.txt -Value 'hello'",
        r"sc.exe query",
        r"Test-NetConnection -Port 443 google.com",
        r"Get-ChildItem -Path C:\ -Directory | Measure-Object",
        r"Get-ChildItem C:\Windows | Out-File inside.txt",  # read outside, write inside
        r"reg query HKLM\SOFTWARE",  # a read, despite the `reg` verb
        r"sc.exe query Spooler",  # a read, despite the `sc` verb
        r"Get-Service | Out-File services.txt",
        "",
    ],
)
def test_allows_reads_and_in_root_writes(c, cmd):
    assert c.check(cmd) is None


# Writes outside the root, and irreversible whole-system operations, must be refused.
@pytest.mark.parametrize(
    "cmd",
    [
        r"Remove-Item -Recurse -Force C:\Windows\System32",
        r"rm -rf /",
        r"rm -rf /etc",
        r"Remove-Item C:\Users\ExampleUser\Desktop -Recurse",
        r"Out-File C:\temp\x.txt",
        r"echo pwned > C:\Users\ExampleUser\pwned.txt",
        r"Set-Content ~/evil.txt -Value x",
        r"diskpart /s script.txt",
        r"format C:",
        r"Copy-Item secret.txt \\server\share",
    ],
)
def test_blocks_writes_outside_root(c, cmd):
    assert c.check(cmd) is not None


# Pathless state mutations cannot be scoped to a workspace, so they are refused outright.
@pytest.mark.parametrize(
    "cmd",
    [
        r"Stop-Service Spooler",
        r"sc delete Spooler",
        r"reg add HKLM\SOFTWARE\X /v Y /d 1",
        r"net user attacker P@ss /add",
        r"shutdown /s /t 0",
        r"icacls C:\ /grant Everyone:F",
        r"winget install Git.Git",
        r"choco upgrade git -y",
        r"sudo apt-get install nginx",
        r"python -m pip install requests",
        r"npm install -g typescript",
        r"setx PATH C:\tools",
        r"Stop-Process -Name explorer",
        r"taskkill /IM explorer.exe /F",
    ],
)
def test_blocks_pathless_system_mutations(c, cmd):
    assert c.check(cmd) is not None


def test_fails_closed_on_unresolvable_path_expansion(c):
    """An env-var expansion that clearly denotes a path cannot be resolved here, so it is
    treated as outside the root rather than assumed benign."""
    assert c.check(r"Remove-Item $env:TEMP\x -Recurse") is not None


# Regression: the first version treated every `$var` as an unresolvable path and refused 4
# of the first 5 benchmark tasks. A PowerShell variable holding a VALUE is not a location.
@pytest.mark.parametrize(
    "cmd",
    [
        r"Set-Content ram.txt -Value $totalRAM",
        r"$output | Out-File result.txt",
        r"Set-Content npm.txt -Value $npmVersion",
    ],
)
def test_bare_variables_are_values_not_paths(c, cmd):
    assert c.check(cmd) is None


@pytest.mark.parametrize(
    "cmd",
    [
        r"Out-File $target",
        r"Set-Content -Path $target -Value x",
        r"Remove-Item ${target} -Recurse",
        r"Get-ChildItem . > $target",
        r"Copy-Item source.txt -Destination $target",
    ],
)
def test_dynamic_write_targets_fail_closed(c, cmd):
    assert c.check(cmd) is not None


def test_dynamic_values_are_not_mistaken_for_write_targets(c):
    assert c.check(r"Set-Content report.txt -Value $totalRAM") is None


def test_redirect_target_is_checked_even_when_source_is_outside(c):
    """Reading outside and writing inside is the common shape of a diagnostic task."""
    assert c.check(r"Get-ChildItem C:\Windows | Out-File inside.txt") is None
    assert c.check(r"Get-ChildItem . | Out-File C:\outside.txt") is not None


def test_check_path_guards_the_safe_fs_sentinels(c, tmp_path):
    assert c.check_path(tmp_path / "a.txt") is None
    assert c.check_path(r"C:\Windows\notepad.exe") is not None


def test_an_unset_environment_does_not_disable_the_filter(monkeypatch):
    """This test previously asserted the OPPOSITE — that `from_env()` returns None when
    SISTEMISTA_CONFINE_ROOT is unset — which encoded the vulnerability as a requirement.

    The variable was set only by the three benchmark harnesses, so "unset" was every
    production run. With None returned, `session.run` and `fileops` both read
    `if confine is not None:` and did nothing, and `_ALWAYS_FATAL` — mkfs, diskpart, bcdedit,
    rm -rf / — never executed outside the lab.
    """
    from src.tools import confinement as confinement_module

    monkeypatch.delenv("SISTEMISTA_CONFINE_ROOT", raising=False)
    monkeypatch.delenv("SISTEMISTA_UNCONFINED", raising=False)
    monkeypatch.setattr(confinement_module, "_root", None)

    c = Confinement.current()
    assert c is not None, "a None filter is indistinguishable from no filter at the call site"
    assert c.check("mkfs.ext4 /dev/sda1") is not None, (
        "whole-device destruction must be refused even with no confinement root configured"
    )


def test_the_run_root_is_what_scopes_writes(monkeypatch, tmp_path):
    """`fileops` only ever receives a cwd. Deriving the root from that cwd would make every
    relative write 'inside' by construction, so the root is a run-level fact set once."""
    from src.tools import confinement as confinement_module

    monkeypatch.delenv("SISTEMISTA_CONFINE_ROOT", raising=False)
    root, outside = tmp_path / "ws", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()

    confinement_module.set_root(root)
    try:
        c = Confinement.current()
        assert c.rooted and c.root == root.resolve()
        assert c.check_path("escape.txt", cwd=outside) is not None
        assert c.check_path("ok.txt", cwd=root) is None
    finally:
        confinement_module.set_root(None)
