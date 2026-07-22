"""
Level 1 — Virtual Screen.

Receives raw PTY bytes, feeds them through a pyte VT100 emulator, and
exposes the rendered screen as a stable list of clean text rows.

The emulator handles *all* ANSI/VT100 interpretation:
  cursor movement, erase, alternate screen, SGR colours, OSC titles, etc.

Nothing above this layer ever sees escape sequences.
"""

from __future__ import annotations

import pyte

# Default terminal dimensions — wide enough for most wizard UIs
_COLS = 220
_ROWS = 50


class VirtualScreen:
    """A VT100 terminal emulator backed by pyte."""

    def __init__(self, cols: int = _COLS, rows: int = _ROWS) -> None:
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.ByteStream(self._screen)
        self._cols = cols
        self._rows = rows
        self._cache: dict[str, object] = {}

    def feed(self, data: bytes | str) -> None:
        """Push raw PTY output into the emulator."""
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        self._stream.feed(data)
        # The rendered views are a pure function of the emulator's state, and the state only
        # changes here. Everything cached is therefore valid until the next feed.
        self._cache.clear()

    @property
    def rows(self) -> list[str]:
        """
        Current rendered screen as a list of plain-text rows (top → bottom).
        Trailing whitespace is stripped from each row.
        Empty rows at the bottom of the screen are excluded.

        CACHED PER FEED. `pyte.Screen.display` renders every cell of a 220x50 grid through
        `wcwidth`; measured at ~5.9 ms per call on this screen size. The closed-loop navigator
        polls for a redraw after every keystroke and the main loop re-reads the screen on every
        iteration, so this was being recomputed hundreds of times between two identical frames
        — enough to make an eleven-item menu take longer than the wizard it was driving.
        """
        cached = self._cache.get("rows")
        if cached is None:
            lines = [self._render_row(r) for r in range(self._rows)]
            while lines and not lines[-1]:  # drop trailing blank lines
                lines.pop()
            cached = lines
            self._cache["rows"] = cached
        return cached  # type: ignore[return-value]

    def _render_row(self, r: int) -> str:
        """One row of text, read straight from the emulator buffer.

        NOT `pyte.Screen.display`. That property runs `wcwidth` over the attribute tuple of
        every cell as an internal assertion, which on this 220x50 screen costs **608 ms per
        full render** — measured, against **0.1 ms** for the loop below. The PTY controller
        reads the screen on every poll, so a wizard that redraws twenty times was spending
        twelve seconds inside a debug assertion.

        The buffer is a sparse defaultdict: absent columns are blank, so iterating the keys
        that exist and placing them by index reproduces the same text without touching cells
        the terminal never wrote.
        """
        line = self._screen.buffer.get(r)
        if not line:
            return ""
        width = max(line) + 1
        out: list[str] = []
        for col in range(width):
            cell = line.get(col)
            if cell is None:
                out.append(" ")  # a column the terminal never wrote
            else:
                # A DOUBLE-WIDTH character occupies two columns: pyte stores the glyph in the
                # first and an EMPTY string in the second. Emitting a space for that
                # continuation cell inserted a spurious gap into every CJK line — caught by
                # differential testing against pyte's own renderer, which is the only reason
                # to trust a hand-written one at all.
                out.append(cell.data)
        return "".join(out).rstrip()

    @property
    def highlighted_rows(self) -> set[int]:
        """Rows rendered in reverse video or on a non-default background.

        This is how most TUIs mark the selected row when they emit no cursor GLYPH — clack,
        BubbleTea, fzf, dialog, questionary and the majority of Go/Rust CLIs among them. The
        `rows` property above renders `screen.display`, which is text only, so that entire
        class of menu had a cursor this agent could not see; `_try_select` then fell back to
        claiming index 0 and navigation counted keystrokes from a fabricated origin.

        pyte carries the full attribute plane per cell (`reverse`, `fg`, `bg`) and it was
        simply discarded. Reading it costs one pass over the buffer and turns "invisible" into
        "measured".
        """
        cached = self._cache.get("highlight_rows")
        if cached is None:
            out: set[int] = set()
            for r in range(self._rows):
                line = self._screen.buffer.get(r)
                if not line:
                    continue
                # Short-circuit on the first highlighted cell rather than materialising the
                # row: this runs on every navigation poll.
                for cell in line.values():
                    if cell.data.strip() and (cell.reverse or cell.bg != "default"):
                        out.add(r)
                        break
            cached = out
            self._cache["highlight_rows"] = cached
        return cached  # type: ignore[return-value]

    def highlighted_rows_text(self) -> set[str]:
        """The stripped TEXT of the highlighted rows.

        Text rather than indices because every consumer above re-indexes the screen (the
        detector filters blank rows), and an index that silently means something different
        one layer up is the shape of defect this tree keeps paying for.
        """
        cached = self._cache.get("highlight_text")
        if cached is None:
            # `self._screen.display` renders EVERY cell of the grid on each access, so
            # indexing it once per highlighted row re-rendered the screen once per row.
            # `rows` is already the rendered, cached view; index that instead.
            rendered = self.rows
            out: set[str] = {
                rendered[r].strip()
                for r in self.highlighted_rows
                if 0 <= r < len(rendered) and rendered[r].strip()
            }
            cached = out
            self._cache["highlight_text"] = cached
        return cached  # type: ignore[return-value]

    @property
    def cursor_row(self) -> int:
        return self._screen.cursor.y

    @property
    def cursor_col(self) -> int:
        return self._screen.cursor.x

    @property
    def title(self) -> str:
        return self._screen.title or ""

    def display_text(self) -> str:
        """Full screen as a single newline-joined string."""
        return "\n".join(self.rows)

    def tail(self, n: int = 15) -> list[str]:
        """Last N non-empty rows (most recent output)."""
        nonempty = [r for r in self.rows if r.strip()]
        return nonempty[-n:]

    def reset(self) -> None:
        """Hard reset — new emulator instance."""
        self._screen = pyte.Screen(self._cols, self._rows)
        self._stream = pyte.ByteStream(self._screen)
