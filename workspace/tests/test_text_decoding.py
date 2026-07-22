"""A verifier that assumes UTF-8 fails on the very shell it targets.

PowerShell 5.1 writes `Out-File` and `>` as UTF-16LE with a BOM. Observed on T01: the agent
correctly produced `OS: Windows / Version: 10.0.19045 / Shell: PowerShell`, and the runtime
declared the step failed because, read as UTF-8, the bytes look like `\\xff\\xfeO\\x00S\\x00`.

A BOM is a Unicode convention, not product knowledge. Sniffing it is exactly the OS-neutral
reasoning this agent is meant to do instead of special-casing a shell.
"""

import pytest
from src.tools import predicates

SAMPLE = "OS: Windows\r\nVersion: 10.0.19045\r\nShell: PowerShell\r\n"


@pytest.mark.parametrize(
    "encoding",
    [
        "utf-8",  # no BOM
        "utf-8-sig",  # BOM
        "utf-16",  # BOM, platform endianness
        "utf-16-le",  # written raw, no BOM
        "utf-32",  # BOM
    ],
)
def test_read_text_round_trips_every_encoding_the_shell_may_emit(tmp_path, encoding):
    p = tmp_path / "os_info.txt"
    p.write_bytes(SAMPLE.encode(encoding))
    out = predicates.read_text(p)
    if encoding == "utf-16-le":
        pytest.skip("BOM-less UTF-16LE is genuinely ambiguous; PowerShell always writes the BOM")
    assert out == SAMPLE
    assert not out.startswith("﻿"), "the BOM must not survive into the decoded text"


def test_powershell_out_file_default_is_readable(tmp_path):
    """The exact bytes PowerShell 5.1 produces for `"OS: Windows" | Out-File os_info.txt`."""
    p = tmp_path / "os_info.txt"
    p.write_bytes(b"\xff\xfe" + "OS: Windows\r\n".encode("utf-16-le"))
    assert predicates.read_text(p) == "OS: Windows\r\n"


def test_file_contains_passes_on_a_utf16_artifact(tmp_path):
    """The end-to-end regression: a correct artifact scored as a failure."""
    p = tmp_path / "os_info.txt"
    p.write_bytes(b"\xff\xfe" + SAMPLE.encode("utf-16-le"))
    ok, reason = predicates.evaluate(
        [{"check": "file_contains", "path": "os_info.txt", "text": "OS"}], tmp_path
    )
    assert ok, reason


def test_undecodable_bytes_do_not_raise(tmp_path):
    p = tmp_path / "bin.dat"
    p.write_bytes(b"\x80\x81\x82")
    assert isinstance(predicates.read_text(p), str)
