#!/usr/bin/env python3
"""Let an anonymous viewer open the OpenEgiz app without an "Unauthorized" toast.

Applied by ``patch-branding.py`` as part of the same rebuild, after the
branding edits and before the SRI digests in ``module.js`` are recomputed, so
there is still one command that turns ``upstream/`` into the shipped zips:

    python3 patch-branding.py                 # rebuild both zips (includes this patch)
    python3 patch-branding.py --check         # verify shipped zips match a fresh run
    python3 patch-anonymous.py                # verify the shipped app zip carries this patch

The defect. Every page of the app calls ``getCurrentUserRole()``
(``utils/auxFunctions/auth.ts`` upstream, the function ``m`` at the top of
``396.js``). It asks ``GET /api/org`` and then ``GET /api/user/orgs`` and reads
the user's role in the current org from the second answer. Grafana registers
``/api/user/*`` behind ``reqSignedInNoAnonymous``, so for an anonymous session
(``[auth.anonymous] enabled``) that call always answers 401 and no Grafana
setting changes that. ``getBackendSrv().get`` shows an error toast for every
failed request by default, so the viewer gets an orange "Unauthorized" toast on
every page, although the function's own ``catch`` already falls back to
``"Viewer"`` and the page works.

The patch. Before the two requests, return ``"Viewer"`` when Grafana's boot
data says the session is not signed in (``config.bootData.user.isSignedIn`` of
``@grafana/runtime``, which the chunk already imports as ``i``). That is the
value the upstream code ends with for an anonymous session anyway (through its
``catch``), so the role the app derives is unchanged; only the failing request
and its toast go away. For a signed-in user ``isSignedIn`` is true and the code
path is byte-for-byte upstream's.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_ZIP = "ertis-opentwins-app.zip"
PREFIX = "ertis-opentwins-app/"
CHUNK = PREFIX + "396.js"

# The start of getCurrentUserRole() in the minified chunk. `i` is
# @grafana/runtime (webpack module 531 -> the AMD dependency "@grafana/runtime"
# of module.js), `p` is the async-to-generator helper.
OLD = (b'const m=()=>p((function*(){try{'
       b'const e=yield(0,i.getBackendSrv)().get("/api/org"),'
       b't=(yield(0,i.getBackendSrv)().get("/api/user/orgs"))')
NEW = (b'const m=()=>p((function*(){try{'
       b'if(!i.config.bootData.user.isSignedIn)return"Viewer";'
       b'const e=yield(0,i.getBackendSrv)().get("/api/org"),'
       b't=(yield(0,i.getBackendSrv)().get("/api/user/orgs"))')


class PatchError(RuntimeError):
    pass


def _sub_once(blob: bytes, old: bytes, new: bytes, where: str) -> bytes:
    n = blob.count(old)
    if n != 1:
        raise PatchError(
            f"{where}: expected exactly 1 occurrence of {old!r}, found {n}. "
            "Upstream probably changed; re-derive the anchor."
        )
    return blob.replace(old, new, 1)


def patch_app(entries: dict[str, bytes]) -> None:
    """Patch the app's entries in place. module.js SRI is the caller's job."""
    entries[CHUNK] = _sub_once(entries[CHUNK], OLD, NEW,
                               "396.js getCurrentUserRole anonymous guard")


def is_patched(chunk: bytes) -> bool:
    return chunk.count(NEW) == 1 and chunk.count(b"/api/user/orgs") == 1


def main() -> int:
    path = HERE / APP_ZIP
    with zipfile.ZipFile(path) as z:
        chunk = z.read(CHUNK)
    if not is_patched(chunk):
        print(f"{path.name}: 396.js lacks the anonymous-viewer guard; "
              "run python3 patch-branding.py", file=sys.stderr)
        return 1
    print(f"{path.name}: 396.js carries the anonymous-viewer guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
