# BlueZ D-Bus is used only for pairing management, not the data path.
# We need our own SDP client due to Apple schenanigans (sdp.py).

from dataclasses import dataclass

from gi.repository import Gio, GLib

# https://www.bluetooth.com/specifications/specs/html/?src=MAP_v1.4.3/out/en/index-en.html
# https://www.bluetooth.com/specifications/specs/html/?src=pbap-v1-2-3_1756156381/PBAP_v1.2.3/out/en/index-en.html
_MESSAGE_ACCESS_SERVICE_UUID = "00001132-0000-1000-8000-00805f9b34fb"
_PHONEBOOK_ACCESS_SERVICE_UUID = "0000112f-0000-1000-8000-00805f9b34fb"


@dataclass
class PairedDevice:
    address: str
    name: str
    map_supported: bool
    pbap_supported: bool


def _get_managed_objects() -> dict:
    connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    reply = connection.call_sync(
        "org.bluez",
        "/",
        "org.freedesktop.DBus.ObjectManager",
        "GetManagedObjects",
        None,
        GLib.VariantType("(a{oa{sa{sv}}})"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    (objects,) = reply.unpack()
    return objects


def paired_devices() -> list[PairedDevice]:
    """
    Returns paired devices, flagging which advertise MAP/PBAP UUIDs.
    """
    devices = []
    for _path, interfaces in _get_managed_objects().items():
        props = interfaces.get("org.bluez.Device1")
        if props is None or not props.get("Paired", False):
            continue

        address = props.get("Address", "")
        name = props.get("Name") or props.get("Alias") or address
        uuids = {u.lower() for u in props.get("UUIDs", [])}

        devices.append(
            PairedDevice(
                address=address,
                name=name,
                map_supported=_MESSAGE_ACCESS_SERVICE_UUID in uuids,
                pbap_supported=_PHONEBOOK_ACCESS_SERVICE_UUID in uuids,
            )
        )

    return devices
