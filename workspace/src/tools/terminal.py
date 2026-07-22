"""PTY terminal abstraction — Windows (winpty) + Unix fallback."""

import re
import sys
import threading
import time

from .. import trace
from .confinement import Confinement, ConfinementViolation

_ANSI_RE = re.compile(
    r"\x1b(?:"
    r"\[[0-?]*[ -/]*[@-~]"  # CSI: \x1b[ ... @-~  (colors, cursor, etc.)
    r"|\][^\x07\x1b]*\x07"  # OSC BEL-terminated: \x1b] ... \x07  (xterm title)
    r"|\][^\x07\x1b]*(?=\x1b|$)"  # OSC unterminated (truncated at buffer edge): eat greedily
    r"|[@-Z\x5c-_]"  # ESC Fe: printable 0x40-0x5A plus 0x5C-0x5F (exclude ] = 0x5B)
    r")"
)

KEY_MAP: dict[str, str] = {
    "ENTER": "\r",
    "TAB": "\t",
    "ESC": "\x1b",
    "CTRL_C": "\x03",
    "CTRL_D": "\x04",
    "CTRL_Z": "\x1a",
    "ARROW_UP": "\x1b[A",
    "ARROW_DOWN": "\x1b[B",
    "ARROW_LEFT": "\x1b[D",
    "ARROW_RIGHT": "\x1b[C",
    "SPACE": " ",
    "BACKSPACE": "\x7f",
}

