# Vendored nOBEX (client side)

Source: https://github.com/nccgroup/nOBEX, commit as of 2019-09-06 (last upstream
commit; the project is unmaintained but stable). License: GPLv3 (see `COPYING`),
compatible with this repo's own GPLv3 license.

Only the client-side modules are vendored — `server.py` is omitted since
Fruitsnack never acts as an OBEX server. `bluez_helper.py` is vendored
unmodified; its `sdptool`-shelling functions (`find_service`,
`advertise_service`, etc.) are dead code here — Fruitsnack's own `sdp.py`
replaces that lookup with a real SDP client, since `sdptool` isn't reliably
available and shelling out doesn't work in a Flatpak sandbox anyway.

Do not hand-edit these files; if a fix is needed, patch it here with a comment
explaining the divergence from upstream.
