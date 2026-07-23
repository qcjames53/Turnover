# In-process stand-in for a paired phone, so the app runs without real Bluetooth
# hardware or a BlueZ/PyGObject install (e.g. developing on macOS).
#
# Enabled by setting TURNOVER_FAKE_DEVICE=1 in the environment. Deliberately not a
# CLI flag -- it shouldn't show up in --help or be something a regular user stumbles
# into, just something a developer opts into explicitly.

import os

_ENV_VAR = "TURNOVER_FAKE_DEVICE"

# Mirrors pbap.py / map.py's OBEX Target UUIDs. Duplicated (rather than imported)
# because this module is imported from bt.py, sdp.py, and obex.py, all of which sit
# below pbap.py/map.py -- importing those here would invert the dependency direction.
_MAP_TARGET_UUID = bytes.fromhex("bb582b40420c11dbb0de0800200c9a66")
_PBAP_TARGET_UUID = bytes.fromhex("796135f0f0c511d809660800200c9a66")

# Mirrors sdp.py's service class constants, same reasoning.
_MESSAGE_ACCESS_SERVICE_CLASS = 0x1132
_PHONEBOOK_ACCESS_SERVICE_CLASS = 0x112F

FAKE_ADDRESS = "AA:BB:CC:DD:EE:FF"
FAKE_NAME = "Fake Device"

_MAP_CHANNEL = 19
_PBAP_CHANNEL = 20

_CONTACTS = [
    {"handle": "1.vcf", "name": "Ada Lovelace", "number": "+15551234567"},
    {"handle": "2.vcf", "name": "Grace Hopper", "number": "+15559876543"},
]

_MESSAGES = {
    "inbox": [
        {
            "handle": "10001",
            "datetime": "20260722T091500",
            "sender_addressing": "+15551234567",
            "recipient_addressing": "",
            "text": "Hey, are we still on for lunch?",
        },
    ],
    "sent": [
        {
            "handle": "10002",
            "datetime": "20260722T093000",
            "sender_addressing": "",
            "recipient_addressing": "+15551234567",
            "text": "Yep, see you at noon!",
        },
    ],
}


def enabled() -> bool:
    """
    True when the app should talk to FakeDevice instead of real Bluetooth hardware.
    """
    return os.environ.get(_ENV_VAR) == "1"


def _vcard(contact: dict) -> bytes:
    return (
        "BEGIN:VCARD\r\n"
        "VERSION:2.1\r\n"
        f"N:{contact['name']};;;;\r\n"
        f"FN:{contact['name']}\r\n"
        f"TEL;CELL:{contact['number']}\r\n"
        "END:VCARD\r\n"
    ).encode()


def _vcard_listing() -> bytes:
    cards = "".join(f'<card handle="{c["handle"]}" name="{c["name"]}"/>\n' for c in _CONTACTS)
    return (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE vCard-listing SYSTEM "vcard-listing.dtd">\n'
        '<vCard-listing version="1.0">\n'
        f"{cards}"
        "</vCard-listing>\n"
    ).encode()


def _msg_listing(folder: str) -> bytes:
    msgs = "".join(
        f'<msg handle="{m["handle"]}" datetime="{m["datetime"]}" '
        f'sender_addressing="{m["sender_addressing"]}" recipient_addressing="{m["recipient_addressing"]}"/>\n'
        for m in _MESSAGES.get(folder, [])
    )
    return f'<?xml version="1.0"?>\n<MAP-msg-listing version="1.0">\n{msgs}</MAP-msg-listing>\n'.encode()


def _bmessage(text: str) -> bytes:
    # Mirrors map.py's send_message() bMessage encoding, so _parse_bmessage_text
    # round-trips it the same way it would a real device's response.
    msg_container_len = 22 + len(text.encode("utf-8"))
    return (
        "BEGIN:BMSG\r\n"
        "VERSION:1.0\r\n"
        "STATUS:READ\r\n"
        "TYPE:SMS_GSM\r\n"
        "FOLDER:telecom/msg/inbox\r\n"
        "BEGIN:BENV\r\n"
        "BEGIN:BBODY\r\n"
        "CHARSET:UTF-8\r\n"
        f"LENGTH:{msg_container_len}\r\n"
        "BEGIN:MSG\r\n"
        f"{text}\r\n"
        "END:MSG\r\n"
        "END:BBODY\r\n"
        "END:BENV\r\n"
        "END:BMSG\r\n"
    ).encode()


class _FakeObexClient:
    """
    Duck-types the subset of nobex.Client's interface that obex.py/pbap.py/map.py use.
    """

    def __init__(self, service: str):
        self._service = service  # "map" | "pbap"
        self.sent: list[tuple[str, bytes]] = []  # (name, data) passed to put(), for tests to inspect

    def setpath(self, name: str) -> None:
        pass

    def get(self, name, header_list=()):
        if self._service == "pbap":
            if name is None:
                return {}, _vcard_listing()
            contact = next((c for c in _CONTACTS if c["handle"] == name), None)
            return {}, _vcard(contact) if contact else b""

        if name in _MESSAGES:
            return {}, _msg_listing(name)
        for messages in _MESSAGES.values():
            match = next((m for m in messages if m["handle"] == name), None)
            if match:
                return {}, _bmessage(match["text"])
        return {}, b""

    def put(self, name, data, header_list=()):
        self.sent.append((name, data))

    def disconnect(self, header_list=()):
        pass


class FakeDevice:
    address = FAKE_ADDRESS
    name = FAKE_NAME

    def paired_device_fields(self) -> dict:
        return {
            "address": self.address,
            "name": self.name,
            "map_supported": True,
            "pbap_supported": True,
        }

    def channel_for(self, service_class: int) -> int:
        if service_class == _MESSAGE_ACCESS_SERVICE_CLASS:
            return _MAP_CHANNEL
        if service_class == _PHONEBOOK_ACCESS_SERVICE_CLASS:
            return _PBAP_CHANNEL
        raise ValueError(f"FakeDevice has no channel for service class {service_class!r}")

    def obex_client(self, target_uuid: bytes) -> _FakeObexClient:
        if target_uuid == _MAP_TARGET_UUID:
            return _FakeObexClient("map")
        if target_uuid == _PBAP_TARGET_UUID:
            return _FakeObexClient("pbap")
        raise ValueError(f"FakeDevice has no service for target UUID {target_uuid!r}")
