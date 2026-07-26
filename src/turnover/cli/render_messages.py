from datetime import datetime
import re
import textwrap
from wcwidth import wcswidth

from .. import config, pbap
from . import utils

# Padding constants
_MIN_WIDTH_MONOGRAM_COL = 7
_MIN_WIDTH_TIMESTAMP_COL = 7  # Not enforced if timestamp column goes unrendered
_MIN_DATETIME_TERMINAL_WIDTH = 50
_IRC_TIME_COL_WIDTH_12H = 8
_IRC_TIME_COL_WIDTH_24H = 6

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_REDUCED_DATETIME_MESSAGE_TIMING_THRESHOLD = 1201  # in seconds
_COSY_MESSAGE_NEWLINE_TIMING_THRESHOLD = 1201  # in seconds
_CONTACT_MONOGRAM = "[{name}]"
_USER_MONOGRAM = utils.colorize("[YOU]", utils.ANSI_CYAN)
_BLOCK_INDICATOR_TOP = utils.colorize("╭ ", utils.ANSI_GREY)
_BLOCK_INDICATOR_MID = utils.colorize("│ ", utils.ANSI_GREY)
_BLOCK_INDICATOR_BTM = utils.colorize("╰ ", utils.ANSI_GREY)


def _actual_width(text: str) -> int:
    return wcswidth(_ANSI_RE.sub("", text))


def _conversation_header(number: str, name: str | None = None):
    formatted_number = pbap.format_phone_display(number)
    center_text = f"  {name} ({formatted_number})  " if name else f"  {formatted_number}  "
    padded = center_text.center(utils.terminal_width(), "-")
    left_dashes, _, right_dashes = padded.partition(center_text)
    return (
        utils.colorize(left_dashes, utils.ANSI_GREY)
        + utils.colorize(center_text, utils.ANSI_RESET)
        + utils.colorize(right_dashes, utils.ANSI_GREY)
    )


def _monogram(name: str) -> str:
    words = name.split()
    if not words:
        return "?"
    initials = [words[0][0]]
    if len(words) >= 2:
        initials.append(words[1][0])
    if len(words) >= 3:
        initials.append(words[-1][0])
    initials_string = "".join(initials).upper()
    return _CONTACT_MONOGRAM.format(name=initials_string)


def _datetime(message_datetime: datetime, previous_message_datetime: datetime | None = None) -> str | None:
    """
    Full date + time string pair for the "dt on the right" layouts (compact/cosy). Returns None
    when nothing should be rendered for this message: datetime_format is "off", or it's a
    "(reduced)" format and this message landed close enough after the previous one to skip.
    """
    date = _date(message_datetime, previous_message_datetime)
    time = _time(message_datetime, previous_message_datetime)
    if date:
        return date + " " + time
    return time


def _date(message_datetime: datetime, previous_message_datetime: datetime | None) -> str | None:
    dt_format = utils.resolve_datetime_format()
    is_irc = config.get("layout") == "irc"
    
    if dt_format == "off":
        return None

    if is_irc:
        if previous_message_datetime and message_datetime.date() == previous_message_datetime.date():
            return None
        if dt_format == "rfc3339":
            return utils.colorize(message_datetime.strftime("%Y-%m-%d"), utils.ANSI_GREY)
        if message_datetime.date().year == datetime.now().date().year:
            return  utils.colorize(message_datetime.strftime("%A, %B %d"), utils.ANSI_GREY)
        return  utils.colorize(message_datetime.strftime("%A, %B %d, %Y"), utils.ANSI_GREY)

    if dt_format == "rfc3339":
        return utils.colorize(message_datetime.strftime("%Y-%m-%d"), utils.ANSI_GREY)
    if previous_message_datetime is None or message_datetime.date() != previous_message_datetime.date():
        if message_datetime.date() == datetime.now().date():
            return utils.colorize("Today", utils.ANSI_GREY)
        if message_datetime.date().year == datetime.now().date().year:
            return utils.colorize(message_datetime.strftime("%b %d"), utils.ANSI_GREY)
        return utils.colorize(message_datetime.strftime("%b %d %Y"), utils.ANSI_GREY)
    return None


def _time(message_datetime: datetime, previous_message_datetime: datetime | None) -> str | None:
    """
    Clock-only timestamp for the irc layout: just H:M in 12h or 24h form, never a date. Callers
    that want date breaks show them separately rather than inline per-message.
    """
    dt_format = utils.resolve_datetime_format()

    if dt_format == "off":
        return None

    if previous_message_datetime and dt_format.find("(reduced)") != -1 and \
        (message_datetime - previous_message_datetime).total_seconds() < _REDUCED_DATETIME_MESSAGE_TIMING_THRESHOLD:
        return None

    if dt_format.startswith("12h"):
        return utils.colorize(message_datetime.strftime("%-I:%M%p").lower(), utils.ANSI_GREY)
    return utils.colorize(message_datetime.strftime("%H:%M"), utils.ANSI_GREY)


