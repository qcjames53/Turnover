# Message access protocol
# https://www.bluetooth.com/specifications/specs/html/?src=MAP_v1.4.3/out/en/index-en.html

import re
from collections.abc import Callable

from . import obex, pbap
from ._vendor.nobex import headers
from ._vendor.nobex.xml_helper import parse_xml
from .db import Message

_SYNCED_FOLDERS = ("inbox", "sent")

# Target UUID (Bluetooth MAP spec section 6.4.1)
_MAP_TARGET_UUID = bytes.fromhex("bb582b40420c11dbb0de0800200c9a66")

# len("BEGIN:MSG\r\n") + len("\r\n") + len("END:MSG\r\n")
_MSG_CONTAINER_LEN = 22


def _parse_bmessage_text(data: bytes) -> str | None:
    """
    Extracts the message body from a raw bMessage object (x-bt/message).
    """
    length_match = re.search(rb"\r\nLENGTH:(\d+)\r\n", data)
    if not length_match:
        return None

    begin_marker = b"BEGIN:MSG\r\n"
    begin_index = data.find(begin_marker, length_match.end())
    if begin_index == -1:
        return None

    message_start = begin_index + len(begin_marker)
    message_len = int(length_match.group(1)) - _MSG_CONTAINER_LEN
    message_end = message_start + message_len
    if message_len < 0 or message_end > len(data):
        return None

    message_bytes = data[message_start:message_end]
    charset_match = re.search(rb"\r\nCHARSET:([^\r\n]+)\r\n", data)
    charset = charset_match.group(1).decode("ascii", errors="replace") if charset_match else "utf-8"
    try:
        return message_bytes.decode(charset, errors="replace")
    except LookupError:
        return message_bytes.decode("utf-8", errors="replace")


def probe(address: str, channel: int) -> None:
    """
    Opens and immediately closes a MAP OBEX session.

    :param address: Bluetooth address of the paired phone.
    :param channel: RFCOMM channel for the MAP service.
    """
    obex.probe(address, channel, _MAP_TARGET_UUID)


def sync_messages(
    address: str,
    channel: int,
    known_handles: set[tuple[str, str]] | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[Message]:
    """
    Syncs new messages from the phone's _SYNCED_FOLDERS.

    :param address: Bluetooth address of the paired phone.
    :param channel: RFCOMM channel for the MAP service.
    :param known_handles: (folder, handle) pairs for which we can skip syncing message contents. Omit for full sync.
    :param on_progress: Callable called as messages are synced / skipped.
    :returns: Newly-fetched messages.
    """
    known_handles = known_handles or set()
    client = obex.connect(address, channel, _MAP_TARGET_UUID, ("telecom", "msg"))
    try:
        entries = []
        for folder in _SYNCED_FOLDERS:
            _hdrs, listing = client.get(folder, header_list=[headers.Type(b"x-bt/MAP-msg-listing")])
            if listing:
                root = parse_xml(listing)
                entries.extend((folder, msg.attrib) for msg in root.findall("msg"))

        messages = []
        total = len(entries)
        for done, (folder, attrib) in enumerate(entries, start=1):
            handle = attrib["handle"]
            if (folder, handle) not in known_handles:
                _hdrs, body = client.get(handle, header_list=[headers.Type(b"x-bt/message")])
                message_text = _parse_bmessage_text(body)
                if message_text is not None:
                    messages.append(
                        Message(
                            handle=handle,
                            folder=folder,
                            datetime=attrib.get("datetime", ""),
                            sender_addressing=pbap.canonicalize_number(attrib.get("sender_addressing", "")),
                            recipient_addressing=pbap.canonicalize_number(attrib.get("recipient_addressing", "")),
                            text=message_text,
                        )
                    )
            if on_progress:
                on_progress(done, total, folder)
    finally:
        client.disconnect()

    return messages


def send_message(address: str, channel: int, recipient: str, text: str) -> None:
    """
    Sends a message to a recipient via MAP PushMessage.

    :param address: Bluetooth address of the paired phone.
    :param channel: RFCOMM channel for the MAP service.
    :param recipient: Bare phone number of message recipient.
    :param text: Message text to send.
    """
    inner_length = _MSG_CONTAINER_LEN + len(text.encode("utf-8"))
    bmsg = (
        "BEGIN:BMSG\r\n"
        "VERSION:1.0\r\n"
        "STATUS:READ\r\n"
        "TYPE:SMS_GSM\r\n"
        "FOLDER:null\r\n"
        "BEGIN:BENV\r\n"
        "BEGIN:VCARD\r\n"
        "VERSION:2.1\r\n"
        "N:;;;;\r\n"
        f"TEL:{recipient}\r\n"
        "END:VCARD\r\n"
        "BEGIN:BBODY\r\n"
        "CHARSET:UTF-8\r\n"
        f"LENGTH:{inner_length}\r\n"
        "BEGIN:MSG\r\n"
        f"{text}\r\n"
        "END:MSG\r\n"
        "END:BBODY\r\n"
        "END:BENV\r\n"
        "END:BMSG\r\n"
    ).encode()

    # Transparent=off, Retry=off, Charset=UTF-8 (Bluetooth MAP spec 5.8.4).
    app_params = bytes([0x0B, 0x01, 0x00, 0x0C, 0x01, 0x00, 0x14, 0x01, 0x01])

    client = obex.connect(address, channel, _MAP_TARGET_UUID, ("telecom", "msg"))
    try:
        client.put(
            "outbox",
            bmsg,
            header_list=[headers.Type(b"x-bt/message"), headers.App_Parameters(app_params)],
        )
    finally:
        client.disconnect()
