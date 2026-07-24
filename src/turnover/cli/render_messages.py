from datetime import datetime, timedelta
import re
import textwrap
from wcwidth import wcswidth

from .. import config, pbap
from . import utils

# Padding constants
_MIN_WIDTH_MONOGRAM_COL = 7
_MIN_WIDTH_TIMESTAMP_COL = 7  # Not enforced if timestamp column goes unrendered
_MIN_DATETIME_TERMINAL_WIDTH = 50

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_REDUCED_DATETIME_MESSAGE_TIMING_THRESHOLD = 1201  # in seconds
_COSY_MESSAGE_NEWLINE_TIMING_THRESHOLD = 1201 # in seconds
_CONTACT_MONOGRAM = "[{name}]"
_USER_MONOGRAM = utils.colorize("[YOU]", utils.ANSI_CYAN)
_BLOCK_INDICATOR_TOP = utils.colorize("╭ ", utils.ANSI_GREY)
_BLOCK_INDICATOR_MID = utils.colorize("│ ", utils.ANSI_GREY)
_BLOCK_INDICATOR_BTM = utils.colorize("╰ ", utils.ANSI_GREY)


def _actual_width(text: str) -> int:
    return wcswidth(_ANSI_RE.sub("", text))


def _conversation_header(number: str, name: str | None = None):
    formatted_number = pbap.format_phone_display(number)
    center_text = f"  {name} ({formatted_number})  "
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
    dt_format = config.get("datetime_format")
    dt_is_reduced = dt_format == "auto (reduced)" or dt_format == "12h (reduced)" or dt_format == "24h (reduced)"

    if dt_format == "off":
        return

    if previous_message_datetime and dt_is_reduced:
        dt_diff = message_datetime - previous_message_datetime
        if dt_diff.total_seconds() < _REDUCED_DATETIME_MESSAGE_TIMING_THRESHOLD:
            return

    date_string = ""
    time_string = ""
    today = datetime.now().date()

    if previous_message_datetime is None or message_datetime.date() != previous_message_datetime.date():
        if dt_format == "rfc3339":
            date_string = message_datetime.strftime("%Y-%m-%d ") 
        elif message_datetime.date() == today:
            date_string = "Today "
        elif message_datetime.date().year == today.year:
            date_string = message_datetime.strftime("%b %d ")
        else:
            date_string = message_datetime.strftime("%b %d %Y ")
        
    if dt_format == "12h" or dt_format == "12h (reduced)":
        time_string = message_datetime.strftime("%-I:%M%p ").lower()  # %P doesn't seem to work?
    else:
        time_string = message_datetime.strftime("%H:%M ")

    return utils.colorize(date_string + time_string, utils.ANSI_GREY)


def get_conversation_string(conversations):
    terminal_width = utils.terminal_width()
    is_cosy = config.get("layout") == "cosy"
    is_rendering_dt = terminal_width > _MIN_DATETIME_TERMINAL_WIDTH
    output: str = ""
    for c in conversations:
        contact_monogram: str = _monogram(c.contact_name)

        if is_cosy: output += "\n"
        output += _conversation_header(c.address, c.contact_name) + "\n"
        if is_cosy: output += "\n"

        prev_dt: datetime | None = None
        for m in c.messages:
            is_outgoing = m.folder == "sent"
            monogram = (_USER_MONOGRAM if is_outgoing else contact_monogram)
            monogram_width = _actual_width(monogram)

            dt = datetime.strptime(m.datetime, "%Y%m%dT%H%M%S")
            dt_string = _datetime(dt, prev_dt) if is_rendering_dt else ""
            dt_width = _actual_width(dt_string)
            if is_cosy and  is_rendering_dt and prev_dt and (dt - prev_dt).total_seconds() > _COSY_MESSAGE_NEWLINE_TIMING_THRESHOLD:
                output += "\n"
            prev_dt = dt

            left_padding = max(monogram_width + 2, _MIN_WIDTH_MONOGRAM_COL)
            right_padding = max(dt_width + 2, _MIN_WIDTH_TIMESTAMP_COL) if is_rendering_dt else 2
            remaining_space = terminal_width - left_padding - right_padding

            lines = []
            for paragraph in m.text.split("\n"):
                lines.extend(textwrap.wrap(paragraph, width=remaining_space) or [""])
            
            if len(lines) == 1:
                lines[0] = monogram + " " * (left_padding - monogram_width) + lines[0]
            else:
                lines[0] = monogram + " " * (left_padding - monogram_width - _actual_width(_BLOCK_INDICATOR_TOP)) + _BLOCK_INDICATOR_TOP + lines[0]
                lines[1:-1] = [" " * (left_padding - _actual_width(_BLOCK_INDICATOR_MID)) + _BLOCK_INDICATOR_MID + line for line in lines[1:-1]]
                lines[-1] = " " * (left_padding - _actual_width(_BLOCK_INDICATOR_BTM)) + _BLOCK_INDICATOR_BTM + lines[-1]

            if is_rendering_dt and dt_string:
                gap = max(terminal_width - _actual_width(lines[0]) - dt_width, 0)
                lines[0] += " " * gap + dt_string       

            output += "\n".join(lines) + "\n"

    return output


def get_output_string(addresses: list[str]):
    pass
    