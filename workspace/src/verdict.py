"""How a run ended, as a value rather than as console output.

`_run_loop` used to print its outcome and return None on all four terminal paths, and
`cli_entry` never called `sys.exit`. So the process exited 0 whether the agent completed the
task, refused it as destructive, gave up after two recovery passes, or died with a traceback.
No wrapper script, scheduler or CI job could tell those apart: every outcome read as success.

The enum is also what lets `run()` own telemetry. Previously each terminal path wrote its own
telemetry record, which meant the paths that were NOT terminal — an exception anywhere in the
loop — wrote none at all, and the run vanished from the record entirely.
"""

from __future__ import annotations

from enum import Enum


class RunVerdict(str, Enum):
    COMPLETE = "COMPLETE"  # every declared success predicate holds
    INCOMPLETE = "INCOMPLETE"  # the agent ran out of recovery passes
    REFUSED = "REFUSED"  # the safety gate rejected the goal before planning
    ERROR = "ERROR"  # an unhandled fault — a bug, or an unreachable model server
    ABORTED = "ABORTED"  # operator interrupt

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self]


# 130 for ABORTED follows the shell convention for SIGINT (128 + 2), so a caller that inspects
# `$?` sees an interrupt rather than an internal error.
_EXIT_CODES: dict[RunVerdict, int] = {
    RunVerdict.COMPLETE: 0,
    RunVerdict.INCOMPLETE: 1,
    RunVerdict.REFUSED: 2,
    RunVerdict.ERROR: 3,
    RunVerdict.ABORTED: 130,
}
