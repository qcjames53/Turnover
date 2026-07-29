"""Renders the ASCII splash logo shown by the setup wizard"""

import textwrap

from .. import __copyright__, __version__
from . import utils

ASCII_LOGO = [
    utils.colorize("████████╗██╗   ██╗██████╗ ███╗   ██╗ ██████╗ ██╗   ██╗███████╗██████╗ ", utils.ANSI_GREEN),
    utils.colorize("╚══██╔══╝██║   ██║██╔══██╗████╗  ██║██╔═══██╗██║   ██║██╔════╝██╔══██╗", utils.ANSI_YELLOW),
    utils.colorize("   ██║   ██║   ██║██████╔╝██╔██╗ ██║██║   ██║██║   ██║█████╗  ██████╔╝", utils.ANSI_RED),
    utils.colorize("   ██║   ██║   ██║██╔══██╗██║╚██╗██║██║   ██║╚██╗ ██╔╝██╔══╝  ██╔══██╗", utils.ANSI_MAGENTA),
    utils.colorize("   ██║   ╚██████╔╝██║  ██║██║ ╚████║╚██████╔╝ ╚████╔╝ ███████╗██║  ██║", utils.ANSI_BLUE),
    utils.colorize("   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝   ╚═══╝  ╚══════╝╚═╝  ╚═╝", utils.ANSI_BLUE),
]
ASCII_LOGO_WIDTH = max(utils.visible_width(row) for row in ASCII_LOGO)
VERSION = utils.colorize(f"v{__version__}", utils.ANSI_BLUE)
VERSION_WIDTH = utils.visible_width(VERSION)
LEGAL_TEXT = f"{__copyright__}. Licensed under GPL-3.0-or-later. iPhone and iMessage are trademarks of Apple Inc., registered in the U.S. and other countries."


def get_splash_string() -> str:
    terminal_width = utils.terminal_width()
    wrapped_legal_text = [utils.colorize(line, utils.ANSI_GREY) for line in textwrap.wrap(LEGAL_TEXT, width=terminal_width)]

    if terminal_width < ASCII_LOGO_WIDTH:
        return f"Turnover {VERSION}\n\n{"\n".join(wrapped_legal_text)}"

    pad = (terminal_width // 2) - (ASCII_LOGO_WIDTH // 2)
    pad_str = ' ' * pad

    lines = [f"{pad_str}{row}" for row in ASCII_LOGO]
    lines.append(f"{pad_str}{' ' * (ASCII_LOGO_WIDTH - VERSION_WIDTH)}{VERSION}")
    lines.append("")
    lines.extend(wrapped_legal_text)
    return "\n".join(lines)
