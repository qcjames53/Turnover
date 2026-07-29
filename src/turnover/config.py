"""Manages config options for user preferences and device connection + channel details"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from . import db


@dataclass
class Setting:
    default: str
    options: list[str]


CONFIG_VALUES: dict[str, Setting] = {
    "auto_sync": Setting(
        default="msgs+new contacts",
        options=["off", "messages", "msgs+new contacts", "msgs+all contacts"]
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
        options=["1", "2", "3", "4", "5", "6", "8", "10", "12", "15", "20", "25", "30", "35", "40", "45", "50", "60", "70", "80", "90", "100", "all"]
    ),
}


_cache: dict | None = None


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
    """
    if option not in CONFIG_VALUES:
        raise KeyError(f"Unknown config option: {option!r}. Valid options: {sorted(CONFIG_VALUES)!r}")

    setting = CONFIG_VALUES[option]
    settings = _read().get("settings", {})
    return settings.get(option, setting.default)


class RepairedSetting(NamedTuple):
    key: str
    def_val: str


def repair_invalid_settings() -> list[RepairedSetting]:
    """
    Resets invalid settings keys to the default

    :returns: A RepairedSetting(key, def_val) named tuple
    """
    settings = _read().setdefault("settings", {})
    fixed = []
    for key, setting in CONFIG_VALUES.items():
        if key in settings and settings[key] not in setting.options:
            repaired = RepairedSetting(key, setting.default)
            settings[key] = repaired.def_val
            fixed.append(repaired)
    if fixed:
        write()
    return fixed


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


def get_linked_device() -> dict | None:
    """
    Returns the persisted linked-device dict ({"address", "mas_channel", "pbap_channel"}), or None
    if no device has been linked yet.
    """
    return _read().get("device")


def set_linked_device(address: str, mas_channel: int, pbap_channel: int) -> None:
    """
    Sets the linked device in the in-memory cache used by get_linked_device() (writing to disk is
    wired up separately, via write()).
    """
    _read()["device"] = {"address": address, "mas_channel": mas_channel, "pbap_channel": pbap_channel}


def clear() -> None:
    """
    Wipes all cached data: the config file, the in-memory config cache, and the synced-data db.
    """
    global _cache
    _config_path().unlink(missing_ok=True)
    _cache = None
    db.clear()
