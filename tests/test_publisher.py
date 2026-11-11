import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MEMBER = "Contents/mods/ExampleMod/42/mod.info"


class PublisherCLI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="publisher-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text('''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
root = pathlib.Path(os.environ["FIXTURES"])
if sys.argv[1] == "api" and '/contents/workshop-publisher.json' in sys.argv[2]:
    print((root / "configuration.json").read_text())
elif sys.argv[1] == "api":
    print((root / "latest.json").read_text())
else:
    out = pathlib.Path(sys.argv[sys.argv.index("--dir")+1])
    for source in root.glob("assets/*"):
        shutil.copyfile(source, out / source.name)
''')
        gh.chmod(0o700)
        self.env = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "FIXTURES": str(self.root)}
        self.configuration()
        self.latest()
        self.package()
        self.stage = self.root / "stage"

    def configuration(self, **overrides):
        values = {"mod_id": "ExampleMod", "item_id": "1234567890",
                  "archive": "ExampleMod-{version}.zip", "app_id": "108600"}
        values.update(overrides)
        (self.root / "configuration.json").write_text(json.dumps(values))

    def latest(self, tag="v0.1.1", prerelease=False):
        (self.root / "latest.json").write_text(json.dumps({"tag_name": tag, "draft": False,
            "prerelease": prerelease, "published_at": "2026-11-10T12:00:00Z"}))

    def package(self, entries=None, files=None):
        entries = entries or [(MEMBER, b"id=ExampleMod\nmodversion=0.1.1\n", stat.S_IFREG | 0o644)]
        archive = self.assets / "ExampleMod-0.1.1.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            for name, data, mode in entries:
                entry = zipfile.ZipInfo(name)
                entry.external_attr = mode << 16
                output.writestr(entry, data)
        files = files if files is not None else {name: hashlib.sha256(data).hexdigest() for name, data, _ in entries}
        (self.assets / "manifest.json").write_text(json.dumps({"id": "ExampleMod", "version": "0.1.1",
            "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": files}))
        (self.assets / "release-notes.txt").write_text('Read "books".\nPath C:\\books\n')

    def run_cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(ROOT / "publisher.py"), *args],
            env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def prepare(self, *extra, success=True):
        return self.run_cli("prepare", "--source", "exampleowner/examplemod", "--tag", "v0.1.1", "--out", str(self.stage),
                            *extra, success=success)

    def steam(self, message="Success. Published item 1234567890.", exit_code=0):
        steam = self.root / "steamcmd"
        steam.mkdir(exist_ok=True)
        launcher = steam / "steamcmd.sh"
        launcher.write_text(f'''#!/usr/bin/env python3
