"""Generic curses drawing helpers"""

import curses
import re

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


def split_ansi(line: str):
    """
    Splits a line containing ANSI SGR color escapes (as produced by utils.colorize) into
    (text, curses_attr) segments, translating the 8 base foreground colors (30-37), bold (1), and
    reset (0). Bright colors (90-97) map to the terminal's real bright-palette pairs (8-15) when
    it has >=16 colors, which is true for virtually every terminal in use today; only on a
    genuinely limited 8-color terminal do we fall back to approximating brightness with A_BOLD,
    since that's the only way to distinguish it there.
    """
    attr = curses.color_pair(PAIR_BACKGROUND)
    pos = 0
    for m in _SGR_RE.finditer(line):
        if m.start() > pos:
            yield line[pos:m.start()], attr
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
        yield line[pos:], attr


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
