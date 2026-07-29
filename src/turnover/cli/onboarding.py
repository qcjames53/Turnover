"""Wizard for running application onboarding and setup"""

import curses
import curses.ascii
import locale
import sys
from dataclasses import dataclass
from typing import Protocol

from wcwidth import wcswidth

from .. import bt, config, sdp
from . import curses_ui, demo_conversation, render_messages, render_logo

# (config key, display label) pairs, in the order they appear in the settings box.
_SETTING_FIELDS: list[tuple[str, str]] = [
    ("layout", "Layout"),
    ("datetime_format", "Datetime format"),
    ("messages_displayed", "Messages shown"),
    ("auto_sync", "Auto sync"),
]

_SETTINGS_BOX_WIDTH = 40
_SETTINGS_BOX_HEIGHT = 8
_BOX_BOTTOM_MARGIN = 2
_VALUE_FIELD_WIDTH = 21
_VALUE_INNER_WIDTH = _VALUE_FIELD_WIDTH - 4

_SAVE_BUTTON_LABEL = "[ Save and exit ]"

_DEVICE_ROW_LABEL = "Linked phone"
_NO_DEVICES_LABEL = "No paired devices"
_DEVICE_BADGE_SUFFIX_WIDTH = 2  # " " + a single-letter badge

# _text_wizard's stand-in for "leave the device link as-is", alongside real device names in its
# _prompt_choice() options list.
_KEEP_UNLINKED_OPTION = "(none)"


class Row(Protocol):
    """Structural type shared by SettingRow and DeviceRow -- whatever _draw_settings_box, _shift_row,
    and _clamp_index need to display and navigate a row, regardless of what backs its options."""
    label: str
    options: list[str]
    index: int


@dataclass
class SettingRow:
    key: str
    label: str
    options: list[str]
    index: int


@dataclass
class DeviceRow:
    """
    Like SettingRow, but backed by live-queried paired devices instead of a static CONFIG_VALUES
    entry -- `options` are the formatted device labels shown in the box, parallel to `devices`.
    Persisting the pick requires an SDP round trip (see _wizard's Save handling), so unlike
    SettingRow, moving through `options` here does not itself touch config.
    """
    label: str
    devices: list[bt.PairedDevice]
    options: list[str]
    index: int


def _clamp_index(row: Row, delta: int) -> bool:
    """Moves `row`'s index one step toward the start/end of its options list. Returns whether it
    moved, so callers can skip follow-up work (e.g. persisting) when already at an edge."""
    new_index = min(max(row.index + delta, 0), len(row.options) - 1)
    moved = new_index != row.index
    row.index = new_index
    return moved


def _build_setting_rows() -> list[SettingRow]:
    rows = []
    for key, label in _SETTING_FIELDS:
        options = config.CONFIG_VALUES[key].options
        rows.append(SettingRow(key, label, options, options.index(config.get(key))))
    return rows


def _shift_setting(row: SettingRow, delta: int) -> None:
    """Moves `row`'s value one step toward the start/end of its options list and persists the
    change to config's in-memory cache (writing to disk is wired up separately)."""
    if _clamp_index(row, delta):
        config.set(row.key, row.options[row.index])


def _reset_setting(row: SettingRow) -> None:
    """Resets `row`'s value to its default, persisting to config's in-memory cache."""
    default = config.CONFIG_VALUES[row.key].default
    new_index = row.options.index(default)
    if new_index != row.index:
        row.index = new_index
        config.set(row.key, default)


def _shift_row(row: Row, delta: int) -> None:
    """Left/right dispatch shared by both row kinds: a DeviceRow only moves its selection (see
    DeviceRow's docstring), everything else shifts and persists like a normal setting."""
    if isinstance(row, DeviceRow):
        _clamp_index(row, delta)
    else:
        _shift_setting(row, delta)


def _device_sort_key(device: bt.PairedDevice) -> tuple[int, str]:
    """Sorts MAP+PBAP devices first, then MAP-only, then PBAP-only, then neither -- alphabetical
    within each group."""
    group = {(True, True): 0, (True, False): 1, (False, True): 2, (False, False): 3}[
        (device.map_supported, device.pbap_supported)
    ]
    return group, device.name.lower()


