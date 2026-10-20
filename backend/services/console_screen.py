"""Server-side terminal emulation of a ConPTY stream (pyte).

ConPTY does not send a plain text stream: it draws on a fixed-size screen with
cursor positioning. Instead of replaying that raw stream into a browser terminal
(which only renders correctly if the browser grid matches exactly), the panel
interprets it here and publishes finished lines plus the current screen. Browsers
show them as normal text in whatever size their box has.
"""
from __future__ import annotations

from collections import deque
from typing import Callable

import pyte

Segment = list  # [text, colour, bold]: colour is a pyte name ("red", "brightcyan", "default") or hex
Line = list[Segment]


def _render(row, cols: int) -> Line:
    segments: Line = []
    text, fg, bold = "", None, None
    for x in range(cols):
        ch = row[x]
        if (ch.fg, ch.bold) != (fg, bold):
            if text:
                segments.append([text, fg, 1 if bold else 0])
            text, fg, bold = "", ch.fg, ch.bold
        text += ch.data
    if text:
        segments.append([text, fg, 1 if bold else 0])
    # Drop trailing blanks so lines are as long as their content.
    while segments and not segments[-1][0].strip():
        segments.pop()
    if segments:
        segments[-1][0] = segments[-1][0].rstrip()
    return segments


class _Screen(pyte.Screen):
    def __init__(self, cols: int, rows: int, on_scroll: Callable[[object], None]):
        super().__init__(cols, rows)
        self._on_scroll = on_scroll

    def index(self) -> None:
        # A line feed on the bottom margin scrolls the top line off the screen: it is final.
        top, bottom = self.margins or pyte.screens.Margins(0, self.lines - 1)
        if self.cursor.y == bottom:
            self._on_scroll(self.buffer[top])
        super().index()


class ConsoleScreen:
    def __init__(self, cols: int, rows: int, max_lines: int):
        self.cols = cols
        self.lines: deque[Line] = deque(maxlen=max_lines)   # lines that scrolled off the screen
        self.total = 0                                       # lines ever scrolled off (this run)
        self._screen = _Screen(cols, rows, self._scrolled)
        self._stream = pyte.Stream(self._screen)

    def _scrolled(self, row) -> None:
        self.lines.append(_render(row, self.cols))
        self.total += 1

    def feed(self, data: str) -> None:
        self._stream.feed(data)

    def screen_lines(self) -> list[Line]:
        """Visible rows down to the cursor (or the last row with text)."""
        rows = [_render(self._screen.buffer[y], self.cols) for y in range(self._screen.lines)]
        last = self._screen.cursor.y
        for y in range(len(rows) - 1, last, -1):
            if rows[y]:
                last = y
                break
        return rows[: last + 1]
