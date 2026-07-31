"""Tests for RowScroller — the LCD marquee that reveals long lines."""

from kivo.brain import RowScroller


def test_short_line_is_static_and_padded():
    scroller = RowScroller(16)
    assert scroller.set("hi") == "hi" + " " * 14  # padded to clear the row
    assert scroller.active is False
    assert scroller.tick() is None  # nothing to animate


def test_line_exactly_the_width_does_not_scroll():
    scroller = RowScroller(16)
    scroller.set("0123456789abcdef")  # exactly 16
    assert scroller.active is False
    assert scroller.tick() is None


def test_long_line_starts_at_the_beginning():
    text = "Kivo says hello there friend"  # 28 chars > 16
    scroller = RowScroller(16, step_ticks=1, hold_ticks=0)
    assert scroller.set(text) == text[:16]
    assert scroller.active is True


def test_scrolling_reveals_every_word_including_the_tail():
    text = "Kivo says hello there friend"
    scroller = RowScroller(16, step_ticks=1, hold_ticks=0)
    windows = [scroller.set(text)]
    span = len(text) + 3  # text + gap; one full loop
    for _ in range(span + 16):
        window = scroller.tick()
        if window is not None:
            windows.append(window)

    # The last word must appear whole in some window (it was previously cut off).
    assert any("friend" in w for w in windows)
    # Every window is exactly the screen width.
    assert all(len(w) == 16 for w in windows)
    # And the animation loops back to the opening.
    assert any(w.startswith("Kivo says hello") for w in windows[1:])


def test_hold_pauses_on_the_opening_before_scrolling():
    scroller = RowScroller(16, step_ticks=1, hold_ticks=3)
    first = scroller.set("this line is definitely too long")
    # First few ticks linger on the opening window (no shift yet).
    assert scroller.tick() is None
    assert scroller.tick() is None
    assert scroller.tick() is None
    # Then it begins to move.
    moved = scroller.tick()
    assert moved is not None and moved != first