def _device_badge(device: bt.PairedDevice) -> str:
    """Single-letter badge for `device`: "B" when both MAP and PBAP are supported, "M"/"C" when
    only one is, "-" when neither is."""
    if device.map_supported and device.pbap_supported:
        return "B"
    if device.map_supported:
        return "M"
    if device.pbap_supported:
        return "C"
    return "-"


def _format_device_option(device: bt.PairedDevice) -> str:
    """
    Formats `device` to exactly fill _VALUE_INNER_WIDTH, e.g. "Quinn's iPhone    B" -- the badge
    (see _device_badge) is right-aligned to the far edge, with the name (or its ellipsis
    truncation, once it no longer fits alongside the badge) filling the rest of the field.
    """
    badge = _device_badge(device)
    name = device.name
    if len(name) <= _VALUE_INNER_WIDTH - _DEVICE_BADGE_SUFFIX_WIDTH:
        filler = _VALUE_INNER_WIDTH - len(name) - len(badge)
        return f"{name}{' ' * filler}{badge}"

    trunc_budget = _VALUE_INNER_WIDTH - _DEVICE_BADGE_SUFFIX_WIDTH - 1
    return f"{name[:trunc_budget]}… {badge}"


def _build_device_row() -> DeviceRow:
    devices = sorted(bt.paired_devices(), key=_device_sort_key)
    if not devices:
        return DeviceRow(_DEVICE_ROW_LABEL, devices, [_NO_DEVICES_LABEL], 0)

    options = [_format_device_option(d) for d in devices]
    linked = config.get_linked_device()
    index = 0
    if linked:
        index = next((i for i, d in enumerate(devices) if d.address == linked["address"]), 0)
    return DeviceRow(_DEVICE_ROW_LABEL, devices, options, index)


def _draw_background(stdscr) -> None:
    text = render_messages.get_conversation_string([demo_conversation.DEMO_CONVERSATION])
    for row, line in enumerate(text.splitlines()):
        x = 0
        for segment, attr in curses_ui.split_ansi(line):
            curses_ui.addstr_clipped(stdscr, row, x, segment, attr)
            x += wcswidth(segment)


def _draw_settings_box(stdscr, rows: list[Row], selected_row: int) -> None:
    max_y, max_x = stdscr.getmaxyx()
    box_x = (max_x - _SETTINGS_BOX_WIDTH) // 2
    box_y = max_y - _BOX_BOTTOM_MARGIN - _SETTINGS_BOX_HEIGHT

    curses_ui.draw_box(stdscr, box_x, box_y, _SETTINGS_BOX_WIDTH, _SETTINGS_BOX_HEIGHT, "Settings")

    value_x = box_x + _SETTINGS_BOX_WIDTH - _VALUE_FIELD_WIDTH - 1
    for i, row in enumerate(rows):
        y = box_y + i + 1
        curses_ui.addstr_clipped(stdscr, y, box_x + 2, row.label, curses.color_pair(curses_ui.PAIR_BOX))

        left_marker = "<" if row.index > 0 else " "
        right_marker = ">" if row.index < len(row.options) - 1 else " "
        value_attr = curses.color_pair(curses_ui.PAIR_HIGHLIGHT if i == selected_row else curses_ui.PAIR_BOX)
        value_text = f"{left_marker} {row.options[row.index]:<{_VALUE_INNER_WIDTH}} {right_marker}"
        curses_ui.addstr_clipped(stdscr, y, value_x, value_text, value_attr)

    button_attr = curses.color_pair(curses_ui.PAIR_HIGHLIGHT if selected_row == len(rows) else curses_ui.PAIR_BOX)
    button_x = box_x + (_SETTINGS_BOX_WIDTH - len(_SAVE_BUTTON_LABEL)) // 2
    curses_ui.addstr_clipped(stdscr, box_y + len(rows) + 1, button_x, _SAVE_BUTTON_LABEL, button_attr)


