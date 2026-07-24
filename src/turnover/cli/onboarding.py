import curses
import locale
import re
from datetime import datetime, timedelta

from wcwidth import wcswidth

from ..db import Conversation, Message
from .. import config
from . import render_messages

_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")

_BOX_WIDTH = 40
_BOX_HEIGHT = 7
_BOX_BOTTOM_MARGIN = 2  # leaves the box's bottom border one row up from the screen's last row

_TOP_LEFT, _TOP_RIGHT = "╔", "╗"
_BOTTOM_LEFT, _BOTTOM_RIGHT = "╚", "╝"
_HORIZONTAL, _VERTICAL = "═", "║"

_PAIR_BOX = 1
_PAIR_SHADOW = 2
_PAIR_BACKGROUND = 3
_PAIR_FG_BASE = 10  # 8 consecutive pairs (SGR 30-37) on the default background, from here
_PAIR_FG_BRIGHT_BASE = 20  # 8 consecutive pairs (SGR 90-97), only used if the terminal has >=16 colors

_bright_supported = False  # set by _wizard() once curses knows the terminal's color count

_WIZARD_OPTIONS = ["auto_sync", "datetime_format", "layout"]

_DEMO_CONVERSATION = Conversation(
    address="+14085551234",
    contact_name="Phil Schiller",
    messages=[
        Message(
            handle="3",
            folder="inbox",
            datetime="20070109T075000",
            text="Still on for dinner tonight?",
        ),
        Message(
            handle="4",
            folder="sent",
            datetime="20070109T075100",
            text="Absolutely",
        ),
        Message(
            handle="5",
            folder="inbox",
            datetime="20070109T081700",
            text="Your turn to pick",
        ),
        Message(
            handle="6",
            folder="sent",
            datetime="20070109T081800",
            text="Hmmm... Sushi place in Marin?",
        ),
        Message(
            handle="7",
            folder="inbox",
            datetime="20070109T082000",
            text="How about 7pm tonight?",
        ),
        Message(
            handle="8",
            folder="sent",
            datetime="20070109T101700",
            text="Sounds great! See you there.",
        ),
        Message(
            handle="9",
            folder="sent",
            datetime=datetime.today().strftime("%Y%m%dT094100") if datetime.today().hour >= 10 else (datetime.today() - timedelta(days=1)).strftime("%Y%m%dT094100"),
            text="Here's to the crazy ones. The misfits. The rebels. The troublemakers. The round pegs in the square holes. The ones who see things differently. They're not fond of rules. And they have no respect for the status quo. You can quote them, disagree with them, glorify or vilify them.\r\n\r\nAbout the only thing you can't do is ignore them."
        ),
    ],
)


def _addstr_clipped(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
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


def _split_ansi(line: str):
    """
    Splits a line containing ANSI SGR color escapes (as produced by utils.colorize) into
    (text, curses_attr) segments, translating the 8 base foreground colors (30-37), bold (1), and
    reset (0). Bright colors (90-97) map to the terminal's real bright-palette pairs (8-15) when
    it has >=16 colors, which is true for virtually every terminal in use today; only on a
    genuinely limited 8-color terminal do we fall back to approximating brightness with A_BOLD,
    since that's the only way to distinguish it there.
    """
    attr = curses.color_pair(_PAIR_BACKGROUND)
    pos = 0
    for m in _SGR_RE.finditer(line):
        if m.start() > pos:
            yield line[pos:m.start()], attr
        for code in (int(c) for c in m.group(1).split(";") if c) or (0,):
            if code == 0:
                attr = curses.color_pair(_PAIR_BACKGROUND)
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


def _draw_background(stdscr) -> None:
    text = render_messages.get_conversation_string([_DEMO_CONVERSATION])
    for row, line in enumerate(text.splitlines()):
        x = 0
        for segment, attr in _split_ansi(line):
            _addstr_clipped(stdscr, row, x, segment, attr)
            x += wcswidth(segment)


def _draw_box(stdscr, box_x, box_y, width, height, title: str | None = None) -> None:
    shadow_attr = curses.color_pair(_PAIR_SHADOW)
    for row in range(height):
        _addstr_clipped(stdscr, box_y + row + 1, box_x + 1, " " * width, shadow_attr)

    box_attr = curses.color_pair(_PAIR_BOX)
    _addstr_clipped(stdscr, box_y, box_x, _TOP_LEFT + _HORIZONTAL * (width - 2) + _TOP_RIGHT, box_attr)
    for y in range(box_y + 1, box_y + height):
        _addstr_clipped(stdscr, y, box_x, _VERTICAL + " " * (width - 2) + _VERTICAL, box_attr)
    _addstr_clipped(stdscr, box_y + height - 1, box_x, _BOTTOM_LEFT + _HORIZONTAL * (width - 2) + _BOTTOM_RIGHT, box_attr)

    if title:
        title = f" {title} "
        _addstr_clipped(stdscr, box_y, (width // 2) - (len(title) // 2) + box_x, title, box_attr)


def _draw_settings_box(stdscr) -> None:
    max_y, max_x = stdscr.getmaxyx()
    box_x = (max_x - _BOX_WIDTH) // 2
    box_y = max_y - _BOX_BOTTOM_MARGIN - _BOX_HEIGHT

    _draw_box(stdscr, box_x, box_y, _BOX_WIDTH, _BOX_HEIGHT, "Settings")

    for i, key in enumerate(config.CONFIG_VALUES.keys()):
        _addstr_clipped(stdscr, box_y + 1 + i, box_x + 2, key, curses.color_pair(_PAIR_BOX))


def _wizard(stdscr) -> None:
    global _bright_supported

    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(_PAIR_BOX, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(_PAIR_SHADOW, curses.COLOR_WHITE, 8)  # 8 == bright black, i.e. grey; no named curses constant for it
    curses.init_pair(_PAIR_BACKGROUND, -1, -1)
    for n in range(8):
        curses.init_pair(_PAIR_FG_BASE + n, n, -1)

    _bright_supported = curses.COLORS >= 16
    if _bright_supported:
        for n in range(8):
            curses.init_pair(_PAIR_FG_BRIGHT_BASE + n, 8 + n, -1)

    selected = 0
    while True:
        stdscr.erase()
        _draw_background(stdscr)
        _draw_settings_box(stdscr)
        stdscr.refresh()

        key = stdscr.getch()
        if key == ord("q"):
            break
        elif key == curses.KEY_UP:
            selected = (selected - 1) % len(_WIZARD_OPTIONS)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(_WIZARD_OPTIONS)


def run_onboarding_wizard(options: list | None = None) -> None:
    locale.setlocale(locale.LC_ALL, "")
    try:
        curses.wrapper(_wizard)
    except KeyboardInterrupt:
        pass
