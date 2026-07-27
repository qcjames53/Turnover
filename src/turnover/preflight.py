import concurrent.futures

from . import config, db, pbap
from . import map as map_
from ._vendor.nobex.common import OBEXError
from .cli import utils

# Transient Bluetooth link trouble during a background auto-sync shouldn't
# block the command the user actually ran.
_LINK_ERRORS = (OSError, OBEXError)


def _quick_sync(migration_job: concurrent.futures.Future) -> tuple[int,int]:
    """
    Silently syncs messages/contacts before a command runs, per the auto_sync setting.

    :param migration_job: Future for the concurrently-running migration -- waited on before any
        db access, since this needs the schema to already exist.
    :returns: Number of messages synced and number of contacts synced.
    """
    auto_sync = config.get("auto_sync")
    if auto_sync == "off":
        return 0, 0

    device = config.get_linked_device()
    if device is None:
        return 0, 0

    messages_synced = 0
    contacts_synced = 0

    try:
        migration_job.result()  # wait for migration to finish

        messages = map_.sync_messages(device["address"], device["mas_channel"], known_handles=db.known_message_handles())
        db.save_messages(messages)
        messages_synced = len(messages)

        if auto_sync == "msgs+new contacts":
            contacts = pbap.sync_contacts(device["address"], device["pbap_channel"], known_handles=db.known_contact_handles())
            db.save_contacts(contacts)
            contacts_synced = len(contacts)
        elif auto_sync == "msgs+all contacts":
            contacts = pbap.sync_contacts(device["address"], device["pbap_channel"], known_handles=None)
            db.save_contacts(contacts)
            contacts_synced = len(contacts)
    except _LINK_ERRORS:
        return 0, 0
    return messages_synced, contacts_synced


def preflight() -> None:
    with utils.Spinner():
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            migration_job = pool.submit(db.migrate)
            quick_sync_job = pool.submit(_quick_sync, migration_job)
            clock_format_warm_job = pool.submit(utils.resolve_datetime_format)
            migration_job.result()
            clock_format_warm_job.result()
        messages_synced, contacts_synced = quick_sync_job.result()

    if messages_synced:
        print(f"Synced {messages_synced} messages")
    if contacts_synced:
        print(f"Synced {contacts_synced} contacts")
