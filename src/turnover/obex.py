import time

from ._vendor.nobex import headers
from ._vendor.nobex.client import Client

_CONNECT_RETRY_DELAY = 0.5


def connect(address: str, channel: int, target_uuid: bytes, path_segments: tuple[str, ...] = ()) -> Client:
    """
    Opens an OBEX session against `target_uuid` then navigates into `path_segments` via setpath.

    :param address: Bluetooth address of the paired phone.
    :param channel: RFCOMM channel for the target service.
    :param target_uuid: OBEX Target UUID for the service.
    :param path_segments: Path segments to navigate into via setpath, in order.
    :returns: The connected Client.
    """
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
