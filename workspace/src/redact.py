"""Single owner of secret redaction. Every sink that leaves the process calls exactly this.

There were four such sinks and none of them redacted anything:

  * the prompt rendered for a model (which may be a REMOTE oracle over HTTP),
  * the per-run trace,
  * the episodic `events` table, which stores each command and 512 bytes of its stdout,
  * the telemetry record, which serialises the whole SystemState including `facts`.

The only outbound transformation that existed was `workspace_paths.scrub`, and that replaces
one string — the workspace root — for tokenizer reasons its own docstring explains. It is not
a privacy control and was never claimed to be.

The exposure is not exotic. A DISCOVERY step runs whatever the plan proposes, and its raw
stdout becomes a fact: `Get-ChildItem Env:`, `printenv`, `npm config list`, `docker inspect`,
`cat ~/.aws/credentials` all print live credentials. `session.run` traces the full command
line, so `git clone https://user:token@host/repo` lands in the trace verbatim. Confirmed in
`var/telemetry/`: the operator's username and home directory were already there in cleartext.

DESIGN NOTE — why named patterns and not entropy.
An entropy threshold is the obvious generalisation and it is wrong here. This is a sysops
agent: it legitimately handles git SHAs, package hashes, UUIDs, base64 file content, lockfile
integrity fields and long absolute paths. A high-entropy rule redacts all of those, and the
model then plans against `<redacted>` where it needed a commit id. Every pattern below is
anchored to a KEY that names the value as a secret, to a documented credential format, or to a
syntactic position (URL userinfo) that can hold nothing else. False negatives are possible;
false positives would silently degrade the agent's reasoning, which is the worse failure for a
control that must stay switched on.

Redaction is idempotent and preserves shape: `token=<redacted>` keeps the assignment visible,
so a model can still reason that a token was supplied without learning its value, and a human
reading a trace can still see which knob was set.
"""

from __future__ import annotations

import re

PLACEHOLDER = "<redacted>"

# Keys whose VALUE is a secret by definition. Matched case-insensitively as a whole word, then
# the value up to a delimiter. Covers `KEY=v`, `KEY: v`, `--key v`, `"key": "v"`.
_SECRET_KEY = (
    r"(?:api[_-]?key|apikey|secret[_-]?key|secret|token|access[_-]?token|refresh[_-]?token"
    r"|auth[_-]?token|password|passwd|pwd|passphrase|credential|client[_-]?secret"
    r"|private[_-]?key|aws_secret_access_key|aws_access_key_id|aws_session_token"
    r"|authorization|bearer|npm_token|gh_token|github_token|slack_token|db_password"
    r"|connection[_-]?string|sas[_-]?token)"
)

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM blocks first: they span lines and would otherwise be shredded by narrower rules.
    # The body is bounded: an unterminated BEGIN marker would otherwise make the engine scan to
    # end-of-input from every candidate start.
    (
        re.compile(
            r"-----BEGIN (?:[A-Z ]{0,32} )?PRIVATE KEY-----.{0,16384}?"
            r"-----END (?:[A-Z ]{0,32} )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        f"{PLACEHOLDER}-private-key",
    ),
    # URL userinfo: `scheme://user:secret@host` — that position holds nothing but a credential.
    #
    # Every quantifier here is BOUNDED, and that is load-bearing rather than tidy. The first
    # version wrote the scheme as `[a-z][a-z0-9+.-]*://`, which is quadratic: at each of N
    # starting positions the engine consumes the remaining input greedily and then backtracks
    # looking for `://`. Measured on 100 KB of plain text with NO url in it at all: 23.9
    # SECONDS for a single search. redact() runs on every prompt render, every trace record and
    # every saved event, over model output and fetched web pages — i.e. on attacker-influenced
    # input, on a hot path. That is a denial of service, not a slow regex. Real schemes are
    # under 16 characters and real userinfo is under 256.
    (
        re.compile(
            r"(?P<scheme>[a-z][a-z0-9+.-]{0,15}://)(?P<user>[^:/?#\[\]@\s]{1,256}):"
            r"[^@/\s]{1,256}@"
        ),
        rf"\g<scheme>\g<user>:{PLACEHOLDER}@",
    ),
    # Documented, self-identifying credential formats. Anchored, so no entropy guessing.
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), f"{PLACEHOLDER}-github-token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), f"{PLACEHOLDER}-github-token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), f"{PLACEHOLDER}-slack-token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), f"{PLACEHOLDER}-api-key"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), f"{PLACEHOLDER}-aws-key-id"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        f"{PLACEHOLDER}-jwt",
    ),
    # `Authorization: Bearer <v>` / `-H "Authorization: token <v>"`.
    (
        re.compile(rf"(?i)\b(authorization\s*:\s*)(?:bearer|token|basic)\s+(?!{PLACEHOLDER})\S+"),
        rf"\g<1>Bearer {PLACEHOLDER}",
    ),
    # KEY=value / KEY: value, including quoted values. Key and separator are kept; only the
    # value is withheld. The `(?!<redacted>)` guard is what makes redaction idempotent — without
    # it a second pass matches its own output and appends another placeholder.
    (
        re.compile(rf"(?i)\b({_SECRET_KEY})(\s*[:=]\s*)(?!{PLACEHOLDER})(\"[^\"]*\"|'[^']*'|\S+)"),
        rf"\g<1>\g<2>{PLACEHOLDER}",
    ),
    # --flag value / --flag=value, e.g. `--password hunter2`, `--token=abc`.
    (
        re.compile(rf"(?i)(--{_SECRET_KEY})(\s+|=)(?!{PLACEHOLDER})(\"[^\"]*\"|'[^']*'|\S+)"),
        rf"\g<1>\g<2>{PLACEHOLDER}",
    ),
    # PowerShell `$env:TOKEN = 'v'` and `$TOKEN = "v"`.
    (
        re.compile(
            rf"(?i)(\$(?:env:)?{_SECRET_KEY})(\s*=\s*)(?!{PLACEHOLDER})"
            rf"(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        rf"\g<1>\g<2>{PLACEHOLDER}",
    ),
)

