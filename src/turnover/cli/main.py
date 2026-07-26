import argparse
import sys

import argcomplete

from .. import __version__, config, db, pbap, preflight, sdp
from .. import map as map_
from . import onboarding, render_messages, utils

_SUBCOMMANDS = ("contacts", "messages", "setup", "status", "sync")


def _complete_contact(prefix: str, **kwargs) -> list[str]:
    """
    Argcomplete completer for messages' `contacts` positional. Completes only the single contact
    name after the last comma, substring-matched (deliberately not db.find_contacts -- that
    resolves to the one best contact, but completion wants to show every candidate while the user
    is still typing), leaving any already-typed "name1,name2," prefix in front of each suggestion
    untouched.
    """
    prior, _, current = prefix.rpartition(",")
    try:
        contacts = db.list_contacts()
    except Exception:
        # Completion runs ahead of preflight's migration -- e.g. no db file yet on a first run.
        return []
    if current:
        query = current.lower()
        contacts = [c for c in contacts if query in c.name.lower()]
    return [f"{prior},{c.name}" if prior else c.name for c in contacts]


def _normalize_argv(argv: list[str]) -> list[str]:
    """
    Resolves turnover's top-level shorthand before argparse ever sees it: a bare invocation is
    shorthand for `status`, and a first token that's neither a flag nor a known subcommand is
    shorthand for `messages <that token> ...` (e.g. `turnover mom "on my way"`).
    """
    if not argv:
        return ["status"]
    if argv[0].startswith("-") or argv[0] in _SUBCOMMANDS:
        return argv
    return ["messages", *argv]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="turnover")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("contacts", help="List all synced contacts")
    messages_parser = subparsers.add_parser("messages", help="Show and send messages")
    contacts_arg = messages_parser.add_argument(
        "contacts",
        nargs="?",
        metavar="address(es)",
        help='(Optional) Comma-separated address list (e.g. "mom, 408-555-1234")',
    )
    contacts_arg.completer = _complete_contact
    messages_parser.add_argument(
        "message", nargs="?", help="(Optional) Message to send to selected address"
    )

    subparsers.add_parser("setup", help="Run the setup wizard to link a phone")
    subparsers.add_parser("status", help="Show which conversations have unread messages")
    subparsers.add_parser("sync", help="Run a full sync of messages and contacts")

    return parser


def _resolve_addresses(contacts_arg: str) -> list[str]:
    """
    Resolves a comma-separated list of contact name queries to a deduped list of addresses, in
    first-seen order. Each name resolves to at most one contact (see db.find_contacts -- an
    ambiguous name is settled by picking whoever has the most recent message), so "foo,bar" can
    still surface two contacts' worth of addresses, one per name, but a single name never does.
    A name that doesn't match any cached contact is skipped (with a warning to stderr) rather
    than aborting the whole lookup.

    :param contacts_arg: Raw "contact1,contact2" argument, as passed on the command line.
    """
    seen: set[str] = set()
    addresses: list[str] = []
    for raw_name in contacts_arg.split(","):
        name = raw_name.strip()
        if not name:
            continue

        contact = db.find_contacts(name)
        if contact is None:
            print(f"turnover: no contact found matching {name!r}", file=sys.stderr)
            continue

        for number in contact.numbers:
            if number not in seen:
                seen.add(number)
                addresses.append(number)

    return addresses


def _show_conversations(addresses: list[str]) -> None:
    """
    Renders `addresses`' conversations (capped per config's messages_displayed, "all" meaning
    uncapped) and marks whatever was unread among them as read -- mirroring db.mark_read's
    contract that this only happens once a conversation has actually been shown to the user.
    """
    m_count = config.get("messages_displayed")
    if m_count == "all":
        m_count = None

    conversations = db.list_conversations(addresses, messages_per_conversation=m_count)
    print(render_messages.get_conversation_string(conversations))

    unread_handles = [(m.folder, m.handle) for c in conversations for m in c.messages if not m.local_read]
    db.mark_read(unread_handles)


def _run_contacts() -> None:
    contacts = db.list_contacts()
    if not contacts:
        print("turnover: no contacts synced yet -- run `turnover sync`", file=sys.stderr)
        return

    for contact in contacts:
        numbers = ", ".join(pbap.format_phone_display(n) for n in contact.numbers)
        print(f"{contact.name}: {numbers}" if numbers else contact.name)


def _run_messages(contacts_arg: str | None, message: str | None) -> None:
    if contacts_arg is None:
        addresses = db.list_unread_addresses()
        if not addresses:
            print("No new messages")
            return
        _show_conversations(addresses)
        return

    addresses = _resolve_addresses(contacts_arg)

    if message is None:
        if addresses:
            _show_conversations(addresses)
        return

    if len(addresses) != 1:
        print(
            f"turnover: refusing to send -- {contacts_arg!r} must resolve to exactly one contact (matched {len(addresses)})",
            file=sys.stderr,
        )
        return

    device = config.get_linked_device()
    if device is None:
        print("turnover: no phone linked -- run `turnover setup`", file=sys.stderr)
        return

    map_.send_message(device["address"], device["mas_channel"], addresses[0], message)


def _run_status() -> None:
    addresses = db.list_unread_addresses()
    if not addresses:
        print("No unread messages")
        return

    for conversation in db.list_conversations(addresses):
        label = conversation.contact_name or pbap.format_phone_display(conversation.address)
        unread = sum(1 for m in conversation.messages if not m.local_read)
        print(f"{label}: {unread} unread")


def _run_sync() -> None:
    device = config.get_linked_device()
    if device is None:
        print("turnover: no phone linked -- run `turnover setup`", file=sys.stderr)
        return

    address = device["address"]
    with utils.Spinner():
        messages = map_.sync_messages(address, device["mas_channel"])
        db.save_messages(messages)

        pbap_channel = sdp.find_rfcomm_channel(address, sdp.PHONEBOOK_ACCESS_SERVICE_CLASS)
        contacts = pbap.sync_contacts(address, pbap_channel)
        db.save_contacts(contacts)

    print(f"Synced {len(messages)} messages and {len(contacts)} contacts")


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args(_normalize_argv(argv))

    preflight.preflight()

    if args.command == "contacts":
        _run_contacts()
    elif args.command == "messages":
        _run_messages(args.contacts, args.message)
    elif args.command == "setup":
        onboarding.run_onboarding_wizard()
    elif args.command == "status":
        _run_status()
    elif args.command == "sync":
        _run_sync()


if __name__ == "__main__":
    main()
