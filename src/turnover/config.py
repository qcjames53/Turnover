import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import db


@dataclass
class Setting:
    default: str
    options: list[str]


CONFIG_VALUES: dict[str, Setting] = {
    "auto_sync": Setting(
        default="incremental",
        options=["off", "incremental", "full"]
    ),
    "datetime_format": Setting(
        default="auto",
        options=["off", "auto (reduced)", "auto", "12h (reduced)", "12h", "24h (reduced)", "24h", "rfc3339"]
    ),
    "layout": Setting(
        default="cosy",
        options=["irc", "compact", "cosy", "bubbles"]
    ),
    "messages_displayed": Setting(
        default="8",
        options=["8"]
    ),
}


_cache: dict | None = None
_resolved_clock_format: str | None = None


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


def write() -> None:
    """
    Persists the in-memory config cache to disk, overwriting the config file.
    """
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
    write()


def get(option: str):
    """
    Returns `option`'s persisted value, or its default (CONFIG_VALUES) if unset.

    :param option: One of CONFIG_VALUES's setting names.
    :returns: The persisted value if the config file has one for `option`, otherwise the default.
        "auto" datetime_format is resolved to a concrete value before being returned.
    """
    if option not in CONFIG_VALUES:
        raise KeyError(f"Unknown config option: {option!r}")

    settings = _read().get("settings", {})
    value = settings.get(option, CONFIG_VALUES[option].default)

    if value == "auto":
        if option == "datetime_format":
            return _resolve_clock_format()
    return value


def set(option: str, value) -> None:
    """
    Sets `option` = `value` in the in-memory cache used by get()

    :param option: One of CONFIG_VALUES's setting names.
    :param value: Value to set.
    """
    if option not in CONFIG_VALUES:
        raise KeyError(f"Unknown config option: {option!r}")

    config = _read()
    config.setdefault("settings", {})[option] = value


def _resolve_clock_format() -> str:
    """
    Resolves "auto" datetime_format

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


def warm() -> None:
    """
    Eagerly resolves every "auto"-valued setting (datetime_format), so later get() calls never pay
    for a GNOME D-Bus round trip mid-render.
    """
    get("datetime_format")


def clear() -> None:
    """
    Wipes all cached data: the config file, the in-memory config cache, and the synced-data db.
    """
    global _cache, _resolved_clock_format
    _config_path().unlink(missing_ok=True)
    _cache = None
    _resolved_clock_format = None
    db.clear()
