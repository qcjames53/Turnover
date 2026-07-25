import curses
import locale
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from wcwidth import wcswidth

from ..db import Conversation, Message
from .. import config
from . import render_messages

_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")

_TOP_LEFT, _TOP_RIGHT = "╔", "╗"
_BOTTOM_LEFT, _BOTTOM_RIGHT = "╚", "╝"
_HORIZONTAL, _VERTICAL = "═", "║"

_PAIR_BOX = 1
_PAIR_SHADOW = 2
_PAIR_BACKGROUND = 3
_PAIR_HIGHLIGHT = 4
_PAIR_FG_BASE = 10  # 8 consecutive pairs (SGR 30-37) on the default background, from here
_PAIR_FG_BRIGHT_BASE = 20  # 8 consecutive pairs (SGR 90-97), only used if the terminal has >=16 colors

_bright_supported = False  # set by _wizard() once curses knows the terminal's color count

# (config key, display label) pairs, in the order they appear in the settings box.
_SETTING_FIELDS: list[tuple[str, str]] = [
    ("layout", "Layout"),
    ("datetime_format", "Datetime format"),
    ("messages_displayed", "Messages shown"),
    ("auto_sync", "Auto sync"),
]

_BOX_WIDTH = 40
_BOX_HEIGHT = len(_SETTING_FIELDS) + 3  # top/bottom border + one blank padding row above it
_BOX_BOTTOM_MARGIN = 2  # leaves the box's bottom border one row up from the screen's last row
_VALUE_FIELD_WIDTH = 20
_VALUE_INNER_WIDTH = _VALUE_FIELD_WIDTH - 4  # "⏴ " + " ⏵" chrome around the value text

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
        Message(
            handle="10",
            folder="sent",
            datetime=datetime.today().strftime("%Y%m%dT094100") if datetime.today().hour >= 10 else (datetime.today() - timedelta(days=1)).strftime("%Y%m%dT094100"),
            text="Because they change things. They push the human race forward. And while some may see them as the crazy ones, we see genius. Because the people who are crazy enough to think they can change the world, are the ones who do."
        ),
    ],
)


@dataclass
class SettingRow:
    key: str
    label: str
    options: list[str]


def _build_setting_rows() -> list[SettingRow]:
    return [SettingRow(key, label, config.CONFIG_VALUES[key].options) for key, label in _SETTING_FIELDS]


def _shift_setting(row: SettingRow, delta: int) -> None:
    """Moves `row`'s value one step toward the start/end of its options list and persists the
    change to config's in-memory cache (writing to disk is wired up separately)."""
    index = row.options.index(config.get(row.key))
    new_index = min(max(index + delta, 0), len(row.options) - 1)
    if new_index != index:
        config.set(row.key, row.options[new_index])


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


def _draw_settings_box(stdscr, rows: list[SettingRow], selected_row: int) -> None:
    max_y, max_x = stdscr.getmaxyx()
    box_x = (max_x - _BOX_WIDTH) // 2
    box_y = max_y - _BOX_BOTTOM_MARGIN - _BOX_HEIGHT

    _draw_box(stdscr, box_x, box_y, _BOX_WIDTH, _BOX_HEIGHT, "Settings")

    value_x = box_x + _BOX_WIDTH - _VALUE_FIELD_WIDTH - 1
    for i, row in enumerate(rows):
        y = box_y + i + 1
        _addstr_clipped(stdscr, y, box_x + 2, row.label, curses.color_pair(_PAIR_BOX))

        value_attr = curses.color_pair(_PAIR_HIGHLIGHT if i == selected_row else _PAIR_BOX)
        value_text = f"⏴ {config.get(row.key):<{_VALUE_INNER_WIDTH}} ⏵"
        _addstr_clipped(stdscr, y, value_x, value_text, value_attr)


def _wizard(stdscr) -> None:
    global _bright_supported

    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(_PAIR_BOX, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(_PAIR_SHADOW, curses.COLOR_WHITE, 8)  # 8 == bright black, i.e. grey; no named curses constant for it
    curses.init_pair(_PAIR_BACKGROUND, -1, -1)
    curses.init_pair(_PAIR_HIGHLIGHT, curses.COLOR_BLUE, curses.COLOR_WHITE)
    for n in range(8):
        curses.init_pair(_PAIR_FG_BASE + n, n, -1)

    _bright_supported = curses.COLORS >= 16
    if _bright_supported:
        for n in range(8):
            curses.init_pair(_PAIR_FG_BRIGHT_BASE + n, 8 + n, -1)

    rows = _build_setting_rows()
    selected_row = 0

    while True:
        stdscr.erase()
        _draw_background(stdscr)
        _draw_settings_box(stdscr, rows, selected_row)
        stdscr.refresh()

        key = stdscr.getch()
        if key == ord("q"):
            break
        elif key == curses.KEY_UP:
            selected_row = (selected_row - 1) % len(rows)
        elif key == curses.KEY_DOWN:
            selected_row = (selected_row + 1) % len(rows)
        elif key == curses.KEY_LEFT:
            _shift_setting(rows[selected_row], -1)
        elif key == curses.KEY_RIGHT:
            _shift_setting(rows[selected_row], 1)


def run_onboarding_wizard() -> None:
    locale.setlocale(locale.LC_ALL, "")
    try:
        curses.wrapper(_wizard)
    except KeyboardInterrupt:
        pass