# Filenames that are credential stores by convention. Their CONTENT never reaches a prompt or a
# trace; naming the file is enough for the agent to reason about it.
SECRET_FILENAME = re.compile(
    r"(?:^|/)(?:\.env(?:\.[\w-]+)?|[\w-]*\.env|id_[rd]sa|id_ecdsa|id_ed25519"
    r"|\.npmrc|\.netrc|_netrc|\.pgpass|credentials|\.htpasswd)$"
    r"|\.(?:pem|key|p12|pfx|jks|keystore)$",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Replace credential-shaped values in `text`. Idempotent; never raises.

    Never raises, because every caller is a sink on a path that must not fail: a trace write, a
    prompt render, a telemetry dump. A redaction bug must not take down a run — but it must not
    fail OPEN either, so on an unexpected error the whole payload is withheld rather than
    emitted unredacted.
    """
    if not text:
        return text
    try:
        for pattern, replacement in _RULES:
            text = pattern.sub(replacement, text)
        return text
    except Exception:  # pragma: no cover — defensive, see docstring
        return f"{PLACEHOLDER}-redaction-failed"


def is_secret_file(path: str) -> bool:
    """True for paths whose content is a credential store by convention.

    Used to keep `fileops.read_file` and the workspace observer from lifting `.env`,
    `id_rsa` or `credentials` into a prompt. Note `observer._TEXT_EXT` previously included
    `".env"` and skipped only names beginning with a dot, so `prod.env` and `local.env` were
    read and previewed into model context in full.
    """
    return bool(SECRET_FILENAME.search((path or "").replace("\\", "/")))


def redact_mapping(data: dict[str, object]) -> dict[str, object]:
    """Redact a JSON-shaped structure, keys included.

    `telemetry.record_run` serialises SystemState wholesale — `facts` carries DISCOVERY stdout
    verbatim — so redacting only the top level would miss everything that matters.
    """

    def _walk(value: object) -> object:
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, dict):
            return {
                k: (f"{PLACEHOLDER}-secret-file" if is_secret_file(str(k)) else _walk(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_walk(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_walk(v) for v in value)
        return value

    return _walk(data)  # type: ignore[return-value]
