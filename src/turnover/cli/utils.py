import sys

ANSI_GREY = "\033[90m"
ANSI_CYAN = "\033[96m"
ANSI_RESET = "\033[0m"

def colorize(text: str, code: str) -> str:
    return f"{code}{text}{ANSI_RESET}" if sys.stdout.isatty() else text