def _wrap_message(m, monogram: str, monogram_width: int, left_padding: int, remaining_space: int) -> list[str]:
    """Wraps a message's text to `remaining_space` columns and prefixes the monogram / block-continuation indicators."""
    lines = []
    for paragraph in m.text.split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=remaining_space) or [""])

    if len(lines) == 1:
        lines[0] = monogram + " " * (left_padding - monogram_width) + lines[0]
    else:
        lines[0] = monogram + " " * (left_padding - monogram_width - _actual_width(_BLOCK_INDICATOR_TOP)) + _BLOCK_INDICATOR_TOP + lines[0]
        lines[1:-1] = [" " * (left_padding - _actual_width(_BLOCK_INDICATOR_MID)) + _BLOCK_INDICATOR_MID + line for line in lines[1:-1]]
        lines[-1] = " " * (left_padding - _actual_width(_BLOCK_INDICATOR_BTM)) + _BLOCK_INDICATOR_BTM + lines[-1]

    return lines


def _render_dt_right(conversations, *, blank_line_around_header: bool, gap_threshold: int | None) -> str:
    """
    Shared body for the compact and cosy layouts: monogram + text on the left, and (when it
    fits) a date/time string right-aligned on each message's first line.
    """
    terminal_width = utils.terminal_width()
    dt_format = utils.resolve_datetime_format()
    is_rendering_dt = terminal_width > _MIN_DATETIME_TERMINAL_WIDTH and dt_format != "off"

    output = ""
    for c in conversations:
        contact_monogram = _monogram(c.contact_name or pbap.format_phone_display(c.address))

        if blank_line_around_header:
            output += "\n"
        output += _conversation_header(c.address, c.contact_name) + "\n"
        if blank_line_around_header:
            output += "\n"

        prev_dt: datetime | None = None
        for m in c.messages:
            is_outgoing = m.folder == "sent"
            monogram = _USER_MONOGRAM if is_outgoing else contact_monogram
            monogram_width = _actual_width(monogram)

            dt = datetime.strptime(m.datetime, "%Y%m%dT%H%M%S")
            dt_pair = _datetime(dt, prev_dt) if is_rendering_dt else None
            dt_string = "".join(dt_pair) if dt_pair else ""
            dt_width = _actual_width(dt_string) if dt_string else 0

            if gap_threshold and prev_dt and (dt - prev_dt).total_seconds() > gap_threshold:
                output += "\n"
            prev_dt = dt

            left_padding = max(monogram_width + 2, _MIN_WIDTH_MONOGRAM_COL)
            right_padding = max(dt_width + 2, _MIN_WIDTH_TIMESTAMP_COL) if is_rendering_dt else 1
            remaining_space = terminal_width - left_padding - right_padding

            lines = _wrap_message(m, monogram, monogram_width, left_padding, remaining_space)

            if dt_string:
                gap = max(terminal_width - _actual_width(lines[0]) - dt_width, 0)
                lines[0] += " " * gap + dt_string

            output += "\n".join(lines) + "\n"

    return output


def _render_compact(conversations) -> str:
    return _render_dt_right(conversations, blank_line_around_header=False, gap_threshold=None)


def _render_cosy(conversations) -> str:
    return _render_dt_right(
        conversations,
        blank_line_around_header=True,
        gap_threshold=_COSY_MESSAGE_NEWLINE_TIMING_THRESHOLD,
    )


def _render_irc(conversations) -> str:
    """
    IRC-style layout: a fixed-width clock column on the left (12h or 24h, per datetime_format),
    monogram + text to its right. No date is rendered inline here -- show date breaks elsewhere
    in the log if you want them.
    """
    terminal_width = utils.terminal_width()
    dt_format = utils.resolve_datetime_format()
    is_rendering_dt = terminal_width > _MIN_DATETIME_TERMINAL_WIDTH and dt_format != "off"

    time_col_width = 0
    if is_rendering_dt:
        time_col_width = _IRC_TIME_COL_WIDTH_12H if dt_format.startswith("12h") else _IRC_TIME_COL_WIDTH_24H

    output = ""
    for c in conversations:
        contact_monogram = _monogram(c.contact_name or pbap.format_phone_display(c.address))
        output += _conversation_header(c.address, c.contact_name) + "\n"

        previous_message_datetime: datetime | None = None
        for m in c.messages:
            is_outgoing = m.folder == "sent"
            monogram = _USER_MONOGRAM if is_outgoing else contact_monogram
            monogram_width = _actual_width(monogram)

            left_padding = max(monogram_width + 2, _MIN_WIDTH_MONOGRAM_COL)
            remaining_space = terminal_width - left_padding - 1 - time_col_width

            lines = _wrap_message(m, monogram, monogram_width, left_padding, remaining_space)

            if is_rendering_dt:
                message_datetime = datetime.strptime(m.datetime, "%Y%m%dT%H%M%S")
                d_string = _date(message_datetime, previous_message_datetime)
                t_string = _time(message_datetime, previous_message_datetime)
                if not t_string:
                    t_string = ""
                previous_message_datetime = message_datetime

                if d_string:
                    output += "\n" + d_string + "\n"

                lines[0] = t_string + " " * (time_col_width - _actual_width(t_string)) + lines[0]
                lines[1:] = [" " * time_col_width + line for line in lines[1:]]

            output += "\n".join(lines) + "\n"

    return output


_LAYOUT_RENDERERS = {
    "irc": _render_irc,
    "compact": _render_compact,
    "cosy": _render_cosy,
    # "bubbles" is a recognized config value (see config.CONFIG_VALUES) but has no renderer
    # yet, so it falls through to the compact default below.
}


def get_conversation_string(conversations) -> str:
    renderer = _LAYOUT_RENDERERS.get(config.get("layout"), _render_compact)
    return renderer(conversations)