import json, os, pathlib, sys
pathlib.Path(os.environ["FIXTURES"], "steam-call.json").write_text(json.dumps({{
    "args": sys.argv[1:], "stdin_eof": sys.stdin.read() == "", "home": os.environ["HOME"],
    "secret_present": any(key in os.environ for key in ["GH_TOKEN", "SOURCE_RELEASES_TOKEN", "STEAM_SESSION_KEY"])
}}))
print({message!r})
sys.exit({exit_code})
''')
        launcher.chmod(0o700)
        return steam

    def upload(self, steam, success=True):
        return self.run_cli("upload", "--stage", str(self.stage), "--backend", "steamcmd", "--steamcmd-dir", str(steam),
                            "--username", "test_account", success=success)

    def test_prepare_stages_exact_release_content_and_content_only_vdf(self):
        self.prepare()
        self.assertEqual((self.stage / MEMBER).read_bytes(), b"id=ExampleMod\nmodversion=0.1.1\n")
        vdf = (self.stage / "upload.vdf").read_text()
        self.assertIn('"appid" "108600"', vdf)
        self.assertIn('"publishedfileid" "1234567890"', vdf)
        self.assertIn('"changenote" "Read \\"books\\".\\nPath C:\\\\books\\n"', vdf)
        for field in ["visibility", "title", "description", "tags", "previewfile"]:
            self.assertNotIn('"' + field + '"', vdf)
        self.assertEqual({p.relative_to(self.stage).as_posix() for p in self.stage.rglob('*') if p.is_file()},
            {MEMBER, "manifest.json", "stage.json", "release-notes.txt", "upload.vdf"})

    def test_latest_stable_release_is_required_before_download_and_upload(self):
        self.latest("v0.1.2")
        self.prepare(success=False)
        self.assertFalse(self.stage.exists())
        self.latest(prerelease=True)
        self.prepare(success=False)
        self.latest()
        self.prepare()
        steam = self.steam()
        self.latest("v0.1.2")
        self.upload(steam, success=False)
        self.assertFalse((self.root / "steam-call.json").exists())

    def test_package_rejects_traversal_symlinks_duplicates_and_unlisted_members(self):
        cases = [
            [("Contents/mods/ExampleMod/../../outside", b"x", stat.S_IFREG | 0o644)],
            [(MEMBER, b"target", stat.S_IFLNK | 0o777)],
            [(MEMBER, b"one", stat.S_IFREG | 0o644), (MEMBER, b"two", stat.S_IFREG | 0o644)],
            [(MEMBER, b"id=ExampleMod\n", stat.S_IFREG | 0o644), ("outside", b"x", stat.S_IFREG | 0o644)],
        ]
        for entries in cases:
            with self.subTest(entries=entries):
                self.package(entries)
                self.prepare(success=False)
                self.assertFalse(self.stage.exists())
                self.assertFalse((self.root / "outside").exists())

    def test_supplied_build_hashes_and_manifest_member_hashes_are_enforced(self):
        self.prepare("--archive-sha256", "0" * 64, success=False)
        self.prepare("--notes-sha256", "0" * 64, success=False)
        manifest = json.loads((self.assets / "manifest.json").read_text())
        manifest["files"][MEMBER] = "0" * 64
        (self.assets / "manifest.json").write_text(json.dumps(manifest))
        self.prepare(success=False)
        self.assertFalse(self.stage.exists())

    def test_upload_uses_noninteractive_existing_item_and_hides_secrets_from_steam(self):
        self.prepare()
        self.env.update(GH_TOKEN="github-secret-canary", SOURCE_RELEASES_TOKEN="reader-canary", STEAM_SESSION_KEY="age-canary")
        self.upload(self.steam())
        call = json.loads((self.root / "steam-call.json").read_text())
        self.assertEqual(call["args"], ["+@ShutdownOnFailedCommand", "1", "+@NoPromptForPassword", "1",
            "+login", "test_account", "+workshop_build_item", str(self.stage / "upload.vdf"), "+quit"])
        self.assertTrue(call["stdin_eof"])
        self.assertFalse(call["secret_present"])
        self.assertEqual(call["home"], str(self.root / "steamcmd"))

    def test_failed_or_wrong_item_upload_never_prints_steam_output(self):
        self.prepare()
        for message, code in [("ERROR! password-canary", 0), ("Success. Published item 999. password-canary", 0),
                              ("Success. Published item 1234567890. password-canary", 1),
                              ("Success. Published item 1234567890. ERROR! password-canary", 0)]:
            with self.subTest(message=message, code=code):
                output = self.upload(self.steam(message, code), success=False)
                self.assertNotIn("password-canary", output)

    def test_stage_mutation_and_existing_output_fail_before_steam(self):
        self.prepare()
        self.prepare(success=False)
        steam = self.steam()
        (self.stage / MEMBER).write_text("changed")
        self.upload(steam, success=False)
        self.assertFalse((self.root / "steam-call.json").exists())

    def test_other_games_allow_their_own_content_and_configured_application_id(self):
        self.configuration(mod_id="Texture", item_id="1234", archive="Texture-{version}.zip", app_id="440")
        archive = self.assets / "Texture-0.1.1.zip"
        data = b"texture fixture"
        name = "Contents/materials/custom.vmt"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr(name, data)
        (self.assets / "manifest.json").write_text(json.dumps({"id": "Texture", "version": "0.1.1",
            "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "files": {name: hashlib.sha256(data).hexdigest()}}))
        result = subprocess.run([sys.executable, str(ROOT / "publisher.py"), "prepare", "--source", "exampleowner/texture",
            "--tag", "v0.1.1", "--out", str(self.stage)], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.stage / name).read_bytes(), data)
        self.assertIn('"appid" "440"', (self.stage / "upload.vdf").read_text())
        self.assertIn('"publishedfileid" "1234"', (self.stage / "upload.vdf").read_text())

    def test_source_configuration_changes_stop_a_staged_upload(self):
        self.prepare()
        steam = self.steam()
        self.configuration(item_id="9999")
        self.upload(steam, success=False)
        self.assertFalse((self.root / "steam-call.json").exists())

    def test_source_and_configuration_are_validated_before_release_download(self):
        for source in ("../outside", "owner/../outside", "owner/repo?query", "owner/repo;command"):
            with self.subTest(source=source):
                self.run_cli("prepare", "--source", source, "--tag", "v0.1.1", "--out", str(self.stage), success=False)
                self.assertFalse(self.stage.exists())
        self.configuration(source="another-owner/another-repository")
        self.prepare(success=False)
        self.assertFalse(self.stage.exists())


if __name__ == "__main__":
    unittest.main()
