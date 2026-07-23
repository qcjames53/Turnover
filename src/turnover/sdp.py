# Service discovery protocol
# https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core_v6.3/out/en/host/service-discovery-protocol--sdp--specification.html
#
# We have to create our own SDP client since BlueZ's D-Bus OBEX API auto-selects OBEX-over-L2CAP, and iOS drops after
# connect; forcing classic RFCOMM actually works. We use BlueZ for pairing management (see bt.py).

import socket
import uuid

from . import _fake_device

MESSAGE_ACCESS_SERVICE_CLASS = 0x1132
PHONEBOOK_ACCESS_SERVICE_CLASS = 0x112F

_ATTR_PROTOCOL_DESCRIPTOR_LIST = 0x0004
_PROTOCOL_ID_RFCOMM = 0x0003
_SDP_PSM = 1
_SERVICE_SEARCH_ATTRIBUTE_REQUEST = 0x06
_SERVICE_SEARCH_ATTRIBUTE_RESPONSE = 0x07


class SdpError(Exception):
    pass


def _encode_uuid16(value: int) -> bytes:
    """
    Encode a UUID as raw bytes

    :param value: UUID to encode
    :returns: bytes representing the UUID
    """
    return bytes([0x19]) + value.to_bytes(2, "big")  # type=3 (UUID), size index=1 (2 bytes)


def _encode_uint16(value: int) -> bytes:
    """
    Encode an integer as raw bytes

    :param value: int to encode
    :returns: bytes representing the int
    """
    return bytes([0x09]) + value.to_bytes(2, "big")  # type=1 (UInt), size index=1 (2 bytes)


def _encode_sequence(items: bytes) -> bytes:
    """
    Encode a byte sequence as raw bytes

    :param items: list of bytes to encode
    :returns: bytes representing the sequence
    """
    if len(items) <= 0xFF:
        return bytes([0x35, len(items)]) + items  # type=6 (seq), size index=5 (8-bit length)
    return bytes([0x36]) + len(items).to_bytes(2, "big") + items  # size index=6 (16-bit length)


def _build_request(transaction_id: int, service_class: int, continuation: bytes = b"") -> bytes:
    """
    Builds an SDP ServiceSearchAttributeRequest PDU requesting the ProtocolDescriptorList for `service_class`.

    :param transaction_id: SDP transaction ID to tag the request with.
    :param service_class: 16-bit SDP service class UUID to search for.
        - MESSAGE_ACCESS_SERVICE_CLASS = 0x1132
        - PHONEBOOK_ACCESS_SERVICE_CLASS = 0x112F
    :param continuation: Continuation state from a previous partial response, or b"" for the initial request.
    :returns: bytes representing the encoded PDU.
    """
    service_search_pattern = _encode_sequence(_encode_uuid16(service_class))
    attribute_id_list = _encode_sequence(_encode_uint16(_ATTR_PROTOCOL_DESCRIPTOR_LIST))
    max_attribute_byte_count = 0xFFFF

    params = bytearray()
    params += service_search_pattern
    params += max_attribute_byte_count.to_bytes(2, "big")
    params += attribute_id_list
    params.append(len(continuation))
    params += continuation

    pdu = bytearray([_SERVICE_SEARCH_ATTRIBUTE_REQUEST])
    pdu += transaction_id.to_bytes(2, "big")
    pdu += len(params).to_bytes(2, "big")
    pdu += params
    return bytes(pdu)


def _parse_uuid(value: bytes) -> uuid.UUID:
    """
    Parse a UUID from raw bytes

    :param bytes: Raw bytes composing the UUID
    :returns: uuid.UUID
    """
    if len(value) == 2:
        return uuid.UUID(f"0000{value.hex()}-0000-1000-8000-00805f9b34fb")
    if len(value) == 4:
        return uuid.UUID(f"{value.hex()}-0000-1000-8000-00805f9b34fb")
    if len(value) == 16:
        return uuid.UUID(bytes=bytes(value))
    raise SdpError("unexpected UUID length")


def _parse_uint(value: bytes) -> int:
    """
    Parse a UInt from raw bytes

    :param value: Raw bytes composing the UInt
    :returns: int
    """
    return int.from_bytes(value, "big")


