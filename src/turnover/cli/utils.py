import itertools
import shutil
import sys
import threading
import locale
import functools

from .. import _fake_device, config

ANSI_GREY = "\033[90m"
ANSI_CYAN = "\033[96m"
ANSI_RESET = "\033[0m"

_SPINNER_FRAMES = "|/-\\"
_SPINNER_DELAY = 0.0667  # in seconds

@functools.cache
def _resolve_system_clock() -> str:
    # Fake-device mode should be deterministic regardless of the host's real GNOME settings
    # (or lack thereof) -- don't let a dev box that happens to have gi/GNOME installed leak
    # its real clock preference into a simulated run.
    if _fake_device.enabled():
        return "12h"

    # Imported here rather than at module level so this module -- and anything that merely
    # imports it without calling _resolve_system_clock() -- doesn't require PyGObject to be
    # installed (e.g. running with TURNOVER_FAKE_DEVICE=1 on a non-Linux box).
    try:
        from gi.repository import Gio

        locale.setlocale(locale.LC_ALL, "")

        schema_source = Gio.SettingsSchemaSource.get_default()
        if schema_source is None or schema_source.lookup("org.gnome.desktop.interface", True) is None:
            return "12h"
        else:
            settings = Gio.Settings.new("org.gnome.desktop.interface")
            if settings.get_string("clock-format") == "24h":
                return "24h"
            return "12h"
    except Exception:
        return "12h"


def resolve_datetime_format() -> str:
    """
    Resolves a possibly-"auto" datetime_format value to a concrete one, for rendering. Non-auto
    values (including the "(reduced)" variants other than "auto (reduced)") pass through
    unchanged.

    :param raw: A datetime_format value as returned by config.get("datetime_format").
    """
    raw = config.get("datetime_format")

    if raw.find("auto") == -1:
        return raw
    
    if raw.find("(reduced)") == -1:
        return _resolve_system_clock()
    return _resolve_system_clock() + " (reduced)"



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