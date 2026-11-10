import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from publisher import send_to_steam

ROOT = Path(__file__).resolve().parents[1]


class FolderCLI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workshop-folder-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workshop = self.root / "Example"
        self.content = self.workshop / "Contents"
        self.content.mkdir(parents=True)
        (self.workshop / "workshop.txt").write_text("id=1234\ntitle=Example\nvisibility=public\n")
        (self.content / "example.lua").write_bytes(b"return 42\n")

    def run_cli(self, *arguments, success=True):
        result = subprocess.run([sys.executable, str(ROOT / "folder.py"), *map(str, arguments)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_native_workshop_folder_autodetects_existing_item_without_authentication(self):
        output = self.run_cli(self.workshop)
        self.assertIn("Validated 1 files for Steam app 108600, existing Workshop item 1234", output)
        self.assertNotIn("Published", output)
        self.assertEqual((self.content / "example.lua").read_bytes(), b"return 42\n")
        self.assertEqual(sorted(p.name for p in self.workshop.iterdir()), ["Contents", "workshop.txt"])

    def test_plain_content_supports_another_game_without_a_registry_or_manifest(self):
        output = self.run_cli(self.content, "--app-id", "440", "--item-id", "5678", "--dry-run")
        self.assertIn("Steam app 440, existing Workshop item 5678", output)
        self.assertNotIn("Published", output)
        self.run_cli(self.content, success=False)
        self.run_cli(self.content, "--app-id", "0", "--item-id", "5678", success=False)
        self.run_cli(self.content, "--app-id", "440", "--item-id", "0", success=False)

    def test_rejects_missing_item_symlinks_special_files_and_repository_metadata(self):
        (self.workshop / "workshop.txt").write_text("id=0\n")
        self.run_cli(self.workshop, success=False)
        (self.workshop / "workshop.txt").write_text("id=1234\n")
        linked = self.content / "link"
        linked.symlink_to(self.workshop / "workshop.txt")
        self.run_cli(self.workshop, success=False)
        linked.unlink()
        pipe = self.content / "pipe"
        os.mkfifo(pipe)
        self.run_cli(self.workshop, success=False)
        pipe.unlink()
        (self.content / ".git").mkdir()
        self.run_cli(self.workshop, success=False)

    def test_publish_uploads_a_snapshot_to_the_existing_item_and_preserves_listing_fields(self):
        steam = self.root / "steamcmd"
        steam.mkdir()
        (steam / "username").write_text("test_account\n")
        observed = self.root / "observed.json"
        launcher = steam / "steamcmd.sh"
        launcher.write_text(f'''#!/usr/bin/env python3
import json, pathlib, re, sys
vdf = pathlib.Path(sys.argv[sys.argv.index('+workshop_build_item') + 1]).read_text()
content = pathlib.Path(re.search(r'"contentfolder" "([^"]+)"', vdf).group(1))
pathlib.Path({str(observed)!r}).write_text(json.dumps({{"vdf": vdf, "content": (content / "example.lua").read_text()}}))
print('Success. Published item 1234.')
''')
        launcher.chmod(0o700)
        output = self.run_cli(self.workshop, "--publish", "--steamcmd-dir", steam)
        self.assertIn("Published content to existing Workshop item 1234", output)
        result = json.loads(observed.read_text())
        self.assertEqual(result["content"], "return 42\n")
        self.assertIn('"appid" "108600"', result["vdf"])
        self.assertIn('"publishedfileid" "1234"', result["vdf"])
        for field in ("title", "description", "visibility", "tags", "previewfile"):
            self.assertNotIn('"' + field + '"', result["vdf"])
        self.assertEqual((self.content / "example.lua").read_bytes(), b"return 42\n")

    def test_timeout_kills_the_actual_steam_child_before_returning(self):
        steam = self.root / "steamcmd"
        steam.mkdir()
        marker = self.root / "continued-upload"
        launcher = steam / "steamcmd.sh"
        child = f"import pathlib,time; time.sleep(0.8); pathlib.Path({str(marker)!r}).write_text('continued')"
        launcher.write_text(f"#!/usr/bin/env python3\nimport subprocess,sys,time\nsubprocess.Popen([sys.executable, '-c', {child!r}])\ntime.sleep(10)\n")
        launcher.chmod(0o700)
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            send_to_steam(self.root / "upload.vdf", "1234", steam, "test_account", timeout=0.25)
        time.sleep(0.9)
        self.assertFalse(marker.exists(), "SteamCMD's child continued uploading after the publisher returned")


if __name__ == "__main__":
    unittest.main()
