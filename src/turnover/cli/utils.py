import itertools
import shutil
import sys
import threading

ANSI_GREY = "\033[90m"
ANSI_CYAN = "\033[96m"
ANSI_RESET = "\033[0m"

_SPINNER_FRAMES = "|/-\\"
_SPINNER_DELAY = 0.0667  # in seconds

_resolved_clock_format: str | None = None


def resolve_clock_format() -> str:
    """
    Resolves datetime_format's "auto" to a concrete clock format, from the desktop's preference
    (GNOME's org.gnome.desktop.interface schema) if available. Memoized for the process, since
    it's a real GNOME D-Bus round trip.

    :returns: "12h" or "24h". Falls back to "12h" if no such preference can be read (e.g.
        non-GNOME desktops, headless environments, or PyGObject not installed).
    """
    global _resolved_clock_format
    if _resolved_clock_format is not None:
        return _resolved_clock_format

    try:
        import locale

        from gi.repository import Gio

        locale.setlocale(locale.LC_ALL, "")

        schema_source = Gio.SettingsSchemaSource.get_default()
        if schema_source is None or schema_source.lookup("org.gnome.desktop.interface", True) is None:
            _resolved_clock_format = "12h"
        else:
            settings = Gio.Settings.new("org.gnome.desktop.interface")
            _resolved_clock_format = "24h" if settings.get_string("clock-format") == "24h" else "12h"
    except Exception:
        _resolved_clock_format = "12h"

    return _resolved_clock_format


def resolve_datetime_format(raw: str) -> str:
    """
    Resolves a possibly-"auto" datetime_format value to a concrete one, for rendering. Non-auto
    values (including the "(reduced)" variants other than "auto (reduced)") pass through
    unchanged.

    :param raw: A datetime_format value as returned by config.get("datetime_format").
    """
    if raw == "auto":
        return resolve_clock_format()
    if raw == "auto (reduced)":
        return f"{resolve_clock_format()} (reduced)"
    return raw


def warm() -> None:
    """
    Eagerly resolves the clock format, so later resolve_datetime_format() calls never pay for a
    GNOME D-Bus round trip mid-render.
    """
    resolve_clock_format()


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