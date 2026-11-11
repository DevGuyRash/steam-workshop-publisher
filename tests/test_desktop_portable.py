"""Portable CLI, backend, filesystem and native ABI checks. Never upload to real Steam."""

import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import content_files
import desktop
import folder
import publisher
import steam_runtime

ROOT = Path(__file__).resolve().parents[1]


class PortableCommands(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.content = self.root / "content"
        self.content.mkdir()
        (self.content / "example.txt").write_text("portable content", encoding="utf-8")

    def cli(self, *args):
        return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT,
                              capture_output=True, text=True, timeout=15)

    def release_boundary(self, member="Contents/example.txt"):
        assets = self.root / "assets"
        assets.mkdir(exist_ok=True)
        archive = assets / "ExampleMod-1.2.3.zip"
        payload = b"verified release content"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr(member, payload)
        (assets / "manifest.json").write_text(json.dumps({"id": "ExampleMod", "version": "1.2.3",
            "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "files": {member: hashlib.sha256(payload).hexdigest()}}), encoding="utf-8")
        (assets / "release-notes.txt").write_bytes(b"Fixture change\r\nSecond line\r\n")
        def github(*arguments):
            if arguments[0] == "api":
                value = ({"mod_id": "ExampleMod", "item_id": "1234", "app_id": "440", "archive": "ExampleMod-{version}.zip"}
                         if "/contents/" in arguments[1]
                         else {"tag_name": "v1.2.3", "draft": False, "prerelease": False, "published_at": "2026-01-01T00:00:00Z"})
                return json.dumps(value).encode()
            self.assertEqual(arguments[:2], ("release", "download"))
            destination = Path(arguments[arguments.index("--dir") + 1])
            for asset in assets.iterdir():
                shutil.copyfile(asset, destination / asset.name)
            return b""
        return github

    def test_release_preparation_and_default_upload_reach_desktop_with_verified_content(self):
        stage = self.root / "stage"
        def observed(app, **kwargs):
            self.assertEqual(app, "440")
            self.assertEqual(kwargs["item_id"], "1234")
            self.assertEqual(kwargs["notes"], "Fixture change\nSecond line\n")
            self.assertEqual((kwargs["content"] / "example.txt").read_bytes(), b"verified release content")
        with patch.object(publisher, "gh", side_effect=self.release_boundary()), patch.object(desktop, "run", side_effect=observed) as run, patch.object(publisher, "send_to_steam") as steamcmd, patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORKSHOP_BACKEND", None)
            publisher.prepare("owner/example-mod", "v1.2.3", None, None, stage)
            publisher.upload(stage)
            run.assert_called_once()
            steamcmd.assert_not_called()

    def test_release_rejects_windows_device_names_before_extraction(self):
        for index, name in enumerate(("CONIN$", "CONOUT$", "COM¹", "LPT²", "CON .txt", "nested/LPT³.txt")):
            stage = self.root / f"stage-{index}"
            with self.subTest(name=name), patch.object(publisher, "gh", side_effect=self.release_boundary("Contents/" + name)):
                with self.assertRaisesRegex(ValueError, "reserved Windows names"):
                    publisher.prepare("owner/example-mod", "v1.2.3", None, None, stage)
            self.assertFalse(stage.exists(), "Invalid names must be rejected before the stage is committed")

    def test_folder_and_package_commands_work_without_authentication(self):
        result = self.cli("folder.py", self.content, "--app-id", "440", "--item-id", "1234")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated 1 files", result.stdout)
        self.assertNotIn("Steam session", result.stdout)
        output = self.root / "package"
        result = self.cli("package.py", self.content, "ExampleMod", "1.2.3", "--out", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["files"]["Contents/example.txt"], hashlib.sha256(b"portable content").hexdigest())

    def test_default_auto_fails_without_a_runtime_and_never_uses_cached_steamcmd(self):
        steam = self.root / "steamcmd"
        steam.mkdir()
        (steam / "username").write_text("fixture_account")
        result = self.cli("folder.py", self.content, "--app-id", "440", "--item-id", "1234", "--publish",
                          "--steamcmd-dir", steam, "--offline", "--runtime-dir", self.root / "empty-runtime", "--backend", "auto")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Steamworks runtime is not cached", result.stderr)
        self.assertIn("no separate login or SteamCMD fallback", result.stdout)
        self.assertNotIn("Published", result.stdout)

    def test_probe_offline_never_fetches_runtime_or_uploads(self):
        result = self.cli("desktop.py", "probe", "--app-id", "440", "--offline", "--runtime-dir", self.root / "empty")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime is not cached", result.stderr)
        self.assertNotIn("Installing", result.stdout)

    def test_auto_and_desktop_routes_use_current_session_and_preserve_snapshot(self):
        for backend in (None, "auto", "desktop"):
            with self.subTest(backend=backend), patch.dict(os.environ, {}, clear=False), patch.object(desktop, "run") as run, patch.object(publisher, "send_to_steam") as steamcmd:
                os.environ.pop("WORKSHOP_BACKEND", None)
                def observed(app, **kwargs):
                    self.assertEqual(app, "440")
                    self.assertEqual(kwargs["item_id"], "1234")
                    self.assertEqual((kwargs["content"] / "example.txt").read_text(), "portable content")
                    self.assertNotEqual(kwargs["content"], self.content)
                run.side_effect = observed
                folder.publish_folder(self.content, "440", "1234", self.root / "steamcmd", None,
                                      "Fixture notes", True, backend=backend)
                self.assertEqual(run.call_count, 1)
                steamcmd.assert_not_called()

    def test_backend_flag_overrides_environment_and_missing_desktop_never_falls_back(self):
        with patch.dict(os.environ, {"WORKSHOP_BACKEND": "steamcmd"}), patch.object(desktop, "run", side_effect=RuntimeError("No desktop")), patch.object(publisher, "send_to_steam") as steamcmd:
            with self.assertRaisesRegex(RuntimeError, "No desktop"):
                folder.publish_folder(self.content, "440", "1234", self.root / "steamcmd", "fixture",
                                      "", True, backend="desktop")
            steamcmd.assert_not_called()
        with patch.dict(os.environ, {"WORKSHOP_BACKEND": "invalid"}):
            with self.assertRaisesRegex(ValueError, "WORKSHOP_BACKEND"):
                folder.publish_folder(self.content, "440", "1234", self.root / "steamcmd", None, "", True)

    def test_steamcmd_environment_selection_is_explicit_and_platform_gated(self):
        with patch.dict(os.environ, {"WORKSHOP_BACKEND": "steamcmd"}), patch.object(publisher.sys, "platform", "linux"), patch.object(publisher, "send_to_steam") as steamcmd:
            folder.publish_folder(self.content, "440", "1234", self.root / "steamcmd", "fixture", "", True)
            steamcmd.assert_called_once()
        with patch.object(publisher.sys, "platform", "win32"), patch.object(publisher, "send_to_steam") as steamcmd:
            with self.assertRaisesRegex(ValueError, "Linux-only"):
                folder.publish_folder(self.content, "440", "1234", self.root / "steamcmd", "fixture", "", True, backend="steamcmd")
            steamcmd.assert_not_called()

    def test_portable_paths_reject_drives_streams_reserved_names_and_collisions(self):
        for name in ("D:/escape", "file:stream", "dir/CON.txt", "file.", "file ", "../file", "dir\\file", "dir/a?b",
                     "CONIN$", "CONOUT$", "COM¹", "LPT²", "CON .txt", "dir/lpt³.log"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                publisher.package_path("Contents/" + name, publisher.Mod("owner/mod", "Example", "1234", "Example-{version}.zip"))
        for name in ("console.txt", "com10.txt", "lpt-notes.txt"):
            self.assertEqual(str(content_files.content_name(name)), name)
        for names in (("Contents/A/x", "Contents/a/y"), ("Contents/a", "Contents/a/x"), ("Contents/a/x", "Contents/a")):
            with self.subTest(names=names), self.assertRaises(ValueError):
                content_files.check_names(names)

    def test_reads_do_not_require_posix_no_follow_and_reject_reparse_points(self):
        with patch.object(content_files.os, "O_NOFOLLOW", 0, create=True):
            self.assertEqual(content_files.read_regular(self.content / "example.txt", 100), b"portable content")
        class Reparse:
            st_mode = 0o040755
            st_file_attributes = 0x400
        with patch.object(Path, "lstat", return_value=Reparse()):
            with self.assertRaisesRegex(ValueError, "reparse"):
                content_files.regular_stat(self.content)

    @unittest.skipUnless(os.name == "nt", "Native Windows junction check")
    def test_windows_junction_is_rejected_before_content_traversal(self):
        outside = self.root / "outside"
        outside.mkdir()
        junction = self.content / "junction"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], check=True, capture_output=True)
        try:
            result = self.cli("folder.py", self.content, "--app-id", "440", "--item-id", "1234")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reparse", result.stderr)
        finally:
            junction.rmdir()


class NativeABI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cmake"):
            raise unittest.SkipTest("CMake and a native C compiler are needed for the Steam ABI fixture")
        cls.temporary = tempfile.TemporaryDirectory(prefix="steam-abi-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        (root / "CMakeLists.txt").write_text('cmake_minimum_required(VERSION 3.16)\nproject(SteamABIFixture C)\nadd_library(steam_stub SHARED "' + (ROOT / "tests/fixtures/steam_stub.c").as_posix() + '")\n')
        subprocess.run(["cmake", "-S", str(root), "-B", str(root / "build")], check=True, capture_output=True)
        subprocess.run(["cmake", "--build", str(root / "build"), "--config", "Release"], check=True, capture_output=True)
        candidates = [p for p in (root / "build").rglob("*steam_stub*") if p.suffix in {".so", ".dll", ".dylib"}]
        assert len(candidates) == 1, candidates
        cls.library = candidates[0]
        cls.api = C.CDLL(str(cls.library))
        if os.name == "nt":
            import _ctypes
            cls.addClassCleanup(_ctypes.FreeLibrary, cls.api._handle)
        for name, result in (("test_reset", None), ("test_shutdowns", C.c_int), ("test_submits", C.c_int), ("test_app", C.c_uint32), ("test_item", C.c_uint64), ("test_content", C.c_char_p), ("test_notes", C.c_char_p)):
            function = getattr(cls.api, name)
            function.restype = result
            function.argtypes = [C.c_int] if name == "test_reset" else []

    def setUp(self):
        self.api.test_reset(0)
        loader = patch.object(desktop.C, "CDLL", return_value=self.api)
        loader.start()
        self.addCleanup(loader.stop)

    def test_native_ffi_preserves_app_item_unicode_and_content_only_update(self):
        steam = desktop.Steam(self.library, 440)
        try:
            steam.upload(440, 12345678901234, Path.cwd() / "fixture ü", "Changes\nПривет", 1)
        finally:
            steam.close()
        self.assertEqual(self.api.test_app(), 440)
        self.assertEqual(self.api.test_item(), 12345678901234)
        self.assertEqual(self.api.test_notes().decode("utf-8"), "Changes\nПривет")
        self.assertEqual(self.api.test_content().decode("utf-8"), str(Path.cwd() / "fixture ü"))
        self.assertEqual(self.api.test_submits(), 1)
        self.assertEqual(self.api.test_shutdowns(), 1)

    def test_native_detection_refuses_unavailable_logins_without_submitting(self):
        for mode, message, shutdowns in ((1, "not running", 0), (2, "not online", 1), (3, "initialization failed", 0), (4, "different application", 1)):
            self.api.test_reset(mode)
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, message) as caught:
                desktop.Steam(self.library, 440)
            self.assertNotIn("private-native-error-canary", str(caught.exception))
            self.assertEqual(self.api.test_shutdowns(), shutdowns)
            self.assertEqual(self.api.test_submits(), 0)

    def test_native_results_timeouts_and_disconnects_cannot_report_success(self):
        for mode, message in ((5, "refused"), (6, "valid Workshop"), (7, "permission"), (8, "different item"), (9, "agreement"), (10, "timed out"), (11, "offline"), (12, "content folder")):
            self.api.test_reset(mode)
            steam = desktop.Steam(self.library, 440)
            try:
                with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, message):
                    steam.upload(440, 1234, Path.cwd(), "fixture", 0.01)
            finally:
                steam.close()
            self.assertEqual(self.api.test_shutdowns(), 1)


class ProcessAndRuntime(unittest.TestCase):
    def test_helper_uses_same_interpreter_isolated_app_and_withholds_native_output(self):
        class Finished:
            def wait(self, timeout=None): return 0
            def poll(self): return 0
        def launch(arguments, **kwargs):
            self.assertEqual(arguments[0], sys.executable)
            self.assertEqual((Path(kwargs["cwd"]) / "steam_appid.txt").read_text(), "440")
            self.assertEqual(kwargs["env"]["SteamAppId"], "440")
            for name in ("GH_TOKEN", "STEAM_SESSION_KEY", "SOURCE_RELEASES_TOKEN", "STEAM_USERNAME"):
                self.assertNotIn(name, kwargs["env"])
            kwargs["stdout"].write(b"private-native-canary\n" + desktop.RESULT_PREFIX.encode() + b'{"ok":true,"backend":"desktop","uploaded":false}\n')
            return Finished()
        with patch.object(desktop, "install"), patch.object(desktop.subprocess, "Popen", side_effect=launch), patch.dict(os.environ, {"GH_TOKEN": "private", "STEAM_USERNAME": "private"}):
            self.assertTrue(desktop.run("440")["ok"])

    def test_parent_timeout_kills_and_reaps_only_its_helper(self):
        children, directories = [], []
        real_popen = subprocess.Popen
        def launch(*args, **kwargs):
            directories.append(Path(kwargs["cwd"]))
            child = real_popen([sys.executable, "-c", "import time;time.sleep(60)"], cwd=kwargs["cwd"], stdin=subprocess.DEVNULL)
            children.append(child)
            return child
        with patch.object(desktop, "install"), patch.object(desktop.subprocess, "Popen", side_effect=launch), patch.object(desktop.time, "monotonic", side_effect=[0, 1000]):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                desktop.run("440")
        self.assertIsNotNone(children[0].returncode)
        self.assertFalse(directories[0].exists(), "Helper must exit before Windows can remove its working directory")

    def test_runtime_platform_selection_and_cached_hashes(self):
        for system, machine, python_platform, expected in (("linux", "x86_64", "linux-x86_64", "linux64"), ("linux", "aarch64", "linux-aarch64", "linuxarm64"), ("win32", "AMD64", "win-amd64", "win64"), ("darwin", "arm64", "macosx-11.0-arm64", "osx"), ("darwin", "x86_64", "macosx-10.9-x86_64", "osx")):
            with self.subTest(system=system, machine=machine), patch.object(steam_runtime.sys, "platform", system), patch.object(steam_runtime.platform, "machine", return_value=machine), patch.object(steam_runtime.sysconfig, "get_platform", return_value=python_platform):
                self.assertEqual(steam_runtime.runtime_platform(), expected)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member, _ = steam_runtime.RUNTIMES[steam_runtime.runtime_platform()]
            lib = root / steam_runtime.VERSION / member
            lib.parent.mkdir(parents=True)
            lib.write_bytes(b"untrusted")
            with patch.object(steam_runtime.urllib.request, "urlopen") as download:
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    steam_runtime.install(root)
                download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
