"""A deterministic terminal that behaves like a real select-menu TUI.

`TerminalSession` already took `write_fn` and `read_fn` as constructor arguments — the
dependency inversion was there from the start; nothing had ever been plugged into it but a
live PTY. With a clock injected too, the entire interactive subsystem becomes testable at
zero wall-clock, with no scheduler jitter and no child process.

This is not a mock. It emits real ANSI, redraws the whole menu on every keystroke the way
inquirer/clack/BubbleTea do, and lets pyte interpret it — so the code under test sees exactly
the byte stream it sees in production. A mock would have asserted that arrow keys were sent;
this asserts where the cursor ends up, which is the thing that was wrong.

Two rendering styles are supported because they exercise different cursor signals:

    GLYPH     `❯ React`         — the cursor is a character in the text plane
    REVERSE   SGR 7 on the row  — the cursor exists ONLY in the attribute plane, which is how
                                  clack, BubbleTea, fzf and most Go/Rust CLIs draw it, and
                                  which this agent could not see at all until the plane was
                                  exposed
"""

from __future__ import annotations

ESC = "\x1b"
UP = f"{ESC}[A"
DOWN = f"{ESC}[B"
ENTER = "\r"


class FakeClock:
    """Time that advances only when the code under test asks it to."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


class FakeMenuPty:
    """A wizard showing one single-select menu, then a shell prompt.

    `wrap=True` reproduces the behaviour that produced `create-marko`: arrowing past either
    end moves the cursor to the opposite end of the list instead of stopping.
    """

    def __init__(
        self,
        title: str,
        options: list[str],
        *,
        selected: int = 0,
        style: str = "glyph",
        wrap: bool = True,
        noise: list[str] | None = None,
    ) -> None:
        self.title = title
        self.options = list(options)
        self.selected = selected
        self.style = style
        self.wrap = wrap
        self.noise = noise or []
        self.committed: str | None = None
        self.keys_received: list[str] = []
        self._pending = self._render()

    # ── The two callables TerminalSession consumes ───────────────────────────

    def read(self) -> bytes:
        out, self._pending = self._pending, ""
        return out.encode("utf-8")

    def write(self, data: str) -> None:
        self.keys_received.append(data)
        if data == UP:
            self._move(-1)
        elif data == DOWN:
            self._move(+1)
        elif data.startswith("\r") or data == ENTER:
            self.committed = self.options[self.selected]
            self._pending = f"\r\n{self.committed} selected\r\nPS C:\\ws> "
            return
        else:
            return
        self._pending = self._render()

    # ── Internals ────────────────────────────────────────────────────────────

    def _move(self, delta: int) -> None:
        n = len(self.options)
        target = self.selected + delta
        if self.wrap:
            self.selected = target % n
        else:
            self.selected = max(0, min(n - 1, target))

    def _render(self) -> str:
        # Full-screen redraw, exactly as a real TUI does it: clear, home, repaint.
        parts = [f"{ESC}[2J{ESC}[H"]
        parts.extend(f"{line}\r\n" for line in self.noise)
        parts.append(f"? {self.title}\r\n")
        for i, opt in enumerate(self.options):
            if i != self.selected:
                parts.append(f"    {opt}\r\n")
            elif self.style == "glyph":
                parts.append(f"❯   {opt}\r\n")
            else:  # reverse video, no glyph at all
                parts.append(f"{ESC}[7m    {opt}{ESC}[0m\r\n")
        return "".join(parts)


class DeafMenuPty(FakeMenuPty):
    """A terminal that renders a menu and then ignores every key.

    Models a child that has hung, or a keystroke the TUI does not accept. The old controller
    could not distinguish this from success: it slept 200 ms, cleared the change-detection
    hash, and fired again. A closed loop must notice and stop.
    """

    def write(self, data: str) -> None:
        self.keys_received.append(data)
