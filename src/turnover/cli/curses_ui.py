"""Generic curses drawing helpers"""

import curses
import curses.ascii
import re
from dataclasses import dataclass
from typing import Callable

from . import utils

_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")

_TOP_LEFT, _TOP_RIGHT = "╔", "╗"
_BOTTOM_LEFT, _BOTTOM_RIGHT = "╚", "╝"
_HORIZONTAL, _VERTICAL = "═", "║"

PAIR_BOX = 1
PAIR_SHADOW = 2
PAIR_BACKGROUND = 3
PAIR_HIGHLIGHT = 4
_PAIR_FG_BASE = 10  # 8 consecutive pairs (SGR 30-37) on the default background, from here
_PAIR_FG_BRIGHT_BASE = 20  # 8 consecutive pairs (SGR 90-97), only used if the terminal has >=16 colors

_bright_supported = False  # set by init_colors() once curses knows the terminal's color count

_BOX_BOTTOM_MARGIN = 2  # rows of clearance between a bottom-centered box and the screen's bottom edge
_MESSAGE_BOX_PADDING = 4  # left+right border/margin columns, for boxes sized to their own content

ENTER_KEYS = (curses.KEY_ENTER, ord("\n"), ord("\r"))
QUIT_KEYS = (curses.ascii.ESC, ord("q"))


@dataclass
class Button:
    """A bracketed button label, e.g. "[ Continue ]" -- shared by every wizard box that shows a
    single actionable button, so the "[ " / " ]" decoration lives in one place instead of being
    baked into each label constant."""
    label: str

    def __str__(self) -> str:
        return f"[ {self.label} ]"


_DEFAULT_CONTINUE_BUTTON = Button("Continue")


