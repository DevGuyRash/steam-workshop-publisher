import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import desktop
import folder
import publisher
from publisher import send_to_steam

ROOT = Path(__file__).resolve().parents[1]


class FolderCLI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workshop-folder-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.uploads = self.root / "uploads"
        uploads = patch.object(folder, "UPLOAD_ROOT", self.uploads)
        uploads.start()
        self.addCleanup(uploads.stop)
        self.workshop = self.root / "Example"
        self.content = self.workshop / "Contents"
        self.content.mkdir(parents=True)
        (self.workshop / "workshop.txt").write_text("id=1234\ntitle=Example\nvisibility=public\n")
        (self.content / "example.lua").write_bytes(b"return 42\n")

    def run_cli(self, *arguments, success=True):
        result = subprocess.run([sys.executable, str(ROOT / "folder.py"), *map(str, arguments)],
                                env={**os.environ, "HOME": str(self.root), "USERPROFILE": str(self.root)},
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
        output = self.run_cli(self.workshop, "--publish", "--backend", "steamcmd", "--steamcmd-dir", steam)
        self.assertIn("Published content to existing Workshop item 1234", output)
        result = json.loads(observed.read_text())
        self.assertEqual(result["content"], "return 42\n")
        self.assertIn('"appid" "108600"', result["vdf"])
        self.assertIn('"publishedfileid" "1234"', result["vdf"])
        for field in ("title", "description", "visibility", "tags", "previewfile"):
            self.assertNotIn('"' + field + '"', result["vdf"])
        self.assertEqual((self.content / "example.lua").read_bytes(), b"return 42\n")

    def test_success_and_dry_run_remove_the_checked_snapshot(self):
        created = []
        make_directory = tempfile.mkdtemp
        def staging_directory(*args, **kwargs):
            kwargs["dir"] = self.root
            result = make_directory(*args, **kwargs)
            created.append(Path(result))
            return result
        with patch.object(folder.tempfile, "mkdtemp", side_effect=staging_directory), patch.object(desktop, "run") as run:
            folder.publish_folder(self.workshop, None, None, self.root / "steamcmd", None, "", False)
        run.assert_not_called()
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists())
        self.assertFalse(self.uploads.exists())
        observed = []
        def confirmed(_app_id, **kwargs):
            observed.append(kwargs["content"])
            self.assertEqual((kwargs["content"] / "example.lua").read_bytes(), b"return 42\n")
            self.assertNotEqual(kwargs["content"], self.content)
        with patch.object(desktop, "run", side_effect=confirmed):
            folder.publish_folder(self.workshop, None, None, self.root / "steamcmd", None, "", True, backend="desktop")
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0].parent.exists())
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_pre_handoff_validation_failures_remove_partial_snapshots(self):
        with patch.object(desktop, "run") as run:
            (self.content / ".env").write_text("fixture-only")
            with self.assertRaisesRegex(ValueError, "packaged content"):
                folder.publish_folder(self.workshop, None, None, self.root / "steamcmd", None, "", True, backend="desktop")
            (self.content / ".env").unlink()
            with self.assertRaisesRegex(ValueError, "control characters"):
                folder.publish_folder(self.workshop, None, None, self.root / "steamcmd", None, "bad\x00notes", True, backend="desktop")
        run.assert_not_called()
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_all_post_handoff_failures_retain_and_report_the_private_snapshot(self):
        for error in (RuntimeError("Upload timed out"), ValueError("Malformed callback"), SystemExit(130), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                output, diagnostics = io.StringIO(), io.StringIO()
                with patch.object(desktop, "run", side_effect=error) as run, redirect_stdout(output), redirect_stderr(diagnostics):
                    with self.assertRaises(type(error)) as raised:
                        folder.publish_folder(self.workshop, None, None, self.root / "steamcmd", None, "", True, backend="desktop")
                self.assertIs(raised.exception, error)
                content = run.call_args.kwargs["content"]
                self.assertEqual((content / "example.lua").read_bytes(), b"return 42\n")
                self.assertEqual(content.parent.parent, self.uploads)
                if os.name == "posix":
                    self.assertEqual(content.parent.stat().st_mode & 0o777, 0o700)
                    self.assertEqual(self.uploads.stat().st_mode & 0o777, 0o700)
                self.assertIn(str(content.parent), output.getvalue())
                self.assertIn(str(content.parent), diagnostics.getvalue())
                self.assertNotIn("Published content", output.getvalue())

    def test_positive_finite_timeout_is_forwarded_to_each_backend_with_the_existing_default(self):
        for backend in ("desktop", "steamcmd"):
            for configured, expected in ((None, 180), (600.25, 600.25)):
                with self.subTest(backend=backend, timeout=configured):
                    with patch.object(desktop, "run") as desktop_run, patch.object(publisher, "send_to_steam") as steamcmd_run, patch.object(publisher.sys, "platform", "linux"):
                        options = {} if configured is None else {"timeout": configured}
                        folder.publish_folder(self.workshop, None, None, self.root / "steamcmd", "fixture", "", True,
                                              backend=backend, **options)
                    selected, unused = (desktop_run, steamcmd_run) if backend == "desktop" else (steamcmd_run, desktop_run)
                    self.assertEqual(selected.call_count, 1)
                    self.assertEqual(selected.call_args.kwargs["timeout"], expected)
                    unused.assert_not_called()
                    self.assertEqual(list(self.uploads.iterdir()), [])

    def test_cli_rejects_nonpositive_and_nonfinite_timeouts_before_publishing(self):
        for value in ("0", "-1", "nan", "inf", "-inf"):
            with self.subTest(timeout=value):
                output = self.run_cli(self.workshop, "--publish", "--backend", "desktop", "--timeout=" + value, success=False)
                self.assertIn("positive finite", output)
                self.assertNotIn("Upload snapshot", output)
        output = self.run_cli(self.workshop, "--dry-run", "--timeout", "600")
        self.assertIn("Validated 1 files", output)
        self.assertNotIn("Upload snapshot", output)

    @unittest.skipUnless(os.name == "posix", "Descriptor handshake uses POSIX inherited descriptors")
    def test_external_reader_can_read_after_the_publishing_caller_returns(self):
        read_fd, write_fd = os.pipe()
        process = None
        reader = """import json,os,pathlib,sys
os.read(int(sys.argv[2]),1)
content=pathlib.Path(sys.argv[1])
print(json.dumps({'content':(content/'example.lua').read_text(),'exists':content.exists()}))
"""
        def remote_reader(_app_id, **kwargs):
            nonlocal process
            process = subprocess.Popen([sys.executable, "-c", reader, str(kwargs["content"]), str(read_fd)],
                                       pass_fds=(read_fd,), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            raise RuntimeError("The foreground upload wait timed out")
        try:
            with patch.object(desktop, "run", side_effect=remote_reader):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    folder.publish_folder(self.workshop, None, None, self.root / "steamcmd", None, "", True, backend="desktop")
            self.assertIsNone(process.poll())
            (self.content / "example.lua").write_bytes(b"source changed after handoff")
            os.write(write_fd, b"read")
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr.decode())
            self.assertEqual(json.loads(stdout), {"content": "return 42\n", "exists": True})
        finally:
            os.close(read_fd)
            os.close(write_fd)
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

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
