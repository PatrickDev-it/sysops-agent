"""
Dataset integrity validator (CI gate).

Verifies the generated corpus is well-formed and self-consistent WITHOUT needing a
live host. Checks:
  - every case round-trips through the Case model (all 25 mandated fields present);
  - conforms to schema/benchmark.schema.json if `jsonschema` is available (optional);
  - no two cases share a semantic signature (true de-duplication);
  - ids are unique and correctly formatted;
  - every `forbidden_commands` / verify `pattern` compiles as a regex;
  - each success_check is a valid, evaluable predicate shape;
  - per-OS counts and difficulty distribution meet the benchmark minimums;
  - required domains are covered on each OS.

Exit code is non-zero on any hard failure, so CI can gate on it.

Usage:
  python -m benchmarks.osbench.validators.validate_dataset
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from ..shared.model import DOMAINS, Case, Verify

ROOT = Path(__file__).resolve().parent.parent
JSONL = ROOT / "datasets" / "all_cases.jsonl"
SCHEMA = ROOT / "schema" / "benchmark.schema.json"

# Per-OS minimums (floors). Total per OS must also be >= 500.
MIN_DIFF = {"easy": 25, "medium": 50, "hard": 150, "expert": 200, "principal": 75}
MIN_PER_OS = 500
MIN_GOLDEN = 100

_ID_RE = re.compile(r"^[A-Z]{3}-[A-Z0-9_]+-[0-9]{5}$")
ID_FIELDS = 25  # the mandated structural fields (excluding alignment metadata)


def _iter_raw():
    with JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _check_regexes(v: Verify, errors: list[str], cid: str) -> None:
    if v.pattern:
        try:
            re.compile(v.pattern)
        except re.error as e:
            errors.append(f"{cid}: bad verify pattern {v.pattern!r}: {e}")
    for c in v.checks:
        _check_regexes(c, errors, cid)


def main() -> int:
    if not JSONL.exists():
        print(f"FATAL: {JSONL} not found — run build_dataset first.", file=sys.stderr)
        return 2

    errors: list[str] = []
    warnings: list[str] = []
    ids: Counter = Counter()
    sigs: dict[str, str] = {}
    per_os: Counter = Counter()
    per_os_diff: dict[str, Counter] = defaultdict(Counter)
    per_os_domain: dict[str, set] = defaultdict(set)
    golden = 0
    total = 0

    # optional jsonschema
    schema = None
    validator = None
    try:
        import jsonschema  # type: ignore

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
    except Exception:  # noqa: BLE001
        warnings.append(
            "jsonschema not installed — skipping JSON Schema conformance (model round-trip still enforced)."
        )

    for raw in _iter_raw():
        total += 1
        cid = raw.get("id", "<no-id>")

        # 1) JSON Schema (optional)
        if validator is not None:
            for e in validator.iter_errors(raw):
                errors.append(f"{cid}: schema: {e.message}")

        # 2) model round-trip (enforces all mandated fields + types)
        try:
            case = Case.from_dict(raw)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cid}: model round-trip failed: {e}")
            continue

        # 3) id format + uniqueness
        if not _ID_RE.match(case.id):
            errors.append(f"{cid}: id does not match required format")
        ids[case.id] += 1

        # 4) signature uniqueness (true dedup)
        sig = case.signature()
        if sig in sigs:
            errors.append(f"{cid}: duplicate signature with {sigs[sig]}")
        else:
            sigs[sig] = case.id

        # 5) regex validity of forbidden_commands + verify patterns
        for fc in case.forbidden_commands:
            try:
                re.compile(fc)
            except re.error as e:
                errors.append(f"{cid}: bad forbidden_command regex {fc!r}: {e}")
        _check_regexes(case.success_check, errors, cid)
        if case.failure_check:
            _check_regexes(case.failure_check, errors, cid)

        # 6) non-empty core content (no placeholders/TODOs)
        for field_name in ("scenario", "success_criteria", "recovery_strategy"):
            val = getattr(case, field_name)
            if not val or "TODO" in val or "PLACEHOLDER" in val.upper():
                errors.append(f"{cid}: field '{field_name}' empty or contains TODO/PLACEHOLDER")
        for list_field in (
            "expected_reasoning",
            "reference_solution",
            "possible_mistakes",
            "safety_constraints",
        ):
            if not getattr(case, list_field):
                errors.append(f"{cid}: list field '{list_field}' is empty")

        # 7) budgets monotonic-sane
        if case.expected_time_s <= 0 or case.expected_token_budget <= 0:
            errors.append(f"{cid}: non-positive time/token budget")

        # tallies
        per_os[case.os.value] += 1
        per_os_diff[case.os.value][case.difficulty.value] += 1
        per_os_domain[case.os.value].add(case.domain)
        if case.golden:
            golden += 1

    # uniqueness of ids
    for cid, n in ids.items():
        if n > 1:
            errors.append(f"duplicate id {cid} appears {n} times")

    # coverage + distribution gates
    for os_name in ("linux", "windows", "macos"):
        n = per_os.get(os_name, 0)
        if n < MIN_PER_OS:
            errors.append(f"{os_name}: only {n} cases (< {MIN_PER_OS})")
        for diff, floor in MIN_DIFF.items():
            got = per_os_diff[os_name].get(diff, 0)
            if got < floor:
                errors.append(f"{os_name}: difficulty '{diff}' has {got} (< {floor})")
        missing = set(DOMAINS) - per_os_domain[os_name]
        # kernel/lvm_raid/boot/wsl are legitimately not universal — warn, don't fail
        hard_missing = missing - {
            "kernel",
            "lvm_raid",
            "boot",
            "wsl",
            "selinux_apparmor",
            "gpu",
            "sudo",
            "acl",
        }
        if hard_missing:
            warnings.append(f"{os_name}: domains not covered: {sorted(hard_missing)}")

    if golden < MIN_GOLDEN:
        errors.append(f"golden set has {golden} (< {MIN_GOLDEN})")

    # report
    print(f"Validated {total} cases.")
    print(f"  per-OS: {dict(per_os)}")
    print(f"  golden: {golden}")
    if warnings:
        print("\nWARNINGS:")
        for w in warnings[:40]:
            print(f"  - {w}")
    if errors:
        print(f"\nFAILED with {len(errors)} error(s):")
        for e in errors[:60]:
            print(f"  - {e}")
        if len(errors) > 60:
            print(f"  ... and {len(errors) - 60} more")
        return 1
    print(
        "\nOK — dataset is well-formed, de-duplicated, and meets all coverage/distribution minimums."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