def init_colors(stdscr) -> None:
    """
    Sets up this module's curses color pairs: PAIR_BOX/SHADOW/BACKGROUND/HIGHLIGHT for draw_box()
    and callers, plus one pair per SGR foreground color (bright variants too, when the terminal
    supports >=16 colors) so split_ansi() can translate render_messages' ANSI output.
    """
    global _bright_supported

    curses.use_default_colors()
    curses.init_pair(PAIR_BOX, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(PAIR_SHADOW, curses.COLOR_WHITE, 8)  # 8 == bright black, i.e. grey; no named curses constant for it
    curses.init_pair(PAIR_BACKGROUND, -1, -1)
    curses.init_pair(PAIR_HIGHLIGHT, curses.COLOR_BLUE, curses.COLOR_WHITE)
    for n in range(8):
        curses.init_pair(_PAIR_FG_BASE + n, n, -1)

    _bright_supported = curses.COLORS >= 16
    if _bright_supported:
        for n in range(8):
            curses.init_pair(_PAIR_FG_BRIGHT_BASE + n, 8 + n, -1)


def addstr_clipped(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    """
    addstr, but clipped to the screen bounds instead of raising on off-screen writes (curses also
    refuses a write that lands exactly on the bottom-right cell, which addstr otherwise raises on).
    """
    max_y, max_x = stdscr.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    text = text[: max_x - x]
    if not text:
        return
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


def split_ansi(line: str, attr: int | None = None) -> tuple[list[tuple[str, int]], int]:
    """
    Splits a line containing ANSI SGR color escapes (as produced by utils.colorize) into
    (text, curses_attr) segments, translating the 8 base foreground colors (30-37), bold (1), and
    reset (0). Bright colors (90-97) map to the terminal's real bright-palette pairs (8-15) when
    it has >=16 colors, which is true for virtually every terminal in use today; only on a
    genuinely limited 8-color terminal do we fall back to approximating brightness with A_BOLD,
    since that's the only way to distinguish it there.

    `attr` is the color state active as the line starts -- pass in a previous line's returned
    attr to carry an unclosed color across the newline between them (mirroring how a real
    terminal keeps SGR state across newlines), or omit for the default background color.

    :returns: The (text, attr) segments, and the attr still active at the end of the line, for
        threading into the next line.
    """
    attr = curses.color_pair(PAIR_BACKGROUND) if attr is None else attr
    segments: list[tuple[str, int]] = []
    pos = 0
    for m in _SGR_RE.finditer(line):
        if m.start() > pos:
            segments.append((line[pos:m.start()], attr))
        for code in (int(c) for c in m.group(1).split(";") if c) or (0,):
            if code == 0:
                attr = curses.color_pair(PAIR_BACKGROUND)
            elif code == 1:
                attr |= curses.A_BOLD
            elif 30 <= code <= 37:
                attr = curses.color_pair(_PAIR_FG_BASE + (code - 30)) | (attr & curses.A_BOLD)
            elif 90 <= code <= 97:
                if _bright_supported:
                    attr = curses.color_pair(_PAIR_FG_BRIGHT_BASE + (code - 90)) | (attr & curses.A_BOLD)
                else:
                    attr = curses.color_pair(_PAIR_FG_BASE + (code - 90)) | curses.A_BOLD
        pos = m.end()
    if pos < len(line):
        segments.append((line[pos:], attr))
    return segments, attr


def bottom_center_origin(stdscr, width: int, height: int, margin: int = _BOX_BOTTOM_MARGIN) -> tuple[int, int]:
    """Top-left (x, y) for a `width`x`height` box horizontally centered and sitting `margin` rows
    above the bottom of the screen -- shared positioning math for every wizard box."""
    max_y, max_x = stdscr.getmaxyx()
    return (max_x - width) // 2, max_y - margin - height


def draw_text(stdscr, text: str) -> None:
    """
    Draws `text` (which may contain ANSI SGR color escapes) top-left, one screen row per line.
    A color left open at a line's end (no SGR reset before its newline) carries into the next
    line, same as it would in a real terminal.
    """
    attr = None
    for row, line in enumerate(text.splitlines()):
        x = 0
        segments, attr = split_ansi(line, attr)
        for segment, seg_attr in segments:
            addstr_clipped(stdscr, row, x, segment, seg_attr)
            x += utils.visible_width(segment)


def draw_message_box(stdscr, title: str, lines: list[str], button: Button | None = None) -> None:
    """
    Bottom-centered box sized to fit `lines` plus an optional `button`, with all text centered
    within the box -- for static "read this, then press enter" screens, as opposed to a
    fixed-size, row-navigable layout like a settings box.
    """
    button_text = str(button) if button else None
    content = [*lines, "", button_text] if button_text else list(lines)
    width = max(len(title), *(len(line) for line in content)) + _MESSAGE_BOX_PADDING
    height = len(content) + 2

    box_x, box_y = bottom_center_origin(stdscr, width, height)
    draw_box(stdscr, box_x, box_y, width, height, title)

    box_attr = curses.color_pair(PAIR_BOX)
    highlight_attr = curses.color_pair(PAIR_HIGHLIGHT)
    button_index = len(content) - 1 if button_text else None
    for i, line in enumerate(content):
        x = box_x + (width - len(line)) // 2
        attr = highlight_attr if i == button_index else box_attr
        addstr_clipped(stdscr, box_y + 1 + i, x, line, attr)


def prompt_page(
    stdscr, background: Callable[[], str], title: str, lines: list[str], button: Button = _DEFAULT_CONTINUE_BUTTON
) -> bool:
    """
    Static "read this, then press enter" screen: draws `background()` full-screen behind a
    bottom-centered message box, and loops until Enter/Esc/q.

    :param background: Called fresh on every redraw so a resize mid-page re-centers it to the
        new terminal size, rather than freezing it to whatever the size was when the page was
        first entered.
    :returns: True on enter (continue), False on Esc/q (back out).
    """
    while True:
        stdscr.erase()
        draw_text(stdscr, background())
        draw_message_box(stdscr, title, lines, button)
        stdscr.refresh()

        key = stdscr.getch()
        if key in QUIT_KEYS:
            return False
        if key in ENTER_KEYS:
            return True


def draw_box(stdscr, box_x, box_y, width, height, title: str | None = None) -> None:
    shadow_attr = curses.color_pair(PAIR_SHADOW)
    for row in range(height):
        addstr_clipped(stdscr, box_y + row + 1, box_x + 1, " " * width, shadow_attr)

    box_attr = curses.color_pair(PAIR_BOX)
    addstr_clipped(stdscr, box_y, box_x, _TOP_LEFT + _HORIZONTAL * (width - 2) + _TOP_RIGHT, box_attr)
    for y in range(box_y + 1, box_y + height):
        addstr_clipped(stdscr, y, box_x, _VERTICAL + " " * (width - 2) + _VERTICAL, box_attr)
    addstr_clipped(stdscr, box_y + height - 1, box_x, _BOTTOM_LEFT + _HORIZONTAL * (width - 2) + _BOTTOM_RIGHT, box_attr)

    if title:
        title = f" {title} "
        addstr_clipped(stdscr, box_y, (width // 2) - (len(title) // 2) + box_x, title, box_attr)
