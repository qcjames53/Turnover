# auto_sync can be:
#   - off (no automatic sync before a command runs)
#   - incremental DEFAULT (only sync messages not already cached)
#   - full (always resync everything, same as `sync --full`)

# datetime_format can be:
#   - auto (12h or 24h) DEFAULT
#   - 12h (Jan 1, 1970 12:00am)
#   - 24h (Jan 1, 1970 00:00)
#   - rfc3339 (1970-01-01 00:00)

# datetime_visibility can be:
#   - off
#   - reduced (no time displayed if within _REDUCED_DATETIME_MESSAGE_TIMING_THRESHOLD of last message)
#   - full DEFAULT

# layout can be:
#   - compact
#   - cosy DEFAULT

# messages_displayed is how many messages back `turnover <name>` shows. DEFAULT 8

# terminal_width can be:
#   - auto DEFAULT (resolves via shutil.get_terminal_size())
#   - a positive int, to hardcode the width instead


import json
import os
import shutil
from pathlib import Path

from . import db

_DEFAULTS = {
    "messages_displayed": 8,
    "datetime_format": "auto",
    "datetime_visibility": "full",
    "terminal_width": "auto",
    "auto_sync": "incremental",
    "layout": "cosy",
}

_cache: dict | None = None
_resolved_clock_format: str | None = None
_resolved_terminal_width: int | None = None


def _config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(config_home) / "turnover" / "config.json"


def _read() -> dict:
    """
    Returns the persisted config dict, reading it from disk on first access and reusing that copy
    (`_cache`) for the rest of the process.
    """
    global _cache
    if _cache is None:
        try:
            with _config_path().open("r") as f:
                _cache = json.load(f)
        except FileNotFoundError:
            _cache = {}
    return _cache


def _write() -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(_cache, f, indent=2)
        f.write("\n")


def load() -> dict:
    """
    Returns the full persisted config dict (device info + settings), as saved on disk.
    """
    return _read()


def save(new_config: dict) -> None:
    """
    Overwrites the full persisted config dict, on disk and in the in-memory cache.

    :param new_config: Full config dict to persist.
    """
    global _cache
    _cache = new_config
    _write()


def get(option: str):
    """
    Returns `option`'s persisted value, or its default (_DEFAULTS) if unset.

    :param option: One of _DEFAULTS's keys.
    :returns: The persisted value if the config file has one for `option`, otherwise the default.
        "auto" datetime_format/terminal_width are resolved to a concrete value before being
        returned.
    """
    if option not in _DEFAULTS:
        raise KeyError(f"Unknown config option: {option!r}")

    settings = _read().get("settings", {})
    value = settings.get(option, _DEFAULTS[option])

    if value == "auto":
        if option == "datetime_format":
            return _resolve_clock_format()
        if option == "terminal_width":
            return _resolve_terminal_width()
    return value


def set(option: str, value) -> None:
    """
    Persists `option` = `value`, on disk and in the in-memory cache used by get().

    :param option: One of _DEFAULTS's keys.
    :param value: Value to persist.
    """
    if option not in _DEFAULTS:
        raise KeyError(f"Unknown config option: {option!r}")

    config = _read()
    config.setdefault("settings", {})[option] = value
    _write()


def _resolve_clock_format() -> str:
    """
    Resolves "auto" datetime_format via GNOME's own clock-format gsetting
    (org.gnome.desktop.interface) -- already have PyGObject as a dependency
    for BlueZ D-Bus, so this is free. Falls back to "12h" if the schema
    isn't installed (non-GNOME session) or anything else goes wrong; this
    is a display nicety, never worth hard-failing a command over.

    GNOME ships a locale-conditional override for this key (24h globally,
    12h specifically for e.g. en_US) -- but Python doesn't call setlocale()
    at startup the way a real C program (like the `gsettings` CLI) does, so
    without this, GLib can't see the process is actually running as
    en_US and silently resolves the wrong (non-locale-specific) default.
    Confirmed directly: `gsettings get ... clock-format` said '12h' while
    Gio.Settings.get_string() said '24h' in the same shell/env, and calling
    setlocale() first made them agree. Safe/idempotent to call repeatedly.

    Cached in `_resolved_clock_format` after the first call -- it's a D-Bus
    round trip, and the answer can't change mid-process.

    :returns: "12h" or "24h".
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


def _resolve_terminal_width() -> int:
    """
    Resolves "auto" terminal_width via shutil.get_terminal_size() -- cached after the first call
    since a single CLI invocation's terminal doesn't resize out from under it.

    :returns: Terminal width in columns.
    """
    global _resolved_terminal_width
    if _resolved_terminal_width is None:
        _resolved_terminal_width = shutil.get_terminal_size().columns
    return _resolved_terminal_width


def warm() -> None:
    """
    Eagerly resolves every "auto"-valued setting (datetime_format, terminal_width), so later
    get() calls never pay for a GNOME D-Bus round trip or terminal ioctl mid-render. Meant to be
    called once, early, alongside preflight's other startup work -- see preflight.py -- so those
    costs overlap with the migration/auto-sync I/O already happening there instead of stalling
    the first render call.
    """
    get("datetime_format")
    get("terminal_width")


def clear() -> None:
    """
    Wipes all cached data: the config file, the in-memory config cache, and the synced-data db.
    """
    global _cache, _resolved_clock_format, _resolved_terminal_width
    _config_path().unlink(missing_ok=True)
    _cache = None
    _resolved_clock_format = None
    _resolved_terminal_width = None
    db.clear()
