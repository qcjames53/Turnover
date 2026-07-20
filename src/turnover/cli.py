import argparse
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

import wcwidth

from . import __version__, bt, config, db, interactive, pbap, preflight, sdp
from . import map as map_
from ._vendor.nobex.common import OBEXError

# Transport-level (socket) and protocol-level (OBEX) failures a real
# Bluetooth link can throw at any time -- a dropped connection, the phone
# rejecting a request, a moment out of range. Caught around actual
# phone-talking calls so a transient link hiccup prints a clear message
# instead of a raw traceback. Deliberately not retried automatically: a
# `sync` that failed here succeeded cleanly on a plain re-run in testing,
# so it reads as one-off flakiness rather than a systematic issue worth
# building retry/backoff logic for.
_LINK_ERRORS = (OSError, OBEXError)


def _capability_label(d: bt.PairedDevice) -> str:
    capabilities = []
    if d.map_supported:
        capabilities.append("Messages")
    if d.pbap_supported:
        capabilities.append("Contacts")
    if not capabilities:
        return d.name
    return f"{d.name} ({' + '.join(capabilities)})"


_NOT_LISTED = "My device is not listed"


def _open_bluetooth_settings() -> None:
    print("Opening Bluetooth settings — pair your phone there, then re-run `turnover link`.")
    try:
        subprocess.Popen(
            ["gnome-control-center", "bluetooth"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


def run_link_wizard(address: str | None) -> None:
    if address is None:
        input(
            "Pair your iPhone to this PC. Open Settings -> Bluetooth on your iPhone and "
            "pair the device using this PC's bluetooth settings page. Press enter once complete. "
        )

    devices = bt.paired_devices()

    if address is not None:
        chosen = next((d for d in devices if d.address == address), None)
        if chosen is None:
            print(f"No paired device with address {address}.")
            return
    else:
        labels = [_capability_label(d) for d in devices] + [_NOT_LISTED]
        index = interactive.select_option(labels, title="Select a bluetooth device:")
        if index is None:
            print("Cancelled.")
            return
        if index == len(devices):
            _open_bluetooth_settings()
            return
        chosen = devices[index]

    print(f"Connecting to {chosen.name} ({chosen.address})...")

    mas_channel = sdp.find_rfcomm_channel(chosen.address, sdp.MESSAGE_ACCESS_SERVICE_CLASS)
    pbap_channel = sdp.find_rfcomm_channel(chosen.address, sdp.PHONEBOOK_ACCESS_SERVICE_CLASS)

    # iOS only reveals the per-device "Show Message Notifications"/"Sync
    # Contacts" toggles after a MAP/PBAP profile handshake has happened at
    # least once. These probes exist purely to trigger that -- failures are
    # non-fatal, since the toggle prompt below still applies either way.
    print("Requesting Messages and Contacts access to reveal the permission toggles on your iPhone...")
    try:
        map_.probe(chosen.address, mas_channel)
    except Exception as e:
        print(f"  MAP request failed (continuing): {e}")
    try:
        pbap.probe(chosen.address, pbap_channel)
    except Exception as e:
        print(f"  PBAP request failed (continuing): {e}")

    # load-modify-save rather than a bare config.save({"device": ...}) --
    # that would silently wipe any existing "settings" key on a re-link.
    current = config.load()
    current["device"] = {
        "address": chosen.address,
        "name": chosen.name,
        "mas_channel": mas_channel,
        "pbap_channel": pbap_channel,
    }
    config.save(current)

    print(f"Linked {chosen.name} ({chosen.address}) — MAP channel {mas_channel}, PBAP channel {pbap_channel}.")

    input(
        "On your iPhone, click the info icon next to this PC's listed Bluetooth connection. "
        "Toggle 'Show Message Notifications' and 'Sync Contacts' on. Press enter once complete. "
    )

    _edit_settings()


def _edit_settings() -> None:
    settings = config.get_settings()
    clock_choices = ["auto", "12h", "24h"]
    sync_choices = ["full", "incremental", "off"]

    while True:
        labels = [
            f"Message history: {settings['message_history']}",
            f"Clock format: {settings['clock_format']}",
            f"Terminal width: {settings['terminal_width']}",
            f"Auto sync: {settings['auto_sync']}",
            "Done",
        ]
        index = interactive.select_option(labels, title="Settings (arrow keys + enter to edit, or Done):")
        if index is None or index == len(labels) - 1:
            break

        if index == 0:
            raw = input(f"Message history [{settings['message_history']}]: ").strip()
            if raw:
                try:
                    settings["message_history"] = max(1, int(raw))
                except ValueError:
                    print("Not a number -- keeping current value.")
        elif index == 1:
            choice = interactive.select_option(clock_choices, title="Clock format:")
            if choice is not None:
                settings["clock_format"] = clock_choices[choice]
        elif index == 2:
            raw = input(f'Terminal width ("auto" or a number) [{settings["terminal_width"]}]: ').strip()
            if raw == "auto":
                settings["terminal_width"] = "auto"
            elif raw:
                try:
                    settings["terminal_width"] = max(20, int(raw))
                except ValueError:
                    print('Not a number or "auto" -- keeping current value.')
        elif index == 3:
            choice = interactive.select_option(sync_choices, title="Auto sync:")
            if choice is not None:
                settings["auto_sync"] = sync_choices[choice]

    config.save_settings(settings)
    print("Settings saved.")


def run_unlink() -> None:
    device = config.load().get("device")
    if device is None:
        print("No device was linked.")
        return

    answer = input(f"Unlink {device['name']} ({device['address']}) and delete all cached data? [y/N] ")
    if answer.strip().lower() != "y":
        print("Cancelled.")
        return

    config.clear()
    print(f"Unlinked {device['name']} ({device['address']}) and cleared cached data.")


def run_contacts_list() -> None:
    contacts = db.list_contacts()
    if not contacts:
        print("No contacts cached. Run `turnover sync` first.")
        return

    for contact in contacts:
        if contact.number:
            print(f"{contact.name or '(no name)'}  {contact.number}")
        else:
            print(contact.name or "(no name)")


def _phone_suffix(number: str) -> str:
    """Last 10 digits of a phone number, for matching MAP addressing values
    (bare digits) against PBAP-synced contact numbers (which may carry a
    country code or leading '+') regardless of formatting differences.
    """
    digits = re.sub(r"\D", "", number)
    return digits[-10:] if len(digits) >= 10 else digits


_MIN_DATE_GAP = 2
_RIGHT_PAD = 1
# Minimum reserved field width -- keeps every row's right-hand reserve at
# least _MIN_DATE_GAP + _MIN_FIELD_WIDTH + _RIGHT_PAD (2 + 5 + 1 = 8) chars
# even on a short field (e.g. 24h same-day "H:MM"), so the field column
# stays visually consistent across a conversation.
_MIN_FIELD_WIDTH = 5
# A blank line is inserted before a message more than this many minutes
# after the immediately preceding one -- visually separates bursts of
# conversation instead of collapsing/hiding the time field like before.
_GAP_BLANK_LINE_MINUTES = 15
# "[XXX]"/"[You]" is always <=5 display columns (monogram capped at 3 chars,
# "You" is 3 chars) -- fixed width means no more dynamic max-label-width
# scan across a conversation like the old _truncate_label did.
_LABEL_COLUMN_WIDTH = 7
_ANSI_GREY = "\033[90m"
_ANSI_CYAN = "\033[96m"
_ANSI_RESET = "\033[0m"


def _colorize(text: str, code: str) -> str:
    """Wraps `text` in the ANSI `code` -- grey for decorative chrome (header
    dashes, continuation connectors, timestamps) so it recedes behind actual
    message content; dim cyan for an entire "You" row, to set your own
    messages apart from received ones. Skipped when stdout isn't a
    terminal, so piped/redirected output stays plain text.
    """
    return f"{code}{text}{_ANSI_RESET}" if sys.stdout.isatty() else text


def _parse_map_datetime(value: str) -> datetime | None:
    try:
        return datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None


def _display_width(s: str) -> int:
    """Terminal column width of `s` -- most emoji render two columns wide in
    a real terminal (confirmed: GNOME Terminal) but count as a single
    Python character, so len() undercounts and misaligns the right-hand
    date column. Falls back to len() for control/unassigned characters,
    where wcswidth returns -1.
    """
    width = wcwidth.wcswidth(s)
    return width if width >= 0 else len(s)


def _terminal_width(settings: dict) -> int:
    configured = settings.get("terminal_width", "auto")
    if configured != "auto":
        try:
            return int(configured)
        except (TypeError, ValueError):
            pass
    try:
        return shutil.get_terminal_size().columns
    except OSError:
        return 80


def _monogram(name: str) -> str:
    """1 word -> its initial; 2 words -> both initials; 3+ words -> first +
    second + *last* word's initials (still capped at 3 chars).
    """
    words = name.split()
    if not words:
        return "?"
    initials = [words[0][0]]
    if len(words) >= 2:
        initials.append(words[1][0])
    if len(words) >= 3:
        initials.append(words[-1][0])
    return "".join(initials).upper()


def _row_label(message: map_.Message, name: str | None) -> str:
    if message.folder == "sent":
        return "You"
    return _monogram(name) if name else "??"


def _label_prefix(label: str) -> str:
    bracketed = f"[{label}]"
    pad = max(_LABEL_COLUMN_WIDTH - _display_width(bracketed), 0)
    return bracketed + " " * pad


def _continuation_prefix(width: int, is_last: bool, color: str) -> str:
    """Box-draw connector for a wrapped message's continuation lines, in
    place of the label -- a vertical bar while more lines of the same
    message follow, a corner on the last one -- so a multi-line message
    reads as one message instead of blank-looking lines that could be
    mistaken for a gap.
    """
    connector = "└" if is_last else "│"
    padded = f" {connector}".ljust(width)
    return padded.replace(connector, _colorize(connector, color), 1)


def _format_datetime_field(dt: datetime, is_new_day: bool, clock_format: str) -> str:
    date_str = "Today" if dt.date() == datetime.now().date() else dt.strftime("%Y-%m-%d")
    if clock_format == "24h":
        return f"{date_str} {dt.strftime('%H:%M')}" if is_new_day else dt.strftime("%H:%M")
    hour12 = dt.strftime("%I").lstrip("0") or "12"
    time_part = f"{hour12}:{dt.strftime('%M')}{dt.strftime('%p').lower()}"
    return f"{date_str} {time_part}" if is_new_day else time_part


def _wrap_message_text(text: str, width: int) -> list[str]:
    """Word-wraps to a target *display* width (not character count) --
    textwrap.wrap operates on character count, which misjudges lines
    containing wide characters like emoji.
    """
    width = max(width, 20)
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current: list[str] = []
        current_width = 0
        for word in words:
            word_width = _display_width(word)
            added = word_width if not current else word_width + 1
            if current and current_width + added > width:
                lines.append(" ".join(current))
                current = [word]
                current_width = word_width
            else:
                current.append(word)
                current_width += added
        lines.append(" ".join(current))
    return lines or [""]


def _conversation_key(message: map_.Message) -> str:
    """Groups by the other party's number: sender for inbox messages,
    recipient for sent ones. There's no thread/participant metadata in
    MAP's msg-listing or bMessage bodies on this phone (checked a real
    group-text message's raw bMessage -- it has exactly one originator
    vCard, no participant list), so a group text's replies from different
    people show up as separate conversations here. That's an iOS/MAP data
    limitation, not something fixable client-side.
    """
    addressing = message.recipient_addressing if message.folder == "sent" else message.sender_addressing
    return _phone_suffix(addressing) or addressing


def _group_conversations(messages: list[map_.Message]) -> dict[str, list[map_.Message]]:
    conversations: dict[str, list[map_.Message]] = {}
    for message in messages:
        conversations.setdefault(_conversation_key(message), []).append(message)
    return conversations


def _conversation_number(thread: list[map_.Message]) -> str:
    representative = thread[0]
    return (
        representative.recipient_addressing
        if representative.folder == "sent"
        else representative.sender_addressing
    )


def _unread_count(thread: list[map_.Message]) -> int:
    return sum(1 for m in thread if m.folder != "sent" and not m.local_read)


def _render_conversation(
    thread: list[map_.Message], name: str | None, number_display: str, clock_format: str, width: int
) -> list[tuple[str, str]]:
    """Prints one conversation's centered dashed header + the given messages
    (caller has already sorted/windowed them), monogram-labeled and with a
    right-aligned datetime field. Returns the (folder, handle) pairs shown,
    for the caller to mark read.
    """
    header_label = f"{name} ({number_display})" if name else number_display
    inner = f"  {header_label}  "
    centered = inner.center(width, "-")
    left_dashes = len(centered) - len(centered.lstrip("-"))
    right_dashes = len(centered) - len(centered.rstrip("-"))
    print()
    left_dash_display = _colorize(centered[:left_dashes], _ANSI_GREY)
    right_dash_display = _colorize(centered[len(centered) - right_dashes :], _ANSI_GREY)
    print(left_dash_display + inner + right_dash_display)
    print()

    shown = []
    current_day = None
    previous_dt = None
    for message in thread:
        is_sent = message.folder == "sent"
        label = _row_label(message, name)
        prefix = _label_prefix(label)
        connector_color = _ANSI_GREY

        dt = _parse_map_datetime(message.datetime)
        is_new_day = dt is None or current_day is None or dt.date() != current_day

        gap = (
            dt is not None
            and previous_dt is not None
            and (dt - previous_dt) > timedelta(minutes=_GAP_BLANK_LINE_MINUTES)
        )
        if gap:
            print()
        if dt is not None:
            current_day = dt.date()
            previous_dt = dt

        field = _format_datetime_field(dt, is_new_day, clock_format) if dt else message.datetime

        # Reserve at least _MIN_DATE_GAP + _MIN_FIELD_WIDTH + _RIGHT_PAD on
        # the right even for a short field, so the field column stays
        # visually consistent across a conversation.
        reserve = _MIN_DATE_GAP + max(len(field), _MIN_FIELD_WIDTH) + _RIGHT_PAD
        wrap_width = width - _display_width(prefix) - reserve
        lines = _wrap_message_text(message.text, wrap_width)
        first_line = lines[0]

        pad = max(
            width - _display_width(prefix) - _display_width(first_line) - len(field) - _RIGHT_PAD,
            _MIN_DATE_GAP,
        )
        if is_sent:
            prefix_display = _colorize(prefix, _ANSI_CYAN)
            first_line_display = _colorize(first_line, _ANSI_CYAN)
            field_display = _colorize(field, _ANSI_GREY)
        else:
            prefix_display = prefix
            first_line_display = first_line
            field_display = _colorize(field, _ANSI_GREY)
        print(f"{prefix_display}{first_line_display}{' ' * pad}{field_display} ")
        for i, line in enumerate(lines[1:], start=1):
            is_last = i == len(lines) - 1
            line_display = _colorize(line, _ANSI_CYAN) if is_sent else line
            print(f"{_continuation_prefix(_display_width(prefix), is_last, connector_color)}{line_display}")

        shown.append((message.folder, message.handle))

    print()
    return shown


def run_messages_list() -> None:
    messages = db.list_messages()
    if not messages:
        print("No messages cached. Run `turnover sync` first.")
        return

    settings = config.get_settings()
    clock_format = config.resolve_clock_format(settings)
    width = _terminal_width(settings)

    contact_names = {_phone_suffix(c.number): c.name for c in db.list_contacts() if c.number}
    conversations = _group_conversations(messages)
    ordered_keys = sorted(
        conversations, key=lambda k: max(m.datetime for m in conversations[k]), reverse=True
    )

    all_shown = []
    for i, key in enumerate(ordered_keys):
        if i > 0:
            print()
        thread = sorted(conversations[key], key=lambda m: m.datetime)
        name = contact_names.get(key)
        number_display = pbap.format_phone_display(_conversation_number(thread))
        all_shown.extend(_render_conversation(thread, name, number_display, clock_format, width))

    db.mark_read(all_shown)


def run_summary() -> None:
    device = config.load().get("device")
    if device is None:
        print("No device linked. Run `turnover link` to link a device.")
        return

    messages = db.list_messages()
    if not messages:
        return

    contact_names = {_phone_suffix(c.number): c.name for c in db.list_contacts() if c.number}
    conversations = _group_conversations(messages)
    ordered_keys = sorted(
        conversations, key=lambda k: max(m.datetime for m in conversations[k]), reverse=True
    )

    print(f"Linked to {device['name']}")
    print()

    no_unreads_found = True
    for key in ordered_keys:
        thread = conversations[key]
        unread = _unread_count(thread)
        if unread <= 1:
            continue
        name = contact_names.get(key)
        label = name or pbap.format_phone_display(_conversation_number(thread))
        print(f"{label} [{unread} unread]")
        no_unreads_found = False
    if no_unreads_found:
        print("No new messages.")


def _resolve_contact_fuzzy(name_query: str) -> pbap.Contact | None:
    """Case-insensitive substring match against synced contact names. Ties
    (more than one match) are broken by most local-unread messages, then
    most recent activity -- "finds the Jon with the most unreads."
    """
    query = name_query.strip().lower()
    matches = [c for c in db.list_contacts() if query in c.name.strip().lower()]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    conversations = _group_conversations(db.list_messages())

    def sort_key(contact: pbap.Contact) -> tuple[int, str]:
        thread = conversations.get(_phone_suffix(contact.number), []) if contact.number else []
        return (_unread_count(thread), max((m.datetime for m in thread), default=""))

    matches.sort(key=sort_key, reverse=True)
    return matches[0]


def run_show(name_query: str, text: str | None = None) -> None:
    device = config.load().get("device")
    if device is None:
        print("No device linked. Run `turnover link` to link a device.")
        return

    contact = _resolve_contact_fuzzy(name_query)
    if contact is not None:
        if not contact.number:
            print(f"'{contact.name}' is a synced contact but has no phone number cached.")
            return
        name, number = contact.name, contact.number
    else:
        number = pbap.normalize_phone_number(name_query)
        if not pbap.looks_like_phone_number(number):
            print(f"'{name_query}' doesn't match a synced contact and isn't a valid phone number.")
            return
        name = None

    if text is not None:
        try:
            map_.send_message(device["address"], device["mas_channel"], number, text)
        except _LINK_ERRORS as e:
            print(f"Send failed ({e}). Bluetooth link trouble -- try again.")
            return

        # The phone's own MAP "sent" folder may not reflect a PushMessage
        # immediately (or ever, on some implementations) -- cache it locally
        # under a synthetic handle so it shows up right away. A later
        # `sync` may add a second row for the same message if the phone
        # does eventually surface it with its own handle; there's no
        # reliable way to de-dupe those without a real handle back from
        # PushMessage.
        db.save_messages(
            [
                map_.Message(
                    handle=f"local-{uuid.uuid4().hex}",
                    folder="sent",
                    datetime=datetime.now().strftime("%Y%m%dT%H%M%S"),
                    sender_addressing="",
                    recipient_addressing=number,
                    text=text,
                )
            ]
        )

    conversations = _group_conversations(db.list_messages())
    thread = sorted(conversations.get(_phone_suffix(number), []), key=lambda m: m.datetime)
    if not thread:
        print(f"No messages with {name or number} yet.")
        return

    settings = config.get_settings()
    windowed = thread[-settings["message_history"] :]
    clock_format = config.resolve_clock_format(settings)
    width = _terminal_width(settings)
    number_display = pbap.format_phone_display(number)
    shown = _render_conversation(windowed, name, number_display, clock_format, width)
    db.mark_read(shown)


def run_sync(full: bool = False) -> None:
    device = config.load().get("device")
    if device is None:
        print("No device linked. Run `turnover link` to link a device.")
        return

    known_handles = set() if full else db.known_contact_handles()
    on_progress = None
    if sys.stdout.isatty():
        def on_progress(done: int, total: int) -> None:
            print(f"\rSyncing contacts [{done}/{total}]...", end="", flush=True)
    try:
        contacts = pbap.sync_contacts(
            device["address"], device["pbap_channel"], known_handles=known_handles, on_progress=on_progress
        )
    except _LINK_ERRORS as e:
        if sys.stdout.isatty():
            print()
        print(f"Contacts sync failed ({e}). Bluetooth link trouble -- try again.")
        return
    if sys.stdout.isatty():
        print()
    db.save_contacts(contacts)
    print(f"Synced {len(contacts)} new contact(s).")

    known_handles = set() if full else db.known_message_handles()
    on_progress = None
    if sys.stdout.isatty():
        def on_progress(done: int, total: int, folder: str) -> None:
            print(f"\rSyncing messages [{done}/{total}] ({folder})...", end="", flush=True)
    try:
        messages = map_.sync_messages(
            device["address"], device["mas_channel"], known_handles=known_handles, on_progress=on_progress
        )
    except _LINK_ERRORS as e:
        if sys.stdout.isatty():
            print()
        print(f"Messages sync failed ({e}). Bluetooth link trouble -- try again (contacts still synced).")
        return
    if sys.stdout.isatty():
        print()
    db.save_messages(messages)
    print(f"Synced {len(messages)} new message(s).")


_TOP_LEVEL_COMMANDS = {"link", "unlink", "status", "contacts", "messages", "sync", "show", "send"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="turnover")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    link = subparsers.add_parser(
        "link", help="Pick a paired device and link it (resolves MAP/PBAP RFCOMM channels)"
    )
    link.add_argument(
        "-a",
        "--address",
        help="Bluetooth address; if omitted, shows an interactive picker over paired devices",
    )
    subparsers.add_parser("unlink", help="Unlink the current device and delete all cached data")
    subparsers.add_parser(
        "status", help="Show the linked device and per-conversation unread counts (same as bare `turnover`)"
    )
    subparsers.add_parser("contacts", help="List cached contacts")
    subparsers.add_parser("messages", help="Show every conversation in full")

    sync_cmd = subparsers.add_parser("sync", help="Sync contacts and messages from the linked phone")
    sync_cmd.add_argument(
        "-f", "--full", action="store_true", help="Re-fetch everything, ignoring the local cache"
    )

    show_cmd = subparsers.add_parser(
        "show", help='Show a contact\'s conversation (also: `turnover "contact"`)'
    )
    show_cmd.add_argument("contact")

    send_cmd = subparsers.add_parser(
        "send", help='Send a message and show the conversation (also: `turnover "contact" "text"`)'
    )
    send_cmd.add_argument("contact")
    send_cmd.add_argument("text")

    return parser


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    # `turnover "contact"` / `turnover "contact" "text"` as shorthand for
    # `turnover show "contact"` / `turnover send "contact" "text"`.
    if len(argv) == 1 and argv[0] not in _TOP_LEVEL_COMMANDS and not argv[0].startswith("-"):
        argv = ["show", argv[0]]
    elif len(argv) == 2 and argv[0] not in _TOP_LEVEL_COMMANDS and not argv[0].startswith("-"):
        argv = ["send", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    preflight.preflight()

    if args.command is None:
        run_summary()
    elif args.command == "link":
        run_link_wizard(args.address)
    elif args.command == "unlink":
        run_unlink()
    elif args.command == "status":
        run_summary()
    elif args.command == "contacts":
        run_contacts_list()
    elif args.command == "messages":
        run_messages_list()
    elif args.command == "sync":
        run_sync(full=args.full)
    elif args.command == "show":
        run_show(args.contact)
    elif args.command == "send":
        run_show(args.contact, text=args.text)


if __name__ == "__main__":
    main()
