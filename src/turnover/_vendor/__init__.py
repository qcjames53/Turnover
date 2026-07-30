"""Vendored third-party packages.

nOBEX's own modules import each other as an absolute top-level `nOBEX`
package (e.g. `from nOBEX.common import ...`), but it's vendored here
unmodified under `_vendor/nobex/` (lowercase, nested). Aliasing just the
package name in sys.modules isn't enough on its own: the first time nOBEX's
own code does e.g. `from nOBEX.common import ...`, Python still imports
common.py fresh under the "nOBEX.common" name, separate from
"turnover._vendor.nobex.common" -- so callers here that catch OBEXError via
the latter path silently never match exceptions raised via the former (two
distinct classes from the same file). Pre-importing each platform-safe
submodule under its real name and aliasing it under "nOBEX.<name>" too
closes that gap, in dependency order (headers has no internal deps; common
needs headers; requests/responses need common).

`client` and `bluez_helper` are deliberately left out: bluez_helper
references AF_BLUETOOTH/BTPROTO_RFCOMM socket constants that don't exist on
non-Linux platforms, so it must stay behind obex.py's fake-device-gated lazy
import rather than being pulled in here at package load time.
"""

import sys

from . import nobex as _nobex

sys.modules.setdefault("nOBEX", _nobex)

from .nobex import headers as _headers  # noqa: E402
sys.modules.setdefault("nOBEX.headers", _headers)

from .nobex import common as _common  # noqa: E402
sys.modules.setdefault("nOBEX.common", _common)

from .nobex import requests as _requests  # noqa: E402
sys.modules.setdefault("nOBEX.requests", _requests)

from .nobex import responses as _responses  # noqa: E402
sys.modules.setdefault("nOBEX.responses", _responses)

from .nobex import xml_helper as _xml_helper  # noqa: E402
sys.modules.setdefault("nOBEX.xml_helper", _xml_helper)
