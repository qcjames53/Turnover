"""Small inline arrow-key + Enter terminal picker.

Deliberately not `curses` -- `curses.wrapper` switches to the terminal's
alternate screen buffer (fullscreen takeover, can restyle colors). This
redraws just the option lines in place instead.
"""

import os
import select
import sys
import termios
import tty


def select_option(options: list[str], title: str = "") -> int | None:
    """Shows an inline arrow-key + Enter picker over `options`.

    Returns the selected index, or None if the user cancelled (q/Esc/Ctrl-C).
    """
    if not options:
        return None

    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)

    def _draw(index: int, first: bool) -> None:
        if not first:
            sys.stdout.write(f"\x1b[{len(options)}A")
        for i, option in enumerate(options):
            prefix = "> " if i == index else "  "
            sys.stdout.write(f"\x1b[2K{prefix}{option}\n")
        sys.stdout.flush()

    def _read_key() -> str:
        # Reads raw bytes from the fd directly (not sys.stdin's buffered
        # reader) so the select() timing check below stays in sync with what
        # has actually been consumed -- otherwise a single read() syscall can
        # slurp the whole ESC-[-A sequence into Python's internal buffer,
        # leaving nothing for select() to see on the fd and misreading every
        # arrow key as a lone Escape.
        ch = os.read(fd, 1).decode()
        if ch != "\x1b":
            return ch
        # Arrow keys arrive as a burst (ESC [ A/B); a lone Escape keypress
        # doesn't have more bytes ready immediately after.
        if select.select([fd], [], [], 0.05)[0]:
            ch2 = os.read(fd, 1).decode()
            if ch2 == "[" and select.select([fd], [], [], 0.05)[0]:
                return "\x1b[" + os.read(fd, 1).decode()
        return "\x1b"

    index = 0
    try:
        tty.setcbreak(fd)
        if title:
            print(title)
        _draw(index, first=True)
        while True:
            key = _read_key()
            if key in ("\x1b[A", "k"):
                index = (index - 1) % len(options)
                _draw(index, first=False)
            elif key in ("\x1b[B", "j"):
                index = (index + 1) % len(options)
                _draw(index, first=False)
            elif key in ("\r", "\n"):
                return index
            elif key in ("\x1b", "q"):
                return None
    except (KeyboardInterrupt, termios.error):
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)
