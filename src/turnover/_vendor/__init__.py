"""Vendored third-party packages.

nOBEX's own modules import each other as an absolute top-level `nOBEX`
package (e.g. `from nOBEX.common import ...`), but it's vendored here
unmodified under `_vendor/nobex/` (lowercase, nested). Alias the name in
sys.modules so those untouched imports resolve to this vendored copy
instead of requiring a real top-level `nOBEX` package.
"""

import sys

from . import nobex as _nobex

sys.modules.setdefault("nOBEX", _nobex)
