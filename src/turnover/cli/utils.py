import itertools
import shutil
import sys
import threading

ANSI_GREY = "\033[90m"
ANSI_CYAN = "\033[96m"
ANSI_RESET = "\033[0m"

_SPINNER_FRAMES = "|/-\\"
_SPINNER_DELAY = 0.0667  # in seconds

def colorize(text: str, code: str) -> str:
    return f"{code}{text}{ANSI_RESET}" if sys.stdout.isatty() else text


def terminal_width() -> int:
    return shutil.get_terminal_size().columns if sys.stdout.isatty() else 80


class Spinner:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self) -> None:
        for frame in itertools.cycle(_SPINNER_FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r{frame}")
            sys.stdout.flush()
            self._stop.wait(_SPINNER_DELAY)
        sys.stdout.write("\r \r")
        sys.stdout.flush()

    def __enter__(self) -> "Spinner":
        if sys.stdout.isatty():
            self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()