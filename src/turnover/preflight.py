"""Runs once at the start of every command, before any db access.

Applies pending schema migrations, a quick auto-sync (see config.py's
"auto_sync" setting), and config's "auto"-valued setting resolution (see
config.warm()) all in parallel -- a migration check is a handful of local
sqlite reads, auto-sync is a real BT round trip, and warming config means
a GNOME D-Bus round trip and a terminal ioctl, so none of the three should
block command startup waiting on the others. In practice, auto-sync still
waits on the migration result before touching the db itself (it needs the
schema to exist to read known handles), so today the overlap only
actually buys time during the BT round trip and config warm-up.
"""

import concurrent.futures

from . import config, db
from . import map as map_
from ._vendor.nobex.common import OBEXError

# Transient Bluetooth link trouble during a background auto-sync shouldn't
# block the command the user actually ran.
_LINK_ERRORS = (OSError, OBEXError)


def _quick_sync(migration_job: concurrent.futures.Future) -> None:
    """
    Silently syncs messages before a command runs, per the auto_sync setting. A link error is
    swallowed -- a background sync failing shouldn't block the command the user actually asked
    for.

    :param migration_job: Future for the concurrently-running migration -- waited on before any
        db access, since this needs the schema to already exist.
    """
    auto_sync = config.get("auto_sync")
    if auto_sync == "off":
        return

    device = config.load().get("device")
    if device is None:
        return

    full = auto_sync == "full"

    try:
        migration_job.result()

        message_handles = set() if full else db.known_message_handles()
        messages = map_.sync_messages(device["address"], device["mas_channel"], known_handles=message_handles)
        db.save_messages(messages)

        if messages:
            print(f"Auto-synced {len(messages)} message(s).")
    except _LINK_ERRORS:
        pass


def preflight() -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        migration_job = pool.submit(db.migrate)
        quick_sync_job = pool.submit(_quick_sync, migration_job)
        config_warm_job = pool.submit(config.warm)
        migration_job.result()
        quick_sync_job.result()
        config_warm_job.result()
