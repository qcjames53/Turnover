# Phone book access protocol
# https://www.bluetooth.com/specifications/specs/html/?src=pbap-v1-2-3_1756156381/PBAP_v1.2.3/out/en/index-en.html

from collections.abc import Callable
from dataclasses import dataclass

import phonenumbers

from . import obex
from ._vendor.nobex import headers
from ._vendor.nobex.xml_helper import parse_xml

# PBAP target UUID (Bluetooth PBAP spec section 6.4)
_PBAP_TARGET_UUID = bytes.fromhex("796135f0f0c511d809660800200c9a66")


@dataclass
class Contact:
    handle: str
    name: str
    numbers: list[str]


def _extract_tels(vcard_text: str) -> list[str]:
    """
    Extracts the contact's phone number(s) from a vcard -- a contact can carry more than one TEL
    line (mobile, home, work, ...).

    :param vcard_text: Body contents of the vcard (string)
    :returns: Contents of each TEL line as reported by the phone, in vcard order.
    """
    tels = []
    for line in vcard_text.splitlines():
        # TEL lines can carry type params, e.g. "TEL;CELL:(513) 889-6098".
        if line.startswith("TEL") and ":" in line:
            tels.append(line.split(":", 1)[1].strip())
    return tels


def probe(address: str, channel: int) -> None:
    """
    Opens and immediately closes a PBAP OBEX session.

    :param address: Bluetooth address of the paired phone.
    :param channel: RFCOMM channel for the PBAP service.
    """
    obex.probe(address, channel, _PBAP_TARGET_UUID)


def sync_contacts(
    address: str,
    channel: int,
    known_handles: set[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[Contact]:
    """
    Syncs new contacts from the phone's reported address book.

    :param address: Bluetooth address of the paired phone.
    :param channel: RFCOMM channel for the PBAP service.
    :param known_handles: Handles for which we can skip syncing contact vcard contents. Omit for full sync.
    :param on_progress: Callable called as contacts are synced / skipped.
    :returns: Newly-fetched contacts.
    """
    known_handles = known_handles or set()
    client = obex.connect(address, channel, _PBAP_TARGET_UUID, ("telecom", "pb"))
    try:
        _hdrs, listing = client.get(None, header_list=[headers.Type(b"x-bt/vcard-listing")])
        root = parse_xml(listing)
        cards = [
            (card.attrib["handle"], card.attrib.get("name", ""))
            for card in root.findall("card")
        ]

        contacts = []
        total = len(cards)
        for done, (handle, name) in enumerate(cards, start=1):
            if handle not in known_handles:
                _hdrs, vcard = client.get(handle, header_list=[headers.Type(b"x-bt/vcard")])
                tels = _extract_tels(vcard.decode("utf-8", errors="replace"))
                numbers = [canonicalize_number(tel) for tel in tels]
                contacts.append(Contact(handle=handle, name=name, numbers=numbers))
            if on_progress:
                on_progress(done, total)
    finally:
        client.disconnect()

    return contacts


def canonicalize_number(number: str) -> str:
    """
    Canonicalizes a phone number to E.164 (e.g. +15551234567)

    :param number: Raw addressing/TEL value, in whatever formatting the source reported.
    :returns: E.164-formatted number, or `number` unchanged if it isn't a valid phone number
        (SMS short codes, iMessage email addresses).
    """
    try:
        parsed = phonenumbers.parse(number, "US")
    except phonenumbers.NumberParseException:
        return number
    if not phonenumbers.is_valid_number(parsed):
        return number
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def looks_like_phone_number(number: str) -> bool:
    """
    Real per-country validation via libphonenumber. Assumes US/NANP when `number` has no leading '+'.

    :param number: Unformatted phone number
    :returns: true if matches valid phone number, false otherwise
    """
    try:
        parsed = phonenumbers.parse(number, "US")
    except phonenumbers.NumberParseException:
        return False
    return phonenumbers.is_valid_number(parsed)


def format_phone_display(number: str) -> str:
    """
    Formats a phone number for display:
        - Plain NANP dash-grouping (555-123-4567) for +1 numbers.
        - `phonenumbers` INTERNATIONAL format (+44 20 7946 0958) for other valid formats.
        - Unchanged string if it isn't a parseable phone number (12345).
    """
    try:
        parsed = phonenumbers.parse(number, "US")
    except phonenumbers.NumberParseException:
        return number
    if not phonenumbers.is_valid_number(parsed):
        return number
    if parsed.country_code == 1:
        national = phonenumbers.national_significant_number(parsed)
        if len(national) == 10:
            return f"{national[0:3]}-{national[3:6]}-{national[6:10]}"
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
