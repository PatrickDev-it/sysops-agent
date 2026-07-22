"""Redaction contract: what must be withheld, and — just as load-bearing — what must not.

A control that degrades the agent gets switched off, and a control that is switched off is not
a control. So the false-positive tests below are not politeness: this is a sysops agent that
legitimately handles git SHAs, package hashes, UUIDs, lockfile integrity fields and long
absolute paths, and if redaction eats those, the planner reasons against `<redacted>` where it
needed a commit id. That is why the implementation anchors on naming keys, documented
credential formats and syntactic position, rather than on entropy.
"""

import pytest
from src import redact
from src.redact import PLACEHOLDER, is_secret_file, redact_mapping

# ── Must be withheld ─────────────────────────────────────────────────────────
#
# Each case is (input, the substring that must NOT survive). Asserting only that a placeholder
# APPEARED is not enough, and that weakness hid a real bug while this file was being written:
# the substitution used the value group where it meant the separator, so it emitted
# `KEY<secret><redacted>` — placeholder present, secret still there, tests green.


@pytest.mark.parametrize(
    "text,secret",
    [
        ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENGbPxRfiCY", "wJalrXUtnFEMI"),  # gitleaks:allow
        (
            "export GITHUB_TOKEN=ghp_16CharsAtLeastHereForTheRule12345",
            "ghp_16CharsAtLeast",
        ),  # gitleaks:allow
        (
            'api_key: "sk-proj-abcdefghijklmnopqrstuvwxyz012345"',
            "sk-proj-abcdefghij",
        ),  # gitleaks:allow
        ("password = 'hunter2'", "hunter2"),
        ("DB_PASSWORD:s3cr3t", "s3cr3t"),
        ("--password hunter2", "hunter2"),
        ("--token=abc123def456ghi789jkl", "abc123def456"),  # gitleaks:allow
        ("$env:SLACK_TOKEN = 'xoxb-1234567890-abcdefghij'", "xoxb-1234567890"),  # gitleaks:allow
        (
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CVPmB92K27uhb",  # gitleaks:allow
            "eyJhbGciOiJIUzI1NiJ9",
        ),
        (
            "git clone https://alice:ghp_secretvaluehere1234@github.com/o/r.git",
            "ghp_secretvalue",
        ),  # gitleaks:allow
        ("psql postgres://admin:tr0ub4dor@db.internal:5432/prod", "tr0ub4dor"),
    ],
)
def test_credentials_are_withheld(text, secret):
    out = redact.redact(text)
    assert secret not in out, f"SECRET SURVIVED redaction of {text!r} -> {out!r}"
    assert PLACEHOLDER in out, f"no placeholder emitted for {text!r} -> {out!r}"


def test_private_key_blocks_are_withheld_whole():
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"  # gitleaks:allow
        "MIIEowIBAAKCAQEAx7Xn9Q==\naGVsbG8gd29ybGQ=\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out = redact.redact(f"cat id_rsa\n{pem}\ndone")
    assert "MIIEowIBAAKCAQEA" not in out
    assert "done" in out, "redaction must not swallow surrounding context"


def test_the_key_name_survives_so_the_model_can_still_reason():
    """Shape is preserved deliberately: a planner may need to know a token WAS supplied."""
    out = redact.redact("GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz123")
    assert "GITHUB_TOKEN" in out and "ghp_abcdefghij" not in out


def test_url_userinfo_keeps_host_and_user():
    out = redact.redact("https://alice:sup3rs3cret@github.com/org/repo.git")
    assert "alice" in out and "github.com/org/repo.git" in out
    assert "sup3rs3cret" not in out


def test_redaction_is_idempotent():
    once = redact.redact("token=abcdefghijklmnop")
    assert redact.redact(once) == once


def test_redaction_never_raises_on_hostile_input():
    for text in ("", "\x00\x01", "token=" + "x" * 100_000, "\udcff lone surrogate"):
        redact.redact(text)


