"""The coder gate must not reject valid PowerShell as prose.

The `not_a_command_or_echoes_hint` gate aborts the whole step when it fires, so a false
positive here is not a cosmetic miss — it turns a working fix into "no alternative fix
available". Classifying every such rejection in the cap_off2/cap_on2 ledgers (334 events)
found zero actual prose; the 16 non-echo rejections were all valid PowerShell, refused for
two reasons this file pins down:

  * the invocation regex admitted no leading `$`, so an assignment
    (`$arch = (Get-WmiObject ...)`) "was not a command";
  * a backtick counted as markdown inline code, but in PowerShell the backtick is the
    escape character — `` `n `` inside a quoted string is a newline, not prose.
"""

from src.orchestrator import _looks_like_command


def test_powershell_assignment_is_a_command():
    # Verbatim from the cap_off2 ledger, rejected as prose_or_multiline.
    assert _looks_like_command("$arch = (Get-WmiObject Win32_Processor).Architecture")
    assert _looks_like_command("$OS_VERSION = (Get-WmiObject -Class Win32_OperatingSystem).Version")


def test_powershell_backtick_escape_is_a_command():
    # Verbatim from the ledger: every backtick is an escape glued to an alphanumeric.
    assert _looks_like_command(
        'echo "OS: $OS`nShell: $SHELL`nVersion: $VERSION" | Out-File -FilePath os_info.txt'
    )
    assert _looks_like_command('Set-Content -Path report.txt -Value "col1`tcol2"')


def test_markdown_inline_code_is_still_prose():
    # A markdown span closes with a backtick followed by space/punctuation/EOL —
    # the shape a PowerShell escape can never take.
    assert not _looks_like_command("Run `npm install` to fix the problem")
    assert not _looks_like_command("install it with `pip install requests`")


def test_error_message_fragments_are_still_prose():
    assert not _looks_like_command("The term 'foo' is not recognized as the name of a cmdlet")
    assert not _looks_like_command("cannot find path 'C:\\x' because it does not exist")


def test_multiline_is_still_rejected():
    assert not _looks_like_command("$a = 1\n$b = 2")