# Shell prompt — signals process finished and shell is ready
_PROMPT_RE = re.compile(r"(?:PS [A-Z]:[^>]*>|[$#]\s*$)", re.MULTILINE)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class Terminal:
    """
    PTY-based terminal. Supports live wizard interaction.

    Key design: snapshot() returns ONLY new output since last call
    (delta mode), so the model always sees fresh screen content.
    """

    def __init__(
        self, shell: str = "powershell", cols: int = 200, rows: int = 50, cwd: str | None = None
    ):
        self._lock = threading.Lock()
        self._buf: list[str] = []
        self._raw_buf: list[bytes] = []  # raw PTY bytes for pyte/VirtualScreen
        self._cwd = cwd

        if sys.platform == "win32":
            from winpty import PtyProcess  # type: ignore

            self._pty = PtyProcess.spawn(shell, dimensions=(rows, cols), cwd=cwd)
            self._reader = threading.Thread(target=self._read_loop_win, daemon=True)
        else:
            import os
            import pty
            import subprocess

            master, slave = pty.openpty()
            self._proc = subprocess.Popen(
                [shell],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                close_fds=True,
                cwd=cwd,
            )
            os.close(slave)
            self._master = master
            self._reader = threading.Thread(target=self._read_loop_unix, daemon=True)

        self._reader.start()
        self._wait_ready(timeout=10.0)

    # ------------------------------------------------------------------
    # Reader threads
    # ------------------------------------------------------------------

    def _read_loop_win(self) -> None:
        while True:
            try:
                chunk = self._pty.read(4096)
                if chunk:
                    with self._lock:
                        self._buf.append(chunk)
                        # Also store raw bytes for pyte (VirtualScreen)
                        self._raw_buf.append(
                            chunk.encode("utf-8", errors="replace")
                            if isinstance(chunk, str)
                            else chunk
                        )
            except Exception:
                break

    def _read_loop_unix(self) -> None:
        import os

        while True:
            try:
                raw = os.read(self._master, 4096)
                chunk = raw.decode(errors="replace")
                if chunk:
                    with self._lock:
                        self._buf.append(chunk)
                        self._raw_buf.append(raw)
            except Exception:
                break

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _wait_ready(self, timeout: float = 10.0) -> None:
        """Wait for shell prompt, then clear buffer so first snapshot is clean."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                text = _strip_ansi("".join(self._buf))
            if _PROMPT_RE.search(text):
                with self._lock:
                    self._buf.clear()
                return
            time.sleep(0.1)

    def clear_buffer(self) -> None:
        with self._lock:
            self._buf.clear()
            self._raw_buf.clear()

    def read_raw(self) -> bytes:
        """Return all accumulated raw PTY bytes (for pyte). Does NOT clear."""
        with self._lock:
            return b"".join(self._raw_buf)

    def pop_raw(self) -> bytes:
        """Return and CLEAR accumulated raw PTY bytes (for pyte delta mode)."""
        with self._lock:
            data = b"".join(self._raw_buf)
            self._raw_buf.clear()
            return data

    # ------------------------------------------------------------------
    # Write / key
    # ------------------------------------------------------------------

    def write(self, text: str) -> None:
        if sys.platform == "win32":
            self._pty.write(text)
        else:
            import os

            os.write(self._master, text.encode())

    def send_key(self, key: str) -> None:
        seq = KEY_MAP.get(key.upper())
        if seq is None:
            raise ValueError(f"Unknown key: {key!r}")
        self.write(seq)

    # ------------------------------------------------------------------
    # Launch (fire-and-forget) vs run_command (blocking)
    # ------------------------------------------------------------------

    def launch(self, cmd: str) -> ConfinementViolation | None:
        """Send command + Enter without waiting for prompt (for interactive tools).

        The PTY is the THIRD execution owner in this tree, after `session.run` and
        `fileops`. A confinement filter wired into two of three owners is not a filter, so
        the same predicate gates this door too. A refusal is returned, not raised: the
        caller keeps its own command, exactly as with a rejected authored command.
        """
        confine = Confinement.from_env()
        if confine is not None:
            reason = confine.check(cmd)
            if reason:
                trace.emit(
                    "exec", command=cmd, exit_code=126, blocked=True, reason=reason, owner="pty"
                )
                return ConfinementViolation(reason)
        trace.emit("exec", command=cmd, exit_code=0, blocked=False, owner="pty")
        self.clear_buffer()
        self.write(cmd + "\r")
        # Give the shell time to echo the command, then clear just the echo.
        # We intentionally do NOT clear again after this — the wizard may start
        # outputting immediately and we must not lose its first prompt.
        time.sleep(0.3)
        self.clear_buffer()

    def read_ring(self, max_chars: int = 4096) -> str:
        """Return last max_chars of accumulated buffer WITHOUT clearing it."""
        with self._lock:
            text = _strip_ansi("".join(self._buf))
        return text[-max_chars:] if len(text) > max_chars else text

    def run_command(self, cmd: str, timeout: float = 60.0) -> str:
        """Send command and block until PS prompt reappears. Returns output."""
        self.clear_buffer()
        self.write(cmd + "\r")
        deadline = time.monotonic() + timeout
        last = ""
        last_change = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(0.15)
            with self._lock:
                cur = _strip_ansi("".join(self._buf))
            if cur != last:
                last = cur
                last_change = time.monotonic()
            if _PROMPT_RE.search(cur) and (time.monotonic() - last_change) > 0.5:
                break
        self.clear_buffer()
        return last

    # ------------------------------------------------------------------
    # Snapshot — delta mode
    # ------------------------------------------------------------------

    def snapshot(self, timeout: float = 0.5, tail_lines: int = 30) -> str:
        """
        Wait timeout seconds, then return and CLEAR current buffer contents.
        Returns only the tail_lines most recent lines (delta since last call).
        """
        time.sleep(timeout)
        with self._lock:
            text = _strip_ansi("".join(self._buf))
            self._buf.clear()  # delta: next call sees only new output
        lines = text.splitlines()
        return "\n".join(lines[-tail_lines:]) if len(lines) > tail_lines else text

    def read(self, timeout: float = 0.5) -> str:
        return self.snapshot(timeout=timeout)

    def close(self) -> None:
        try:
            if sys.platform == "win32":
                self._pty.close()
            else:
                import os

                os.close(self._master)
        except Exception:
            pass
