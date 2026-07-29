"""Renders the ASCII splash logo shown by the setup wizard"""

import textwrap

from .. import __legal__, __version__
from . import utils

ASCII_LOGO = [
    "████████╗██╗   ██╗██████╗ ███╗   ██╗ ██████╗ ██╗   ██╗███████╗██████╗ ",
    "╚══██╔══╝██║   ██║██╔══██╗████╗  ██║██╔═══██╗██║   ██║██╔════╝██╔══██╗",
    "   ██║   ██║   ██║██████╔╝██╔██╗ ██║██║   ██║██║   ██║█████╗  ██████╔╝",
    "   ██║   ██║   ██║██╔══██╗██║╚██╗██║██║   ██║╚██╗ ██╔╝██╔══╝  ██╔══██╗",
    "   ██║   ╚██████╔╝██║  ██║██║ ╚████║╚██████╔╝ ╚████╔╝ ███████╗██║  ██║",
    "   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝   ╚═══╝  ╚══════╝╚═╝  ╚═╝",
]
ASCII_LOGO_WIDTH = max(len(row) for row in ASCII_LOGO)


def get_logo_string() -> str:
    terminal_width = utils.terminal_width()
    if terminal_width < ASCII_LOGO_WIDTH:
        return f"Turnover v{__version}\n{__legal__}"

    left_pad = ' ' * ((terminal_width // 2) - (ASCII_LOGO_WIDTH // 2))

    lines = [left_pad + row for row in ASCII_LOGO]
    lines[-1] += f" v{__version__}"
    lines.append(f"\n{utils.colorize(__legal__, utils.ANSI_GREY)}\n")
    return "\n".join(lines)
