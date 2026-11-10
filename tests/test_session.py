import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import session


@unittest.skipUnless(shutil.which("age") and shutil.which("age-keygen"), "age is required")
class EncryptedSession(unittest.TestCase):
    def test_saved_session_is_encrypted_and_can_be_restored_without_plaintext_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "config").mkdir(parents=True)
            fixture = b'"test-fixture" "no-real-credentials"\n'
            (source / "config/config.vdf").write_bytes(fixture)
            key = root / "key"
            subprocess.run(["age-keygen", "-o", str(key)], check=True, capture_output=True)
            fake_gh = root / "gh"
            fake_gh.write_text("""#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
release = pathlib.Path(os.environ['FAKE_RELEASE'])
if sys.argv[2] == 'view':
    if '--json' in sys.argv:
        print(json.dumps({'body': (release / 'pointer.json').read_text()}))
    sys.exit(0 if release.exists() else 1)
elif sys.argv[2] == 'create':
    release.mkdir()
elif sys.argv[2] == 'upload':
    shutil.copyfile(sys.argv[4], release / pathlib.Path(sys.argv[4]).name)
elif sys.argv[2] == 'edit':
    if os.environ.get('FAIL_EDIT'):
        sys.exit(1)
    shutil.copyfile(sys.argv[sys.argv.index('--notes-file') + 1], release / 'pointer.json')
elif sys.argv[2] == 'download':
    destination = pathlib.Path(sys.argv[sys.argv.index('--dir') + 1])
    asset = sys.argv[sys.argv.index('--pattern') + 1]
    shutil.copyfile(release / asset, destination / asset)
else:
    sys.exit(9)
""")
            fake_gh.chmod(0o700)
            environment = {"PATH": str(root) + os.pathsep + os.environ["PATH"],
                           "FAKE_RELEASE": str(root / "release")}
            with patch.dict(os.environ, environment):
                session.save(source, key, "example/publisher")
                asset = json.loads((root / "release/pointer.json").read_text())["asset"]
                ciphertext = (root / "release" / asset).read_bytes()
                self.assertTrue(ciphertext.startswith(b"age-encryption.org/v1"))
                self.assertNotIn(fixture, ciphertext)
                self.assertEqual(len(list((root / "release").glob("*.age"))), 1)
                with patch.dict(os.environ, {"FAIL_EDIT": "1"}):
                    with self.assertRaises(subprocess.CalledProcessError):
                        session.save(source, key, "example/publisher")
                self.assertEqual(json.loads((root / "release/pointer.json").read_text())["asset"], asset)
                self.assertEqual((root / "release" / asset).read_bytes(), ciphertext)
                target = root / "target"
                with patch.object(session, "install", lambda path: path.mkdir(mode=0o700)):
                    session.restore(target, key, "example/publisher")
                self.assertEqual((target / "config/config.vdf").read_bytes(), fixture)
                self.assertEqual((target / "config/config.vdf").stat().st_mode & 0o777, 0o600)
                damaged = bytearray(ciphertext)
                damaged[-10] ^= 1
                (root / "release" / asset).write_bytes(damaged)
                with patch.object(session, "install", lambda path: path.mkdir(mode=0o700)):
                    with self.assertRaises(subprocess.CalledProcessError):
                        session.restore(root / "damaged", key, "example/publisher")

    def test_restore_rejects_escaping_paths_links_and_duplicate_members(self):
        for kind in ("traversal", "link", "duplicate"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / "state.tar"
                with tarfile.open(archive, "w") as package:
                    member = tarfile.TarInfo("config/../../outside" if kind == "traversal" else "config/config.vdf")
                    if kind == "link":
                        member.type = tarfile.SYMTYPE
                        member.linkname = "../../outside"
                        package.addfile(member)
                    else:
                        member.size = 1
                        package.addfile(member, io.BytesIO(b"x"))
                        if kind == "duplicate":
                            package.addfile(member, io.BytesIO(b"y"))
                with self.assertRaises(ValueError):
                    session.unpack(archive, root / "target")
                self.assertFalse((root / "outside").exists())


if __name__ == "__main__":
    unittest.main()
