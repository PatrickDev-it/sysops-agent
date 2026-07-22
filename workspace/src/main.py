"""Entry point — CLI for Sistemista sysops agent."""

import argparse
import sys

# No model is loaded in this process. `model_router` supervises one `llama-server` per
# owned model (lazily, on first use) and borrows the parent agent's model over HTTP.
# CUDA is llama-server's problem: nothing here touches DLLs.
from . import config
from .orchestrator import Orchestrator

# A goal is a sentence, not a document. The cap exists because the goal is interpolated into
# every planner prompt: an unbounded paste would silently evict the instruction block that the
# prefix cache and invariant #13 depend on.
MAX_GOAL_CHARS = 8000


def read_multiline_goal() -> str:
    print()
    print("Enter objective. Finish with a line containing only: END")
    print()

    lines: list[str] = []
    size = 0

    while True:
        try:
            line = input()
        except EOFError:
            break

        if line.strip() == "END":
            break

        size += len(line) + 1
        if size > MAX_GOAL_CHARS:
            print(
                f"Objective exceeds {MAX_GOAL_CHARS} characters; truncated here.", file=sys.stderr
            )
            break

        lines.append(line)

    return "\n".join(lines).strip()


def cli_entry() -> None:
    parser = argparse.ArgumentParser(
        prog="sistemista",
        description="SysOps dual-GGUF: Qwen3-4B orchestrator + Qwen2.5-Coder-3B, via llama.cpp",
    )
    parser.add_argument(
        "goal",
        nargs="?",
        help="System administration objective. If omitted, read from stdin.",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Working directory root for the session (default: current directory)",
    )
    args = parser.parse_args()

    # Preflight before anything is constructed. A missing GGUF used to surface as a 180 s
    # boot-loop timeout, and a port collision not at all — `health()` would answer from
    # whatever process already owned the port and the agent would plan against an unknown
    # model. Report every problem at once: an operator fixing a fresh install should not
    # rediscover them one restart at a time.
    problems = config.validate()
    if problems:
        print("Configuration is not runnable:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(2)

    # Stripped before the emptiness test: `"   "` is truthy, so a whitespace-only argument
    # passed both `if args.goal:` and `if not goal:` and the agent started planning against
    # an empty objective.
    goal = (args.goal or "").strip() or read_multiline_goal().strip()

    if not goal:
        print("No objective provided.", file=sys.stderr)
        sys.exit(1)
    if len(goal) > MAX_GOAL_CHARS:
        print(f"Objective exceeds {MAX_GOAL_CHARS} characters.", file=sys.stderr)
        sys.exit(1)

    orch = Orchestrator(workspace=args.workspace)
    # The process used to exit 0 on every path — completed, refused, and gave-up all read as
    # success to any wrapper script, scheduler or CI job.
    sys.exit(orch.run(goal).exit_code)


if __name__ == "__main__":
    cli_entry()
