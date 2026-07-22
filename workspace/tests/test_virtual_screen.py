"""The screen renderer, tested differentially against pyte's own — and for the cost of a read.

`VirtualScreen.rows` used to be `pyte.Screen.display`, which runs `wcwidth` over the attribute
tuple of every cell as an internal assertion. MEASURED on the 220x50 screen this agent uses:
**608 ms per full render**. The PTY controller reads the screen on every poll iteration, so a
wizard that redraws twenty times spent twelve seconds inside a debug assertion — while its own
navigation timeout is 1.5 s per keystroke.

A hand-written renderer is only trustworthy if it is checked against the thing it replaces, so
these tests assert byte-equality with `display` across ANSI colour, screen clears, tabs and —
the case that actually caught a bug — double-width characters.

The module had ZERO tests before this, and it is where invariant #8 lives.
"""

import pytest
from src.terminal_runtime.virtual_screen import VirtualScreen

CASES = {
    "plain": b"hello\r\nworld\r\n",
    "ansi_colour": b"\x1b[31mred\x1b[0m normal\r\n\x1b[1mbold\x1b[0m\r\n",
    "reverse_video": b"\x1b[7mselected\x1b[0m\r\n  other\r\n",
    "clear_and_home": b"junk\r\n\x1b[2J\x1b[Hfresh\r\n",
    "tabs": b"a\tb\tc\r\n",
    "cjk_wide": "日本語テキスト\r\nmixed 漢字 text\r\n".encode(),
    "cursor_moves": b"abc\x1b[2Dxy\r\n",
    "erase_line": b"abcdef\r\x1b[Kzz\r\n",
    "empty": b"",
}


def _pyte_reference(vs: VirtualScreen) -> list[str]:
    lines = [vs._screen.display[r].rstrip() for r in range(vs._rows)]
    while lines and not lines[-1]:
        lines.pop()
    return lines


@pytest.mark.parametrize("name", sorted(CASES))
def test_render_matches_pyte_exactly(name):
    vs = VirtualScreen()
    vs.feed(CASES[name])
    assert vs.rows == _pyte_reference(vs)


def test_double_width_characters_are_not_padded():
    """pyte stores a wide glyph in one column and an EMPTY string in the next. Emitting a
    space for that continuation cell inserted a gap into every CJK line — found by the
    differential test above, not by inspection."""
    vs = VirtualScreen()
    vs.feed("日本語\r\n".encode())
    assert vs.rows[0] == "日本語"


def test_reading_the_screen_is_cheap():
    """The controller polls the screen after every keystroke; a read must not cost more than
    the keystroke's own timeout."""
    import time

    vs = VirtualScreen()
    vs.feed(b"\x1b[2J\x1b[H" + b"".join(f"  option {i}\r\n".encode() for i in range(20)))

    t0 = time.perf_counter()
    for _ in range(50):
        vs._cache.clear()  # force a genuine cold render each time
        _ = vs.rows
    cold_ms = (time.perf_counter() - t0) * 1000 / 50
    assert cold_ms < 5.0, f"{cold_ms:.1f} ms per screen render (was 608 ms via pyte.display)"


def test_repeated_reads_between_feeds_are_free():
    """The rendered views are a pure function of emulator state, and state only changes on
    feed. Without this the navigator re-rendered the same frame on every poll."""
    import time

    vs = VirtualScreen()
    vs.feed(b"  a\r\n  b\r\n")
    vs.rows, vs.highlighted_rows_text()  # warm

    t0 = time.perf_counter()
    for _ in range(2000):
        _ = vs.rows
        _ = vs.highlighted_rows_text()
    assert (time.perf_counter() - t0) < 0.2


def test_the_cache_is_invalidated_by_a_feed():
    vs = VirtualScreen()
    vs.feed(b"first\r\n")
    assert vs.rows == ["first"]
    vs.feed(b"second\r\n")
    assert vs.rows == ["first", "second"]


# ── The attribute plane (invisible cursors) ──────────────────────────────────


def test_reverse_video_rows_are_reported():
    vs = VirtualScreen()
    vs.feed(b"  alpha\r\n\x1b[7m  beta\x1b[0m\r\n  gamma\r\n")
    assert vs.highlighted_rows_text() == {"beta"}


def test_a_non_default_background_counts_as_highlight():
    vs = VirtualScreen()
    vs.feed(b"  alpha\r\n\x1b[44m  beta\x1b[0m\r\n")
    assert "beta" in vs.highlighted_rows_text()


def test_a_screen_with_no_highlight_reports_none():
    vs = VirtualScreen()
    vs.feed(b"  alpha\r\n  beta\r\n")
    assert vs.highlighted_rows_text() == set()


# ── Invariant #8 ─────────────────────────────────────────────────────────────


def test_feed_accepts_raw_bytes_with_ansi_intact():
    """AGENTS.md invariant #8. The module had no test at all, so the invariant was a comment."""
    vs = VirtualScreen()
    vs.feed(b"\x1b[7mSELECTED\x1b[0m\r\nplain\r\n")
    assert vs.rows[0] == "SELECTED"
    assert vs.highlighted_rows_text() == {"SELECTED"}


def test_ansi_split_across_two_feeds_is_still_interpreted():
    """pyte's ByteStream buffers incomplete sequences across calls — which is precisely why
    the bytes must reach it undecoded, and why a 4096-byte read boundary is safe."""
    vs = VirtualScreen()
    vs.feed(b"\x1b[")
    vs.feed(b"7mSPLIT\x1b[0m\r\n")
    assert vs.rows[0] == "SPLIT"
    assert vs.highlighted_rows_text() == {"SPLIT"}


def test_a_multibyte_character_split_across_feeds_survives():
    payload = "日本".encode()
    vs = VirtualScreen()
    vs.feed(payload[:3])
    vs.feed(payload[3:])
    assert vs.rows[0] == "日本"
