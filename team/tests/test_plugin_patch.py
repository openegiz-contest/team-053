"""Tests for the vendored OpenEgiz app plugin (vendor/grafana-plugins at the repository root).

The anonymous-viewer patch (vendor/grafana-plugins/patch-anonymous.py): the shipped
app zip must skip GET /api/user/orgs for a session that is not signed in, keep the
signed-in path byte-for-byte upstream's, pin correct SRI digests for every chunk, and
match a fresh run of patch-branding.py. Skipped where vendor/ is absent (the stand
image holds team/ only).
"""

import base64
import hashlib
import importlib.util
import re
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
VENDOR = REPO / "vendor" / "grafana-plugins"
APP = "ertis-opentwins-app/"

GUARD = b'if(!i.config.bootData.user.isSignedIn)return"Viewer";'


def load_script(name, module_name):
    spec = importlib.util.spec_from_file_location(module_name, VENDOR / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        return {i.filename: (b"" if i.is_dir() else z.read(i.filename)) for i in z.infolist()}


def sri(blob):
    return "sha256-" + base64.b64encode(hashlib.sha256(blob).digest()).decode()


@unittest.skipUnless((VENDOR / "patch-anonymous.py").is_file(), "vendor/grafana-plugins not present")
class TestAnonymousViewerPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shipped = read_zip(VENDOR / "ertis-opentwins-app.zip")
        cls.upstream = read_zip(VENDOR / "upstream" / "ertis-opentwins-app.zip")

    def test_guard_sits_at_the_start_of_get_current_user_role(self):
        chunk = self.shipped[APP + "396.js"]
        self.assertEqual(chunk.count(GUARD), 1)
        self.assertIn(b'const m=()=>p((function*(){try{' + GUARD
                      + b'const e=yield(0,i.getBackendSrv)().get("/api/org")', chunk)
        # `i` is @grafana/runtime in this chunk: module 531 is the AMD dependency "@grafana/runtime"
        self.assertIn(b"i=n(531)", chunk[:600])
        self.assertIn(b'"@grafana/runtime"', self.shipped[APP + "module.js"][:600])

    def test_signed_in_path_is_upstream_apart_from_branding(self):
        anon = load_script("patch-anonymous.py", "patch_anonymous_test")
        chunk = self.shipped[APP + "396.js"]
        self.assertTrue(anon.is_patched(chunk))
        without_guard = chunk.replace(GUARD, b"", 1)
        branded_upstream = (self.upstream[APP + "396.js"]
                            .replace(b'alt:"OpenTwins Logo"', b'alt:"OpenEgiz Logo"')
                            .replace(b'n.appName},"OpenTwins")', b'n.appName},"OpenEgiz")'))
        self.assertEqual(without_guard, branded_upstream)

    def test_sri_digests_match_every_chunk(self):
        module = self.shipped[APP + "module.js"]
        block = re.search(rb"sriHashes=\{(.*?)\}", module, re.S).group(1)
        pinned = dict(re.findall(rb"(\d+):\"(sha256-[A-Za-z0-9+/=]+)\"", block))
        self.assertEqual(sorted(int(k) for k in pinned), [126, 202, 396])
        for cid, digest in pinned.items():
            self.assertEqual(sri(self.shipped[f"{APP}{int(cid)}.js"]), digest.decode(), cid)

    def test_shipped_zips_match_a_fresh_patch_run(self):
        branding = load_script("patch-branding.py", "patch_branding_test")
        logo = branding.build_logo()
        for name, prefix, patch in branding.PLUGINS:
            _, data = branding.read_zip(VENDOR / "upstream" / name)
            patch(data, logo)
            self.assertEqual(read_zip(VENDOR / name), data, name)


if __name__ == "__main__":
    unittest.main()
