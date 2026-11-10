import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class SetupTools(unittest.TestCase):
    def test_packager_creates_release_assets_from_an_arbitrary_content_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = root / "content"
            content.mkdir()
            (content / "example.dat").write_bytes(b"abc")
            output = root / "package"
            result = subprocess.run(["just", "package", str(content), "AnyGameMod", "1.2.3", "--out", str(output)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            archive = output / "AnyGameMod-1.2.3.zip"
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(package.namelist(), ["Contents/example.dat"])
                self.assertEqual(package.read("Contents/example.dat"), b"abc")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["files"], {"Contents/example.dat": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"})
            self.assertEqual(manifest["archiveSha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertEqual((output / "release-notes.txt").read_text(), "Release v1.2.3\n")

    def test_registration_is_repeatable_and_does_not_overwrite_another_item(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("register.py", "publisher.py"):
                shutil.copyfile(ROOT / name, root / name)
            (root / "mods.json").write_text("{}\n")
            arguments = [sys.executable, str(root / "register.py"), "example", "owner/repo", "Example", "1234", "440"]
            for _ in range(2):
                result = subprocess.run(arguments, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            expected = {"example": {"source": "owner/repo", "mod_id": "Example", "item_id": "1234", "app_id": "440", "archive": "Example-{version}.zip"}}
            self.assertEqual(json.loads((root / "mods.json").read_text()), expected)
            arguments[-2] = "9999"
            result = subprocess.run(arguments, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads((root / "mods.json").read_text()), expected)


if __name__ == "__main__":
    unittest.main()