def test_redaction_is_linear_in_input_size():
    """Regression: the URL-userinfo rule was quadratic and took 23.9 s on 100 KB of plain text.

    redact() runs on every prompt render, every trace record and every saved event, over model
    output and fetched web pages — attacker-influenced input on a hot path. A regex that
    backtracks there is a denial of service, not a slow function. Measured as a ratio rather
    than an absolute so the test does not turn into a flaky benchmark of the host.
    """
    import time

    def _elapsed(size: int) -> float:
        payload = "lorem ipsum dolor sit amet " * (size // 27)
        t0 = time.perf_counter()
        redact.redact(payload)
        return time.perf_counter() - t0

    small = max(_elapsed(20_000), 1e-4)
    large = _elapsed(200_000)
    assert large / small < 40, (
        f"10x the input took {large / small:.0f}x the time ({small * 1000:.1f}ms -> "
        f"{large * 1000:.1f}ms): a quantifier is backtracking"
    )
    assert large < 2.0, f"200 KB took {large:.2f}s; redaction is on every prompt render"


# ── Must NOT be withheld ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "git checkout 9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e",  # commit SHA
        "sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=",  # lockfile integrity
        "id: 550e8400-e29b-41d4-a716-446655440000",  # UUID
        r"C:\Users\ExampleUser\AppData\Local\Programs\Python\Python312",  # long path
        "npm install express@4.18.2 --save-exact",
        "python -m pip install --index-url https://pypi.org/simple pkg",
        "Set-Content config.json -Value '{\"port\": 8080}'",
        "docker run -e NODE_ENV=production myimage:latest",
    ],
)
def test_ordinary_sysops_text_is_untouched(text):
    assert redact.redact(text) == text, "a false positive here degrades the planner's context"


def test_a_word_that_merely_contains_token_is_not_a_secret():
    """`tokenizer`, `tokenize` — substring matching here would redact half a build log."""
    assert redact.redact("tokenizer=fast") == "tokenizer=fast"


# ── Secret files ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "prod.env",
        "local.env",
        ".env.production",
        "config/.env",
        "~/.ssh/id_rsa",
        "id_ed25519",
        "server.pem",
        "cert.p12",
        "keystore.jks",
        ".npmrc",
        ".netrc",
        ".pgpass",
        "aws/credentials",
        ".htpasswd",
    ],
)
def test_credential_stores_are_recognised(path):
    assert is_secret_file(path), path


@pytest.mark.parametrize(
    "path",
    [
        "package.json",
        "main.py",
        "README.md",
        "environment.yml",
        "src/keyboard.ts",
        "docs/tokens.md",
        "public/key-visual.png",
    ],
)
def test_ordinary_files_are_not_credential_stores(path):
    assert not is_secret_file(path), path


def test_prod_env_was_the_reported_gap():
    """observer._TEXT_EXT included ".env" and skipped only DOT-prefixed names, so `prod.env`
    was read whole and previewed into model context."""
    assert is_secret_file("prod.env") and is_secret_file(".env")


# ── Nested structures ────────────────────────────────────────────────────────


def test_mapping_redaction_reaches_nested_values():
    """telemetry.record_run serialises SystemState wholesale; `facts` holds DISCOVERY stdout."""
    # fmt: off
    payload = {
        "facts": {"discovery::env": "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENGbPxRfiCY"},  # gitleaks:allow
        "history": [{"command": "curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.e30.sig'"}],  # gitleaks:allow
        "exit_code": 0,
    }
    # fmt: on
    out = redact_mapping(payload)
    assert "wJalrXUtnFEMI" not in str(out)
    assert "eyJhbGciOiJIUzI1NiJ9" not in str(out)
    assert out["exit_code"] == 0, "non-string values must survive unchanged"


def test_mapping_redaction_withholds_secret_file_contents_by_key():
    out = redact_mapping({"files": {".env": "DATABASE_URL=postgres://u:p@h/db"}})
    assert "postgres://u:p@h/db" not in str(out)