def _interactive_wizard(stdscr) -> None:
    curses.curs_set(0)
    curses.set_escdelay(25)
    curses_ui.init_colors(stdscr)

    device_row = _build_device_row()
    rows: list[Row] = [device_row] + _build_setting_rows()
    selected_row = 0
    item_count = len(rows) + 1  # device row + settings rows, plus the "Save and exit" button

    while True:
        stdscr.erase()
        _draw_background(stdscr)
        _draw_settings_box(stdscr, rows, selected_row)
        stdscr.refresh()

        key = stdscr.getch()
        if key in (curses.ascii.ESC, ord("q")):
            break
        elif key in (curses.KEY_UP, ord("w"), ord("k")):
            selected_row = (selected_row - 1) % item_count
        elif key in (curses.KEY_DOWN, ord("s"), ord("j")):
            selected_row = (selected_row + 1) % item_count
        elif key in (curses.KEY_LEFT, ord("a"), ord("h")) and selected_row < len(rows):
            _shift_row(rows[selected_row], -1)
        elif key in (curses.KEY_RIGHT, ord("d"), ord("l")) and selected_row < len(rows):
            _shift_row(rows[selected_row], 1)
        elif key == ord("r") and selected_row < len(rows) and isinstance(rows[selected_row], SettingRow):
            _reset_setting(rows[selected_row])
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")) and selected_row == len(rows):
            if device_row.devices:
                address = device_row.devices[device_row.index].address
                mas_channel = sdp.find_rfcomm_channel(address, sdp.MESSAGE_ACCESS_SERVICE_CLASS)
                pbap_channel = sdp.find_rfcomm_channel(address, sdp.PHONEBOOK_ACCESS_SERVICE_CLASS)
                config.set_linked_device(address, mas_channel, pbap_channel)
            config.write()
            break


def _prompt_choice(label: str, options: list[str], current: str) -> str:
    by_lower = {option.lower(): option for option in options}
    print(f"\n{label}:")
    while True:
        raw = input(f"Select from [{', '.join(options)}] or press enter to keep '{current}': ").strip()
        if not raw:
            return current
        if raw.lower() in by_lower:
            return by_lower[raw.lower()]
        print(f"Invalid selection: '{raw!r}'")


def _text_wizard() -> None:
    """
    Backup for _interactive_wizard() on terminals that can't run curses: asks for each of the same
    settings, one at a time, via plain input().
    """
    print(render_logo.get_logo_string())
    input("Press enter to continue...")
    devices = sorted(bt.paired_devices(), key=_device_sort_key)
    if not devices:
        print(f"\n{_DEVICE_ROW_LABEL}: no paired devices found -- pair a phone in your OS's Bluetooth settings first.")
    else:
        by_name = {device.name: device for device in devices}
        linked = config.get_linked_device()
        current = next(
            (name for name, device in by_name.items() if linked and device.address == linked["address"]),
            _KEEP_UNLINKED_OPTION,
        )
        chosen_name = _prompt_choice(_DEVICE_ROW_LABEL, [*by_name, _KEEP_UNLINKED_OPTION], current)
        if chosen_name != _KEEP_UNLINKED_OPTION:
            chosen = by_name[chosen_name]
            mas_channel = sdp.find_rfcomm_channel(chosen.address, sdp.MESSAGE_ACCESS_SERVICE_CLASS)
            pbap_channel = sdp.find_rfcomm_channel(chosen.address, sdp.PHONEBOOK_ACCESS_SERVICE_CLASS)
            config.set_linked_device(chosen.address, mas_channel, pbap_channel)

    for key, label in _SETTING_FIELDS:
        options = config.CONFIG_VALUES[key].options
        config.set(key, _prompt_choice(label, options, config.get(key)))

    config.write()
    print("Sucessfully saved config")


def run_onboarding_wizard() -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        _text_wizard()
        return

    locale.setlocale(locale.LC_ALL, "")
    try:
        curses.wrapper(_interactive_wizard)
    except KeyboardInterrupt:
        pass
