import argparse
import sys

import argcomplete

from .. import __version__, db, preflight
from . import onboarding, render_messages


def _complete_contact(prefix: str, **kwargs) -> list[str]:
    """
    Argcomplete completer for the `contacts` positional. Completes only the single contact name
    after the last comma, fuzzy-matched via db.find_contacts, leaving any already-typed
    "name1,name2," prefix in front of each suggestion untouched.
    """
    prior, _, current = prefix.rpartition(",")
    try:
        matches = db.find_contacts(current) if current else db.list_contacts()
    except Exception:
        # Completion runs ahead of preflight's migration -- e.g. no db file yet on a first run.
        return []
    return [f"{prior},{c.name}" if prior else c.name for c in matches]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="turnover")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    contacts_arg = parser.add_argument(
        "contacts",
        nargs="?",
        help='Comma-separated contact names to show messages for (e.g. "mom,alice"), or "setup" to configure a device link',
    )
    contacts_arg.completer = _complete_contact

    return parser


def _resolve_addresses(contacts_arg: str) -> list[str]:
    """
    Resolves a comma-separated list of contact name queries to a deduped list of addresses, in
    first-seen order. A name that doesn't fuzzy-match any cached contact is skipped (with a
    warning to stderr) rather than aborting the whole lookup; a name matching more than one
    contact includes all of them, also with a warning.

    :param contacts_arg: Raw "contact1,contact2" argument, as passed on the command line.
    """
    seen: set[str] = set()
    addresses: list[str] = []
    for raw_name in contacts_arg.split(","):
        name = raw_name.strip()
        if not name:
            continue

        matches = db.find_contacts(name)
        if not matches:
            print(f"turnover: no contact found matching {name!r}", file=sys.stderr)
            continue
        if len(matches) > 1:
            matched_names = ", ".join(c.name for c in matches)
            print(f"turnover: {name!r} matched multiple contacts ({matched_names}) -- including all", file=sys.stderr)

        for contact in matches:
            for number in contact.numbers:
                if number not in seen:
                    seen.add(number)
                    addresses.append(number)

    return addresses


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)

    preflight.preflight()

    if args.contacts == "setup":
        onboarding.run_onboarding_wizard()
    elif args.contacts:
        addresses = _resolve_addresses(args.contacts)
        if addresses:
            print(render_messages.get_output_string(addresses))


if __name__ == "__main__":
    main()