def _parse_sequence(value: bytes) -> list:
    """
    Parse a Sequence/Alternative from raw bytes

    :param value: Raw bytes composing the sequence's data elements, back to back
    :returns: list of parsed data elements
    """
    items = []
    pos = 0
    while pos < len(value):
        item, pos = _parse_data_element(value, pos)
        items.append(item)
    return items


def _parse_data_element(buf: bytes, offset: int = 0):
    """
    Parses one SDP Data Element (Bluetooth Core Spec, SDP section 3: "Data representation").

    :param buf: The data buffer as a raw bytestream
    :param offset: The offset at which to start parsing the data element
    :returns: (value, offset of next data element)
        - UInt returns int
        - UUID returns uuid.UUID
        - Sequence/Alternative returns list
        - Other data types return None
    """
    descriptor = buf[offset]
    elem_type = descriptor >> 3
    size_index = descriptor & 0x07

    if size_index <= 4:
        data_len, header_len = (1, 2, 4, 8, 16)[size_index], 1
    elif size_index == 5:
        data_len, header_len = buf[offset + 1], 2
    elif size_index == 6:
        data_len, header_len = int.from_bytes(buf[offset + 1 : offset + 3], "big"), 3
    else:
        data_len, header_len = int.from_bytes(buf[offset + 1 : offset + 5], "big"), 5

    if elem_type == 0:  # Nil always has zero-length data, regardless of size index.
        data_len = 0

    value_start = offset + header_len
    value_end = value_start + data_len
    value_bytes = buf[value_start:value_end]

    if elem_type == 1:  # UInt
        value = _parse_uint(value_bytes)
    elif elem_type == 3:  # UUID
        value = _parse_uuid(value_bytes)
    elif elem_type in (6, 7):  # Sequence / Alternative
        value = _parse_sequence(value_bytes)
    else:
        value = None

    return value, value_end


def find_rfcomm_channel(address: str, service_class: int) -> int:
    """
    Determines the RFCOMM channel advertised for `service_class` by the linked device.

    :param address: Bluetooth address of the paired phone.
    :param service_class: 16-bit SDP service class UUID to search for
        - MESSAGE_ACCESS_SERVICE_CLASS = 0x1132
        - PHONEBOOK_ACCESS_SERVICE_CLASS = 0x112F
    :returns: RFCOMM channel number advertised for the service.
    """
    if _fake_device.enabled():
        return _fake_device.FakeDevice().channel_for(service_class)

    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
    try:
        sock.settimeout(5.0)
        sock.connect((address, _SDP_PSM))

        transaction_id = 0
        continuation = b""
        attribute_data = bytearray()

        while True:
            sock.send(_build_request(transaction_id, service_class, continuation))
            response = sock.recv(4096)

            if response[0] != _SERVICE_SEARCH_ATTRIBUTE_RESPONSE:
                raise SdpError("Unexpected PDU ID in response")

            param_len = int.from_bytes(response[3:5], "big")
            params = response[5 : 5 + param_len]

            byte_count = int.from_bytes(params[0:2], "big")
            attribute_data += params[2 : 2 + byte_count]

            cont_len = params[2 + byte_count]
            if cont_len == 0:
                break
            continuation = params[2 + byte_count + 1 : 2 + byte_count + 1 + cont_len]
            transaction_id += 1
    finally:
        sock.close()

    records, _ = _parse_data_element(bytes(attribute_data))
    if not records:
        raise SdpError("Service not advertised by device")

    record_attrs = iter(records[0])
    protocol_descriptor_list = None
    # record_attrs is a flat [id, value, id, value, ...] sequence; zipping it against itself pairs each id with
    # its value. strict=True guards against a malformed record with a trailing id and no value.
    for attr_id, attr_value in zip(record_attrs, record_attrs, strict=True):
        if attr_id == _ATTR_PROTOCOL_DESCRIPTOR_LIST:
            protocol_descriptor_list = attr_value
            break
    if protocol_descriptor_list is None:
        raise SdpError("Missing ProtocolDescriptorList")

    for protocol in protocol_descriptor_list:
        if not protocol or not isinstance(protocol[0], uuid.UUID):
            continue
        if protocol[0].int >> 96 == _PROTOCOL_ID_RFCOMM and len(protocol) > 1:
            return protocol[1]

    raise SdpError("RFCOMM channel not found in ProtocolDescriptorList")
