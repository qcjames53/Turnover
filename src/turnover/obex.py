import time
from typing import Any

from . import _fake_device
from ._vendor.nobex import headers

_CONNECT_RETRY_DELAY = 0.5


def connect(address: str, channel: int, target_uuid: bytes, path_segments: tuple[str, ...] = ()) -> Any:
    """
    Opens an OBEX session against `target_uuid` then navigates into `path_segments` via setpath.

    :param address: Bluetooth address of the paired phone.
    :param channel: RFCOMM channel for the target service.
    :param target_uuid: OBEX Target UUID for the service.
    :param path_segments: Path segments to navigate into via setpath, in order.
    :returns: The connected Client.
    """
    if _fake_device.enabled():
        client = _fake_device.FakeDevice().obex_client(target_uuid)
        for segment in path_segments:
            client.setpath(segment)
        return client

    # Imported here, not at module level, so this module doesn't require BlueZ/Linux
    # socket support to import (e.g. running with TURNOVER_FAKE_DEVICE=1 on macOS) --
    # nOBEX's bluez_helper touches socket.BDADDR_ANY at import time, which only exists
    # on Linux.
    from ._vendor.nobex.client import Client

    client = Client(address, channel)
    try:
        client.connect(header_list=[headers.Target(target_uuid)])
    except OSError:
        # Allow one connection retry
        time.sleep(_CONNECT_RETRY_DELAY)
        client.connect(header_list=[headers.Target(target_uuid)])
    for segment in path_segments:
        client.setpath(segment)
    return client


def probe(address: str, channel: int, target_uuid: bytes) -> None:
    """
    Opens and immediately closes an OBEX session.

    :param address: Bluetooth address of the paired phone.
    :param channel: RFCOMM channel for the target service.
    :param target_uuid: OBEX Target UUID for the service.
    """
    client = connect(address, channel, target_uuid)
    client.disconnect()
