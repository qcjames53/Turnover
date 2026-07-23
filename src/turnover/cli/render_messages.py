# Padding constants
_MIN_WIDTH_MONOGRAM_COL = 7
_MIN_WIDTH_TIMESTAMP_COL = 7  # Not enforced if timestamp column goes unrendered
_MIN_DATETIME_TERMINAL_WIDTH = 50

_REDUCED_DATETIME_MESSAGE_TIMING_THRESHOLD = 20  # in minutes
_CONTACT_MONOGRAM = "[{name}]"
_USER_MONOGRAM = utils.colorize("[YOU]", utils.ANSI_CYAN)


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
    dt_visibility  = config.get("datetime_visibility")
    
    dt_diff = message_datetime - previous_message_datetime

    if dt_visibility == "off" or (dt_visibility == "reduced" and dt_diff < _REDUCED_DATETIME_MESSAGE_TIMING_THRESHOLD):
        return

    date_string = ""
    time_string = ""
    today = datetime.now().date()

    if previous_message_datetime is None or message_datetime.date() != previous_message_datetime.date():
        if message_datetime.date() == today:
            date_string = "Today"
        elif dt_format == "rfc3339":
            date_string = message_datetime.strftime("%Y-%m-%d ") 
        elif message_datetime.date().year == today.year:
            date_string = message_datetime.strftime("%b %d ")
        else:
            date_string = message_datetime.strftime("%b %d %Y ")
        
    if dt_format == "12h":
        time_string = message_datetime.strftime("%I:%M%P")
    else:
        time_string = message_datetime.strftime("%H:%M")

    return utils.colorize(date_string + time_string, utils.ANSI_GREY)


def get_conversation_string(conversations, width: int = 80):
    pass


def get_output_string(addresses: list[str], width: int = 80)
    return get_conversation_string()
    