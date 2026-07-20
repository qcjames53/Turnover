"""Persisted app configuration: which phone to talk to, its cached RFCOMM
channels, and user-editable settings (see DEFAULT_SETTINGS).
"""

import json
import os
from pathlib import Path

from . import db

# message_history: how many messages back `turnover <name>` shows.
# clock_format: "auto" | "12h" | "24h" -- "auto" resolves via _detect_clock_format().
# terminal_width: "auto" | int -- "auto" resolves via shutil.get_terminal_size().
# auto_sync: "full" | "incremental" | "off" -- controls preflight.py's automatic message sync
# before every command. Independent of the sync command's own --full flag, which always does a
# full sync regardless of this setting.
DEFAULT_SETTINGS = {
    "message_history": 8,
    "clock_format": "auto",
    "terminal_width": "auto",
    "auto_sync": "incremental",
}


def _config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(config_home) / "turnover" / "config.json"


def load() -> dict:
    try:
        with _config_path().open("r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def get_settings() -> dict:
    """DEFAULT_SETTINGS overlaid with whatever's actually saved -- so a
    config file predating a given setting (or missing the "settings" key
    entirely) still gets a sane value for it.
    """
    settings = dict(DEFAULT_SETTINGS)
    settings.update(load().get("settings", {}))
    return settings


def save_settings(settings: dict) -> None:
    config = load()
    config["settings"] = settings
    save(config)


def detect_clock_format() -> str:
    """Resolves "auto" clock_format via GNOME's own clock-format gsetting
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
    """
    try:
        import locale

        from gi.repository import Gio

        locale.setlocale(locale.LC_ALL, "")

        schema_source = Gio.SettingsSchemaSource.get_default()
        if schema_source is None or schema_source.lookup("org.gnome.desktop.interface", True) is None:
            return "12h"
        settings = Gio.Settings.new("org.gnome.desktop.interface")
        return "24h" if settings.get_string("clock-format") == "24h" else "12h"
    except Exception:
        return "12h"


def resolve_clock_format(settings: dict) -> str:
    value = settings.get("clock_format", "auto")
    return detect_clock_format() if value == "auto" else value


def clear() -> None:
    """Wipes all cached data: the config file and the synced-data db."""
    _config_path().unlink(missing_ok=True)
    db.clear()
